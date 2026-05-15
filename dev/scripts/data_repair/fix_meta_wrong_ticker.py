"""P0.b.3: META wrong-ticker purge + re-fetch.

Problem: META parquet 2021-10-26 → 2022-06-08 contains META Financial
Group (the original META ticker holder, a small bank) data, NOT Meta
Platforms (formerly FB, renamed to META 2022-06-09). Verified by yfinance
returning $300+ prices for these dates but our parquet has $12-15.

Fix: backup existing parquet + re-fetch yfinance META full history
from 2012-05-18 (FB IPO date per universe.yaml::first_trade_dates::META).
yfinance ticker "META" today returns the unified Meta Platforms history
going back through FB era, so a fresh fetch gives the correct ticker
mapping.

META has no splits in data/ref/splits.parquet, so no split-aware
adjustment needed.

Run:
    python dev/scripts/data_repair/fix_meta_wrong_ticker.py [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path("/home/zibo/Documents/projects/pqs")
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))

import pandas as pd

from core.data.data_repair import (
    _backup_parquet,
    _fetch_yfinance_bars,
    append_repair_provenance,
    REPAIR_PROVENANCE_TAG,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    log = logging.getLogger(__name__)

    log.info("=== META wrong-ticker fix (P0.b.3) ===")
    log.info("Mode: %s", "DRY-RUN" if args.dry_run else "LIVE")

    pq_path = PROJ / "data/daily/META.parquet"
    if not pq_path.exists():
        log.error("META parquet not found at %s", pq_path)
        return 1

    df_old = pd.read_parquet(pq_path).sort_index()
    log.info("Existing META parquet: %d rows, %s → %s",
             len(df_old), df_old.index.min().date(), df_old.index.max().date())
    log.info("Sample early close: $%.2f on %s (suspect = META Financial Group)",
             df_old.iloc[0]['close'], df_old.index[0].date())
    log.info("Sample recent close: $%.2f on %s (Meta Platforms current)",
             df_old.iloc[-1]['close'], df_old.index[-1].date())

    # Fetch yfinance META full history
    start = pd.Timestamp("2012-05-18")  # FB IPO date
    end = pd.Timestamp.today().normalize()
    log.info("Fetching yfinance META: %s → %s", start.date(), end.date())

    try:
        yf_df = _fetch_yfinance_bars("META", start, end)
    except Exception as e:
        log.error("yfinance fetch failed: %s", e)
        return 1

    log.info("yfinance returned %d rows, %s → %s",
             len(yf_df), yf_df.index.min().date(), yf_df.index.max().date())
    log.info("Sample early yfinance close: $%.2f on %s",
             yf_df.iloc[0]['close'], yf_df.index[0].date())

    # Verify yfinance returns sane prices for the suspect-zone in our parquet
    test_dates = [pd.Timestamp("2021-10-26"), pd.Timestamp("2022-01-31")]
    for d in test_dates:
        if d in yf_df.index:
            yf_val = yf_df.loc[d]['close']
            old_val = df_old.loc[d]['close'] if d in df_old.index else float('nan')
            log.info("  %s: yfinance=$%.2f (Meta Platforms), parquet=$%.2f (likely wrong)",
                     d.date(), yf_val, old_val)

    if args.dry_run:
        log.info("[dry-run] would replace META parquet with %d rows of "
                 "fresh yfinance data", len(yf_df))
        return 0

    # Backup + replace
    backup_path = _backup_parquet(pq_path)
    log.info("Backup created: %s", backup_path.name)

    # Align columns to existing schema (preserve column names + types)
    out = pd.DataFrame(index=yf_df.index)
    for c in df_old.columns:
        if c in yf_df.columns:
            out[c] = yf_df[c]
        else:
            out[c] = pd.NA
    out.index.name = df_old.index.name
    out = out.sort_index()
    out.to_parquet(pq_path)
    log.info("Wrote replacement META parquet: %d rows", len(out))

    # Append provenance — note: this is a REPLACE not a gap-fill, so we mark
    # the entire date range with the repair source tag
    append_repair_provenance(
        "META",
        [str(d.date()) for d in out.index],
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
