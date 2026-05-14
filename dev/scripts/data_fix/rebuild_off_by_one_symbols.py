"""Rebuild data/daily/<SYM>.parquet for SPY/BIL/SHV — fixing off-by-one date labels.

Per postmortem `docs/memos/20260513-spy_off_by_one_date_label_postmortem.md`,
these 3 PQS-active-universe symbols have +1 day label offset for
2007/2009-2026-04-19 ingest. The root cause was align_daily_index
(`core/data/calendar.py`) doing tz_localize(None) without prior
tz_convert(ET), which on UTC-midnight yfinance bars produced +1 day labels.

Fix shipped 2026-05-13 to align_daily_index. This script re-fetches
the affected symbols using the FIXED code path.

Strategy:
- Use YFinanceProvider (which now calls the fixed align_daily_index)
- Save raw (auto_adjust=False) data to data/daily/<sym>.parquet
- Preserve same OHLCV column schema
- Validate: 0 weekend rows after rebuild
- Update bar_provenance.parquet

Usage:
    python dev/scripts/data_fix/rebuild_off_by_one_symbols.py [--symbols SPY,BIL,SHV] [--start 2007-01-01]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

# Path imports for project root
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.data.yfinance_provider import YFinanceProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("rebuild")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DAILY_DIR = PROJECT_ROOT / "data" / "daily"
DEFAULT_SYMBOLS = ["SPY", "BIL", "SHV"]


def fetch_one(sym: str, start: str, end: str) -> pd.DataFrame:
    """Use the fixed YFinanceProvider to fetch a clean panel."""
    prov = YFinanceProvider(auto_adjust=False)
    result = prov.fetch_daily([sym], start=start, end=end)
    if sym not in result:
        raise RuntimeError(f"no data returned for {sym}")
    df = result[sym].df  # OHLCVFrame.df is the underlying DataFrame
    if df is None or df.empty:
        raise RuntimeError(f"empty frame for {sym}")
    # Standardize column order (existing parquet schema): open, high, low, close, volume, amount
    needed = ["open", "high", "low", "close", "volume"]
    for c in needed:
        if c not in df.columns:
            raise RuntimeError(f"{sym} missing column {c}; got {df.columns.tolist()}")
    df = df[needed].copy()
    df["amount"] = 0.0  # legacy column, preserved as 0 (not used downstream)
    return df


def validate_clean(df: pd.DataFrame, sym: str) -> None:
    """Assert no weekend rows + sorted ascending + no duplicates."""
    if df.empty:
        raise AssertionError(f"{sym}: empty")
    weekends = df[df.index.dayofweek.isin([5, 6])]
    if len(weekends) > 0:
        raise AssertionError(
            f"{sym}: {len(weekends)} weekend rows still present after rebuild "
            f"(first: {weekends.index[0].date()})"
        )
    if not df.index.is_monotonic_increasing:
        raise AssertionError(f"{sym}: index not sorted")
    if df.index.duplicated().any():
        raise AssertionError(f"{sym}: duplicate dates")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS),
                        help="comma-separated symbols (default: SPY,BIL,SHV)")
    parser.add_argument("--start", default="2007-01-01")
    parser.add_argument("--end", default=str(date.today()))
    parser.add_argument("--dry-run", action="store_true", help="fetch + validate, no write")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    log.info("Rebuilding %d symbols: %s | %s..%s | dry-run=%s",
             len(symbols), symbols, args.start, args.end, args.dry_run)

    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    for sym in symbols:
        target = DAILY_DIR / f"{sym}.parquet"
        backup = DAILY_DIR / f"{sym}.parquet.preFix_2026-05-13"
        log.info("=== %s ===", sym)

        # Backup existing parquet (idempotent — don't overwrite an existing backup)
        if target.exists() and not backup.exists():
            target.replace(backup)
            log.info("backed up old %s → %s", target.name, backup.name)

        df = fetch_one(sym, args.start, args.end)
        validate_clean(df, sym)
        log.info("%s: fetched %d rows | %s..%s | 0 weekend rows ✓",
                 sym, len(df), df.index.min().date(), df.index.max().date())

        if args.dry_run:
            log.info("DRY-RUN: not writing %s", target.name)
            # Restore backup if dry-run
            if backup.exists() and not target.exists():
                backup.replace(target)
        else:
            df.to_parquet(target)
            log.info("wrote %s (%d rows)", target.name, len(df))

    log.info("DONE")


if __name__ == "__main__":
    main()
