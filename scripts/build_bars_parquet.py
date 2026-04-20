#!/usr/bin/env python3
"""
Build unified raw 1m parquet from heterogeneous sources.

Sources:
  2015-2023: ~/Documents/projects/Data/1m/YYYY/YYYYMM/YYYYMMDD.gz
             (Polygon flat: ticker,volume,open,close,high,low,window_start(ns UTC),transactions)

  2024-01..2025-11: ~/Documents/projects/Data/1m/YYYY/YYYYMM/YYYYMMDD/<SYMBOL>.csv
             (exchange,symbol,open,high,low,close,amount,volume,bob,eob,type)

  2025-11..2025-12: /mnt/c/Users/Admin/Documents/projects/output/2025/YYYYMM/YYYYMMDD/
  2026-01..2026-04: /mnt/c/Users/Admin/Documents/projects/output/YYYYMM/YYYYMMDD/

Output (RAW, unadjusted — forward-adjust at read time via splits.parquet):
  pqs/data/intraday/1m/<SYMBOL>.parquet
  schema: DatetimeIndex 'timestamp' (tz-naive ET)
          columns [open, high, low, close] float32
                  [volume] int64
                  [amount] float64  (NaN for 2015-2023; dollar volume otherwise)

Phases:
  ingest     : read sources month-by-month, write per-symbol parquet to staging/<YYYY-MM>/
  consolidate: merge all staging months per-symbol → pqs/data/intraday/1m/<SYMBOL>.parquet
  all        : ingest then consolidate (default)

Resume: if staging/<YYYY-MM>/ exists with >0 files, that month is skipped.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
from tqdm import tqdm

SRC_WSL = Path(os.path.expanduser("~/Documents/projects/Data/1m"))
SRC_WIN = Path("/mnt/c/Users/Admin/Documents/projects/output")
OUT_ROOT = Path(os.path.expanduser("~/Documents/projects/pqs/data"))
OUT_1M = OUT_ROOT / "intraday" / "1m"
STAGING = OUT_1M / ".staging"
ET = "America/New_York"


def safe_symbol(sym: str) -> str:
    """Match pqs MarketDataStore sanitization: ^ and - → _."""
    return sym.replace("^", "_").replace("-", "_")


def list_month_sources(year: int, month: int):
    """Return [(date_str, kind, path), ...] in date order, preferring WSL over WIN."""
    yyyymm = f"{year:04d}{month:02d}"
    out: list[tuple[str, str, Path]] = []

    wsl_d = SRC_WSL / f"{year}" / yyyymm
    if wsl_d.exists():
        for entry in sorted(wsl_d.iterdir()):
            if entry.is_file() and entry.suffix == ".gz":
                out.append((entry.stem, "gz", entry))
            elif entry.is_dir():
                out.append((entry.name, "csv_folder", entry))
    if out:
        return out

    if year == 2025:
        win_d = SRC_WIN / "2025" / yyyymm
    else:
        win_d = SRC_WIN / yyyymm
    if win_d.exists():
        for entry in sorted(win_d.iterdir()):
            if entry.is_dir():
                out.append((entry.name, "csv_folder", entry))
    return out


def read_gz_day(path: Path) -> pd.DataFrame:
    """Read a Polygon flat gz (whole market for one day)."""
    df = pd.read_csv(
        path,
        compression="gzip",
        usecols=["ticker", "volume", "open", "close", "high", "low", "window_start"],
        dtype={
            "ticker": "string",
            "volume": "int64",
            "open": "float32",
            "close": "float32",
            "high": "float32",
            "low": "float32",
            "window_start": "int64",
        },
    )
    ts = pd.to_datetime(df["window_start"], unit="ns", utc=True)
    df["timestamp"] = ts.dt.tz_convert(ET).dt.tz_localize(None)
    df = df.rename(columns={"ticker": "symbol"})
    df["amount"] = float("nan")
    return df[["symbol", "timestamp", "open", "high", "low", "close", "volume", "amount"]]


_PACSV_INCLUDE = ["symbol", "open", "high", "low", "close", "amount", "volume", "bob"]
_PACSV_READ_OPTS = pacsv.ReadOptions(use_threads=True)
# Pin column types to avoid cross-file schema drift (int64 vs float64 for whole-number prices).
_PACSV_CONV_OPTS = pacsv.ConvertOptions(
    include_columns=_PACSV_INCLUDE,
    column_types={
        "symbol": pa.string(),
        "open": pa.float64(),
        "high": pa.float64(),
        "low": pa.float64(),
        "close": pa.float64(),
        "amount": pa.float64(),
        "volume": pa.float64(),  # NaN-safe; cast to int64 after clean
        "bob": pa.string(),
    },
)


def read_csv_day(day_dir: Path) -> pd.DataFrame:
    """Read a day folder of per-ticker CSVs (2024+ schema) using pyarrow for speed."""
    tables: list[pa.Table] = []
    for f in day_dir.iterdir():
        if f.suffix != ".csv":
            continue
        try:
            t = pacsv.read_csv(str(f), read_options=_PACSV_READ_OPTS,
                               convert_options=_PACSV_CONV_OPTS)
        except Exception as e:
            sys.stderr.write(f"WARN: failed to read {f}: {e}\n")
            continue
        if t.num_rows == 0:
            continue
        tables.append(t)
    if not tables:
        return pd.DataFrame()
    big = pa.concat_tables(tables, promote_options="default")
    out = big.to_pandas()
    # bob is like "2024-01-02 04:00:00-05:00" (tz-aware ET) → convert to tz-naive ET
    ts = pd.to_datetime(out["bob"], utc=True, format="ISO8601")
    out["timestamp"] = ts.dt.tz_convert(ET).dt.tz_localize(None)
    out["symbol"] = out["symbol"].astype("string")
    out["volume"] = out["volume"].fillna(0).astype("int64")
    return out[["symbol", "timestamp", "open", "high", "low", "close", "volume", "amount"]]


def _read_day_task(date_str: str, kind: str, path_str: str):
    """Worker: read one day's source → return dict[symbol → DataFrame (without symbol col)]."""
    p = Path(path_str)
    try:
        df = read_gz_day(p) if kind == "gz" else read_csv_day(p)
    except Exception as e:
        sys.stderr.write(f"ERROR reading {p}: {e}\n")
        return {}
    if df.empty:
        return {}
    return {str(sym): grp.drop(columns=["symbol"])
            for sym, grp in df.groupby("symbol", sort=False)}


