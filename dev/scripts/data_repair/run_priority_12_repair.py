"""Repair internal gaps on user's priority-12 symbol list.

User 2026-05-14: "可以从web上面抓取数据进行补充. 下面这些票是值得优先修的:
META XLC ACGL MCK TT ISRG CMG BKNG SHY VLUE QUAL MTUM"

Repair rules per core/data/data_repair.py:
  - 只补 internal gaps (within valid window)
  - 不扩 history start
  - 备份原 parquet
  - 写 manifest
  - 追加 provenance
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

from core.data.data_repair import (
    RepairManifest,
    SymbolRepairResult,
    repair_symbol_internal_gaps,
    append_repair_provenance,
    write_repair_manifest,
    REPAIR_PROVENANCE_TAG,
)

PRIORITY_12 = [
    "META", "XLC", "ACGL", "MCK", "TT", "ISRG",
    "CMG", "BKNG", "SHY", "VLUE", "QUAL", "MTUM",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be repaired without writing")
    parser.add_argument("--symbols", nargs="*", default=PRIORITY_12,
                        help="Symbol list (default: priority-12)")
    parser.add_argument("--max-gap", type=int, default=1,
                        help="Min gap length to repair (default 1 = skip single days)")
    parser.add_argument("--suspect-threshold", type=float, default=0.30,
                        help="Reject yfinance bar if differs >X from neighbor (default 0.30)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger(__name__)

    log.info("=== Data repair P0.b (Codex 2026-05-14 fix) ===")
    log.info("Mode: %s", "DRY-RUN" if args.dry_run else "LIVE WRITE")
    log.info("Symbols: %s", args.symbols)
    log.info("Min gap length to repair: > %d BD", args.max_gap)
    log.info("Suspect threshold: %.2f", args.suspect_threshold)
    log.info("Provenance tag: %s", REPAIR_PROVENANCE_TAG)
    log.info("")

    manifest = RepairManifest(
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
    )

    for sym in args.symbols:
        log.info("--- %s ---", sym)
        result = repair_symbol_internal_gaps(
            sym,
            max_consecutive_missing_bd=args.max_gap,
            suspect_threshold=args.suspect_threshold,
            dry_run=args.dry_run,
        )
        manifest.per_symbol[sym] = result
        log.info("[%s] pre=%d rows, post=%d, filled=%d, unfillable=%d, suspect=%d",
                 sym, result.pre_repair_n_rows, result.post_repair_n_rows,
                 result.n_filled, result.n_unfillable, result.n_suspect_skipped)
        if result.error:
            log.warning("[%s] ERROR: %s", sym, result.error)
        if not args.dry_run and result.n_filled > 0:
            append_repair_provenance(sym, result.filled_dates)

    log.info("")
    log.info("=== Summary ===")
    total_filled = sum(r.n_filled for r in manifest.per_symbol.values())
    total_unfillable = sum(r.n_unfillable for r in manifest.per_symbol.values())
    total_suspect = sum(r.n_suspect_skipped for r in manifest.per_symbol.values())
    log.info("Total filled rows: %d", total_filled)
    log.info("Total unfillable: %d", total_unfillable)
    log.info("Total suspect-skipped: %d", total_suspect)

    if not args.dry_run:
        manifest_path = write_repair_manifest(manifest)
        log.info("Manifest: %s", manifest_path)
    else:
        log.info("[dry-run] no manifest written")

    return 0


if __name__ == "__main__":
    sys.exit(main())
