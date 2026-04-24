#!/usr/bin/env python3
"""
One-shot migration: backfill data/ref/bar_provenance.parquet with provenance
rows for all existing tickers that lack them.

Background:
  trades_scanner.py writes sidecar rows as it ingests. Earlier ingestion
  scripts (build_bars_parquet for polygon_gz 2015-2023 + stocks_csv 2024+,
  and the manual yfinance refresh for universe ETFs) did not write sidecar
  rows. This migration infers source_type from date ranges and writes rows.

Source heuristic per (symbol, date_range):
  - dates < 2024-01-01                             → polygon_gz
  - 2024-01-01 <= dates < 2025-12-01               → stocks_csv
  - dates >= 2025-12-01                            → stocks_csv_c_drive
  - ticker only in data/daily/, not in intraday/1m/ → yfinance_daily
  - existing rows with source_type='trades_backfill' are PRESERVED, and new
    rows do NOT duplicate date ranges they cover

After migration, every (ticker, freq) has at least one sidecar row.

Run once:
  python dev/scripts/migrations/migrate_provenance.py [--dry-run]

Idempotent-ish: re-running adds new rows (for dates beyond prior coverage)
without touching rows already in sidecar. `--reset-non-backfill` flag wipes
non-backfill rows before rewriting.
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from tqdm import tqdm

PQS_ROOT = Path(os.path.expanduser("~/Documents/projects/pqs"))
ROOT_1M = PQS_ROOT / "data" / "intraday" / "1m"
ROOT_DAILY = PQS_ROOT / "data" / "daily"
SIDECAR = PQS_ROOT / "data" / "ref" / "bar_provenance.parquet"
INTRADAY_FREQS = ("1m", "5m", "15m", "30m", "60m")

RULE_VERSION = "migration_v1_2026-04-20"

BOUNDARY_GZ_END = pd.Timestamp("2023-12-31")
BOUNDARY_STOCKS_CSV_END = pd.Timestamp("2025-11-30")


def _peek_ts_range(path: Path) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Return (min, max) index timestamps. Reads a single column so the
    pandas index (stored as separate index column in parquet) comes with it.
    """
    try:
        pf = pq.ParquetFile(path)
        if pf.metadata.num_rows == 0:
            return None
        # pick the first non-index column to read along with the pandas index
        cols = pf.schema.names
        payload = None
        for c in ("open", "close"):
            if c in cols:
                payload = c
                break
        if payload is None:
            for c in cols:
                if not c.startswith("__"):
                    payload = c
                    break
    except Exception:
        return None
    try:
        df = pd.read_parquet(path, columns=[payload] if payload else None)
        idx = df.index
        if len(idx) == 0:
            return None
        return pd.Timestamp(idx.min()), pd.Timestamp(idx.max())
    except Exception:
        return None


def _infer_rows(symbol: str, ts_min: pd.Timestamp, ts_max: pd.Timestamp,
                freq: str) -> list[dict]:
    """Infer source rows for a ticker's (ts_min, ts_max) date range.
    Returns list of rows (possibly multiple source epochs)."""
    rows = []
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    # normalize to date-compat
    min_d = pd.Timestamp(ts_min).normalize()
    max_d = pd.Timestamp(ts_max).normalize()

    def _row(source, start, end):
        return {
            "symbol": symbol, "freq": freq,
            "source_type": source, "rule_version": RULE_VERSION,
            "first_bar_ts": start, "last_bar_ts": end,
            "n_bars_added": 0,  # unknown; migration, not an actual ingest
            "updated_at": now,
        }

    # polygon_gz epoch: bars before 2024-01-01
    if min_d <= BOUNDARY_GZ_END:
        end_gz = min(max_d, BOUNDARY_GZ_END)
        rows.append(_row("polygon_gz", min_d, end_gz))
    # stocks_csv epoch (WSL source): 2024-01-01 to 2025-11-30
    if max_d > BOUNDARY_GZ_END and min_d <= BOUNDARY_STOCKS_CSV_END:
        start_csv = max(min_d, BOUNDARY_GZ_END + pd.Timedelta(days=1))
        end_csv = min(max_d, BOUNDARY_STOCKS_CSV_END)
        rows.append(_row("stocks_csv", start_csv, end_csv))
    # stocks_csv_c_drive epoch: 2025-12-01+
    if max_d > BOUNDARY_STOCKS_CSV_END:
        start_cd = max(min_d, BOUNDARY_STOCKS_CSV_END + pd.Timedelta(days=1))
        rows.append(_row("stocks_csv_c_drive", start_cd, max_d))
    return rows


