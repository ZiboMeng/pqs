#!/usr/bin/env python3
"""
Validate our bar data vs yfinance by random walking.

Two tests:
  1. Intraday 1m: compare last 60 days of our 1m bars vs yfinance 1m download
     on a random universe subset (yfinance only serves ~60d of 1m).
  2. Daily: compare our aggregated daily vs yfinance daily over random windows
     for the full history we have (2015+).

Compares forward-adjusted prices (so dividends aside — both sides should be
split-adjusted; yfinance auto_adjust=True includes dividend adjustments which
we can't replicate without a dividend table, so we report OPEN/HIGH/LOW/CLOSE
relative differences and flag anomalies >0.5%).

Usage:
  python scripts/validate_vs_yfinance.py --freq 1m --n-symbols 8
  python scripts/validate_vs_yfinance.py --freq daily --n-symbols 10 --n-windows 5
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.data.bar_store import BarStore  # noqa: E402


UNIVERSE = [
    "SPY", "QQQ", "GLD", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "TQQQ", "SOXL", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU",
    "XLB", "XLRE", "XLC", "MTUM", "QUAL", "VLUE", "USMV", "SCHD",
    "TLT", "IEF", "SHY", "SLV",
]


def _pct_diff(a: pd.Series, b: pd.Series) -> pd.Series:
    denom = b.replace(0.0, np.nan).astype("float64")
    return (a.astype("float64") - b.astype("float64")).abs() / denom


def compare_daily(store: BarStore, symbol: str, n_windows: int, mode: str = "split") -> dict:
    """Random-walk windows across history; compare daily OHLC.

    Notes on adjustment semantics:
      * yfinance `Close` with auto_adjust=False is SPLIT-ADJUSTED (not raw).
      * yfinance `Close` with auto_adjust=True is SPLIT + DIVIDEND adjusted.
      * Our RAW is truly pre-split. Our ADJUSTED applies splits only (no divs).

    mode='split': our split-adj vs yfinance Close (auto_adjust=False). Expected EXACT match.
    mode='full':  our split-adj vs yfinance Close (auto_adjust=True). Expected divergence ≈ cumulative div yield.
    """
    import yfinance as yf
    # Always load our SPLIT-ADJUSTED series — yfinance's "raw" is already split-adj.
    ours = store.load(symbol, freq="daily", adjusted=True)
    if ours.empty:
        return {"symbol": symbol, "status": "NO_DATA_OURS"}
    auto_adjust = (mode == "full")

    first, last = ours.index.min(), ours.index.max()
    results = []
    for _ in range(n_windows):
        w_end = pd.Timestamp(random.choice(ours.index))
        w_start = w_end - pd.Timedelta(days=20)
        yf_df = yf.download(
            symbol,
            start=str(w_start.date()),
            end=str((w_end + pd.Timedelta(days=1)).date()),
            progress=False, auto_adjust=auto_adjust, threads=False,
        )
        if yf_df is None or yf_df.empty:
            continue
        if isinstance(yf_df.columns, pd.MultiIndex):
            yf_df.columns = yf_df.columns.get_level_values(0)
        yf_df.columns = [c.lower() for c in yf_df.columns]
        yf_df.index = pd.DatetimeIndex(yf_df.index.date)

        our_slice = ours.loc[(ours.index >= w_start) & (ours.index <= w_end)]
        merged = our_slice.join(yf_df, how="inner", lsuffix="_ours", rsuffix="_yf")
        if merged.empty:
            continue
        rec = {
            "symbol": symbol,
            "window": f"{w_start.date()}→{w_end.date()}",
            "n_days": len(merged),
        }
        for col in ("open", "high", "low", "close"):
            a = merged[f"{col}_ours"]
            b = merged[f"{col}_yf"]
            pd_ = _pct_diff(a, b).dropna()
            rec[f"{col}_med_%"] = round(pd_.median() * 100, 3) if len(pd_) else np.nan
            rec[f"{col}_max_%"] = round(pd_.max() * 100, 3) if len(pd_) else np.nan
        results.append(rec)
    return {"symbol": symbol, "results": results}


def compare_intraday_1m(store: BarStore, symbol: str, mode: str = "split") -> dict:
    """Compare 1m over the past ~55 days (within yfinance 60d limit)."""
    import yfinance as yf
    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=55)
    auto_adjust = (mode == "full")
    yf_df = yf.download(
        symbol, start=str(start.date()), end=str(end.date()),
        interval="1m", progress=False, auto_adjust=auto_adjust, threads=False,
    )
    if yf_df is None or yf_df.empty:
        return {"symbol": symbol, "status": "NO_YF_DATA"}
    if isinstance(yf_df.columns, pd.MultiIndex):
        yf_df.columns = yf_df.columns.get_level_values(0)
    yf_df.columns = [c.lower() for c in yf_df.columns]
    # yfinance 1m has tz-aware ET index; normalize to tz-naive ET
    if yf_df.index.tz is not None:
        yf_df.index = yf_df.index.tz_convert("America/New_York").tz_localize(None)

    ours = store.load(symbol, freq="1m", adjusted=True, start=start, end=end)
    if ours.empty:
        return {"symbol": symbol, "status": "NO_DATA_OURS"}

    merged = ours.join(yf_df, how="inner", lsuffix="_ours", rsuffix="_yf")
    if merged.empty:
        return {"symbol": symbol, "status": "NO_OVERLAP", "ours_range": (ours.index.min(), ours.index.max()),
                "yf_range": (yf_df.index.min(), yf_df.index.max())}
    rec = {"symbol": symbol, "n_bars_matched": len(merged),
           "ours_bars": len(ours), "yf_bars": len(yf_df)}
    for col in ("open", "high", "low", "close"):
        if f"{col}_ours" in merged.columns and f"{col}_yf" in merged.columns:
            pd_ = _pct_diff(merged[f"{col}_ours"], merged[f"{col}_yf"]).dropna()
            rec[f"{col}_med_%"] = round(pd_.median() * 100, 3) if len(pd_) else np.nan
            rec[f"{col}_p95_%"] = round(pd_.quantile(0.95) * 100, 3) if len(pd_) else np.nan
            rec[f"{col}_max_%"] = round(pd_.max() * 100, 3) if len(pd_) else np.nan
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freq", choices=["1m", "daily"], default="daily")
    ap.add_argument("--n-symbols", type=int, default=6)
    ap.add_argument("--n-windows", type=int, default=3, help="daily only")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--symbols", nargs="*", help="override random pick")
    ap.add_argument("--mode", choices=["split", "full"], default="split",
                    help="split: our split-adj vs yfinance Close (auto_adjust=False, also split-adj only) "
                         "— apples-to-apples, expect near-exact match. "
                         "full: our split-adj vs yfinance auto_adjust=True (incl dividends) — expect "
                         "divergence by cumulative div yield.")
    args = ap.parse_args()

    random.seed(args.seed)
    store = BarStore()
    available = set(store.list_symbols(args.freq))
    pool = [s for s in UNIVERSE if s in available]
    if not pool:
        sys.exit(f"No universe symbols available for freq={args.freq} in {store.root}")
    chosen = args.symbols or random.sample(pool, min(args.n_symbols, len(pool)))
    print(f"freq={args.freq} chosen={chosen}")

    print(f"mode={args.mode}")
    if args.freq == "daily":
        rows = []
        for sym in chosen:
            r = compare_daily(store, sym, args.n_windows, mode=args.mode)
            for rec in r.get("results", []):
                rows.append(rec)
        df = pd.DataFrame(rows)
        if df.empty:
            print("no comparisons collected")
        else:
            print(df.to_string(index=False))
    else:
        rows = []
        for sym in chosen:
            rows.append(compare_intraday_1m(store, sym, mode=args.mode))
        df = pd.DataFrame(rows)
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
