#!/usr/bin/env python
"""Research Composite Miner v1 runner (PRD 20260424 §15 Step 6, R13).

Runs N Optuna trials of family-aware research composite sampling on the
79-symbol universe with 12 PRD features + existing RESEARCH_FACTORS.
Persists every trial to rcm_archive.db + Optuna state to rcm_optuna.db.
Writes top-K JSON + lineage summary to data/ml/research_miner/.

This runner is research-only: it does NOT promote to PRODUCTION_FACTORS,
does NOT touch config/production_strategy.yaml, does NOT mix with the
production mining archive.

Usage:
  python scripts/run_research_miner.py --trials 50 --study rcm-v1-run-01
  python scripts/run_research_miner.py --trials 200 --study rcm-v1-run-02 \
      --lineage post-2026-04-24-rcm-v1 --resume
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.factors.base_masks import research_mask
from core.factors.factor_generator import (
    compute_forward_returns,
    generate_all_factors,
)
from core.factors.factor_registry import RESEARCH_FACTORS
from core.logging_setup import get_logger, setup_logging
from core.mining.rcm_archive import RCMArchive
from core.mining.research_miner import (
    FAMILIES_V1,
    ObjectiveWeights,
    ResearchMiner,
    all_family_factors,
)

setup_logging()
logger = get_logger("research_miner_cli")


def _load_price_volume(cfg, store) -> dict[str, pd.DataFrame]:
    """Return {close, open, high, low, volume} DataFrames for the tradable
    universe + SPY/QQQ benchmarks.
    """
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    # Include SPY & QQQ whether or not blacklisted (always needed as benchmarks)
    tradable = [s for s in all_syms
                if s not in uni.blacklist and s not in uni.macro_reference]
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in tradable:
        df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    out = {}
    out["close"] = pd.DataFrame(frames["close"]).sort_index()
    for col in ("open", "high", "low", "volume"):
        if frames[col]:
            out[col] = pd.DataFrame(frames[col]).reindex_like(out["close"])
        else:
            out[col] = None
    # Start date
    start = cfg.backtest.start_date or "2007-01-02"
    out["close"] = out["close"][out["close"].index >= pd.Timestamp(start)]
    for col in ("open", "high", "low", "volume"):
        if out[col] is not None:
            out[col] = out[col].reindex(out["close"].index)
    return out, tradable


def _build_factor_panel_map(
    frames: dict, tradable: list[str], horizon: int = 21,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame, int]:
    """Generate factor panels + forward returns + research mask.

    Returns (factor_panel_map, fwd_returns_<horizon>d, mask, n_masked_out)
    """
    close = frames["close"]
    volume = frames["volume"]

    # Research mask (PRD §7): shared sample definition
    mask = (
        research_mask(close, volume, min_price=5.0, min_usd=20e6, window=20)
        if volume is not None else None
    )

    # Build benchmark_map from SPY + QQQ (columns of close)
    benchmark_map = {}
    for bench in ("SPY", "QQQ"):
        if bench in close.columns:
            benchmark_map[bench] = close[bench]

    factors = generate_all_factors(
        close,
        volume_df=volume,
        open_df=frames["open"], high_df=frames["high"], low_df=frames["low"],
        benchmark_map=benchmark_map,
    )
    # Restrict to RESEARCH_FACTORS set (the miner uses FAMILIES_V1 which is
    # a subset, but having the full RESEARCH_FACTORS available means users
    # can experiment with extending families)
    panel_map = {
        name: fdf for name, fdf in factors.items()
        if name in RESEARCH_FACTORS
    }

    # Forward returns: `horizon`-day CC return (default 21d = medium-term)
    fwd_all = compute_forward_returns(close, horizons=[horizon], mode="cc")
    fwd_h = fwd_all[horizon]

    n_masked_out = None
    if mask is not None:
        try:
            n_masked_out = int((~mask).sum().sum())
        except Exception:
            n_masked_out = None
    return panel_map, fwd_h, mask, n_masked_out


def _write_artifacts(
    out_dir: Path,
    study_id: str,
    lineage_tag: str,
    results,
    archive: RCMArchive,
    config_snapshot: dict,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    # top-K from archive (authoritative — includes persisted rows)
    top_df = archive.top_k(k=20, lineage_tag=lineage_tag)
    if len(top_df):
        top_df.to_parquet(out_dir / "top_20.parquet")
        top_df.to_csv(out_dir / "top_20.csv", index=False)

    lineage_df = archive.lineage_summary()
    lineage_df.to_csv(out_dir / "lineage_summary.csv", index=False)

    # Summary JSON
    summary = {
        "timestamp": ts,
        "lineage_tag": lineage_tag,
        "study_id": study_id,
        "config": config_snapshot,
        "archive_n_trials_for_lineage": archive.n_trials(lineage_tag=lineage_tag),
        "miner_in_memory_completed": len(results),
        "top_3_preview": (
            top_df.head(3).to_dict(orient="records") if len(top_df) else []
        ),
    }
    (out_dir / "run_summary.json").write_text(
        json.dumps(summary, indent=2, default=str)
    )
    logger.info("Artifacts written to %s", out_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research Composite Miner v1 (PRD 20260424)",
    )
    parser.add_argument("--trials", type=int, default=50,
                        help="Optuna trial count")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--study", default=None,
                        help="Optuna study_name (and miner study_id); "
                             "default = timestamped rcm-v1-run-<utc>")
    parser.add_argument("--lineage", default="post-2026-04-24-rcm-v1")
    parser.add_argument("--archive-db",
                        default="data/mining/rcm_archive.db")
    parser.add_argument("--optuna-db",
                        default="data/mining/rcm_optuna.db")
    parser.add_argument("--out-dir",
                        default="data/ml/research_miner")
    parser.add_argument("--resume", action="store_true",
                        help="Pass load_if_exists=True to Optuna")
    parser.add_argument("--min-families", type=int, default=3)
    parser.add_argument("--max-features-per-family", type=int, default=2)
    parser.add_argument("--horizon", type=int, default=21,
                        help="Forecast horizon in trading days (also used "
                             "for IC_IR annualization factor sqrt(252/h))")
    parser.add_argument("--sampler", default="tpe",
                        choices=["tpe", "random"],
                        help="Optuna sampler (R19: random for baseline check)")
    parser.add_argument("--lag", type=int, default=1,
                        help="Bars to shift composite before IC (R15: "
                             "1 prevents shared-close leakage; 0 allows "
                             "contemporaneous IC for benchmarking)")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    study_id = args.study or (
        "rcm-v1-run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    )
    logger.info("Study: %s  Lineage: %s  Trials: %d  Seed: %d",
                study_id, args.lineage, args.trials, args.seed)

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    logger.info("Loading price/volume frames...")
    frames, tradable = _load_price_volume(cfg, store)
    n_syms = frames["close"].shape[1]
    n_dates = frames["close"].shape[0]
    logger.info("Panel: %d dates × %d symbols (%d tradable)",
                n_dates, n_syms, len(tradable))

    logger.info("Generating factors (this takes 1-2 min)...")
    panel_map, fwd_h, mask, n_masked = _build_factor_panel_map(
        frames, tradable, horizon=args.horizon,
    )
    family_factor_names = all_family_factors(FAMILIES_V1)
    missing = family_factor_names - set(panel_map)
    if missing:
        logger.warning(
            "Family factors not present in panel_map — sampler will still "
            "generate but evaluate will raise KeyError on those: %s",
            sorted(missing),
        )
    panel_feature_count = len(panel_map)
    logger.info(
        "factor_panel_map: %d factors; 12 PRD features in catalog: %s",
        panel_feature_count,
        all(f in panel_map for f in [
            "rel_spy_20d", "rel_qqq_20d", "beta_spy_60d",
            "residual_mom_spy_20d", "range_pos_252d", "days_since_52w_high",
            "breakout_20d_strength", "dist_from_new_high_252",
            "amihud_20d", "downside_vol_20d", "vol_ratio_5_20",
            "trend_tstat_20d",
        ]),
    )
    if n_masked is not None:
        logger.info("Research mask: %d bar-symbol cells masked out", n_masked)

    logger.info("Opening archive: %s", args.archive_db)
    archive = RCMArchive(args.archive_db)

    logger.info("Building ResearchMiner...")
    miner = ResearchMiner(
        factor_panel_map=panel_map,
        fwd_returns=fwd_h,
        mask=mask,
        families=FAMILIES_V1,
        objective_weights=ObjectiveWeights(),
        min_families=args.min_families,
        max_features_per_family=args.max_features_per_family,
        horizon=args.horizon,
        lag=args.lag,
        archive=archive,
        lineage_tag=args.lineage,
        study_id=study_id,
    )

    logger.info(
        "Starting mining (Optuna storage: sqlite:///%s, study=%s, resume=%s)",
        args.optuna_db, study_id, args.resume,
    )
    optuna_storage = f"sqlite:///{args.optuna_db}"
    Path(args.optuna_db).parent.mkdir(parents=True, exist_ok=True)

    results = miner.mine(
        n_trials=args.trials, seed=args.seed,
        sampler=args.sampler,
        optuna_storage=optuna_storage, study_name=study_id,
        load_if_exists=args.resume,
    )
    logger.info("Completed: %d finite-objective trials (of %d attempted)",
                len(results), args.trials)

    # Report top-3 in-memory for immediate feedback
    for i, r in enumerate(results[:3], start=1):
        logger.info(
            "  #%d obj=%+.4f  IR=%+.3f  corr=%.3f  turn=%.3f  n_feat=%d  families=%s",
            i, r.objective, r.metrics.ic_ir,
            r.metrics.corr_concentration, r.metrics.turnover_proxy,
            r.spec.n_features, dict(r.spec.family_counts),
        )

    # Write artifacts
    out_root = Path(args.out_dir) / study_id
    _write_artifacts(
        out_root, study_id, args.lineage, results, archive,
        config_snapshot={
            "trials": args.trials, "seed": args.seed,
            "min_families": args.min_families,
            "max_features_per_family": args.max_features_per_family,
            "n_syms": int(n_syms), "n_dates": int(n_dates),
            "n_factors_in_panel": panel_feature_count,
            "fwd_return_horizon_days": int(args.horizon),
            "fwd_return_mode": "cc",
            "composite_lag_bars": int(args.lag),
        },
    )

    print("=" * 70)
    print(f"Research Composite Miner v1 — {study_id}")
    print(f"Lineage: {args.lineage}  Trials: {args.trials}")
    print("=" * 70)
    if results:
        print(f"Best objective: {results[0].objective:+.4f}")
        print(f"Best IC_IR:     {max(r.metrics.ic_ir for r in results):+.4f}")
        print(f"Archive rows under lineage: "
              f"{archive.n_trials(lineage_tag=args.lineage)}")
    else:
        print("No finite-objective trials (all pruned or failed).")
    print(f"\nArtifacts: {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
