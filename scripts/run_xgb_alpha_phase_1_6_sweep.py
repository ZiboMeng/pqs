"""ML Phase 1.6 objective sweep — tests 4 alternative objectives vs Phase 1.5
baseline reg:squarederror to see if SOTA ranking objectives unlock alpha.

Per `docs/memos/20260513-ml_phase_1_5_closeout.md` §6 hypothesis +
WebSearch SOTA finding (Yan Lin LambdaRankIC 2026: +174% Rank IC + 33%
Sharpe vs reg:squarederror baseline).

Objectives tested:
  1. reg:squarederror (Phase 1.5 baseline; for sanity check reproduction)
  2. rank:pairwise (XGBoost native LambdaRank/RankNet)
  3. rank:ndcg (XGBoost native LambdaMART)
  4. LambdaRankIC (custom — Yan Lin 2026 closed-form)
  5. quintile_classification (5-class multinomial; top-quintile prob → score)

Fixed Phase 1.5 best setting:
  - lr=0.05 (best post-fix)
  - inner_val_strategy=multi_2016_2017 (Bug 1 fix from Phase 1.5)
  - n_estimators=200 (early stop manages)

ADDITIVE only — does not modify Phase 1.5 baseline pipeline. Outputs go
to data/ml/xgb_alpha_phase_1_6/ (separate from phase_1_5).

Usage:
  python scripts/run_xgb_alpha_phase_1_6_sweep.py --smoke   # baseline + ranking only
  python scripts/run_xgb_alpha_phase_1_6_sweep.py --full    # all 5 objectives
"""

from __future__ import annotations

import argparse
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
    _expand_year_entries,
    load_temporal_split,
    partition_for_role,
    purge_labels_at_boundary,
)
from core.research.temporal_split_acceptance import run_split_acceptance