def process_month(year: int, month: int, workers: int = 1, force: bool = False) -> int | None:
    """Ingest one month into staging/<YYYY-MM>/<SYMBOL>.parquet. Returns symbol count or None if skipped."""
    month_tag = f"{year:04d}-{month:02d}"
    stage_dir = STAGING / month_tag
    if (not force) and stage_dir.exists() and any(stage_dir.iterdir()):
        return None  # already done

    sources = list_month_sources(year, month)
    if not sources:
        return 0

    stage_dir.mkdir(parents=True, exist_ok=True)

    buckets: dict[str, list[pd.DataFrame]] = defaultdict(list)
    args = [(d, k, str(p)) for d, k, p in sources]

    if workers <= 1:
        results_iter = (_read_day_task(*a) for a in args)
        for day_groups in tqdm(results_iter, total=len(args),
                                desc=month_tag, unit="day", leave=False):
            for sym, grp in day_groups.items():
                buckets[sym].append(grp)
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_read_day_task, d, k, p): (d, k) for (d, k, p) in args}
            for fut in tqdm(as_completed(futs), total=len(futs),
                             desc=month_tag, unit="day", leave=False):
                day_groups = fut.result()
                for sym, grp in day_groups.items():
                    buckets[sym].append(grp)

    for sym, parts in buckets.items():
        mdf = pd.concat(parts, ignore_index=True)
        mdf = mdf.drop_duplicates(subset=["timestamp"], keep="last")
        mdf = mdf.sort_values("timestamp").reset_index(drop=True)
        mdf = mdf.astype({
            "open": "float32", "high": "float32", "low": "float32", "close": "float32",
            "volume": "int64", "amount": "float64",
        })
        mdf.to_parquet(stage_dir / f"{safe_symbol(sym)}.parquet",
                       compression="snappy", index=False)
    return len(buckets)


def consolidate() -> None:
    """Merge staging/<YYYY-MM>/<SYM>.parquet → intraday/1m/<SYM>.parquet."""
    if not STAGING.exists():
        sys.stderr.write(f"no staging dir at {STAGING}\n")
        return
    # Gather: safe_symbol → [month_file_paths]
    per_sym: dict[str, list[Path]] = defaultdict(list)
    for month_dir in sorted(STAGING.iterdir()):
        if not month_dir.is_dir():
            continue
        for f in month_dir.iterdir():
            if f.suffix == ".parquet":
                per_sym[f.stem].append(f)

    OUT_1M.mkdir(parents=True, exist_ok=True)
    for sym, files in tqdm(per_sym.items(), desc="consolidate", unit="sym"):
        parts = [pd.read_parquet(f) for f in sorted(files)]
        df = pd.concat(parts, ignore_index=True)
        df = df.drop_duplicates(subset=["timestamp"], keep="last")
        df = df.sort_values("timestamp").reset_index(drop=True)
        df = df.set_index(pd.DatetimeIndex(df["timestamp"], name="timestamp"))
        df = df.drop(columns=["timestamp"])
        df.to_parquet(OUT_1M / f"{sym}.parquet", compression="snappy")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["ingest", "consolidate", "all"], default="all")
    ap.add_argument("--year-start", type=int, default=2015)
    ap.add_argument("--year-end", type=int, default=2026)
    ap.add_argument("--month-only", type=str,
                    help="Process exactly one month (e.g. 201501). Implies --phase ingest.")
    ap.add_argument("--workers", type=int, default=1,
                    help="Parallel day-reading workers per month (default 1). Each worker uses ~0.5-1GB RAM for 2024+ CSV months.")
    ap.add_argument("--force", action="store_true", help="Reprocess even if staging exists")
    args = ap.parse_args()

    if args.month_only:
        y, m = int(args.month_only[:4]), int(args.month_only[4:])
        t0 = time.time()
        n = process_month(y, m, workers=args.workers, force=args.force)
        dt = time.time() - t0
        if n is None:
            print(f"{y}-{m:02d}: SKIP (already in staging)")
        else:
            print(f"{y}-{m:02d}: {n} symbols in {dt:.1f}s")
        return

    if args.phase in ("ingest", "all"):
        for y in range(args.year_start, args.year_end + 1):
            for m in range(1, 13):
                t0 = time.time()
                n = process_month(y, m, workers=args.workers, force=args.force)
                dt = time.time() - t0
                if n is None:
                    print(f"{y}-{m:02d}: skip", flush=True)
                elif n == 0:
                    pass  # no source
                else:
                    print(f"{y}-{m:02d}: {n} symbols in {dt:.1f}s", flush=True)

    if args.phase in ("consolidate", "all"):
        consolidate()


if __name__ == "__main__":
    main()
