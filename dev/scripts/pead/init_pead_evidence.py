"""Initialize PEAD trial 1 evidence-only forward observation.

User explicit-go 2026-05-14 "forward-init trial 1 as evidence-only".

Frozen spec: data/research_candidates/pead_sue_trial1_evidence_v1.yaml
Manifest:    data/research_candidates/pead_sue_trial1_evidence_v1_forward_manifest.json
Forward NAV: data/research_candidates/pead_sue_trial1_evidence_v1_forward_nav.parquet

This is a standalone observation track (does NOT use core/research/forward
main runner, which is built for factor-composite candidates). Manifest
schema mirrors the main runner's contract conceptually but with
PEAD-specific fields.

Idempotency: re-running without --overwrite is a no-op (preserves existing
manifest + NAV). With --overwrite, archives existing artifacts to
`.archived_<timestamp>` sidecar and writes fresh.

Usage:
    python dev/scripts/pead/init_pead_evidence.py
    python dev/scripts/pead/init_pead_evidence.py --overwrite
    python dev/scripts/pead/init_pead_evidence.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path("/home/zibo/Documents/projects/pqs")
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd
import yaml

from core.backtest.signal_driven_runner import SignalDrivenBacktest
from core.data.bar_store import BarStore
from core.data.edgar_provider import EdgarProvider
from core.execution.cost_model import CostModel
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.research.pead.earnings_dates import extract_earnings_dates_panel
from core.research.pead.sue_calculator import compute_sue_panel, build_sue_signal_panel

from dev.scripts.pead._pead_smoke_common import load_universe, build_panels


CANDIDATE_ID = "pead_sue_trial1_evidence_v1"
SPEC_PATH = PROJ / f"data/research_candidates/{CANDIDATE_ID}.yaml"
MANIFEST_PATH = PROJ / f"data/research_candidates/{CANDIDATE_ID}_forward_manifest.json"
NAV_PATH = PROJ / f"data/research_candidates/{CANDIDATE_ID}_forward_nav.parquet"


def _compute_spec_hash(spec: dict) -> str:
    """Canonical sha256 of frozen spec yaml (sorted keys, deterministic)."""
    canon = json.dumps(spec, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _build_frozen_panel(spec: dict, universe: list, start: str, end: str):
    """Build close + open panels per spec.panel_contract."""
    close_df, open_df = build_panels(universe, start=start, end=end, add_benchmark=False)
    return close_df, open_df


def _run_initial_backtest(spec, close_df, open_df, sue_panel, universe):
    """Run the strategy through history to capture initial NAV reference.

    This is the 'frozen baseline' — the NAV trajectory the candidate
    achieved before forward observation began. Forward TDs incrementally
    extend this NAV.
    """
    entry = build_sue_signal_panel(
        sue_panel,
        sue_threshold=spec["signal_spec"]["signal_threshold"]["sue_threshold_sigma"],
        price_index=close_df.index,
        universe=universe,
    )
    exit_ = entry.shift(
        spec["signal_spec"]["exit_rule"]["max_hold_business_days"]
    ).fillna(False).astype(bool)

    cost = CostModel(CostModelConfig(
        tiers={"default": CostTierConfig(
            symbols=[],
            commission_bps=spec["cost_model"]["commission_bps"],
            slippage_interday_bps=spec["cost_model"]["slippage_interday_bps"],
            slippage_intraday_bps=spec["cost_model"]["slippage_intraday_bps"],
        )}
    ))

    bt = SignalDrivenBacktest(
        entry_signals=entry,
        exit_signals=exit_,
        price_df=close_df,
        ttl_bars=spec["signal_spec"]["entry_mechanics"]["ttl_bars"],
        top_n=spec["construction"]["top_n"],
        cost_model=cost,
        initial_capital=spec["construction"]["initial_capital"],
        execution_delay_bars=spec["signal_spec"]["entry_mechanics"]["execution_delay_bars"],
        open_df=open_df,
    )
    result = bt.run()
    return result, int(entry.values.sum())


def _benchmark_navs(start, end):
    """SPY + QQQ NAV time series for the soak window."""
    store = BarStore()
    spy = store.load("SPY", freq="1d", adjusted=True).sort_index()
    qqq = store.load("QQQ", freq="1d", adjusted=True).sort_index()
    spy = spy.loc[pd.Timestamp(start):pd.Timestamp(end), "close"]
    qqq = qqq.loc[pd.Timestamp(start):pd.Timestamp(end), "close"]
    return spy, qqq


def _max_dd(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    peak = nav.cummax()
    return float(((nav - peak) / peak.replace(0, np.nan)).min())


def _archive_existing(path: Path):
    """Move existing file to .archived_<timestamp> sidecar."""
    if path.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
        archive = path.with_suffix(path.suffix + f".archived_{ts}")
        path.rename(archive)
        print(f"  Archived existing: {path.name} → {archive.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true",
                        help="Archive existing manifest/NAV and re-init")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan, do not write artifacts")
    args = parser.parse_args()

    print(f"=== Init PEAD evidence-only candidate: {CANDIDATE_ID} ===")

    if not SPEC_PATH.exists():
        print(f"ERROR: spec yaml not found at {SPEC_PATH}")
        return 1

    if MANIFEST_PATH.exists() and not args.overwrite:
        print(f"  Manifest already exists at {MANIFEST_PATH}")
        print(f"  Re-run with --overwrite to archive + re-init.")
        return 0

    spec = yaml.safe_load(SPEC_PATH.read_text())
    spec_hash = _compute_spec_hash(spec)
    print(f"  Spec hash (sha256): {spec_hash}")

    universe = load_universe()
    print(f"  Universe: {len(universe)} stocks")

    start = spec["panel_contract"]["start_date"]
    end = spec["panel_contract"]["end_date_at_freeze"]  # 2026-05-14 = freeze day
    print(f"  Initial backtest window: {start} → {end}")

    close_df, open_df = _build_frozen_panel(spec, universe, start=start, end=end)
    print(f"  Panel: close={close_df.shape}, open={open_df.shape}")

    edgar = EdgarProvider()
    print("  Extracting earnings dates from EDGAR cache...")
    earn = extract_earnings_dates_panel(universe, edgar_provider=edgar)
    print(f"    {len(earn)} earnings events across {earn['ticker'].nunique()} tickers")

    print("  Computing SUE panel...")
    sue = compute_sue_panel(earn)
    n_triggers_at_threshold = int(
        (sue["sue"].notna()
         & (sue["sue"] >= spec["signal_spec"]["signal_threshold"]["sue_threshold_sigma"])
        ).sum()
    )
    print(f"    SUE non-NaN: {sue['sue'].notna().sum()}/{len(sue)}; "
          f"≥1.5σ count: {n_triggers_at_threshold}")

    print("  Running initial backtest (frozen baseline)...")
    result, n_signals = _run_initial_backtest(spec, close_df, open_df, sue, universe)
    strat_nav = result.equity_curve
    n_trades = len(result.trades) if result.trades is not None else 0
    cagr = (strat_nav.iloc[-1] / strat_nav.iloc[0]) ** (
        365.25 / (strat_nav.index[-1] - strat_nav.index[0]).days
    ) - 1
    daily_ret = strat_nav.pct_change().dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0

    print(f"    Initial backtest result:")
    print(f"      n_signals: {n_signals}, n_trades: {n_trades}")
    print(f"      final equity: ${strat_nav.iloc[-1]:.2f}")
    print(f"      Sharpe: {sharpe:+.3f}, CAGR: {cagr*100:+.2f}%, MaxDD: {_max_dd(strat_nav)*100:+.2f}%")

    # Benchmark for TD0 comparison
    spy_nav, qqq_nav = _benchmark_navs(start, end)
    spy_final = spy_nav.iloc[-1] / spy_nav.iloc[0]
    strat_final_ratio = strat_nav.iloc[-1] / strat_nav.iloc[0]
    print(f"      vs SPY ratio: strat={strat_final_ratio:.4f} vs SPY={spy_final:.4f}")

    if args.dry_run:
        print("\n  [dry-run] No artifacts written.")
        return 0

    # Save initial NAV (parquet for future incremental appending)
    print(f"\n  Writing forward NAV: {NAV_PATH.name}")
    if NAV_PATH.exists() and args.overwrite:
        _archive_existing(NAV_PATH)
    nav_df = pd.DataFrame({
        "equity": strat_nav,
        "ts_phase": ["initial_baseline"] * len(strat_nav),
    })
    nav_df.to_parquet(NAV_PATH)

    # Build manifest TD000 (initial baseline observation)
    td000 = {
        "td_id": "TD000",
        "td_phase": "initial_baseline",
        "observation_date": str(strat_nav.index[-1].date()),
        "freeze_date": str(pd.Timestamp(end).date()),
        "strat_equity": float(strat_nav.iloc[-1]),
        "strat_cum_ret": float(strat_final_ratio - 1.0),
        "spy_cum_ret": float(spy_final - 1.0),
        "qqq_cum_ret": float(qqq_nav.iloc[-1] / qqq_nav.iloc[0] - 1.0),
        "n_signals_total_lifetime": int(n_signals),
        "n_trades_lifetime": int(n_trades),
        "frozen_baseline_sharpe": float(sharpe),
        "frozen_baseline_cagr": float(cagr),
        "frozen_baseline_max_dd": float(_max_dd(strat_nav)),
    }

    manifest = {
        "candidate_id": CANDIDATE_ID,
        "candidate_role": spec["candidate_role"],
        "strategy_type": spec["strategy_type"],
        "spec_hash_sha256": spec_hash,
        "spec_path": str(SPEC_PATH.relative_to(PROJ)),
        "nav_path": str(NAV_PATH.relative_to(PROJ)),
        "start_date": spec["forward_contract"]["start_date"],
        "freeze_date": spec["forward_contract"]["freeze_date"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "pead_evidence_v1",
        "current_status": "in_progress",
        "lifecycle_note": (
            "Evidence-only observation. Does NOT enter fleet allocation. "
            "Decision point TD60 ~ 2026-08-13."
        ),
        "panel_contract": spec["panel_contract"],
        "universe_size_at_freeze": len(universe),
        "earnings_events_at_freeze": int(len(earn)),
        "sue_triggers_threshold_at_freeze": n_triggers_at_threshold,
        "td_observations": [td000],
        "td_count": 1,
    }

    print(f"  Writing manifest: {MANIFEST_PATH.name}")
    if MANIFEST_PATH.exists() and args.overwrite:
        _archive_existing(MANIFEST_PATH)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str))

    print(f"\n=== Init complete ===")
    print(f"  candidate_id: {CANDIDATE_ID}")
    print(f"  candidate_role: {spec['candidate_role']}")
    print(f"  spec_hash: {spec_hash}")
    print(f"  start_date: {spec['forward_contract']['start_date']}")
    print(f"  freeze_date: {spec['forward_contract']['freeze_date']}")
    print(f"  TD000 baseline: Sharpe {sharpe:+.3f} / CAGR {cagr*100:+.2f}% / "
          f"MaxDD {_max_dd(strat_nav)*100:+.2f}%")
    print(f"\n  Next: post-NYSE close 2026-05-15 ET, run:")
    print(f"    python dev/scripts/pead/observe_pead_evidence.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
