#!/usr/bin/env python
"""Bulk download SEC EDGAR companyfacts JSON for PQS universe.

Usage:
    python dev/scripts/fundamentals/build_edgar_cache.py [--force] [--syms SPY,AAPL,...]

Rate limit: respects SEC's 10 req/sec cap with a 0.11s sleep between
fetches (≈9 req/sec safe).

Caches to data/fundamentals/edgar_cache/<CIK_padded_10>.json plus a
manifest at data/fundamentals/edgar_cache/_manifest.json mapping ticker
→ {cik, last_fetched_utc, size_bytes, status}.

ETFs / leveraged products are silently skipped (no us-gaap filings).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Allow running as script from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.data.edgar_provider import (  # noqa: E402
    DEFAULT_RATE_LIMIT_SECONDS,
    EdgarProvider,
    is_etf_or_unsupported,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_universe() -> list[str]:
    with open("config/universe.yaml") as f:
        cfg = yaml.safe_load(f)
    return list(cfg.get("seed_pool", []))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="Re-download even if cached.")
    p.add_argument("--syms", type=str, default=None, help="CSV of specific tickers.")
    p.add_argument("--cache-dir", type=str, default="data/fundamentals/edgar_cache")
    p.add_argument("--rate-limit", type=float, default=DEFAULT_RATE_LIMIT_SECONDS,
                   help="Seconds between requests (default 0.11s = 9/sec safe).")
    args = p.parse_args()

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    provider = EdgarProvider(cache_dir=cache_dir)
    # Force-refresh CIK map first (lightweight)
    cik_map = provider.get_cik_map(force_refresh=True)
    logger.info("Loaded CIK map: %d entries", len(cik_map))

    if args.syms:
        tickers = [s.strip().upper() for s in args.syms.split(",")]
    else:
        tickers = load_universe()
    logger.info("Target universe: %d tickers", len(tickers))

    manifest_path = cache_dir / "_manifest.json"
    manifest = {}
    if manifest_path.exists() and not args.force:
        with open(manifest_path) as f:
            manifest = json.load(f)

    stats = {"downloaded": 0, "skipped_etf": 0, "skipped_cached": 0, "skipped_no_cik": 0, "failed": 0}

    for i, t in enumerate(tickers, 1):
        t = t.upper()
        if is_etf_or_unsupported(t):
            stats["skipped_etf"] += 1
            manifest[t] = {"status": "skipped_etf", "cik": None}
            continue
        cik = provider.get_cik(t)
        if cik is None:
            stats["skipped_no_cik"] += 1
            manifest[t] = {"status": "no_cik", "cik": None}
            logger.warning("[%d/%d] %s: no CIK in SEC ticker map (skipping)", i, len(tickers), t)
            continue
        out_path = cache_dir / f"{cik:010d}.json"
        if out_path.exists() and not args.force:
            stats["skipped_cached"] += 1
            manifest.setdefault(t, {}).update({"status": "cached", "cik": cik, "size_bytes": out_path.stat().st_size})
            continue
        try:
            path = provider.download_company_facts(t)
            size = path.stat().st_size
            manifest[t] = {
                "status": "downloaded",
                "cik": cik,
                "size_bytes": size,
                "last_fetched_utc": datetime.now(timezone.utc).isoformat(),
            }
            stats["downloaded"] += 1
            logger.info("[%d/%d] %s (CIK %d): %d bytes", i, len(tickers), t, cik, size)
        except Exception as e:
            stats["failed"] += 1
            manifest[t] = {"status": f"failed: {type(e).__name__}: {e}", "cik": cik}
            logger.error("[%d/%d] %s: failed (%s)", i, len(tickers), t, e)
        time.sleep(args.rate_limit)

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)

    logger.info("Build complete: %s", stats)
    logger.info("Manifest: %s", manifest_path)


if __name__ == "__main__":
    main()
