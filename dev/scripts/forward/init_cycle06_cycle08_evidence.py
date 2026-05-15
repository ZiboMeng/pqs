"""Forward-init for cycle06 + cycle08 sealed-test survivors (evidence cohort).

Both candidates PASSED Track A acceptance (post-MaxDD-fix 2026-05-15)
AND the sealed 2026 single-shot test (2/2 PASS). Per the corrected
pipeline ordering (sealed gate → forward observation), they are now
forward-init'd as an evidence-only cohort.

Role: candidate_role=core_alpha (the role whose acceptance gates they
passed). evidence-only operational stance via candidate_id `_evidence_v1`
suffix + registry status S2_PAPER. See:
docs/memos/20260515-cycle06_cycle08_evidence_forward_init.md

Idempotent: skips registry if already registered; refuses manifest
overwrite without --overwrite.

Usage:
    python dev/scripts/forward/init_cycle06_cycle08_evidence.py
        [--start-date 2026-05-15] [--overwrite] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path("/home/zibo/Documents/projects/pqs")
sys.path.insert(0, str(PROJ))

from core.research.candidate_registry import (
    CandidateRegistry, CandidateStatus, DuplicateCandidateError,
)
from core.research.forward import runner
from core.research.forward.manifest_schema import CandidateRole

DECISION_MEMO = "docs/memos/20260515-cycle06_cycle08_evidence_forward_init.md"

COHORT = [
    {"candidate_id": "cycle08_3f40e3f4ed1a_evidence_v1",
     "source_trial_id": "3f40e3f4ed1a",
     "source_lineage_tag": "track-c-cycle-2026-05-08-01"},
    {"candidate_id": "cycle06_31af04cf2ff9_evidence_v1",
     "source_trial_id": "31af04cf2ff9",
     "source_lineage_tag": "track-c-cycle-2026-05-06-01"},
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start-date", default="2026-05-15")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    registry = CandidateRegistry()
    promoted_at = datetime.now(timezone.utc).isoformat()

    for c in COHORT:
        cid = c["candidate_id"]
        print(f"\n=== {cid} ===")
        spec_path = PROJ / "data/research_candidates" / f"{cid}.yaml"
        if not spec_path.exists():
            raise SystemExit(f"frozen spec not found: {spec_path}")

        if args.dry_run:
            print(f"[dry-run] would register + forward-init {cid} "
                  f"role=core_alpha status=S2_PAPER")
            continue

        # Step 1: register
        try:
            rec = registry.register(
                candidate_id=cid,
                source_trial_id=c["source_trial_id"],
                source_lineage_tag=c["source_lineage_tag"],
                status=CandidateStatus.S2_PAPER,
                frozen_spec_path=f"data/research_candidates/{cid}.yaml",
                decision_memo_path=DECISION_MEMO,
                promoted_at=promoted_at,
                role="core_alpha",
            )
            print(f"  registered: role={rec.role} status={rec.status.value}")
        except DuplicateCandidateError:
            rec = registry.get(cid)
            print(f"  already registered: role={rec.role} status={rec.status.value}")
            if rec.role != "core_alpha":
                raise SystemExit(
                    f"existing candidate role={rec.role!r}, expected core_alpha")

        # Step 2: forward init
        manifest = runner.init(
            candidate_id=cid,
            start_date=args.start_date,
            benchmark="SPY",
            secondary_benchmark="QQQ",
            overwrite=args.overwrite,
            candidate_role=CandidateRole.core_alpha,
        )
        print(f"  forward manifest initialized:")
        print(f"    spec_hash: {manifest.spec_hash}")
        print(f"    start_date: {manifest.start_date.isoformat()}")
        print(f"    candidate_role: {manifest.candidate_role.value}")
        print(f"    current_status: {manifest.current_status.value}")
        print(f"    evidence_class: {manifest.evidence_class.value}")

    if not args.dry_run:
        print("\nCohort forward-init complete. First observe = next "
              "trading-day EOD post-NYSE close.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
