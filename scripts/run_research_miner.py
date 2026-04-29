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
from typing import Optional
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.factors.base_masks import research_mask_default
from core.factors.factor_generator import (
    compute_forward_returns,
    generate_all_factors,
)
from core.factors.factor_registry import RESEARCH_FACTORS
from core.logging_setup import get_logger, setup_logging
from core.mining.rcm_archive import RCMArchive
from core.research.temporal_split import (
    compute_panel_max_date,
    compute_split_sha256,
    ensure_role_assigned,
    load_temporal_split,
    restrict_frames_to_train,
    validate_no_holdout_leakage,
)
from core.mining.research_miner import (
    FAMILIES_V1,
    ObjectiveWeights,
    ResearchMiner,
    all_family_factors,
)

setup_logging()
logger = get_logger("research_miner_cli")


def _load_price_volume(
    cfg, store, end_date: Optional[str] = None,
    drop_symbols: Optional[list] = None,
) -> dict[str, pd.DataFrame]:
    """Return {close, open, high, low, volume} DataFrames for the tradable
    universe + SPY/QQQ benchmarks.

    ``end_date`` (post-2026-04-26 audit, research-cycle pre-registration):
    if provided, filters the panel to dates ≤ end_date. Used by mining
    cycles that pre-register a panel cutoff per
    ``docs/memos/20260426-research_layer_partial_unfreeze.md`` §G4.

    ``drop_symbols`` (same audit): symbols to exclude from the panel
    even if present in universe.yaml. Used to honor a research-cycle
    criteria's ``drop_symbols`` declaration without modifying
    universe.yaml itself (which remains frozen under the partial
    unfreeze).
    """
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    # Include SPY & QQQ whether or not blacklisted (always needed as benchmarks)
    tradable = [s for s in all_syms
                if s not in uni.blacklist and s not in uni.macro_reference]
    if drop_symbols:
        drop_set = set(drop_symbols)
        tradable = [s for s in tradable if s not in drop_set]
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
    mask = out["close"].index >= pd.Timestamp(start)
    if end_date is not None:
        mask = mask & (out["close"].index <= pd.Timestamp(end_date))
    out["close"] = out["close"][mask]
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
        research_mask_default(close, volume)
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
    temporal_split_metadata: Optional[dict] = None,
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
    if temporal_split_metadata is not None:
        # Track A audit fields: split_sha256 + split_name + role + panel_max_date.
        # Trial-level archive metadata wiring is Step A.4; here we capture
        # them at run-summary level as authoritative provenance.
        summary["temporal_split"] = temporal_split_metadata
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
    parser.add_argument(
        "--end-date", default=None,
        help="ISO date upper bound on panel data (e.g. 2023-12-31). "
             "Used by mining cycles that pre-register a panel cutoff per "
             "docs/memos/20260426-research_layer_partial_unfreeze.md §G4.",
    )
    parser.add_argument(
        "--drop-symbols", nargs="*", default=None,
        help="Symbols to exclude from the panel (e.g. BRK-B). Used to "
             "honor research-cycle criteria's drop_symbols list without "
             "modifying universe.yaml (which is frozen under the "
             "partial unfreeze).",
    )
    parser.add_argument(
        "--temporal-split", default=None,
        help="Path to temporal_split.yaml (Track A v1). When provided, "
             "the panel is restricted to train_years and "
             "validate_no_holdout_leakage is enforced. --role becomes "
             "REQUIRED. Mutually compatible with --end-date (split "
             "takes precedence; end-date acts as additional cap).",
    )
    parser.add_argument(
        "--role", default=None,
        help="Candidate role under the temporal split (e.g. core, "
             "diversifier). REQUIRED when --temporal-split is given. "
             "Audit guard fail_closed_if_role_unspecified_at_mining_start "
             "+ M6 C1+C2 (pre-mining lock; no post-hoc reclassification).",
    )
    args = parser.parse_args()

    study_id = args.study or (
        "rcm-v1-run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    )
    logger.info("Study: %s  Lineage: %s  Trials: %d  Seed: %d",
                study_id, args.lineage, args.trials, args.seed)

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    # Track A: temporal split discipline. Mutually exclusive precondition:
    # --temporal-split requires --role; --role without --temporal-split
    # is silently ignored (legacy mining flow).
    split_cfg = None
    split_sha256 = None
    if args.temporal_split:
        split_cfg = load_temporal_split(Path(args.temporal_split))
        split_sha256 = compute_split_sha256(Path(args.temporal_split))
        # M6 C1+C2 + audit guard fail_closed_if_role_unspecified_at_mining_start
        ensure_role_assigned(args.role, split_cfg)
        logger.info(
            "Temporal split active: %s (sha256=%s) role=%s",
            split_cfg.split_name, split_sha256[:16], args.role,
        )

    logger.info("Loading price/volume frames...")
    if args.end_date:
        logger.info("Panel end_date cap: %s (G4 cutoff)", args.end_date)
    if args.drop_symbols:
        logger.info("Drop symbols: %s (criteria yaml drop_symbols)",
                    args.drop_symbols)
    frames, tradable = _load_price_volume(
        cfg, store,
        end_date=args.end_date,
        drop_symbols=args.drop_symbols,
    )

    # Track A: restrict panel to train years + validate no holdout leakage
    panel_max_date = None
    if split_cfg is not None:
        n_pre = frames["close"].shape[0]
        frames = restrict_frames_to_train(frames, split_cfg)
        validate_no_holdout_leakage(frames, split_cfg)
        n_post = frames["close"].shape[0]
        logger.info(
            "Temporal split filter: %d → %d rows (dropped %d holdout-year rows)",
            n_pre, n_post, n_pre - n_post,
        )
        pmd = compute_panel_max_date(frames)
        panel_max_date = pmd.isoformat() if pmd is not None else None
        logger.info("Panel max date (post-split): %s", panel_max_date)

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
        # Track A v1 fingerprint threading (None when --temporal-split absent)
        split_name=(split_cfg.split_name if split_cfg is not None else None),
        split_sha256=split_sha256,
        panel_max_date=panel_max_date,
        role=(args.role if split_cfg is not None else None),
        max_factor_lookback_days=(
            split_cfg.access_rules.factor_warmup_max_lookback_days
            if split_cfg is not None else None
        ),
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
    temporal_split_metadata = None
    if split_cfg is not None:
        temporal_split_metadata = {
            "split_name": split_cfg.split_name,
            "split_sha256": split_sha256,
            "split_yaml_path": str(args.temporal_split),
            "role": args.role,
            "panel_max_date": panel_max_date,
            "train_year_count": len(
                [y for y in range(2007, 2027)
                 if y in {x for entry in split_cfg.partition.train_years
                          for x in (range(entry.range[0], entry.range[1] + 1)
                                    if hasattr(entry, "range") else [entry.year])}]
            ),
        }
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
        temporal_split_metadata=temporal_split_metadata,
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
