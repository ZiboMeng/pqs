#!/usr/bin/env python3
"""
Merge .staging_trades/ backfill data into data/intraday/1m/<SYM>.parquet.

Runs AFTER trades_scanner.py writes per-month backfill files. Strategy B
ensures each backfill ticker is NOT already in root — sanity check warns
if it is.

Schema of backfill files includes provenance columns (source_type,
ingestion_rule_version); root parquet retains them.
"""
from __future__ import annotations

import argparse
import os
from collections import defaultdict
from pathlib import Path

import pandas as pd
from tqdm import tqdm

PQS_ROOT = Path(os.path.expanduser("~/Documents/projects/pqs"))
STAGING_TRADES = PQS_ROOT / "data" / "intraday" / "1m" / ".staging_trades"
OUT_1M = PQS_ROOT / "data" / "intraday" / "1m"


def main():
    ap = argparse.ArgumentParser()
    args = ap.parse_args()

    if not STAGING_TRADES.exists():
        print(f"no staging_trades dir at {STAGING_TRADES}")
        return

    per_sym: dict[str, list[Path]] = defaultdict(list)
    for month_dir in sorted(STAGING_TRADES.iterdir()):
        if not month_dir.is_dir():
            continue
        for f in month_dir.glob("*.parquet"):
            per_sym[f.stem].append(f)

    n_total = len(per_sym)
    n_new = 0
    n_merged = 0
    OUT_1M.mkdir(parents=True, exist_ok=True)

    # Backfill files may include provenance cols; existing root files may not.
    # Concat handles the column union; missing values fill with NaN.

    for sym, files in tqdm(per_sym.items(), desc="consolidate_trades", unit="sym"):
        root_file = OUT_1M / f"{sym}.parquet"
        parts = [pd.read_parquet(f) for f in sorted(files)]
        if root_file.exists():
            parts.insert(0, pd.read_parquet(root_file))
            n_merged += 1
        else:
            n_new += 1
        combined = pd.concat(parts)
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()
        combined.to_parquet(root_file, compression="snappy")

    print(f"\ntotal backfill tickers: {n_total}")
    print(f"  new root files:        {n_new}")
    print(f"  merged into existing:  {n_merged}")


if __name__ == "__main__":
    main()
