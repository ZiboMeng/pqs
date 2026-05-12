"""Forward init for trial9_diversifier_002 (PRD 20260512 opt-in successor).

Supersedes trial9_diversifier_001 which halted at TD004 on 2026-05-12
under v2.1 revalidate bound_only trigger. PRD:
docs/prd/20260512-per_candidate_track_signal_input_per_cell_prd.md.

This script:
1. Registers trial9_diversifier_002 in candidate registry with role=diversifier
2. Calls forward.runner.init() with the spec yaml + role + soft_warn_flags
3. Reports manifest path + spec hash + start_date

Idempotent on registry (skip if candidate_id already registered).
Idempotent on manifest (refuses to overwrite without --overwrite).

Usage:
    python dev/scripts/forward/init_trial9_diversifier_002.py [--start-date 2026-05-13]
                                                              [--overwrite]
                                                              [--dry-run]
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


CANDIDATE_ID = "trial9_diversifier_002"
SOURCE_TRIAL_ID = "6c745c601a47"
SOURCE_LINEAGE_TAG = "track-c-cycle-2026-05-01-05"
FROZEN_SPEC_PATH = "data/research_candidates/trial9_diversifier_002.yaml"
DECISION_MEMO_PATH = "docs/memos/20260512-trial9_diversifier_001_closeout.md"
SOFT_WARN_FLAGS = ["diversifier_2025_maxdd_18_20pct"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start-date", default="2026-05-13",
                    help="forward observation start date YYYY-MM-DD; default 2026-05-13")
    ap.add_argument("--overwrite", action="store_true",
                    help="overwrite existing forward manifest (drops runs[])")
    ap.add_argument("--dry-run", action="store_true",
                    help="print actions without executing")
    args = ap.parse_args()

    print(f"[init_trial9_002] candidate_id={CANDIDATE_ID}")
    print(f"[init_trial9_002] role={CandidateRole.diversifier.value}")
    print(f"[init_trial9_002] soft_warn_flags={SOFT_WARN_FLAGS}")
    print(f"[init_trial9_002] frozen_spec={FROZEN_SPEC_PATH}")
    print(f"[init_trial9_002] decision_memo={DECISION_MEMO_PATH}")
    print(f"[init_trial9_002] start_date={args.start_date}")

    spec_path = PROJ / FROZEN_SPEC_PATH
    if not spec_path.exists():
        raise SystemExit(f"frozen spec not found: {spec_path}")

    if args.dry_run:
        print(f"[init_trial9_002] DRY RUN — exiting without changes")
        return 0

    # ── Step 1: register in candidate registry ──
    registry = CandidateRegistry()
    promoted_at = datetime.now(timezone.utc).isoformat()
    try:
        rec = registry.register(
            candidate_id=CANDIDATE_ID,
            source_trial_id=SOURCE_TRIAL_ID,
            source_lineage_tag=SOURCE_LINEAGE_TAG,
            status=CandidateStatus.S2_PAPER,  # straight to paper observation
            frozen_spec_path=FROZEN_SPEC_PATH,
            decision_memo_path=DECISION_MEMO_PATH,
            promoted_at=promoted_at,
            role="diversifier",
        )
        print(f"[init_trial9_002] Registered: {rec.candidate_id} role={rec.role} "
              f"status={rec.status.value}")
    except DuplicateCandidateError:
        rec = registry.get(CANDIDATE_ID)
        print(f"[init_trial9_002] Already registered: role={rec.role} status={rec.status.value}")
        if rec.role != "diversifier":
            raise SystemExit(
                f"existing candidate has role={rec.role!r}, expected 'diversifier'. "
                f"role is immutable post-init; cannot proceed."
            )

    # ── Step 2: forward init ──
    # NB: spec yaml already lives at data/research_candidates/ which is
    # also runner.DEFAULT_OUTPUT_DIR, so no copy step needed (unlike v1
    # init script which copied from a separate path).
    manifest = runner.init(
        candidate_id=CANDIDATE_ID,
        start_date=args.start_date,
        benchmark="SPY",
        secondary_benchmark="QQQ",
        overwrite=args.overwrite,
        candidate_role=CandidateRole.diversifier,
        soft_warn_flags=SOFT_WARN_FLAGS,
    )
    print(f"[init_trial9_002] Forward manifest initialized:")
    print(f"  candidate_id: {manifest.candidate_id}")
    print(f"  spec_hash: {manifest.spec_hash}")
    print(f"  start_date: {manifest.start_date.isoformat()}")
    print(f"  candidate_role: {manifest.candidate_role.value}")
    print(f"  soft_warn_flags: {manifest.soft_warn_flags}")
    print(f"  current_status: {manifest.current_status.value}")
    print(f"  evidence_class: {manifest.evidence_class.value}")
    print(f"  manifest_path: {runner.manifest_path(CANDIDATE_ID, runner.DEFAULT_OUTPUT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
