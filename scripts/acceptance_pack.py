#!/usr/bin/env python
"""Run the acceptance pack for a given spec_id (PRD M2).

Standalone CLI — does NOT modify config/production_strategy.yaml.
Use scripts/promote_strategy.py for the promote action.

Typical usage:
  python scripts/acceptance_pack.py --spec-id 81f5cdaa053e --out-dir artifacts/
  python scripts/acceptance_pack.py --spec-id 81f5 --verbose   # prefix match
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.mining.acceptance_pack import (
    AcceptancePackError,
    run_acceptance_pack,
    write_acceptance_artifact,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run mining acceptance pack (PRD M2)")
    parser.add_argument("--spec-id", required=True,
                        help="Archive spec_id (prefix match allowed)")
    parser.add_argument("--archive-db", default="data/mining/archive.db",
                        help="Path to mining archive DB")
    parser.add_argument("--out-dir", default="artifacts/acceptance_packs",
                        help="Directory to write the pack JSON")
    parser.add_argument("--verbose", action="store_true",
                        help="Print full gate breakdown to stdout")
    args = parser.parse_args()

    try:
        result = run_acceptance_pack(args.spec_id, archive_db=args.archive_db)
    except AcceptancePackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.out_dir) / f"acceptance_{result.spec_id[:12]}_{ts}.json"
    write_acceptance_artifact(result, out_path)

    print(result.summary_line())
    print(f"Artifact: {out_path}")
    for g in result.gates:
        mark = "✅" if g.passed else "❌"
        print(f"  {mark} {g.name}")
        if args.verbose:
            for k, v in g.values.items():
                print(f"       {k}: {v}")
            if g.notes:
                print(f"       ({g.notes})")

    return 0 if result.overall_passed else 1


if __name__ == "__main__":
    sys.exit(main())
