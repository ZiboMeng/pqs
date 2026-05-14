"""T1c FOMC pre-announcement drift smoke test.

Hypothesis (Lucca-Moench 2015 J.Finance): SPX up ~49bps in 24h pre-FOMC.
Skeptic (FRL 2021): drift disappeared after 2015.

Quick informative-null test: long SPY from 2-bar-before to 1-bar-before FOMC,
sell at FOMC announcement (Wednesday close), no other days. Period 2017-2025.

If positive → revisit, build full T1c
If negative / near-zero → confirm signal dead, mark T1c as informative null
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import date

PROJ = Path("/home/zibo/Documents/projects/pqs")
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.data.bar_store import BarStore
from core.data.macro_event_calendar import (
    generate_fomc_dates_heuristic, load_calendar,
)


def main():
    print("=== T1c FOMC pre-announcement drift smoke ===")

    # Load FOMC dates 2017-2025
    fomc_dates = generate_fomc_dates_heuristic(2017, 2025)
    print(f"FOMC dates: {len(fomc_dates)} | range {fomc_dates[0].date()} → {fomc_dates[-1].date()}")
    print(f"Sample 2025: {[d.date() for d in fomc_dates if d.year == 2025][:8]}")

    # Load SPY
    store = BarStore()
    spy = store.load("SPY", freq="1d", adjusted=True).sort_index()
    spy = spy[(spy.index >= "2017-01-01") & (spy.index <= "2025-12-31")]
    print(f"SPY: {len(spy)} bars")

    # For each FOMC date, measure pre-announcement window return
    # Lucca-Moench: 24h before FOMC, so essentially T-1 close to T close.
    # We use 2-day window: T-2 close → T close.
    pre_returns = []
    for evt in fomc_dates:
        valid = spy.index[spy.index <= evt]
        if len(valid) < 3:
            continue
        # Snap to nearest prior business day
        evt_snapped = valid[-1]
        pos = spy.index.get_loc(evt_snapped)
        if pos < 2:
            continue
        # T-2 close, T-1 close, T close
        c_minus_2 = spy.iloc[pos - 2]["close"]
        c_minus_1 = spy.iloc[pos - 1]["close"]
        c_t = spy.iloc[pos]["close"]
        # Pre-announcement window: T-2 close to T close (~48h pre + announce day)
        ret_pre = (c_t - c_minus_2) / c_minus_2
        # Just T-1 to T (Lucca-Moench's 24h)
        ret_24h = (c_t - c_minus_1) / c_minus_1
        pre_returns.append({
            "fomc_date": evt_snapped.date(),
            "return_pre_48h": ret_pre,
            "return_pre_24h": ret_24h,
        })

    df = pd.DataFrame(pre_returns)
    print(f"\nFOMC windows analyzed: {len(df)}")
    print(f"\n=== Lucca-Moench-style pre-FOMC drift ===")
    print(f"Mean 24h return:   {df['return_pre_24h'].mean()*10000:+.1f} bps (Lucca-Moench claim: +49 bps)")
    print(f"Median 24h return: {df['return_pre_24h'].median()*10000:+.1f} bps")
    print(f"Hit rate 24h>0:    {(df['return_pre_24h']>0).mean()*100:.1f}%")
    print(f"Mean 48h return:   {df['return_pre_48h'].mean()*10000:+.1f} bps")

    # Per-year breakdown
    df["year"] = pd.to_datetime(df["fomc_date"]).dt.year
    by_year = df.groupby("year")["return_pre_24h"].agg(["count", "mean", "median"])
    by_year["mean_bps"] = by_year["mean"] * 10000
    by_year["median_bps"] = by_year["median"] * 10000
    print(f"\nPer-year (24h pre-FOMC):")
    print(by_year[["count", "mean_bps", "median_bps"]].round(1))

    # Simulate a "long SPY 24h pre-FOMC" strategy: 8 trades/year × ~0.1% gain
    # Compounded 9 years:
    if len(df) > 0:
        compounded = (1 + df["return_pre_24h"]).prod()
        print(f"\nCompound return if held SPY only on those {len(df)} pre-FOMC windows: {(compounded-1)*100:+.2f}%")
        years = (df["fomc_date"].max() - df["fomc_date"].min()).days / 365.25
        if years > 0:
            cagr = compounded ** (1/years) - 1
            print(f"Implied CAGR: {cagr*100:+.2f}%")

    # Verdict
    mean_24h_bps = df["return_pre_24h"].mean() * 10000
    print()
    if mean_24h_bps > 20:
        print(f"VERDICT: pre-FOMC drift ALIVE ({mean_24h_bps:.0f} bps > 20) — worth building full T1c")
    elif mean_24h_bps > 0:
        print(f"VERDICT: pre-FOMC drift WEAK ({mean_24h_bps:.0f} bps) — likely degraded post-2015")
    else:
        print(f"VERDICT: pre-FOMC drift DEAD or REVERSED ({mean_24h_bps:.0f} bps) — confirms FRL 2021")

    return 0


if __name__ == "__main__":
    sys.exit(main())
