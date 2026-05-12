#!/usr/bin/env python
"""Bulk download FRED macro series for PQS.

Usage:
    python dev/scripts/fundamentals/build_macro_cache.py [--force]

Downloads CPIAUCNS / FEDFUNDS / DGS10 / DGS2 / DTWEXBGS / DCOILWTICO /
VIXCLS / UNRATE — all free, no API key (fredgraph.csv endpoint).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.data.fred_provider import FredProvider, MACRO_SERIES  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true")
    p.add_argument("--cache-dir", default="data/fundamentals/macro")
    args = p.parse_args()

    provider = FredProvider(cache_dir=args.cache_dir)
    for sid in MACRO_SERIES:
        path = provider.cache_dir / f"{sid}.csv"
        if path.exists() and not args.force:
            logger.info("%s: cached (%d bytes)", sid, path.stat().st_size)
            continue
        try:
            path = provider.download_series(sid)
            logger.info("%s: downloaded (%d bytes)", sid, path.stat().st_size)
        except Exception as e:
            logger.error("%s: failed (%s)", sid, e)
        time.sleep(0.5)  # courteous pacing


if __name__ == "__main__":
    main()
