#!/usr/bin/env python
"""Fetch S&P 500 daily bars as a mining candidate pool.

PRD: docs/20260421-prd_deep_mining_50round.md §2 Track D (R34)

This is SEPARATE from config/universe.yaml fetch_data.py path. It builds
a broader candidate pool stored at data/daily/ (same format, same location
as universe symbols — just more of them). `config/universe.yaml` is NOT
modified; this script just deposits parquets ready for:
  - universe_alpha_diagnostic.py  (R35)
  - universe_admission_screen.py  (R36)
  - user review and manual universe.yaml update (R38)

S&P 500 ticker list source: Wikipedia (no external API key, no lxml
dependency; uses pure urllib + regex so works in any Python env).

Usage:
  python scripts/fetch_sp500_pool.py                # ~30-60 min first time
  python scripts/fetch_sp500_pool.py --skip-existing # skip already-downloaded
  python scripts/fetch_sp500_pool.py --limit 50     # testing: first 50 only
  python scripts/fetch_sp500_pool.py --ticker-list my_list.txt  # use custom list instead of wiki
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def _fetch_sp500_tickers_from_wikipedia() -> List[str]:
    """Fetch current S&P 500 constituents via urllib + regex.

    Returns sorted unique ticker list (typically ~500). Does not require lxml.
    """
    req = urllib.request.Request(_WIKI_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8")
    # Pattern matches the 1st table's symbol column (anchor-wrapped tickers).
    # Yfinance uses '-' for Berkshire etc; wikipedia may use '.' — we normalize.
    matches = re.findall(
        r'<td[^>]*>\s*<a[^>]*>([A-Z\.\-]{1,6})</a>\s*</td>\s*<td[^>]*>',
        html,
    )
    # Normalize: wikipedia 'BRK.B' → yfinance 'BRK-B'
    normalized = [t.replace(".", "-") for t in matches]
    # De-dup + sort, strip false positives (footnote anchors etc.)
    unique = sorted(set(t for t in normalized if 1 <= len(t) <= 6 and t.isupper() or "-" in t))
    return unique


def _read_ticker_list_file(path: Path) -> List[str]:
    """Read newline-separated ticker list, strip comments/blank lines."""
    lines = path.read_text().splitlines()
    tickers = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # Allow "AAPL  # Apple Inc" format — take first token
        tickers.append(s.split()[0].upper())
    return sorted(set(tickers))


def _existing_tickers(data_dir: Path) -> set:
    daily_dir = data_dir / "daily"
    if not daily_dir.exists():
        return set()
    # MDSStore convention: symbols with `-` saved as `_`.
    # Return both raw stems and hyphen-normalized stems so callers can
    # pattern-match either convention.
    stems = set()
    for p in daily_dir.glob("*.parquet"):
        stems.add(p.stem)
        if "_" in p.stem:
            stems.add(p.stem.replace("_", "-"))
        if "." in p.stem:
            stems.add(p.stem.replace(".", "-"))
    return stems


def _download_batch(tickers: List[str], data_dir: Path, batch_size: int,
                    sleep_between_batches: float, incremental: bool) -> dict:
    """Batch download via YFinanceProvider, save via MDSStore.

    When incremental=True (default), uses MDSStore.append() which only adds
    new bars past existing last_date. Fast for daily sync.
    When incremental=False, full-history fetch (2015-01-01) and overwrite.
    """
    try:
        from core.data.yfinance_provider import YFinanceProvider
        from core.data.market_data_store import MarketDataStore
    except Exception as exc:
        raise RuntimeError(f"Import failed: {exc}")

    provider = YFinanceProvider()
    store = MarketDataStore(data_dir=data_dir)
    stats = {"downloaded": 0, "skipped": 0, "failed": [], "total": len(tickers),
             "rows_added": 0}

    daily_dir = data_dir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i : i + batch_size]
        batch_num = i // batch_size + 1
        print(f"[batch {batch_num}/{(len(tickers)+batch_size-1)//batch_size}] "
              f"{'incr' if incremental else 'full'} {len(batch)} symbols: {batch[:3]}...",
              flush=True)

        # For incremental: compute earliest missing date across batch
        start = "2015-01-01"
        if incremental:
            earliest = None
            for sym in batch:
                try:
                    existing = store.read(sym, "1d")
                    if existing is not None and not existing.empty:
                        last = existing.index[-1]
                        if earliest is None or last < earliest:
                            earliest = last
                except Exception:
                    pass
            if earliest is not None:
                # Fetch from day after earliest (inclusive window)
                import pandas as _pd
                start = (earliest + _pd.Timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            frames = provider.fetch_daily(batch, start=start, end=None)
            for sym, frame in frames.items():
                # YFinanceProvider returns OHLCVFrame wrapper; .df is the DataFrame
                df = getattr(frame, "df", frame)
                if df is None or df.empty:
                    stats["failed"].append(sym)
                    continue
                if incremental:
                    try:
                        added = store.append(sym, "1d", df)
                        stats["rows_added"] += added
                        stats["downloaded"] += 1
                    except Exception as e:
                        print(f"  WARN {sym} append failed: {e}", flush=True)
                        stats["failed"].append(sym)
                else:
                    try:
                        store.write(sym, "1d", df)
                        stats["downloaded"] += 1
                    except Exception as e:
                        stats["failed"].append(sym)
        except Exception as exc:
            print(f"  WARN batch failed: {exc}", flush=True)
            stats["failed"].extend(batch)

        if i + batch_size < len(tickers):
            time.sleep(sleep_between_batches)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch S&P 500 daily bars as mining pool (PRD deep_mining §R34)"
    )
    parser.add_argument("--ticker-list", type=Path, default=None,
                        help="Path to newline-separated ticker list (override wiki fetch)")
    parser.add_argument("--data-dir", default="data", help="Data root (parquets go to <data-dir>/daily/)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip tickers already at data/daily/<SYM>.parquet")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit to first N tickers (for testing)")
    parser.add_argument("--batch-size", type=int, default=20,
                        help="Yfinance batch size (avoid rate limit)")
    parser.add_argument("--sleep", type=float, default=1.5,
                        help="Sleep seconds between batches")
    parser.add_argument("--save-list", type=Path, default=None,
                        help="Save fetched ticker list to this path (for reproducibility)")
    parser.add_argument("--incremental", action="store_true", default=True,
                        help="Incremental append (default; fast for daily sync)")
    parser.add_argument("--full", dest="incremental", action="store_false",
                        help="Force full-history fetch (2015-01-01 onward; overwrites existing)")
    args = parser.parse_args()

    # Get ticker list
    if args.ticker_list:
        tickers = _read_ticker_list_file(args.ticker_list)
        print(f"Loaded {len(tickers)} tickers from {args.ticker_list}")
    else:
        print(f"Fetching S&P 500 constituents from Wikipedia...")
        tickers = _fetch_sp500_tickers_from_wikipedia()
        print(f"Got {len(tickers)} tickers")
        if len(tickers) < 400:
            print(f"  WARN: fewer than 400 tickers — wiki parse may be incomplete. "
                  f"Consider --ticker-list with a known-good file.")

    if args.save_list:
        args.save_list.parent.mkdir(parents=True, exist_ok=True)
        args.save_list.write_text("\n".join(tickers) + "\n")
        print(f"Saved ticker list: {args.save_list}")

    if args.limit:
        tickers = tickers[: args.limit]
        print(f"Limited to first {len(tickers)}")

    # Filter existing
    if args.skip_existing:
        existing = _existing_tickers(Path(args.data_dir))
        before = len(tickers)
        tickers = [t for t in tickers if t not in existing]
        print(f"Skipping {before - len(tickers)} already-downloaded; {len(tickers)} remain")

    if not tickers:
        print("Nothing to download.")
        return 0

    # Download
    mode = "incremental" if args.incremental else "full"
    print(f"\nStarting {mode} download: {len(tickers)} tickers, "
          f"batch={args.batch_size}, sleep={args.sleep}s between batches\n")
    stats = _download_batch(
        tickers, Path(args.data_dir), args.batch_size, args.sleep,
        incremental=args.incremental,
    )

    # Report
    print("\n" + "=" * 60)
    print(f"Downloaded: {stats['downloaded']} / {stats['total']}")
    if args.incremental:
        print(f"Rows added: {stats['rows_added']}")
    print(f"Failed: {len(stats['failed'])}")
    if stats["failed"]:
        print(f"Failed symbols: {stats['failed'][:20]}"
              + (f"... ({len(stats['failed'])} total)" if len(stats['failed']) > 20 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
