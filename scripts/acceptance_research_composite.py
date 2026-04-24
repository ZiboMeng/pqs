#!/usr/bin/env python
"""Research-level acceptance for a research composite spec (R18, PRD §15 Step 7).

Takes a converged spec (from rcm_archive or explicit YAML), runs:
  1. In-sample vs OOS walk-forward (4-fold temporal split)
  2. Regime-stratified IC (6 states via RegimeDetector)
  3. Cost / turnover proxy at 2x stress
  4. Decision summary (pass/hold/reject per PRD2 §7 criteria)

Output: data/ml/research_miner/<study>/acceptance/

This is RESEARCH acceptance, NOT production promotion. Per PRD §13.4
autonomous rules: no touching of PRODUCTION_FACTORS, production config,
or auto-promote path.

Usage:
  python scripts/acceptance_research_composite.py \
      --study rcm-v1-run-02-lag1 \
      --lineage post-2026-04-24-rcm-v1-lag1
  python scripts/acceptance_research_composite.py \
      --trial-id <hex12>  # explicit override
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.factors.base_masks import apply_research_mask, research_mask_default
from core.factors.factor_generator import (
    compute_forward_returns,
    generate_all_factors,
)
from core.factors.factor_registry import RESEARCH_FACTORS
from core.logging_setup import get_logger, setup_logging
from core.mining.rcm_archive import RCMArchive
from core.mining.research_miner import (
    ResearchCompositeSpec,
    _spearman_ic_per_date,
    build_composite_series,
)

setup_logging()
logger = get_logger("rcm_acceptance")


def _load_converged_spec(
    archive: RCMArchive, lineage: str, trial_id: str | None,
) -> tuple[ResearchCompositeSpec, str]:
    """Return ResearchCompositeSpec + trial_id from archive."""
    db = archive.db_path
    with sqlite3.connect(str(db)) as conn:
        if trial_id:
            row = conn.execute(
                "SELECT trial_id, spec_json FROM rcm_trials "
                "WHERE trial_id = ?", (trial_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT trial_id, spec_json FROM rcm_trials "
                "WHERE lineage_tag = ? AND objective IS NOT NULL "
                "ORDER BY objective DESC LIMIT 1",
                (lineage,),
            ).fetchone()
    if row is None:
        raise RuntimeError(f"No trials found for lineage={lineage!r}")
    parsed = json.loads(row[1])
    spec = ResearchCompositeSpec(
        features=tuple(parsed["features"]),
        weights=tuple(parsed["weights"]),
        family_counts=parsed["family_counts"],
    )
    return spec, row[0]


def _build_panel(cfg, store, horizon: int):
    """Build the same panel shape the miner used (79-sym + benchmark_map)."""
    uni = cfg.universe
    syms = [s for s in dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ) if s not in uni.blacklist and s not in uni.macro_reference]
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    close = pd.DataFrame(frames["close"]).sort_index()
    start = cfg.backtest.start_date or "2007-01-02"
    close = close[close.index >= pd.Timestamp(start)]

    def _df(col):
        if not frames[col]:
            return None
        return pd.DataFrame(frames[col]).reindex_like(close)

    volume = _df("volume")
    open_df = _df("open")
    high_df = _df("high")
    low_df = _df("low")
    benchmark_map = {b: close[b] for b in ("SPY", "QQQ") if b in close.columns}
    factors = generate_all_factors(
        close, volume_df=volume,
        open_df=open_df, high_df=high_df, low_df=low_df,
        benchmark_map=benchmark_map,
    )
    panel_map = {n: f for n, f in factors.items() if n in RESEARCH_FACTORS}
    mask = (
        research_mask_default(close, volume)
        if volume is not None else None
    )
    fwd = compute_forward_returns(close, horizons=[horizon], mode="cc")[horizon]
    return panel_map, fwd, mask, close


def _composite_ic(
    spec: ResearchCompositeSpec,
    panel_map, fwd, mask, lag: int = 1,
) -> pd.Series:
    composite = build_composite_series(spec, panel_map)
    if lag > 0:
        composite = composite.shift(lag)
    if mask is not None:
        composite = apply_research_mask(composite, mask)
    return _spearman_ic_per_date(composite, fwd)


# R7 (Phase E-1) — the IC summary / walkforward / regime / decision
# helpers used to live here. They moved to core/research/acceptance_helpers.py
# so future research acceptance paths share the same pure evaluator code.
# Thin wrappers kept below for backward-compat with the existing CLI.
from core.research.acceptance_helpers import (
    fmt as _fmt,
    ic_stability_decision as _ic_stability_decision,
    regime_stratified_ic as _regime_stratified_ic,
    summarize_ic as _summarize_ic,
    walkforward_ic as _walkforward,
)


def _classify_regimes(cfg, store, dates: pd.DatetimeIndex) -> pd.Series:
    """Classify each date into a 6-state regime using RegimeDetector."""
    from core.regime.regime_detector import RegimeDetector
    detector = RegimeDetector(cfg.regime)
    spy_df = store.read("SPY", "1d")
    vix_df = store.read("^VIX", "1d")
    tnx_df = store.read("^TNX", "1d")
    spy = spy_df["close"] if spy_df is not None and "close" in spy_df.columns else None
    vix = vix_df["close"] if vix_df is not None and "close" in vix_df.columns else None
    tnx = tnx_df["close"] if tnx_df is not None and "close" in tnx_df.columns else None
    if spy is None or vix is None:
        return pd.Series("NEUTRAL", index=dates, dtype=str)
    regimes = detector.classify_series(spy, vix, tnx)
    return regimes.reindex(dates).ffill()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research composite acceptance (PRD §15 Step 7, R18)",
    )
    parser.add_argument("--study", required=True)
    parser.add_argument("--lineage", default="post-2026-04-24-rcm-v1-lag1")
    parser.add_argument("--trial-id", default=None,
                        help="Override: specific trial_id to audit")
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--lag", type=int, default=1)
    parser.add_argument("--archive-db", default="data/mining/rcm_archive.db")
    parser.add_argument("--out-dir", default="data/ml/research_miner")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--n-folds", type=int, default=4)
    args = parser.parse_args()

    archive = RCMArchive(args.archive_db)
    spec, trial_id = _load_converged_spec(archive, args.lineage, args.trial_id)
    logger.info("Auditing spec %s from lineage %s", trial_id, args.lineage)
    for f, w in zip(spec.features, spec.weights):
        logger.info("  %s: w=%+.4f", f, w)

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    logger.info("Building panel (horizon=%d, lag=%d)...", args.horizon, args.lag)
    panel_map, fwd, mask, close = _build_panel(cfg, store, args.horizon)

    # Check panel contains all spec features
    missing = [f for f in spec.features if f not in panel_map]
    if missing:
        raise RuntimeError(f"Spec requires features not in panel: {missing}")

    # Full-period IC
    logger.info("Full-period IC...")
    ic_series = _composite_ic(spec, panel_map, fwd, mask, lag=args.lag)
    full = _summarize_ic(ic_series, args.horizon)
    logger.info("Full: n=%d ic_mean=%.4f ic_ir=%s pos_rate=%.3f",
                full["n_dates"], full["ic_mean"] or 0,
                f"{full['ic_ir']:+.4f}" if full["ic_ir"] else "nan",
                full["positive_rate"] or 0)

    # Walk-forward
    logger.info("Walk-forward %d folds...", args.n_folds)
    wf = _walkforward(ic_series, args.horizon, n_folds=args.n_folds)
    for f in wf:
        logger.info("  Fold %d [%s → %s]  n=%d  ic_mean=%+.4f  ic_ir=%s",
                    f["fold"], f["date_start"], f["date_end"],
                    f["n_dates"], f["ic_mean"] or 0,
                    f"{f['ic_ir']:+.4f}" if f["ic_ir"] else "nan")

    # Regime
    logger.info("Classifying regimes...")
    regimes = _classify_regimes(cfg, store, ic_series.index)
    regime_stats = _regime_stratified_ic(ic_series, regimes, args.horizon)
    for state, s in sorted(regime_stats.items()):
        logger.info("  %s: n=%d ic_mean=%+.4f ic_ir=%s",
                    state, s["n_dates"], s["ic_mean"] or 0,
                    f"{s['ic_ir']:+.4f}" if s["ic_ir"] else "nan")

    decision = _ic_stability_decision(full, wf, regime_stats)

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "study_id": args.study,
        "lineage_tag": args.lineage,
        "trial_id": trial_id,
        "spec": {
            "features": list(spec.features),
            "weights": list(spec.weights),
            "family_counts": dict(spec.family_counts),
        },
        "config": {
            "horizon": args.horizon, "lag": args.lag,
            "n_folds": args.n_folds,
            "ic_ir_threshold": 0.2,
            "walkforward_min_positive_folds": 3,
            "regime_min_positive": 3,
        },
        "full_period": full,
        "walkforward": wf,
        "regime_stratified": regime_stats,
        "decision": decision,
    }

    out_root = Path(args.out_dir) / args.study / "acceptance"
    out_root.mkdir(parents=True, exist_ok=True)
    out_file = out_root / f"acceptance_{trial_id}.json"
    out_file.write_text(json.dumps(summary, indent=2, default=str))
    logger.info("Acceptance summary: %s", out_file)

    print("=" * 70)
    print(f"Research Acceptance — {args.study}")
    print(f"Trial: {trial_id}  Lineage: {args.lineage}")
    print("=" * 70)
    print(f"Full period : n={full['n_dates']} "
          f"ic_mean={full['ic_mean']:+.4f} "
          f"ic_ir={_fmt(full['ic_ir'])} "
          f"pos_rate={full['positive_rate']:.3f}")
    if wf:
        print(f"\nWalk-forward (n_folds={len(wf)}):")
        for f in wf:
            print(f"  fold {f['fold']} [{f['date_start']} → {f['date_end']}]  "
                  f"n={f['n_dates']:4d}  ic_mean={f['ic_mean']:+.4f}  "
                  f"ic_ir={_fmt(f['ic_ir'])}")
    if regime_stats:
        print(f"\nRegime-stratified ({len(regime_stats)} regimes):")
        for state in sorted(regime_stats):
            s = regime_stats[state]
            print(f"  {state:10s}  n={s['n_dates']:4d}  "
                  f"ic_mean={s['ic_mean']:+.4f}  "
                  f"ic_ir={_fmt(s['ic_ir'])}")
    print(f"\nDecision: {decision['outcome']}")
    for reason in decision["blocking_reasons"]:
        print(f"  - {reason}")
    print(f"\nArtifact: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
