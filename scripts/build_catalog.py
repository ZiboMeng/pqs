#!/usr/bin/env python3
"""
Build pqs/data/_catalog.parquet — per (symbol, freq) coverage summary.

Columns:
  symbol, freq, n_rows, first_ts, last_ts, bytes, months_span
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from tqdm import tqdm

DATA_ROOT = Path(os.path.expanduser("~/Documents/projects/pqs/data"))
FREQ_DIRS = {
    "1m":  DATA_ROOT / "intraday" / "1m",
    "5m":  DATA_ROOT / "intraday" / "5m",
    "15m": DATA_ROOT / "intraday" / "15m",
    "30m": DATA_ROOT / "intraday" / "30m",
    "60m": DATA_ROOT / "intraday" / "60m",
    "daily": DATA_ROOT / "daily",
}


def summarize_parquet(path: Path) -> dict:
    pf = pq.ParquetFile(path)
    n_rows = pf.metadata.num_rows
    size = path.stat().st_size
    first_ts = last_ts = None
    if n_rows:
        # Read the timestamp/date index from parquet metadata — can't cheaply
        # do with just metadata, so read the index column.
        # We stored DatetimeIndex; pyarrow exposes it via pandas_metadata/index.
        try:
            tbl = pq.read_table(path, columns=[])
            df = tbl.to_pandas()
            if len(df):
                first_ts, last_ts = df.index.min(), df.index.max()
        except Exception:
            pass
    return {"n_rows": n_rows, "bytes": size, "first_ts": first_ts, "last_ts": last_ts}


def main() -> None:
    argparse.ArgumentParser(
        description="Build pqs/data/_catalog.parquet — per (symbol, freq) coverage summary."
    ).parse_args()
    rows = []
    for freq, d in FREQ_DIRS.items():
        if not d.exists():
            continue
        files = sorted(d.glob("*.parquet"))
        for f in tqdm(files, desc=freq, unit="sym"):
            meta = summarize_parquet(f)
            months_span = None
            if meta["first_ts"] is not None and meta["last_ts"] is not None:
                span = (pd.Timestamp(meta["last_ts"]) - pd.Timestamp(meta["first_ts"])).days
                months_span = round(span / 30.44, 1)
            rows.append({
                "symbol": f.stem,
                "freq": freq,
                "n_rows": meta["n_rows"],
                "first_ts": meta["first_ts"],
                "last_ts": meta["last_ts"],
                "bytes": meta["bytes"],
                "months_span": months_span,
            })
    df = pd.DataFrame(rows)
    if df.empty:
        print("no data found")
        return
    out = DATA_ROOT / "_catalog.parquet"
    df.to_parquet(out, compression="snappy", index=False)
    print(f"\ncatalog written: {len(df)} entries → {out}")
    print(f"  total bytes: {df['bytes'].sum() / 1e9:.2f} GB")
    print(f"  per freq:")
    for freq, sub in df.groupby("freq"):
        print(f"    {freq:6s}: {len(sub)} symbols, {sub['n_rows'].sum():,} rows, {sub['bytes'].sum()/1e9:.2f} GB")


if __name__ == "__main__":
    main()