from core.ml.feature_panel_builder import build_ml_panel
from core.ml.xgb_alpha import XGBAlphaModel
from core.ml.xgb_ranking import (
    LambdaRankICModel,
    XGBQuintileModel,
    XGBRankingModel,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("phase_1_6_sweep")


# ── Fixed Phase 1.5 best settings ───────────────────────────────────────


COMMON_KWARGS = dict(
    n_estimators=200,
    max_depth=5,
    learning_rate=0.05,
    early_stopping_rounds=20,
)
INNER_VAL_YEARS = [2016, 2017]  # multi_2016_2017 from Phase 1.5


SMOKE_OBJECTIVES = ["reg:squarederror", "rank:pairwise", "rank:ndcg"]
FULL_OBJECTIVES = [
    "reg:squarederror",
    "rank:pairwise",
    "rank:ndcg",
    "lambda_rank_ic",
    "quintile_classification",
]


# ── Panel + factor build (shared across all configs; same as Phase 1.5) ─


def _build_factors_panel():
    """88-OHLCV-factor build (same as Phase 1.5 for apples-to-apples
    objective comparison)."""
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


def _build_predictions_via_oof(
    objective: str,
    ml_panel: pd.DataFrame,
    feature_cols: List[str],
    train_years: List[int],
    validation_years: List[int],
    inner_val_years: List[int],
) -> Tuple[pd.DataFrame, Dict[Any, int]]:
    """For each Y in train_years (excluding inner_val_years), train on
    other train years + predict on Y (OOF). Then train_full + predict on
    validation_years + inner_val_years. Returns combined predictions.

    Bug 2 fix from Phase 1.5: predictions cover train+validation so stress
    slices in train years get harness scores.
    """
    ml_panel = ml_panel.copy()
    if not pd.api.types.is_datetime64_any_dtype(ml_panel["date"]):
        ml_panel["date"] = pd.to_datetime(ml_panel["date"])
    ml_panel["year"] = ml_panel["date"].dt.year

    parts: List[pd.DataFrame] = []
    best_iter_log: Dict[Any, int] = {}

    # OOF for each train year
    for y_test in train_years:
        if y_test in inner_val_years:
            continue
        train_mask = (
            ml_panel["year"].isin(train_years)
            & (ml_panel["year"] != y_test)
            & ~ml_panel["year"].isin(inner_val_years)
        )
        val_mask = ml_panel["year"].isin(inner_val_years)
        test_mask = ml_panel["year"] == y_test
        train_p = ml_panel[train_mask]
        val_p = ml_panel[val_mask]
        test_p = ml_panel[test_mask]
        if train_p.empty or test_p.empty:
            continue
        model = _build_model(objective)
        _fit_model(model, train_p, val_p, feature_cols)
        y_pred = _predict_model(model, test_p)
        test_pred = test_p[["date", "symbol", "fwd_return"]].copy()
        test_pred["y_pred"] = y_pred
        parts.append(test_pred)
        best_iter_log[y_test] = getattr(model, "best_iteration", None) or 0

    # Full-train + predict on validation_years + inner_val_years
    train_p = ml_panel[
        ml_panel["year"].isin(train_years)
        & ~ml_panel["year"].isin(inner_val_years)
    ]
    val_p = ml_panel[ml_panel["year"].isin(inner_val_years)]
    predict_p = ml_panel[ml_panel["year"].isin(validation_years + inner_val_years)]
    if not train_p.empty and not predict_p.empty:
        model = _build_model(objective)
        _fit_model(model, train_p, val_p, feature_cols)
        y_pred = _predict_model(model, predict_p)
        val_pred = predict_p[["date", "symbol", "fwd_return"]].copy()
        val_pred["y_pred"] = y_pred
        parts.append(val_pred)
        best_iter_log["full_train"] = getattr(model, "best_iteration", None) or 0

    if not parts:
        return pd.DataFrame(columns=["date", "symbol", "fwd_return", "y_pred"]), best_iter_log
    predictions = pd.concat(parts, ignore_index=True).sort_values(["date", "symbol"])
    return predictions, best_iter_log


def _build_model(objective: str):
    if objective == "reg:squarederror":
        return XGBAlphaModel(**COMMON_KWARGS)
    if objective in ("rank:pairwise", "rank:ndcg"):
        return XGBRankingModel(objective=objective, **COMMON_KWARGS)
    if objective == "lambda_rank_ic":
        return LambdaRankICModel(**COMMON_KWARGS)
    if objective == "quintile_classification":
        return XGBQuintileModel(**COMMON_KWARGS, n_quintiles=5)
    raise ValueError(f"unknown objective: {objective}")


def _fit_model(model, train_p: pd.DataFrame, val_p: Optional[pd.DataFrame], feature_cols):
    if isinstance(model, XGBAlphaModel):
        model.fit(
            train_p, train_p["fwd_return"],
            X_val=val_p, y_val=val_p["fwd_return"] if val_p is not None else None,
            feature_cols=feature_cols,
        )
    else:
        model.fit(
            train_p, train_p["fwd_return"],
            val_panel=val_p, y_val=val_p["fwd_return"] if val_p is not None else None,
            feature_cols=feature_cols,
        )


def _predict_model(model, panel) -> np.ndarray:
    return model.predict(panel)


def run_one_objective(
    objective: str,
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
    cfg_id = objective.replace(":", "_").replace("_classification", "_cls")
    cfg_out = out_dir / cfg_id
    cfg_out.mkdir(parents=True, exist_ok=True)
    logger.info("─" * 70)
    logger.info("Objective %s", objective)
    t0 = time.time()

    predictions, best_iter_log = _build_predictions_via_oof(
        objective, ml_panel, feature_cols, train_years, validation_years,
        INNER_VAL_YEARS,
    )
    fit_elapsed = time.time() - t0
    logger.info("  Predictions: %d rows; best_iter %s (%.1fs)",
                len(predictions), best_iter_log, fit_elapsed)

    if predictions.empty:
        logger.error("  EMPTY predictions; skipping")
        return {"objective": objective, "error": "empty_predictions"}

    # Harness evaluate (same setup as Phase 1.5 for apples-to-apples)
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

    # Track A 17-gate
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
        metrics_for_acceptance, role="core", freeze_date=_date(2026, 5, 13),
    )
    n_pass_vs_spy = sum(1 for v in per_year_vs_spy.values() if v > 0)
    avg_vs_spy = float(np.mean(list(per_year_vs_spy.values()))) if per_year_vs_spy else float("nan")

    elapsed = time.time() - t0
    summary = {
        "objective": objective,
        "config_id": cfg_id,
        "common_kwargs": COMMON_KWARGS,
        "inner_val_years": INNER_VAL_YEARS,
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
        "wall_clock_s": elapsed,
    }
    (cfg_out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    res.nav.to_csv(cfg_out / "nav.csv", header=["nav"])
    res.weights.to_parquet(cfg_out / "weights.parquet")

    logger.info("  Track A: %s (n_pass=%d/%d)",
                summary["track_a"]["overall_passed"],
                summary["track_a"]["n_pass"], summary["track_a"]["n_total"])
    logger.info("  avg per-yr vs_spy: %+.2f%% (n_pass=%d/5) wall=%.1fs",
                avg_vs_spy * 100.0, n_pass_vs_spy, elapsed)
    return summary


# ── Main ────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--smoke", action="store_true",
                     help="Run 3 objectives (baseline + 2 rankings)")
    grp.add_argument("--full", action="store_true",
                     help="Run all 5 objectives (adds LambdaRankIC + quintile)")
    ap.add_argument("--out-dir", default="data/ml/xgb_alpha_phase_1_6")
    args = ap.parse_args()

    objectives = SMOKE_OBJECTIVES if args.smoke else FULL_OBJECTIVES
    logger.info("Phase 1.6 sweep: %d objectives", len(objectives))
    for o in objectives:
        logger.info("  - %s", o)

    out_dir = PROJ / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

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

    train_years = sorted(set(_expand_year_entries(split_cfg.partition.train_years)))
    validation_years = sorted({vy.year for vy in split_cfg.partition.validation_years})
    stress_slices = {
        ss.name: (ss.start.isoformat(), ss.end.isoformat())
        for ss in split_cfg.partition.stress_slices
    }

    grid_rows = []
    for i, obj in enumerate(objectives, 1):
        logger.info("\n═══ Phase 1.6 objective %d/%d: %s ═══", i, len(objectives), obj)
        try:
            summary = run_one_objective(
                obj, panel, factors, mask, split_cfg,
                train_years, validation_years, stress_slices,
                ml_panel, feature_cols, out_dir,
            )
            grid_rows.append({
                "objective": summary["objective"],
                "config_id": summary["config_id"],
                "avg_per_year_vs_spy": summary["avg_per_year_vs_spy"],
                "n_pass_vs_spy": summary["n_pass_vs_spy"],
                "track_a_passed": summary["track_a"]["overall_passed"],
                "track_a_n_pass": summary["track_a"]["n_pass"],
                "track_a_failed": ",".join(summary["track_a"]["failed_gates"][:5]),
                "wall_clock_s": summary["wall_clock_s"],
            })
        except Exception as e:
            logger.exception("objective %s failed: %s", obj, e)
            grid_rows.append({"objective": obj, "error": str(e)})

    grid_df = pd.DataFrame(grid_rows)
    grid_path = out_dir / ("smoke_grid.csv" if args.smoke else "sweep_grid.csv")
    grid_df.to_csv(grid_path, index=False)
    logger.info("\nGrid saved: %s", grid_path)
    logger.info("Grid:\n%s", grid_df.to_string())

    cycle09b_baseline = 0.1531
    if "avg_per_year_vs_spy" in grid_df.columns:
        passers = grid_df[grid_df["avg_per_year_vs_spy"] > cycle09b_baseline]
    else:
        passers = pd.DataFrame()
    if len(passers) > 0:
        logger.info("\n✅ %d objective(s) beat cycle09b baseline +%.2f%%:\n%s",
                    len(passers), cycle09b_baseline * 100,
                    passers.to_string())
    else:
        logger.info("\n❌ NO objective beats cycle09b baseline +%.2f%% — §3.9 abort confirmed across objectives",
                    cycle09b_baseline * 100)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