def _process_file(args: tuple[str, str, str]) -> tuple[str, list[dict]]:
    """Worker: peek parquet range, infer rows. args=(symbol, freq, path_str)."""
    symbol, freq, path_str = args
    r = _peek_ts_range(Path(path_str))
    if r is None:
        return symbol, []
    ts_min, ts_max = r
    return symbol, _infer_rows(symbol, ts_min, ts_max, freq)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="scan + print count; don't write sidecar")
    ap.add_argument("--reset-non-backfill", action="store_true",
                    help="delete existing non-trades_backfill rows in sidecar "
                         "before writing (useful when rerunning with updated "
                         "heuristics)")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    # Collect work: every 1m parquet (propagates to 5m/15m/30m/60m) + daily.
    jobs: list[tuple[str, str, str]] = []
    if ROOT_1M.exists():
        for f in sorted(ROOT_1M.glob("*.parquet")):
            sym = f.stem
            # 1m canonical file → emit rows for 1m AND derived intraday freqs
            for freq in INTRADAY_FREQS:
                jobs.append((sym, freq, str(f)))
    # daily: may include yfinance-only tickers (e.g. _VIX, _TNX, DX_Y.NYB)
    daily_syms_from_1m = {f.stem for f in ROOT_1M.glob("*.parquet")} if ROOT_1M.exists() else set()
    if ROOT_DAILY.exists():
        for f in sorted(ROOT_DAILY.glob("*.parquet")):
            sym = f.stem
            jobs.append((sym, "daily", str(f)))

    print(f"scanning {len(jobs)} (symbol, freq) pairs with {args.workers} workers")

    # Track yfinance-only daily tickers (no 1m)
    yf_only_daily = {f.stem for f in ROOT_DAILY.glob("*.parquet") if ROOT_DAILY.exists()
                     } - daily_syms_from_1m if ROOT_DAILY.exists() else set()

    all_rows: list[dict] = []
    if args.workers <= 1:
        for j in tqdm(jobs, desc="scan"):
            sym, rows = _process_file(j)
            all_rows.extend(rows)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(_process_file, j) for j in jobs]
            for fut in tqdm(as_completed(futs), total=len(futs), desc="scan"):
                sym, rows = fut.result()
                all_rows.extend(rows)

    # Promote any yfinance-only daily tickers' rows to source_type=yfinance_daily
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    promoted = 0
    for r in all_rows:
        if r["freq"] == "daily" and r["symbol"] in yf_only_daily:
            r["source_type"] = "yfinance_daily"
            promoted += 1

    # Also add rows for universe ETFs that we explicitly refreshed from yfinance
    # (these co-exist with trades_backfill for intraday). See summary note.
    UNIVERSE_YF_REFRESHED = {  # from fetch step earlier
        "SPY","QQQ","GLD","AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA",
        "TQQQ","SOXL","XLK","XLF","XLE","XLV","XLI","XLY","XLP","XLU","XLB",
        "XLRE","XLC","MTUM","QUAL","VLUE","USMV","SCHD","TLT","IEF","SHY","SLV",
    }
    for r in all_rows:
        if r["freq"] == "daily" and r["symbol"] in UNIVERSE_YF_REFRESHED:
            # Downgrade the previously-inferred source to yfinance_daily since
            # daily/<sym>.parquet was overwritten from yfinance canonical fetch.
            r["source_type"] = "yfinance_daily"

    new_df = pd.DataFrame(all_rows)
    print(f"inferred {len(new_df)} new rows; yfinance-only daily: {len(yf_only_daily)}")
    print(f"source breakdown:\n{new_df['source_type'].value_counts().to_string()}")

    if args.dry_run:
        print("\n--- DRY RUN — sidecar not updated ---")
        print(new_df.head(10))
        return

    # Merge with existing sidecar: preserve trades_backfill rows, replace
    # non-backfill rows if --reset-non-backfill.
    if SIDECAR.exists():
        existing = pd.read_parquet(SIDECAR)
        print(f"existing sidecar: {len(existing)} rows")
        if args.reset_non_backfill:
            existing = existing[existing["source_type"] == "trades_backfill"]
            print(f"  kept trades_backfill only: {len(existing)} rows")
        else:
            # Don't duplicate: drop new rows that already have a matching
            # (symbol, freq, source_type) in existing.
            key = lambda d: list(zip(d["symbol"], d["freq"], d["source_type"]))
            existing_keys = set(key(existing))
            new_keys = set(key(new_df))
            new_to_keep = new_df[~pd.Series(key(new_df)).isin(existing_keys)]
            print(f"  deduped: {len(new_to_keep)}/{len(new_df)} new rows to add")
            new_df = new_to_keep
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    SIDECAR.parent.mkdir(parents=True, exist_ok=True)
    tmp = SIDECAR.with_suffix(".parquet.tmp")
    combined.to_parquet(tmp, compression="snappy")
    tmp.replace(SIDECAR)
    print(f"\n✅ wrote {len(combined)} rows to {SIDECAR}")
    print(f"source_type counts:\n{combined['source_type'].value_counts().to_string()}")


if __name__ == "__main__":
    main()
