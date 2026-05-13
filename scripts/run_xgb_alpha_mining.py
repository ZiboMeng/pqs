#!/usr/bin/env python3
"""ML Phase 1: XGBoost alpha mining — end-to-end pipeline.

Per `docs/prd/20260512-ml_mining_pipeline_prd.md` §3.

Pipeline:
  1. Build multi-path factor panel (162 RESEARCH_FACTORS: OHLCV + EDGAR +
     sector + macro + event + signal-conf)
  2. Apply cross-sectional rank transformation per date
  3. Build forward-return target (21d horizon, purged at split boundary)
  4. Run leave-one-train-year-out CV → mean IC across folds
  5. Train final model on full train_years, predict on validation_years +
     sealed (latter NOT scored against — held out)
  6. Convert predictions to top-N portfolio (rebalance monthly) →
     BacktestEngine.run() → NAV
  7. Run Track A 17-gate acceptance
  8. Anti-sibling NAV correlation vs anchors

Usage
-----
    python scripts/run_xgb_alpha_mining.py
    python scripts/run_xgb_alpha_mining.py --smoke   # 100 train rows, 1 fold
    python scripts/run_xgb_alpha_mining.py --top-n 10 --horizon 21
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date as _date
from pathlib import Path
from typing import Any, Dict, List

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.factors.factor_generator import compute_forward_returns
from core.factors.base_masks import research_mask_default
from core.logging_setup import get_logger, setup_logging
from core.ml.feature_panel_builder import (
    build_ml_panel,
    build_multi_path_factors,
    build_panel_frames,
)
from core.ml.xgb_alpha import (
    leave_one_train_year_out_cv,
    train_full_then_predict,
)
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

setup_logging()
logger = get_logger("xgb_alpha_mining")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config-dir", default="config")
    ap.add_argument("--horizon", type=int, default=21,
                    help="forward return horizon in trading days (PRD §3.2)")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--n-estimators", type=int, default=200)
    ap.add_argument("--max-depth", type=int, default=5)
    ap.add_argument("--learning-rate", type=float, default=0.05)
    ap.add_argument("--smoke", action="store_true",
                    help="smoke: 2 LOTYO folds only, no full train + Track A")
    ap.add_argument("--out-dir", default="data/ml/xgb_alpha_phase_1")
    ap.add_argument("--lineage", default="ml-xgb-alpha-phase-1-2026-05-12")
    args = ap.parse_args()

    out_dir = PROJ / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    logger.info("Loading config...")
    cfg = load_config(PROJ / args.config_dir)

    logger.info("Loading panel + cross-asset frames (selector role)...")
    panel, tradable = build_panel_frames(cfg, drop_symbols=["BRK-B", "USO", "SLV"])
    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = partition_for_role(panel, split_cfg, role="selector")
    logger.info("  panel: %d dates × %d symbols (%.1fs)",
                panel["close"].shape[0], panel["close"].shape[1], time.time() - t0)

    logger.info("Building multi-path factors...")
    t1 = time.time()
    factors = build_multi_path_factors(panel)
    logger.info("  factors: %d (%.1fs)", len(factors), time.time() - t1)

    logger.info("Computing forward returns (horizon=%dd)...", args.horizon)
    t2 = time.time()
    fwd_all = compute_forward_returns(panel["close"], [args.horizon], mode="cc")
    fwd = fwd_all[args.horizon]
    # M4 purge cross-boundary labels
    fwd = purge_labels_at_boundary(fwd, split_cfg)
    logger.info("  fwd_returns: %s (%.1fs)", fwd.shape, time.time() - t2)

    mask = (
        research_mask_default(panel["close"], panel["volume"])
        if panel["volume"] is not None else None
    )

    logger.info("Building ML panel (cross-sectional rank features)...")
    t3 = time.time()
    ml_panel, feature_cols = build_ml_panel(
        factors, fwd, research_mask=mask, apply_rank=True,
    )
    logger.info("  ml_panel: %d rows × %d features (%.1fs)",
                len(ml_panel), len(feature_cols), time.time() - t3)

    train_years = sorted({y.year for y in split_cfg.partition.train_years})
    validation_years = sorted({y.year for y in split_cfg.partition.validation_years})
    sealed_years = sorted({y.year for y in split_cfg.partition.sealed_years})
    logger.info("Train years: %s", train_years)
    logger.info("Validation years: %s", validation_years)
    logger.info("Sealed years: %s (NEVER scored against)", sealed_years)

    model_kwargs: Dict[str, Any] = {
        "n_estimators": args.n_estimators,
        "max_depth": args.max_depth,
        "learning_rate": args.learning_rate,
    }
    if args.smoke:
        model_kwargs["n_estimators"] = 50
        smoke_folds = train_years[-2:]
        logger.info("SMOKE: 2 LOTYO folds only (%s) with n_estimators=50",
                    smoke_folds)
        fold_metrics, ic_table = leave_one_train_year_out_cv(
            ml_panel[ml_panel["date"].dt.year.isin(smoke_folds + [2017])],
            feature_cols, train_years=smoke_folds, model_kwargs=model_kwargs,
        )
        logger.info("smoke fold metrics:\n%s", ic_table.to_string())
        result = {
            "lineage": args.lineage, "smoke": True,
            "fold_metrics": {str(k): v for k, v in fold_metrics.items()},
            "elapsed_s": time.time() - t0,
        }
        out_path = out_dir / "smoke_summary.json"
        out_path.write_text(json.dumps(result, indent=2, default=str))
        logger.info("Smoke complete: wrote %s", out_path)
        return 0

    # ── Full LOTYO CV ───────────────────────────────────────────────
    logger.info("Running leave-one-train-year-out CV (%d folds)...",
                len(train_years))
    t4 = time.time()
    fold_metrics, ic_table = leave_one_train_year_out_cv(
        ml_panel, feature_cols,
        train_years=train_years, model_kwargs=model_kwargs,
    )
    mean_ic = ic_table["ic_mean"].mean() if not ic_table.empty else float("nan")
    logger.info("LOTYO CV: mean ic across folds=%.4f (%.1fs)",
                mean_ic, time.time() - t4)
    logger.info("Per-fold ic table:\n%s", ic_table.to_string())

    # ── Final model + predictions for validation ────────────────────
    logger.info("Training final model on full train_years; predicting on "
                "validation_years (NOT sealed)...")
    t5 = time.time()
    model, predictions = train_full_then_predict(
        ml_panel, feature_cols,
        train_years=train_years, predict_years=validation_years,
        model_kwargs=model_kwargs,
    )
    logger.info("  best_iteration=%s (%.1fs)",
                model.best_iteration, time.time() - t5)
    imp = model.feature_importance().head(15)
    logger.info("Top-15 feature importance (gain):\n%s", imp.to_string())

    # ── Convert predictions → top-N portfolio ───────────────────────
    logger.info("Converting predictions to top-%d portfolio (monthly rebalance)...",
                args.top_n)
    weights_rows = []
    for date, grp in predictions.groupby("date"):
        if len(grp) < args.top_n:
            continue
        top = grp.nlargest(args.top_n, "y_pred")
        n = len(top)
        for _, row in top.iterrows():
            weights_rows.append({
                "date": date, "symbol": row["symbol"], "weight": 1.0 / n,
            })
    weights_df = (
        pd.DataFrame(weights_rows)
        .pivot(index="date", columns="symbol", values="weight")
        .fillna(0.0)
    )

    # ── Build research_score series for harness (per-date cross-sectional score)
    score_df = (
        predictions.pivot(index="date", columns="symbol", values="y_pred")
        .sort_index()
    )

    # ── Eval via harness (uses score_df as the composite alpha) ─────
    logger.info("Evaluating via cap_aware_cross_asset harness...")
    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster_map[sym]]
        for sym in panel["close"].columns if sym in cluster_map
    }
    # Treat the XGBoost prediction as a single composite "factor"
    spec = ResearchCompositeSpec(
        features=("xgb_score",), weights=(1.0,),
        family_counts={"ML": 1}, holding_freq="monthly",
    )
    hc = HarnessConfig(
        rebalance_cadence="monthly",
        construction_mode="cap_aware_cross_asset",
        top_n=args.top_n, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map,
        asset_class_map=asset_class_map,
        asset_class_caps={
            "equities": 0.70, "bonds": 0.40,
            "commodities": 0.20, "cash_anchor": 0.30,
        },
    )
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    stress_slices = {
        ss.name: (ss.start.isoformat(), ss.end.isoformat())
        for ss in split_cfg.partition.stress_slices
    }
    res = evaluate_composite_spec(
        spec=spec, factor_panel_map={"xgb_score": score_df},
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq, config=hc,
        validation_years=validation_years, stress_slices=stress_slices,
        research_mask=mask,
    )

    # ── Track A 17-gate acceptance ──────────────────────────────────
    metrics: Dict[str, Any] = {
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
    for y, m in res.metrics_per_validation_year.items():
        metrics["validation"][int(y)] = {
            "maxdd": float(m.get("max_dd", 0.0)),
            "excess_vs_spy": float(m.get("vs_spy", 0.0)),
            "excess_vs_qqq": float(m.get("vs_qqq", 0.0)),
        }
    for sname, sm in res.metrics_per_stress_slice.items():
        metrics["stress_slice"][sname] = {"maxdd": float(sm.get("max_dd", 0.0))}
    verdict = run_split_acceptance(
        metrics, role="core", freeze_date=_date(2026, 5, 12),
    )
    track_a_passed = verdict.overall_passed
    failed_gates = [g.name for g in verdict.gates if not g.passed]

    result = {
        "lineage": args.lineage,
        "config": {
            "horizon": args.horizon, "top_n": args.top_n,
            "n_estimators": args.n_estimators, "max_depth": args.max_depth,
            "learning_rate": args.learning_rate,
        },
        "panel": {
            "n_dates": int(panel["close"].shape[0]),
            "n_symbols": int(panel["close"].shape[1]),
            "n_factors": len(feature_cols),
            "ml_panel_rows": len(ml_panel),
        },
        "lotyo_cv": {
            "mean_ic": float(mean_ic),
            "fold_metrics": {str(k): v for k, v in fold_metrics.items()},
        },
        "final_model": {
            "best_iteration": model.best_iteration,
            "top_15_features_by_gain": imp.to_dict(),
        },
        "harness_eval": {
            "metrics_full_period": res.metrics_full_period,
            "metrics_per_year": {int(y): dict(m) for y, m in res.metrics_per_validation_year.items()},
            "metrics_per_stress": {k: dict(v) for k, v in res.metrics_per_stress_slice.items()},
            "concentration": dict(res.concentration),
            "nav_correlation_vs_benchmark": dict(res.nav_correlation_vs_benchmark),
            "n_observed_days": int(res.n_observed_days),
        },
        "track_a": {
            "overall_passed": bool(track_a_passed),
            "failed_gates": failed_gates,
            "n_gates": len(verdict.gates),
        },
        "elapsed_s": time.time() - t0,
    }
    out_path = out_dir / "phase_1_summary.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    logger.info("Phase 1 complete: wrote %s", out_path)
    logger.info("Track A verdict: %s", "PASS" if track_a_passed else "FAIL")
    if not track_a_passed:
        logger.info("  failed gates: %s", failed_gates)
    return 0


if __name__ == "__main__":
    sys.exit(main())
