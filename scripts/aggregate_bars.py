#!/usr/bin/env python3
"""
Aggregate 1m parquet → 5m / 15m / 30m / 60m / daily parquet.

Input:  pqs/data/intraday/1m/<SYMBOL>.parquet   (RAW, DatetimeIndex tz-naive ET)
Output: pqs/data/intraday/{5m,15m,30m,60m}/<SYMBOL>.parquet
        pqs/data/daily/<SYMBOL>.parquet

Bar labelling convention [2026-04-20: CHANGED]:
- Resample labels = RIGHT edge (bar CLOSE time). A 5m bar dated 09:35
  covers [09:30, 09:35] — i.e. `index==09:35` means "bar closed at 09:35".
- Previously was left-label; changed because downstream multi-timescale
  code naturally reasons about "latest completed bar at decision_time T"
  via `index <= T`, which is correct only when bar timestamp == close time.
- OHLCV aggregation: open=first, high=max, low=min, close=last, volume=sum, amount=sum.
- Daily uses Regular Trading Hours only (09:30–16:00 ET) to match yfinance daily convention.
- Intraday aggregates include extended hours (same coverage as input 1m).
"""
from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

DATA_ROOT = Path(os.path.expanduser("~/Documents/projects/pqs/data"))
SRC_1M = DATA_ROOT / "intraday" / "1m"

INTRADAY_FREQS = {
    "5m":  "5min",
    "15m": "15min",
    "30m": "30min",
    "60m": "60min",
}

OHLCV_AGG = {
    "open": "first",
    "high": "max",
    "low":  "min",
    "close": "last",
    "volume": "sum",
    "amount": "sum",
}


def resample_intraday(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 1m → rule (e.g. '5min') using RIGHT-labeled bars.
    Bar index = bar CLOSE timestamp. Preserves tz-naive ET index."""
    out = df.resample(rule, label="right", closed="right").agg(OHLCV_AGG)
    out = out.dropna(subset=["open", "high", "low", "close"], how="all")
    return out


def resample_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Resample 1m → daily using RTH bars only. Index = date (tz-naive).
    Bar label convention is moot here since we collapse to date afterwards.
    RTH filter extended to 16:00 inclusive to capture any closing print."""
    rth = df.between_time("09:30", "16:00")
    if rth.empty:
        return pd.DataFrame()
    out = rth.resample("1D", label="right", closed="right").agg(OHLCV_AGG)
    out = out.dropna(subset=["open", "high", "low", "close"], how="all")
    out.index = pd.DatetimeIndex(out.index.date, name="date")
    return out


def process_symbol(sym_file: Path) -> dict[str, int]:
    df = pd.read_parquet(sym_file)
    if df.empty:
        return {}
    # Ensure DatetimeIndex (convert from column if persisted flat)
    if "timestamp" in df.columns:
        df = df.set_index(pd.DatetimeIndex(df["timestamp"], name="timestamp")).drop(columns=["timestamp"])
    df = df.sort_index()

    counts: dict[str, int] = {}
    symbol_name = sym_file.stem

    for freq, rule in INTRADAY_FREQS.items():
        out_df = resample_intraday(df, rule)
        out_dir = DATA_ROOT / "intraday" / freq
        out_dir.mkdir(parents=True, exist_ok=True)
        out_df.to_parquet(out_dir / f"{symbol_name}.parquet", compression="snappy")
        counts[freq] = len(out_df)

    daily_df = resample_daily(df)
    if not daily_df.empty:
        daily_dir = DATA_ROOT / "daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        daily_df.to_parquet(daily_dir / f"{symbol_name}.parquet", compression="snappy")
        counts["daily"] = len(daily_df)
    return counts


def _safe_process(sym_file: Path) -> tuple[str, dict[str, int] | str]:
    try:
        return sym_file.stem, process_symbol(sym_file)
    except Exception as e:
        return sym_file.stem, f"ERROR: {type(e).__name__}: {e}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", help="Filter to specific symbols (stems, e.g. SPY AAPL)")
    ap.add_argument("--limit", type=int, help="Only process first N symbols (debug)")
    ap.add_argument("--workers", type=int, default=1,
                    help="Process symbols in parallel with N workers (default 1).")
    args = ap.parse_args()

    if not SRC_1M.exists():
        raise SystemExit(f"No 1m data at {SRC_1M}. Run build_bars_parquet.py first.")

    files = sorted(SRC_1M.glob("*.parquet"))
    if args.symbols:
        sym_set = set(args.symbols)
        files = [f for f in files if f.stem in sym_set]
    if args.limit:
        files = files[: args.limit]

    totals: dict[str, int] = {}
    errors: list[str] = []

    if args.workers <= 1:
        for f in tqdm(files, desc="aggregate", unit="sym"):
            sym, res = _safe_process(f)
            if isinstance(res, str):
                errors.append(f"{sym}: {res}")
                continue
            for k, v in res.items():
                totals[k] = totals.get(k, 0) + v
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_safe_process, f): f for f in files}
            for fut in tqdm(as_completed(futs), total=len(futs),
                            desc="aggregate", unit="sym"):
                sym, res = fut.result()
                if isinstance(res, str):
                    errors.append(f"{sym}: {res}")
                    continue
                for k, v in res.items():
                    totals[k] = totals.get(k, 0) + v

    print("\nDone. total rows written per freq:")
    for k, v in sorted(totals.items()):
        print(f"  {k}: {v:,}")
    if errors:
        print(f"\n{len(errors)} errors:")
        for e in errors[:20]:
            print(f"  {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors)-20} more")


if __name__ == "__main__":
    main()
