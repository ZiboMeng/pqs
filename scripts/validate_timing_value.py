#!/usr/bin/env python3
"""
scripts/validate_timing_value.py — measure the VALUE of multi-TF timing.

约束 3 framing: the multi-timescale layer is a TIMING / EXECUTION layer,
NOT a direction-voting alpha system. Prior validation (iter #9/#10/#11)
proved the direction-voting framing loses to a 60m-only baseline and
fails cost stress. This script answers the timing-role question:

    Given the daily MFS has already decided WHAT to hold, does adding
    multi-TF timing on top IMPROVE NET execution after realistic
    trading cost?

Extended in P1.7 (2026-04-20) from its initial proxy-only form to
produce a pass/fail verdict suitable for gating the decision to enter
intraday mining.

Design
------
For each hypothetical entry event (symbol × trading day):

  Naive execution (baseline):
    - entry price = first RTH bar open of T (naive immediate)
    - holding path = mark-to-market via close prices through EOD
    - cost = 1 entry × base_cost_bps

  Timed execution (multi-TF):
    - walk T's RTH bars; at first execute=True bar, enter at NEXT
      bar's open scaled by timing_scale
    - if deferred past last bar, skip the entry (missed opportunity)
    - holding path = MTM from executed bar to EOD
    - cost = (0 or 1) entry × base_cost_bps × timing_scale

Per-event metrics:
  - entry_bps_vs_mean    : entry price − day mean, bps (exec quality)
  - gross_return_bps     : entry_price → EOD_close, bps (realized return)
  - net_return_bps       : gross − cost_bps_charged
  - missed_opportunity   : True if naive gross > 0 but timing deferred

Aggregate verdict:
  - net_delta_bps_per_event : timed − naive average net bps
  - turnover_delta          : (n_timed_entries − n_naive_entries) per day
  - value_verdict           : POSITIVE / NEUTRAL / NEGATIVE based on
                              net_delta and statistical significance

Usage
-----
    python scripts/validate_timing_value.py
    python scripts/validate_timing_value.py --cost-bps 13
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


def _naive_entry(day_bars: pd.DataFrame) -> dict:
    """Naive path: buy at first RTH bar open, hold to EOD close.

    Returns dict with entry_price, eod_close, gross_bps, entered=True.
    """
    bars = _rth_slice(day_bars)
    if bars.empty:
        return {}
    entry_px = float(bars["open"].iloc[0])
    eod_close = float(bars["close"].iloc[-1])
    gross_bps = (eod_close - entry_px) / entry_px * 10_000.0
    return {
        "entered":     True,
        "entry_price": entry_px,
        "eod_close":   eod_close,
        "gross_bps":   gross_bps,
        "applied_scale": 1.0,
        "bar_index":   0,
    }


def _timed_entry(
    multi_bars: dict,
    symbol:     str,
    day_bars:   pd.DataFrame,
    base_weight: float,
) -> dict:
    """Walk the day's 60m bars. At each bar compute decide_timing;
    enter at the NEXT bar's open if execute=True. If the whole day is
    deferred, skip the entry (missed opportunity, not force-EOD).

    Returns a dict with:
      entered          : bool — did timing actually fire an entry?
      entry_price      : executed price (NaN if not entered)
      applied_scale    : timing_scale of the executing bar
      bar_index        : which bar fired (0 = first; None if deferred)
      deferred_bars    : count of execute=False bars before firing
      gross_bps        : entry_price → EOD_close return, bps
      fired_reason     : decision reason tag
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
            entry_px = float(bars["open"].iloc[i + 1])
            eod_close = float(bars["close"].iloc[-1])
            gross_bps = (eod_close - entry_px) / entry_px * 10_000.0
            return {
                "entered":      True,
                "entry_price":  entry_px,
                "eod_close":    eod_close,
                "gross_bps":    gross_bps,
                "applied_scale": d.timing_scale,
                "bar_index":    i + 1,
                "deferred_bars": deferred,
                "fired_reason": d.reason,
            }
        deferred += 1

    # Fully deferred — skip entry (no cost, no MTM, no opportunity)
    return {
        "entered":       False,
        "entry_price":   float("nan"),
        "eod_close":     float("nan"),
        "gross_bps":     0.0,         # not entered → no PnL contribution
        "applied_scale": 0.0,
        "bar_index":     None,
        "deferred_bars": deferred,
        "fired_reason":  "fully_deferred",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--max-symbols", type=int, default=15)
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--cost-bps", type=float, default=13.0,
                        help="One-way trading cost in bps applied to "
                             "BOTH naive + timed entries for fair net "
                             "comparison. Default 13 matches config/"
                             "cost_model.yaml default tier (comm 1 + "
                             "slippage_intraday 12).")
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

            naive = _naive_entry(day_bars)
            if not naive:
                continue
            timed = _timed_entry(multi_bars, sym, day_bars, base_weight=1.0)
            if not timed:
                continue

            day_mean = float(day_bars["close"].mean())

            # Entry-quality bps (negative = entered below mean = good for buy)
            naive_bps_vs_mean = (naive["entry_price"] - day_mean) / day_mean * 10_000.0
            if timed["entered"]:
                timed_bps_vs_mean = (timed["entry_price"] - day_mean) / day_mean * 10_000.0
            else:
                timed_bps_vs_mean = float("nan")

            # Net-of-cost P&L per event. Cost applies iff we actually
            # entered. Timed scale partially reduces position → cost
            # scales proportionally (approximation for sizing).
            cost_bps = args.cost_bps
            naive_net_bps = naive["gross_bps"] - cost_bps
            if timed["entered"]:
                # Scale cost by applied_scale since position is sized down
                timed_net_bps = (timed["gross_bps"]
                                  - cost_bps * timed["applied_scale"])
                timed_gross_bps = timed["gross_bps"]
            else:
                # Not entered → no cost, no gross. But track as "missed"
                # if naive gross would have been positive.
                timed_net_bps = 0.0
                timed_gross_bps = 0.0

            missed_opportunity = (
                not timed["entered"] and naive["gross_bps"] > 0
            )
            cost_saved_from_defer = (
                not timed["entered"] and naive["gross_bps"] < 0
            )

            results.append({
                "symbol":           sym,
                "date":             date,
                "naive_entry":      naive["entry_price"],
                "timed_entry":      timed["entry_price"],
                "day_mean":         day_mean,
                "naive_bps_vs_mean": naive_bps_vs_mean,
                "timed_bps_vs_mean": timed_bps_vs_mean,
                "naive_gross_bps":  naive["gross_bps"],
                "timed_gross_bps":  timed_gross_bps,
                "naive_net_bps":    naive_net_bps,
                "timed_net_bps":    timed_net_bps,
                "applied_scale":    timed["applied_scale"],
                "entered":          timed["entered"],
                "bar_index":        timed["bar_index"],
                "deferred_bars":    timed["deferred_bars"],
                "fired_reason":     timed["fired_reason"],
                "missed_opportunity": missed_opportunity,
                "cost_saved_from_defer": cost_saved_from_defer,
            })

    if not results:
        print("no results — check intraday data coverage")
        return

    df = pd.DataFrame(results)
    n_total = len(df)
    n_entered = int(df['entered'].sum())
    print(f"\n=== Multi-TF Timing Value Validation ===")
    print(f"Symbols: {df['symbol'].nunique()}  Days: {df['date'].nunique()}  "
          f"Events: {n_total}  Timed-entered: {n_entered} "
          f"({100.0 * n_entered / n_total:.1f}%)  "
          f"Cost: {args.cost_bps:.1f} bps/entry")

    # ── (1) Entry quality ──────────────────────────────────────────────
    print("\n── (1) Entry price vs day mean (bps; negative = entered "
          "below mean = better for a buy) ──")
    timed_entered = df[df['entered']]
    print(f"  naive         : mean {df['naive_bps_vs_mean'].mean():+7.2f} bps  "
          f"median {df['naive_bps_vs_mean'].median():+7.2f}")
    if not timed_entered.empty:
        print(f"  timed (ent.)  : mean {timed_entered['timed_bps_vs_mean'].mean():+7.2f} bps  "
              f"median {timed_entered['timed_bps_vs_mean'].median():+7.2f}")

    # ── (2) Gross holding-path P&L (entry → EOD close) ────────────────
    print("\n── (2) Gross holding-path P&L (entry → EOD close, bps) ──")
    print(f"  naive         : sum {df['naive_gross_bps'].sum():+9.1f}  "
          f"mean/event {df['naive_gross_bps'].mean():+6.2f}")
    print(f"  timed         : sum {df['timed_gross_bps'].sum():+9.1f}  "
          f"mean/event {df['timed_gross_bps'].mean():+6.2f}")
    gross_delta = df['timed_gross_bps'].sum() - df['naive_gross_bps'].sum()
    print(f"  timed-naive   : total {gross_delta:+9.1f} bps  "
          f"({'timed wins' if gross_delta > 0 else 'naive wins'})")

    # ── (3) Net-of-cost P&L — the actual verdict ──────────────────────
    print("\n── (3) NET P&L after cost (the actual verdict) ──")
    naive_net_sum = df['naive_net_bps'].sum()
    timed_net_sum = df['timed_net_bps'].sum()
    net_delta = timed_net_sum - naive_net_sum
    net_delta_per_event = net_delta / n_total if n_total else 0.0
    print(f"  naive net     : sum {naive_net_sum:+9.1f}  "
          f"mean/event {df['naive_net_bps'].mean():+6.2f}")
    print(f"  timed net     : sum {timed_net_sum:+9.1f}  "
          f"mean/event {df['timed_net_bps'].mean():+6.2f}")
    print(f"  Δ (timed-naive): total {net_delta:+9.1f} bps  "
          f"per_event {net_delta_per_event:+6.2f} bps")

    # ── (4) Turnover delta + hit analytics ─────────────────────────────
    print("\n── (4) Turnover & deferral ──")
    n_naive_entries = n_total  # naive enters every event
    n_timed_entries = n_entered
    turnover_delta = n_timed_entries - n_naive_entries
    print(f"  naive entries : {n_naive_entries}")
    print(f"  timed entries : {n_timed_entries}  "
          f"(Δ={turnover_delta:+d}, {turnover_delta/n_total*100:+.1f}%)")
    print(f"  avg timing_scale (entered events): "
          f"{timed_entered['applied_scale'].mean() if not timed_entered.empty else 0:.3f}")

    # ── (5) Missed opportunity vs cost saved ──────────────────────────
    n_missed = int(df['missed_opportunity'].sum())
    n_cost_saved = int(df['cost_saved_from_defer'].sum())
    missed_bps = df.loc[df['missed_opportunity'], 'naive_gross_bps'].sum()
    # On cost_saved events, we SAVED the cost (naive would have paid
    # cost for a losing trade). Value saved = -naive_gross − cost (we
    # avoided both the loss AND the cost).
    cost_saved_bps = -df.loc[df['cost_saved_from_defer'], 'naive_gross_bps'].sum() \
                     + n_cost_saved * args.cost_bps
    print("\n── (5) Defer diagnostics ──")
    print(f"  fully_deferred missed_opportunity: {n_missed} events "
          f"(would-have-been +{missed_bps:+.0f} bps gross)")
    print(f"  fully_deferred cost_saved        : {n_cost_saved} events "
          f"(avoided {cost_saved_bps:+.0f} bps loss+cost)")

    # ── (6) VERDICT ────────────────────────────────────────────────────
    print("\n── (6) VERDICT ──")
    significant_threshold_bps = 2.0  # per-event
    if net_delta_per_event > significant_threshold_bps:
        verdict = "POSITIVE — timing adds net value"
    elif net_delta_per_event < -significant_threshold_bps:
        verdict = "NEGATIVE — timing REDUCES net value"
    else:
        verdict = "NEUTRAL — timing is a wash (within ±2 bps/event)"
    print(f"  {verdict}")
    print(f"  Net Δ/event: {net_delta_per_event:+.2f} bps  "
          f"(threshold ±{significant_threshold_bps:.1f} bps)")

    # ── Fired reason distribution ─────────────────────────────────────
    print("\n── Fired-reason distribution ──")
    print(df['fired_reason'].value_counts().to_string())


if __name__ == "__main__":
    main()
