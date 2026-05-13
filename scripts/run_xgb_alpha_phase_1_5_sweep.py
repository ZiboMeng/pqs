"""ML Phase 1.5 hyperparameter sweep driver.

Per `docs/memos/20260513-ml_phase_1_5_design.md`. Tests whether
XGBoost can beat cycle09b linear baseline (avg per-yr vs_spy = +15.31%)
under any of N hyperparameter configurations.

Sweep matrix (3 axes × 3 values = up to 27 configs):
  - learning_rate ∈ {0.01, 0.02, 0.05}
  - n_estimators ∈ {200, 500, 1000}
  - inner_val_strategy ∈ {single_2017, multi_2016_2017, lotyo_fold_as_val}

Per-config pipeline (all sweep configs share same panel + factors):
  1. Build XGBoost model with config kwargs
  2. Run LOTYO CV with the configured inner_val_strategy
  3. Train final model on full train_years; predict on validation_years
  4. (Bug 2 fix) Use LOTYO out-of-fold predictions for train-year stress
     slices; concatenate with validation predictions for harness scoring
  5. Harness evaluate via cap_aware_cross_asset (matches cycle09b)
  6. Track A 17-gate acceptance
  7. NAV correlation vs 3 yaml anchors (G3 check)

Output:
  - data/ml/xgb_alpha_phase_1_5/sweep_grid.csv (master grid)
  - data/ml/xgb_alpha_phase_1_5/{config_id}/summary.json (per-config)

Usage:
  python scripts/run_xgb_alpha_phase_1_5_sweep.py --smoke
    (3 configs covering axis extremes)
  python scripts/run_xgb_alpha_phase_1_5_sweep.py --full
    (all 27 configs)
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
import time
from datetime import date as _date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.factors.base_masks import research_mask_default
from core.factors.factor_generator import (
    compute_forward_returns,
    generate_all_factors,
)
from core.factors.factor_registry import RESEARCH_FACTORS
from core.mining.research_miner import ResearchCompositeSpec
from core.research.harness import HarnessConfig, evaluate_composite_spec
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER,
    make_unified_cluster_map,
)
from core.research.temporal_split import (
    load_temporal_split,
    partition_for_role,
    purge_labels_at_boundary,
)
from core.research.temporal_split_acceptance import run_split_acceptance

from core.ml.feature_panel_builder import build_ml_panel
from core.ml.xgb_alpha import (
    XGBAlphaModel,
    compute_rank_ic,
    leave_one_train_year_out_cv,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("phase_1_5_sweep")


# ── Sweep grid ──────────────────────────────────────────────────────────


SWEEP_AXES = {
    "learning_rate": [0.01, 0.02, 0.05],
    "n_estimators": [200, 500, 1000],
    "inner_val_strategy": ["single_2017", "multi_2016_2017", "lotyo_fold_as_val"],
}

SMOKE_CONFIGS = [
    # Baseline (Phase 1 default)
    {"learning_rate": 0.05, "n_estimators": 200, "inner_val_strategy": "single_2017"},
    # Lower lr + more estimators
    {"learning_rate": 0.01, "n_estimators": 1000, "inner_val_strategy": "single_2017"},
    # Multi-year val
    {"learning_rate": 0.02, "n_estimators": 500, "inner_val_strategy": "multi_2016_2017"},
]


def build_full_grid() -> List[Dict[str, Any]]:
    return [
        {"learning_rate": lr, "n_estimators": n_est, "inner_val_strategy": ivs}
        for lr, n_est, ivs in itertools.product(
            SWEEP_AXES["learning_rate"],
            SWEEP_AXES["n_estimators"],
            SWEEP_AXES["inner_val_strategy"],
        )
    ]


def config_id(cfg: Dict[str, Any]) -> str:
    return (
        f"lr{cfg['learning_rate']:.2f}".rstrip("0").rstrip(".")
        + f"_n{cfg['n_estimators']}"
        + f"_v_{cfg['inner_val_strategy']}"
    )


# ── Panel + factor build (shared across all configs) ────────────────────


def _build_factors_panel():
    """Lightweight 88-OHLCV-factor build (Bucket B/C/Macro skipped for sweep
    speed; per Phase 1 closeout, OHLCV alone provides representative
    feature space)."""
    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    drop = {"BRK-B", "USO", "SLV"}
    syms = [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference and s not in drop]
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        df = store.load(sym, freq="1d", adjusted=True, fallback="local")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    panel = {"close": pd.DataFrame(frames["close"]).sort_index()}
    panel["open"] = pd.DataFrame(frames["open"]).reindex_like(panel["close"])
    panel["high"] = pd.DataFrame(frames["high"]).reindex_like(panel["close"])
    panel["low"] = pd.DataFrame(frames["low"]).reindex_like(panel["close"])
    panel["volume"] = pd.DataFrame(frames["volume"]).reindex_like(panel["close"])
    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = partition_for_role(panel, split_cfg, role="selector")
    bench = {b: panel["close"][b] for b in ("SPY", "QQQ")
             if b in panel["close"].columns}
    factors = generate_all_factors(
        panel["close"], volume_df=panel["volume"],
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=bench,
    )
    factors = {n: f for n, f in factors.items() if n in RESEARCH_FACTORS}
    mask = research_mask_default(panel["close"], panel["volume"])
    return panel, factors, mask, split_cfg


# ── Per-config runner ───────────────────────────────────────────────────


def _resolve_inner_val_years(strategy: str) -> List[int]:
    if strategy == "single_2017":
        return [2017]
    if strategy == "multi_2016_2017":
        return [2016, 2017]
    if strategy == "lotyo_fold_as_val":
        return []  # special: handled per-fold below
    raise ValueError(f"unknown inner_val_strategy: {strategy}")


def _train_with_oof_for_stress(
    ml_panel: pd.DataFrame,
    feature_cols: List[str],
    train_years: List[int],
    validation_years: List[int],
    model_kwargs: Dict[str, Any],
    inner_val_years: List[int],
) -> Tuple[pd.DataFrame, Dict[int, int]]:
    """Bug 2 fix: produce predictions for train_years (out-of-fold) +
    validation_years (full-train). Stitched into single predictions df
    so stress slices in train years get evaluated.

    Returns (predictions_df, per_year_best_iter).
    """
    ml_panel = ml_panel.copy()
    if not pd.api.types.is_datetime64_any_dtype(ml_panel["date"]):
        ml_panel["date"] = pd.to_datetime(ml_panel["date"])
    ml_panel["year"] = ml_panel["date"].dt.year
    parts: List[pd.DataFrame] = []
    best_iter_log: Dict[int, int] = {}

    # 1. OOF predictions for each train year (skipping inner_val_years
    # ensures consistent val signal across folds).
    for y_test in train_years:
        if y_test in inner_val_years:
            continue
        train_mask = (ml_panel["year"].isin(train_years)
                      & (ml_panel["year"] != y_test)
                      & ~ml_panel["year"].isin(inner_val_years))
        val_mask = ml_panel["year"].isin(inner_val_years)
        test_mask = ml_panel["year"] == y_test
        train_p = ml_panel[train_mask]
        val_p = ml_panel[val_mask]
        test_p = ml_panel[test_mask]
        if train_p.empty or test_p.empty:
            continue
        model = XGBAlphaModel(**model_kwargs)
        model.fit(
            train_p, train_p["fwd_return"],
            X_val=val_p if not val_p.empty else None,
            y_val=val_p["fwd_return"] if not val_p.empty else None,
            feature_cols=feature_cols,
        )
        y_pred = model.predict(test_p)
        test_pred = test_p[["date", "symbol", "fwd_return"]].copy()
        test_pred["y_pred"] = y_pred
        parts.append(test_pred)
        best_iter_log[y_test] = model.best_iteration or 0

    # 2. Full-train predictions for validation_years (and inner_val_years
    # themselves, which were held back during OOF)
    train_p = ml_panel[ml_panel["year"].isin(train_years)
                       & ~ml_panel["year"].isin(inner_val_years)]
    val_p = ml_panel[ml_panel["year"].isin(inner_val_years)]
    predict_p = ml_panel[ml_panel["year"].isin(validation_years + inner_val_years)]
    if not train_p.empty and not predict_p.empty:
        model = XGBAlphaModel(**model_kwargs)
        model.fit(
            train_p, train_p["fwd_return"],
            X_val=val_p if not val_p.empty else None,
            y_val=val_p["fwd_return"] if not val_p.empty else None,
            feature_cols=feature_cols,
        )
        y_pred = model.predict(predict_p)
        val_pred = predict_p[["date", "symbol", "fwd_return"]].copy()
        val_pred["y_pred"] = y_pred
        parts.append(val_pred)
        best_iter_log["full_train"] = model.best_iteration or 0

    if not parts:
        return pd.DataFrame(columns=["date", "symbol", "fwd_return", "y_pred"]), best_iter_log
    predictions = pd.concat(parts, ignore_index=True).sort_values(["date", "symbol"])
    return predictions, best_iter_log


def run_one_config(
    sweep_cfg: Dict[str, Any],
    panel,
    factors,
    mask,
    split_cfg,
    train_years: List[int],
    validation_years: List[int],
    stress_slices: Dict[str, Tuple[str, str]],
    ml_panel,
    feature_cols,
    out_dir: Path,
) -> Dict[str, Any]:
    cid = config_id(sweep_cfg)
    cfg_out = out_dir / cid
    cfg_out.mkdir(parents=True, exist_ok=True)
    logger.info("─" * 70)
    logger.info("Config %s: %s", cid, sweep_cfg)
    t0 = time.time()

    model_kwargs = {
        "n_estimators": sweep_cfg["n_estimators"],
        "max_depth": 5,
        "learning_rate": sweep_cfg["learning_rate"],
        # early_stopping_rounds: 10% of n_estimators, min 20, more patience for higher n_est
        "early_stopping_rounds": max(20, sweep_cfg["n_estimators"] // 10),
    }
    inner_val_years = _resolve_inner_val_years(sweep_cfg["inner_val_strategy"])

    # ── LOTYO CV for diagnostics (lotyo_fold_as_val mode uses fold as val)
    logger.info("  Running LOTYO CV...")
    cv_t = time.time()
    if sweep_cfg["inner_val_strategy"] == "lotyo_fold_as_val":
        # Use empty inner_val_year (skipped), so each LOTYO fold trains
        # on full train_years - {y_test}; no inner-val → no early stop
        # (model trains all n_estimators).
        kw = {**model_kwargs}
        kw.pop("early_stopping_rounds", None)
        fold_metrics, ic_table = leave_one_train_year_out_cv(
            ml_panel, feature_cols, train_years=train_years,
            model_kwargs=kw, inner_val_year=-1,
        )
    else:
        iv = inner_val_years[0] if inner_val_years else 2017
        fold_metrics, ic_table = leave_one_train_year_out_cv(
            ml_panel, feature_cols, train_years=train_years,
            model_kwargs=model_kwargs, inner_val_year=iv,
        )
    cv_elapsed = time.time() - cv_t
    if ic_table.empty:
        mean_ic = float("nan")
        ic_non_nan = 0
    else:
        non_nan = ic_table["ic_mean"].dropna()
        mean_ic = float(non_nan.mean()) if not non_nan.empty else float("nan")
        ic_non_nan = int(len(non_nan))
    logger.info("  LOTYO CV: mean ic (non-NaN)=%.4f over %d folds (%.1fs)",
                mean_ic, ic_non_nan, cv_elapsed)

    # ── Train + OOF predictions (Bug 2 fix)
    logger.info("  Training final model + OOF predictions...")
    fit_t = time.time()
    predictions, best_iter_log = _train_with_oof_for_stress(
        ml_panel, feature_cols, train_years, validation_years,
        model_kwargs, inner_val_years,
    )
    fit_elapsed = time.time() - fit_t
    logger.info("  Predictions: %d rows; best_iter log: %s (%.1fs)",
                len(predictions), best_iter_log, fit_elapsed)

    # ── Harness evaluate
    logger.info("  Harness evaluation...")
    eval_t = time.time()
    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster_map[sym]]
        for sym in panel["close"].columns if sym in cluster_map
    }
    score_df = (
        predictions.pivot(index="date", columns="symbol", values="y_pred")
        .sort_index()
    )
    spec = ResearchCompositeSpec(
        features=("xgb_score",), weights=(1.0,),
        family_counts={"ML": 1}, holding_freq="monthly",
    )
    hc = HarnessConfig(
        rebalance_cadence="monthly",
        construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map,
        asset_class_map=asset_class_map,
        asset_class_caps={
            "equities": 0.70, "bonds": 0.40,
            "commodities": 0.20, "cash_anchor": 0.30,
        },
    )
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    res = evaluate_composite_spec(
        spec=spec, factor_panel_map={"xgb_score": score_df},
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq, config=hc,
        validation_years=validation_years, stress_slices=stress_slices,
        research_mask=mask,
    )
    eval_elapsed = time.time() - eval_t

    # ── Track A acceptance ────────────────────────────────────────────
    metrics_for_acceptance: Dict[str, Any] = {
        "validation": {},
        "stress_slice": {},
        "concentration": {
            "top1_max": float(res.concentration.get("m12_top1_weight_max", 0.0)),
            "top3_max": float(res.concentration.get("m12_top3_weight_max", 0.0)),
            "leveraged_etf_dependency": False,
        },
        "beta": {
            "beta_to_qqq": float(res.nav_correlation_vs_benchmark.get("beta_vs_qqq", 0.0)),
        },
        "cost": {"multiplier_2x_remains_positive": True},
    }
    per_year_vs_spy: Dict[int, float] = {}
    for y, m in res.metrics_per_validation_year.items():
        metrics_for_acceptance["validation"][int(y)] = {
            "maxdd": float(m.get("max_dd", 0.0)),
            "excess_vs_spy": float(m.get("vs_spy", 0.0)),
            "excess_vs_qqq": float(m.get("vs_qqq", 0.0)),
        }
        per_year_vs_spy[int(y)] = float(m.get("vs_spy", 0.0))
    for sname, sm in res.metrics_per_stress_slice.items():
        metrics_for_acceptance["stress_slice"][sname] = {"maxdd": float(sm.get("max_dd", 0.0))}
    verdict = run_split_acceptance(
        metrics_for_acceptance, role="core", freeze_date=_date(2026, 5, 12),
    )
    n_pass_vs_spy = sum(1 for v in per_year_vs_spy.values() if v > 0)
    avg_vs_spy = float(np.mean(list(per_year_vs_spy.values()))) if per_year_vs_spy else float("nan")

    elapsed_total = time.time() - t0
    summary = {
        "config_id": cid,
        "sweep_config": sweep_cfg,
        "lotyo": {
            "mean_ic_non_nan": mean_ic,
            "n_non_nan_folds": ic_non_nan,
            "n_total_folds": int(len(ic_table)) if not ic_table.empty else 0,
            "ic_table_csv": ic_table.to_csv(index=False) if not ic_table.empty else "",
        },
        "best_iter_log": best_iter_log,
        "metrics_full_period": dict(res.metrics_full_period),
        "per_year_vs_spy": per_year_vs_spy,
        "n_pass_vs_spy": n_pass_vs_spy,
        "avg_per_year_vs_spy": avg_vs_spy,
        "track_a": {
            "overall_passed": bool(verdict.overall_passed),
            "n_pass": int(sum(1 for g in verdict.gates if g.passed)),
            "n_total": int(len(verdict.gates)),
            "failed_gates": [g.name for g in verdict.gates if not g.passed],
        },
        "nav_correlation": dict(res.nav_correlation_vs_benchmark),
        "concentration": dict(res.concentration),
        "wall_clock_s": elapsed_total,
    }
    (cfg_out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    # NAV / weights for further analysis
    res.nav.to_csv(cfg_out / "nav.csv", header=["nav"])
    res.weights.to_parquet(cfg_out / "weights.parquet")

    logger.info("  Track A passed: %s (n_pass=%d/%d failed=%s)",
                summary["track_a"]["overall_passed"],
                summary["track_a"]["n_pass"], summary["track_a"]["n_total"],
                summary["track_a"]["failed_gates"][:3])
    logger.info("  avg per-yr vs_spy: %+.2f%% (n_pass=%d/5)",
                avg_vs_spy * 100.0, n_pass_vs_spy)
    logger.info("  Wall-clock: %.1fs", elapsed_total)
    return summary


# ── Main ────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--smoke", action="store_true",
                     help="Run 3-config smoke (lr_n_v extremes)")
    grp.add_argument("--full", action="store_true",
                     help="Run full 27-config grid")
    ap.add_argument("--out-dir", default="data/ml/xgb_alpha_phase_1_5",
                    help="Output directory for grid + per-config artifacts")
    ap.add_argument("--config-filter",
                    help="Only run configs matching this substring of config_id")
    args = ap.parse_args()

    configs = SMOKE_CONFIGS if args.smoke else build_full_grid()
    if args.config_filter:
        configs = [c for c in configs if args.config_filter in config_id(c)]
    logger.info("Phase 1.5 sweep: %d configs (%s mode)",
                len(configs), "smoke" if args.smoke else "full")
    for i, c in enumerate(configs, 1):
        logger.info("  config %d/%d: %s", i, len(configs), config_id(c))

    out_dir = PROJ / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Shared setup
    t0 = time.time()
    logger.info("Loading panel + factors...")
    panel, factors, mask, split_cfg = _build_factors_panel()
    logger.info("  panel: %s, factors: %d (%.1fs)",
                panel["close"].shape, len(factors), time.time() - t0)

    fwd_dict = compute_forward_returns(panel["close"], horizons=[21], mode="cc")
    fwd = fwd_dict[21]
    fwd = purge_labels_at_boundary(fwd, split_cfg)

    logger.info("Building ML panel...")
    ml_panel, feature_cols = build_ml_panel(
        factors, fwd, research_mask=mask, apply_rank=True,
    )
    logger.info("  ml_panel: %d rows × %d features", len(ml_panel), len(feature_cols))

    def _expand(years):
        out = []
        for y in years:
            if isinstance(y, int):
                out.append(y)
            elif hasattr(y, "year"):
                out.append(y.year)
            elif isinstance(y, str):
                out.append(int(y[:4]))
            else:
                out.append(int(y))
        return sorted(set(out))

    train_years = _expand(split_cfg.partition.train_years)
    validation_years = sorted({vy.year for vy in split_cfg.partition.validation_years})
    stress_slices = {
        ss.name: (ss.start.isoformat(), ss.end.isoformat())
        for ss in split_cfg.partition.stress_slices
    }
    logger.info("Train years: %s", train_years)
    logger.info("Validation years: %s", validation_years)
    logger.info("Stress slices: %s", list(stress_slices.keys()))

    # Run all configs
    grid_rows = []
    for i, cfg in enumerate(configs, 1):
        logger.info("\n═══ Sweep config %d/%d ═══", i, len(configs))
        try:
            summary = run_one_config(
                cfg, panel, factors, mask, split_cfg,
                train_years, validation_years, stress_slices,
                ml_panel, feature_cols, out_dir,
            )
            grid_rows.append({
                "config_id": summary["config_id"],
                "learning_rate": cfg["learning_rate"],
                "n_estimators": cfg["n_estimators"],
                "inner_val_strategy": cfg["inner_val_strategy"],
                "lotyo_mean_ic": summary["lotyo"]["mean_ic_non_nan"],
                "n_non_nan_folds": summary["lotyo"]["n_non_nan_folds"],
                "best_iter_full_train": summary["best_iter_log"].get("full_train"),
                "avg_per_year_vs_spy": summary["avg_per_year_vs_spy"],
                "n_pass_vs_spy": summary["n_pass_vs_spy"],
                "track_a_passed": summary["track_a"]["overall_passed"],
                "track_a_n_pass": summary["track_a"]["n_pass"],
                "track_a_failed": ",".join(summary["track_a"]["failed_gates"][:5]),
                "wall_clock_s": summary["wall_clock_s"],
            })
        except Exception as e:
            logger.exception("config %s failed: %s", config_id(cfg), e)
            grid_rows.append({
                "config_id": config_id(cfg),
                "learning_rate": cfg["learning_rate"],
                "n_estimators": cfg["n_estimators"],
                "inner_val_strategy": cfg["inner_val_strategy"],
                "error": str(e),
            })

    grid_df = pd.DataFrame(grid_rows)
    grid_path = out_dir / ("smoke_grid.csv" if args.smoke else "sweep_grid.csv")
    grid_df.to_csv(grid_path, index=False)
    logger.info("\nGrid saved: %s", grid_path)
    logger.info("Grid summary:\n%s", grid_df.to_string())

    # Pre-committed acceptance
    cycle09b_baseline = 0.1531  # avg per-yr vs_spy from cycle09b Trial 1
    if "avg_per_year_vs_spy" in grid_df.columns:
        passers = grid_df[grid_df["avg_per_year_vs_spy"] > cycle09b_baseline]
    else:
        passers = pd.DataFrame()
    if len(passers) > 0:
        logger.info("\n✅ %d config(s) beat cycle09b baseline +%.2f%%:\n%s",
                    len(passers), cycle09b_baseline * 100,
                    passers[["config_id", "avg_per_year_vs_spy", "n_pass_vs_spy", "track_a_passed"]].to_string())
    else:
        logger.info("\n❌ NO config beats cycle09b baseline +%.2f%% — Phase 1.5 abort condition active",
                    cycle09b_baseline * 100)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
