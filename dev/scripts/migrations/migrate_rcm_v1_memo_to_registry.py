#!/usr/bin/env python
"""One-time migration: ingest RCMv1 S1 memo as first registry candidate.

The RCMv1 S1 promotion memo at docs/20260424-rcm_v1_s1_candidate_memo.md
was written before the candidate registry (Phase E-0 R1) existed. It's
functionally a valid S1 research candidate — 4/4 walk-forward + 6/6
regime positive, full acceptance pack, frozen spec — but isn't in any
registry.

This script ingests the memo as the first real S1 record, pointing to:
  - frozen spec YAML (extracted in R3 prep to
    data/research_candidates/rcm_v1_defensive_composite_01.yaml)
  - decision memo (the original memo file)
  - source trial (rcm_archive row f24aefecc91a)
  - source lineage (post-2026-04-24-rcm-v1-lag1)

Idempotency: if the candidate_id is already registered, the script is
a no-op (logs and returns 0). Safe to run multiple times.

This is a ONE-TIME migration. Future candidates should go through
scripts/freeze_research_candidate.py (Phase E-1 R5) +
scripts/research_promote.py (R6).

Usage:
    python dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py
    python dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.logging_setup import get_logger, setup_logging
from core.research.candidate_registry import (
    CandidateRegistry,
    CandidateStatus,
    DuplicateCandidateError,
)

setup_logging()
logger = get_logger("migrate_rcm_v1_memo")


# Hardcoded migration target — this IS the one-time migration
CANDIDATE_ID = "rcm_v1_defensive_composite_01"
SOURCE_TRIAL_ID = "f24aefecc91a"
SOURCE_LINEAGE_TAG = "post-2026-04-24-rcm-v1-lag1"
FROZEN_SPEC_PATH = "data/research_candidates/rcm_v1_defensive_composite_01.yaml"
DECISION_MEMO_PATH = "docs/20260424-rcm_v1_s1_candidate_memo.md"


def _validate_prerequisites() -> list[str]:
    """Return list of missing prerequisites (empty = OK to proceed)."""
    missing = []
    if not Path(FROZEN_SPEC_PATH).exists():
        missing.append(f"frozen spec: {FROZEN_SPEC_PATH}")
    if not Path(DECISION_MEMO_PATH).exists():
        missing.append(f"decision memo: {DECISION_MEMO_PATH}")
    # Spot-check: the source trial exists in rcm_archive
    import sqlite3
    try:
        conn = sqlite3.connect("data/mining/rcm_archive.db")
        row = conn.execute(
            "SELECT trial_id FROM rcm_trials WHERE trial_id = ?",
            (SOURCE_TRIAL_ID,),
        ).fetchone()
        if row is None:
            missing.append(
                f"rcm_archive trial: {SOURCE_TRIAL_ID} (not in "
                "data/mining/rcm_archive.db::rcm_trials)"
            )
        conn.close()
    except Exception as e:
        missing.append(f"rcm_archive query failed: {e}")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate RCMv1 S1 memo into candidate registry "
                    "(one-time, Phase E-0 R3)",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate prereqs + print plan but don't write")
    parser.add_argument("--registry-db",
                        default="data/research_candidates/registry.db")
    args = parser.parse_args()

    # Prereq check
    missing = _validate_prerequisites()
    if missing:
        logger.error("Missing prerequisites:")
        for m in missing:
            logger.error("  - %s", m)
        return 1
    logger.info("Prereq check OK")

    # Print plan
    print("=" * 70)
    print("RCMv1 S1 memo migration plan")
    print("=" * 70)
    print(f"  candidate_id        : {CANDIDATE_ID}")
    print(f"  source_trial_id     : {SOURCE_TRIAL_ID}")
    print(f"  source_lineage_tag  : {SOURCE_LINEAGE_TAG}")
    print(f"  status              : S1_research_candidate")
    print(f"  frozen_spec_path    : {FROZEN_SPEC_PATH}")
    print(f"  decision_memo_path  : {DECISION_MEMO_PATH}")
    print(f"  registry_db         : {args.registry_db}")
    print()

    if args.dry_run:
        print("DRY-RUN: no write performed.")
        return 0

    registry = CandidateRegistry(args.registry_db)

    # Idempotency check
    if registry.exists(CANDIDATE_ID):
        existing = registry.get(CANDIDATE_ID)
        logger.info(
            "Candidate %s already registered (status=%s, created_at=%s). "
            "No-op.",
            CANDIDATE_ID, existing.status.value, existing.created_at,
        )
        print(f"Already registered (status={existing.status.value}). "
              f"Migration is a no-op.")
        return 0

    # Register
    try:
        rec = registry.register(
            candidate_id=CANDIDATE_ID,
            source_trial_id=SOURCE_TRIAL_ID,
            source_lineage_tag=SOURCE_LINEAGE_TAG,
            status=CandidateStatus.S1_CANDIDATE,
            frozen_spec_path=FROZEN_SPEC_PATH,
            decision_memo_path=DECISION_MEMO_PATH,
        )
    except DuplicateCandidateError:
        # Race condition (shouldn't happen after exists check but safe)
        logger.info("Candidate %s registered during this migration "
                    "run — treating as no-op", CANDIDATE_ID)
        return 0

    print(f"Registered: {rec.candidate_id}")
    print(f"  status      : {rec.status.value}")
    print(f"  created_at  : {rec.created_at}")
    print(f"  promoted_at : {rec.promoted_at}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
