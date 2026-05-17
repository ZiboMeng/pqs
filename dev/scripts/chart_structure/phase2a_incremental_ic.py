"""Phase 2A — incremental-IC paired test for chart-structure family T.

Per `docs/prd/20260515-chart_structure_input_representation_prd.md` §4.2 and
the ralph-loop execution PRD §5 (round P2A·R1 builds this harness; P2A·R2
runs it).

Question: does adding the 12 family-T swing-structure features to the ML
input raise the OOS Rank IC of the Phase 1.6 canonical `rank:ndcg` model?

Design (PRD §4.2 + execution PRD §B-B3):
  - baseline  = RESEARCH_FACTORS minus the 12 `swing_*` family-T factors
  - treatment = baseline + family T (recomputed per K in the sweep)
  - both run the SAME LOTYO OOF folds, SAME seed; the ONLY difference is
    the 12 family-T columns.
  - **B3 fix**: `colsample_bytree=1.0` for the paired runs so that adding
    12 columns does not perturb XGBoost's per-tree column subsampling.
  - metric = per-year OOS Rank IC (cross-sectional Spearman, mean over
    dates); paired t-test on per-year ΔIC = IC_treat − IC_base.
  - K is swept over {6, 8, 12} (execution PRD §3 q5; K is a PLACEHOLDER).

Output: data/audit/chart_structure/phase2a_incremental_ic.json — carries a
`verdict_scope` field (machine proxy for AC P2-A2).

Usage:
  python dev/scripts/chart_structure/phase2a_incremental_ic.py
  python dev/scripts/chart_structure/phase2a_incremental_ic.py --k-grid 8
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.factors.base_masks import research_mask_default
from core.factors.factor_generator import compute_forward_returns, generate_all_factors
from core.factors.factor_registry import RESEARCH_FACTORS
from core.factors.swing_structure import (
    SWING_STRUCTURE_FEATURES,
    SwingStructureConfig,
    compute_swing_structure_factors,
)
from core.ml.feature_panel_builder import build_ml_panel
from core.ml.xgb_ranking import XGBRankingModel
from core.research.temporal_split import (
    _expand_year_entries,
    load_temporal_split,
    partition_for_role,
    purge_labels_at_boundary,
)
from core.universe.universe_resolver import resolve_universe

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("phase2a")

INNER_VAL_YEARS = [2016, 2017]
# Phase 1.6 canonical config + B3 fix (colsample_bytree=1.0 for paired runs).
COMMON_KWARGS = dict(
    n_estimators=200, max_depth=5, learning_rate=0.05,
    early_stopping_rounds=20, colsample_bytree=1.0, seed=42,
)


def _build_panel(universe: str = "executable"):
    """Selector-partition panel + non-family-T factors + family-T inputs.

    `universe` is resolved via core.universe.universe_resolver — the
    default "executable" reproduces the pre-Phase-4 79-symbol set
    bit-for-bit (D6); "expanded_v1" uses the Phase-4 expanded universe."""
    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    syms = resolve_universe(universe, config_dir=PROJ / "config")
    frames: Dict[str, Dict[str, pd.Series]] = {
        k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        df = store.load(sym, freq="1d", adjusted=True, fallback="local")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    panel = {"close": pd.DataFrame(frames["close"]).sort_index()}
    for col in ("open", "high", "low", "volume"):
        panel[col] = pd.DataFrame(frames[col]).reindex_like(panel["close"])
    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = partition_for_role(panel, split_cfg, role="selector")
    bench = {b: panel["close"][b] for b in ("SPY", "QQQ")
             if b in panel["close"].columns}

    all_factors = generate_all_factors(
        panel["close"], volume_df=panel["volume"], open_df=panel["open"],
        high_df=panel["high"], low_df=panel["low"], benchmark_map=bench,
    )
    swing = set(SWING_STRUCTURE_FEATURES)
    # baseline = RESEARCH_FACTORS minus family T
    baseline_factors = {
        n: f for n, f in all_factors.items()
        if n in RESEARCH_FACTORS and n not in swing
    }
    mask = research_mask_default(panel["close"], panel["volume"])
    return panel, baseline_factors, mask, split_cfg


def _family_t_at_k(close_df, high_df, low_df, k: int) -> Dict[str, pd.DataFrame]:
    """Recompute family T at a given K (tol / maturity_cap stay at PLACEHOLDER
    defaults; only K sweeps per execution PRD §3 q5)."""
    cfg = SwingStructureConfig(swing_n=5, K=k, tol=0.15, maturity_cap=5)
    return compute_swing_structure_factors(close_df, high_df, low_df, cfg=cfg)


def _oof_predictions(ml_panel: pd.DataFrame, feature_cols: List[str],
                     train_years: List[int],
                     validation_years: List[int]) -> pd.DataFrame:
    """LOTYO OOF predictions with rank:ndcg (mirrors Phase 1.6
    _build_predictions_via_oof, rank:ndcg only)."""
    ml_panel = ml_panel.copy()
    if not pd.api.types.is_datetime64_any_dtype(ml_panel["date"]):
        ml_panel["date"] = pd.to_datetime(ml_panel["date"])
    ml_panel["year"] = ml_panel["date"].dt.year
    parts: List[pd.DataFrame] = []

    for y_test in train_years:
        if y_test in INNER_VAL_YEARS:
            continue
        tr = ml_panel[ml_panel["year"].isin(train_years)
                      & (ml_panel["year"] != y_test)
                      & ~ml_panel["year"].isin(INNER_VAL_YEARS)]
        va = ml_panel[ml_panel["year"].isin(INNER_VAL_YEARS)]
        te = ml_panel[ml_panel["year"] == y_test]
        if tr.empty or te.empty:
            continue
        model = XGBRankingModel(objective="rank:ndcg", **COMMON_KWARGS)
        model.fit(tr, tr["fwd_return"], val_panel=va, y_val=va["fwd_return"],
                  feature_cols=feature_cols)
        pred = te[["date", "symbol", "fwd_return"]].copy()
        pred["y_pred"] = model.predict(te)
        parts.append(pred)

    tr = ml_panel[ml_panel["year"].isin(train_years)
                  & ~ml_panel["year"].isin(INNER_VAL_YEARS)]
    va = ml_panel[ml_panel["year"].isin(INNER_VAL_YEARS)]
    pe = ml_panel[ml_panel["year"].isin(validation_years + INNER_VAL_YEARS)]
    if not tr.empty and not pe.empty:
        model = XGBRankingModel(objective="rank:ndcg", **COMMON_KWARGS)
        model.fit(tr, tr["fwd_return"], val_panel=va, y_val=va["fwd_return"],
                  feature_cols=feature_cols)
        pred = pe[["date", "symbol", "fwd_return"]].copy()
        pred["y_pred"] = model.predict(pe)
        parts.append(pred)

    if not parts:
        return pd.DataFrame(columns=["date", "symbol", "fwd_return", "y_pred"])
    return pd.concat(parts, ignore_index=True)


def _per_year_rank_ic(predictions: pd.DataFrame) -> Dict[int, float]:
    """Per-year mean daily cross-sectional Spearman Rank IC."""
    p = predictions.copy()
    p["date"] = pd.to_datetime(p["date"])
    p["year"] = p["date"].dt.year
    out: Dict[int, float] = {}
    for year, g in p.groupby("year"):
        ics: List[float] = []
        for _, gd in g.groupby("date"):
            if len(gd) >= 5 and gd["y_pred"].std() > 0 and gd["fwd_return"].std() > 0:
                ic = gd["y_pred"].rank().corr(gd["fwd_return"].rank())
                if np.isfinite(ic):
                    ics.append(float(ic))
        if ics:
            out[int(year)] = float(np.mean(ics))
    return out


def _paired_t(deltas: List[float]) -> Dict[str, Any]:
    """Paired t-test summary on a list of per-year ΔIC values."""
    from scipy import stats
    d = np.asarray(deltas, dtype=float)
    n = len(d)
    mean = float(d.mean()) if n else float("nan")
    std = float(d.std(ddof=1)) if n > 1 else float("nan")
    if n > 1 and std > 0:
        t_stat, p_val = stats.ttest_1samp(d, 0.0)
        se = std / np.sqrt(n)
        ci_half = stats.t.ppf(0.975, n - 1) * se
        ci = [mean - ci_half, mean + ci_half]
    else:
        t_stat, p_val, ci = float("nan"), float("nan"), [float("nan"), float("nan")]
    return {
        "n_years": n, "mean_delta_ic": mean, "std_delta_ic": std,
        "t_stat": float(t_stat), "p_value": float(p_val),
        "ci95": [float(ci[0]), float(ci[1])],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--k-grid", type=int, nargs="+", default=[6, 8, 12])
    ap.add_argument("--universe", choices=["executable", "expanded_v1", "expanded_v2"],
                    default="executable",
                    help="symbol universe (default executable = 79-symbol; "
                         "expanded_v1 = Phase-4 expanded)")
    ap.add_argument("--out", default="data/audit/chart_structure/phase2a_incremental_ic.json")
    args = ap.parse_args()

    t0 = time.time()
    logger.info("Building panel + baseline (non-family-T) factors [universe=%s]...",
                args.universe)
    panel, baseline_factors, mask, split_cfg = _build_panel(args.universe)
    logger.info("  panel %s, baseline factors %d (%.1fs)",
                panel["close"].shape, len(baseline_factors), time.time() - t0)

    fwd = purge_labels_at_boundary(
        compute_forward_returns(panel["close"], horizons=[21], mode="cc")[21],
        split_cfg,
    )
    train_years = sorted(set(_expand_year_entries(split_cfg.partition.train_years)))
    validation_years = sorted({vy.year for vy in split_cfg.partition.validation_years})

    # baseline OOF (K-independent — compute once)
    logger.info("Baseline (no family T): building ml_panel + OOF rank:ndcg...")
    base_ml, base_cols = build_ml_panel(baseline_factors, fwd,
                                        research_mask=mask, apply_rank=True)
    base_pred = _oof_predictions(base_ml, base_cols, train_years, validation_years)
    base_ic = _per_year_rank_ic(base_pred)
    logger.info("  baseline per-year IC: %s", {k: round(v, 4) for k, v in base_ic.items()})

    results: Dict[str, Any] = {}
    for k in args.k_grid:
        logger.info("─" * 60)
        logger.info("Treatment K=%d: family T + baseline...", k)
        famT = _family_t_at_k(panel["close"], panel["high"], panel["low"], k)
        treat_factors = dict(baseline_factors)
        treat_factors.update(famT)
        treat_ml, treat_cols = build_ml_panel(treat_factors, fwd,
                                              research_mask=mask, apply_rank=True)
        # B3 audit: treatment columns must differ from baseline by exactly
        # the 12 family-T factors.
        col_diff = set(treat_cols) - set(base_cols)
        treat_pred = _oof_predictions(treat_ml, treat_cols, train_years,
                                      validation_years)
        treat_ic = _per_year_rank_ic(treat_pred)
        years = sorted(set(base_ic) & set(treat_ic))
        deltas = [treat_ic[y] - base_ic[y] for y in years]
        stat = _paired_t(deltas)
        results[f"K={k}"] = {
            "k": k,
            "col_diff_count": len(col_diff),
            "col_diff_is_family_t": sorted(col_diff) == sorted(SWING_STRUCTURE_FEATURES),
            "per_year_ic_baseline": {str(y): base_ic[y] for y in years},
            "per_year_ic_treatment": {str(y): treat_ic[y] for y in years},
            "per_year_delta_ic": {str(y): d for y, d in zip(years, deltas)},
            "paired_t": stat,
        }
        logger.info("  K=%d: mean ΔIC=%+.5f  p=%.4f  CI95=[%+.5f,%+.5f]  n=%d",
                    k, stat["mean_delta_ic"], stat["p_value"],
                    stat["ci95"][0], stat["ci95"][1], stat["n_years"])

    # verdict (config-scoped per D2 / AC P2-A2): significant positive
    # incremental IC = mean ΔIC > 0 AND p < 0.05 for at least one K.
    sig_ks = [k for k, r in results.items()
              if r["paired_t"]["mean_delta_ic"] > 0
              and r["paired_t"]["p_value"] < 0.05]
    report = {
        "evaluation": "phase2a_incremental_ic",
        "verdict_scope": "config_scoped",
        "baseline": "RESEARCH_FACTORS minus 12 family-T swing_* factors, "
                    "Phase 1.6 canonical rank:ndcg, colsample_bytree=1.0 (B3)",
        "k_grid": args.k_grid,
        "results": results,
        "significant_positive_ks": sig_ks,
        "verdict": (
            f"family T shows significant positive incremental IC at K={sig_ks} "
            f"(this feature set + rank:ndcg config + 21d horizon)"
            if sig_ks else
            "family T (this 12-feature set + rank:ndcg config + 21d horizon) "
            "shows NO significant positive incremental IC on the K grid tested "
            "— config-scoped result, NOT a 'structure has no information' verdict"
        ),
        "wall_clock_s": time.time() - t0,
    }
    out_path = PROJ / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str))
    logger.info("Report -> %s", out_path)
    logger.info("VERDICT: %s", report["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
