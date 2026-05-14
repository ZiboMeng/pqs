"""Observe PEAD trial 1 evidence-only candidate — append next TD.

Re-runs the frozen strategy from start_date to today's latest bar.
Appends one TD entry to the manifest with cumulative + incremental metrics.

Idempotent within a single trading day: re-running on the same EOD
appends only if the latest bar date is newer than the most recent TD's
observation_date. Otherwise no-op (with a notice).

Usage:
    python dev/scripts/pead/observe_pead_evidence.py
    python dev/scripts/pead/observe_pead_evidence.py --dry-run
"""

from __future__ import annotations

import argparse
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


def _max_dd(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    peak = nav.cummax()
    return float(((nav - peak) / peak.replace(0, np.nan)).min())


def _rolling_max_dd(nav: pd.Series, window_bd: int = 60) -> float:
    """Rolling max drawdown over the last `window_bd` business days."""
    if len(nav) < 2:
        return 0.0
    recent = nav.tail(window_bd)
    return _max_dd(recent)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results, do not write manifest/NAV")
    args = parser.parse_args()

    print(f"=== Observe PEAD evidence candidate: {CANDIDATE_ID} ===")

    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest not found at {MANIFEST_PATH}")
        print(f"  Run init first: python dev/scripts/pead/init_pead_evidence.py")
        return 1

    manifest = json.loads(MANIFEST_PATH.read_text())
    spec = yaml.safe_load(SPEC_PATH.read_text())

    if manifest.get("current_status") in ("completed_pass", "completed_fail",
                                            "aborted", "requires_data_review"):
        print(f"  Candidate status = {manifest['current_status']} (terminal). "
              f"Manual review required to proceed.")
        return 0

    start_date = pd.Timestamp(manifest["start_date"])
    freeze_date = pd.Timestamp(manifest["freeze_date"])
    print(f"  start_date: {start_date.date()}, freeze_date: {freeze_date.date()}")

    universe = load_universe()
    # Build close + open up to latest available bar
    close_df, open_df = build_panels(universe,
                                     start=spec["panel_contract"]["start_date"],
                                     end=str(pd.Timestamp.today().date()),
                                     add_benchmark=False)
    latest_bar = close_df.index[-1]
    print(f"  Latest bar in panel: {latest_bar.date()}")

    # Idempotency: skip if latest_bar <= most recent observation
    last_td = manifest["td_observations"][-1]
    last_obs_date = pd.Timestamp(last_td["observation_date"])
    if latest_bar <= last_obs_date:
        print(f"  Latest bar {latest_bar.date()} <= last observation "
              f"{last_obs_date.date()}. No new data. Exiting.")
        return 0

    edgar = EdgarProvider()
    earn = extract_earnings_dates_panel(universe, edgar_provider=edgar)
    sue = compute_sue_panel(earn)
    n_triggers = int(
        (sue["sue"].notna()
         & (sue["sue"] >= spec["signal_spec"]["signal_threshold"]["sue_threshold_sigma"])
        ).sum()
    )
    print(f"  Earnings events: {len(earn)}; SUE triggers ≥threshold: {n_triggers}")

    # Re-run strategy from start to latest_bar
    entry = build_sue_signal_panel(
        sue,
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
        entry_signals=entry, exit_signals=exit_,
        price_df=close_df, ttl_bars=0,
        top_n=spec["construction"]["top_n"],
        cost_model=cost,
        initial_capital=spec["construction"]["initial_capital"],
        execution_delay_bars=1, open_df=open_df,
    )
    result = bt.run()
    strat_nav = result.equity_curve

    # Slice forward portion (post-start_date)
    forward_nav = strat_nav[strat_nav.index >= start_date]
    if len(forward_nav) == 0:
        print(f"  No bars yet past start_date {start_date.date()}. Waiting.")
        return 0

    # Benchmark forward NAV
    store = BarStore()
    spy_df = store.load("SPY", freq="1d", adjusted=True).sort_index()
    qqq_df = store.load("QQQ", freq="1d", adjusted=True).sort_index()
    spy_fwd = spy_df.loc[forward_nav.index[0]:forward_nav.index[-1], "close"]
    qqq_fwd = qqq_df.loc[forward_nav.index[0]:forward_nav.index[-1], "close"]

    fwd_strat_ratio = float(forward_nav.iloc[-1] / forward_nav.iloc[0] - 1.0)
    fwd_spy_ratio = float(spy_fwd.iloc[-1] / spy_fwd.iloc[0] - 1.0) if len(spy_fwd) >= 2 else 0.0
    fwd_qqq_ratio = float(qqq_fwd.iloc[-1] / qqq_fwd.iloc[0] - 1.0) if len(qqq_fwd) >= 2 else 0.0
    fwd_max_dd_60d = _rolling_max_dd(forward_nav, window_bd=60)
    fwd_max_dd_full = _max_dd(forward_nav)
    fwd_daily_ret = forward_nav.pct_change().dropna()
    fwd_sharpe = (float(fwd_daily_ret.mean() / fwd_daily_ret.std() * np.sqrt(252))
                  if fwd_daily_ret.std() > 0 else 0.0)

    n_trades_lifetime = len(result.trades) if result.trades is not None else 0
    n_signals_lifetime = int(entry.values.sum())

    td_index = len(manifest["td_observations"])  # TD000 was init, TD001 first forward
    td_id = f"TD{td_index:03d}"

    td_entry = {
        "td_id": td_id,
        "td_phase": "forward_observation",
        "observation_date": str(latest_bar.date()),
        "strat_equity": float(forward_nav.iloc[-1]),
        "forward_cum_ret": fwd_strat_ratio,
        "forward_cum_ret_spy": fwd_spy_ratio,
        "forward_cum_ret_qqq": fwd_qqq_ratio,
        "forward_excess_vs_spy": fwd_strat_ratio - fwd_spy_ratio,
        "forward_excess_vs_qqq": fwd_strat_ratio - fwd_qqq_ratio,
        "forward_sharpe_annualized": fwd_sharpe,
        "forward_max_dd_full": fwd_max_dd_full,
        "forward_rolling_max_dd_60d": fwd_max_dd_60d,
        "n_forward_trading_days": int(len(forward_nav)),
        "n_signals_total_lifetime": n_signals_lifetime,
        "n_trades_lifetime": int(n_trades_lifetime),
        "sue_triggers_total_lifetime": n_triggers,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }

    print(f"\n  {td_id} (forward day {len(forward_nav)}):")
    print(f"    observation_date: {td_entry['observation_date']}")
    print(f"    forward cum_ret: {fwd_strat_ratio*100:+.2f}%")
    print(f"    forward vs SPY: {td_entry['forward_excess_vs_spy']*100:+.2f}% "
          f"(SPY {fwd_spy_ratio*100:+.2f}%)")
    print(f"    forward vs QQQ: {td_entry['forward_excess_vs_qqq']*100:+.2f}% "
          f"(QQQ {fwd_qqq_ratio*100:+.2f}%)")
    print(f"    forward Sharpe (annualized): {fwd_sharpe:+.3f}")
    print(f"    forward MaxDD: {fwd_max_dd_full*100:+.2f}% "
          f"(60d rolling: {fwd_max_dd_60d*100:+.2f}%)")
    print(f"    lifetime signals: {n_signals_lifetime}, trades: {n_trades_lifetime}")

    if args.dry_run:
        print("\n  [dry-run] No manifest/NAV write.")
        return 0

    # Append to manifest
    manifest["td_observations"].append(td_entry)
    manifest["td_count"] = len(manifest["td_observations"])
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str))

    # Append forward NAV (update parquet — overwrite with combined)
    nav_df = pd.DataFrame({
        "equity": strat_nav,
        "ts_phase": ["initial_baseline"] * (len(strat_nav) - len(forward_nav)) +
                    ["forward_observation"] * len(forward_nav),
    })
    nav_df.to_parquet(NAV_PATH)

    print(f"\n  Wrote: {MANIFEST_PATH.name} ({manifest['td_count']} TDs)")
    print(f"  Wrote: {NAV_PATH.name} ({len(nav_df)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
