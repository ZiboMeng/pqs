#!/usr/bin/env python3
"""
scripts/validate_timing_value.py — measure the VALUE of multi-TF timing.

约束 3 framing: the multi-timescale layer is a TIMING / EXECUTION layer,
NOT a direction-voting alpha system. Prior validation (iter #9/#10/#11)
proved the direction-voting framing loses to a 60m-only baseline and
fails cost stress. This script reframes the question:

    Given the daily MFS has already decided WHAT to hold, does adding
    multi-TF timing on top IMPROVE execution on metrics that matter:

      - entry slippage (actual entry price vs baseline naive entry)
      - turnover (fewer flips = less cost)
      - drawdown during execution window
      - pct of days where timing deferred (execute=False → saved a trade)

    Crucially, we do NOT measure CAGR/Sharpe of "direction voting"
    because that is not the role we want multi-TF to play.

Design
------
For each daily rebalance event where the daily MFS wants to BUY a
symbol at T+1 open:

  Naive execution (baseline):
    entry price = first 60m bar open of T+1

  Timed execution (multi-TF):
    walk through T+1's 60m bars; at each bar run decide_timing().
    If execute=True, enter at NEXT 60m bar's open.
    If execute=False for entire day, fall back to EOD close.
    Scale the position by timing_scale on the executing bar.

Compare:
  - mean entry price (naive) vs (timed)
  - avg timing_scale applied
  - pct of days timing deferred past the first bar
  - pct of days timing deferred until EOD (worst case)

Usage
-----
    python scripts/validate_timing_value.py
    python scripts/validate_timing_value.py --symbols SPY QQQ AAPL
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.intraday.multi_timescale import (
    build_context, decide_timing, load_multi_timescale_bars,
)
from core.logging_setup import setup_logging, get_logger

setup_logging()
logger = get_logger("validate_timing_value")


def _rth_slice(df: pd.DataFrame) -> pd.DataFrame:
    mins = df.index.hour * 60 + df.index.minute
    return df.loc[(mins > 9 * 60 + 30) & (mins <= 16 * 60)]


def _naive_entry_price(day_bars: pd.DataFrame) -> float | None:
    """First RTH bar's open — the baseline 'execute immediately' price."""
    bars = _rth_slice(day_bars)
    if bars.empty:
        return None
    return float(bars["open"].iloc[0])


def _timed_entry(
    multi_bars: dict,
    symbol:     str,
    day_bars:   pd.DataFrame,
    base_weight: float,
) -> dict:
    """Walk the day's 60m bars. At each bar compute decide_timing;
    enter at the NEXT bar's open if execute=True. If the whole day is
    deferred, fall back to EOD close.

    Returns:
      entry_price      : actual executed price
      applied_scale    : timing_scale of the executing bar
      bar_index        : which bar fired (0 = first RTH, -1 = EOD fallback)
      deferred_bars    : count of bars where execute=False before firing
    """
    bars = _rth_slice(day_bars)
    if bars.empty:
        return {}

    bar_times = bars.index
    n_bars = len(bar_times)
    deferred = 0
    for i in range(n_bars - 1):
        ts = bar_times[i]
        ctx = build_context(multi_bars, symbol, ts)
        d = decide_timing(ctx, symbol, base_weight=base_weight)
        if d.execute:
            return {
                "entry_price":   float(bars["open"].iloc[i + 1]),
                "applied_scale": d.timing_scale,
                "bar_index":     i + 1,
                "deferred_bars": deferred,
                "fired_reason":  d.reason,
            }
        deferred += 1

    # Fallback: never fired → EOD close at last bar
    return {
        "entry_price":   float(bars["close"].iloc[-1]),
        "applied_scale": 0.0,
        "bar_index":     -1,
        "deferred_bars": deferred,
        "fired_reason":  "eod_fallback",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--max-symbols", type=int, default=15)
    parser.add_argument("--start-date", default="2024-01-01")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    if args.symbols:
        symbols = list(args.symbols)
    else:
        uni = cfg.universe
        all_syms = list(dict.fromkeys(
            list(uni.seed_pool) + list(uni.sector_etfs) +
            list(uni.factor_etfs) + list(uni.cross_asset)
        ))
        symbols = [s for s in all_syms
                   if s not in uni.blacklist and s not in uni.macro_reference]
    symbols = symbols[: args.max_symbols]

    # Load 60m / 30m / 15m bars (5m optional — not all symbols have it)
    multi_bars = load_multi_timescale_bars(
        store, symbols, freqs=["60m", "30m", "15m"],
    )
    if "60m" not in multi_bars:
        print("no 60m data; aborting")
        return

    # Collect one "entry event" per (symbol, trading day) from the
    # available 60m coverage. Treat every day as a hypothetical entry —
    # the daily MFS would only actually buy on some of them, but for a
    # timing measurement we want a clean cross-section of all days.
    results = []
    for sym, df60 in multi_bars["60m"].items():
        df60 = _rth_slice(df60)
        if df60.empty:
            continue
        df60 = df60[df60.index >= args.start_date]
        all_dates = sorted(set(df60.index.date))
        for date in all_dates:
            mask = df60.index.date == date
            day_bars = df60[mask]
            if len(day_bars) < 3:
                continue

            naive_px = _naive_entry_price(day_bars)
            if naive_px is None:
                continue
            timed = _timed_entry(multi_bars, sym, day_bars, base_weight=1.0)
            if not timed:
                continue

            # What did timing save vs naive, measured in bps on the
            # difference between executed price and day's VWAP-proxy
            # (mean close)?
            day_mean = float(day_bars["close"].mean())
            naive_vs_mean = (naive_px - day_mean) / day_mean * 10_000
            timed_vs_mean = (timed["entry_price"] - day_mean) / day_mean * 10_000

            results.append({
                "symbol":          sym,
                "date":            date,
                "naive_entry":     naive_px,
                "timed_entry":     timed["entry_price"],
                "day_mean":        day_mean,
                "naive_bps_vs_mean":  naive_vs_mean,
                "timed_bps_vs_mean":  timed_vs_mean,
                "applied_scale":   timed["applied_scale"],
                "bar_index":       timed["bar_index"],
                "deferred_bars":   timed["deferred_bars"],
                "fired_reason":    timed["fired_reason"],
            })

    if not results:
        print("no results — check intraday data coverage")
        return

    df = pd.DataFrame(results)
    print(f"\n=== Multi-TF Timing Value Validation ===")
    print(f"Symbols: {df['symbol'].nunique()}  Days: {df['date'].nunique()}  "
          f"Events: {len(df)}")

    print("\n── Entry price vs day mean (bps; closer to 0 = entering at "
          "typical price; negative = entering BELOW day mean = good for "
          "a buy) ──")
    print(f"  naive  : mean {df['naive_bps_vs_mean'].mean():+7.2f} bps  "
          f"median {df['naive_bps_vs_mean'].median():+7.2f} bps")
    print(f"  timed  : mean {df['timed_bps_vs_mean'].mean():+7.2f} bps  "
          f"median {df['timed_bps_vs_mean'].median():+7.2f} bps")
    delta = df['timed_bps_vs_mean'] - df['naive_bps_vs_mean']
    print(f"  delta  : mean {delta.mean():+7.2f} bps  "
          f"median {delta.median():+7.2f} bps  "
          f"(negative = timing improved buy entry)")

    print("\n── Defer behavior ──")
    n_deferred_any = int((df['deferred_bars'] > 0).sum())
    n_eod = int((df['bar_index'] == -1).sum())
    print(f"  deferred ≥1 bar : {n_deferred_any}/{len(df)} "
          f"({100.0 * n_deferred_any / len(df):.1f}%)")
    print(f"  deferred to EOD : {n_eod}/{len(df)} "
          f"({100.0 * n_eod / len(df):.1f}%)")
    print(f"  avg timing_scale: {df['applied_scale'].mean():.3f}")

    print("\n── Fired reason distribution ──")
    print(df['fired_reason'].value_counts().to_string())


if __name__ == "__main__":
    main()
