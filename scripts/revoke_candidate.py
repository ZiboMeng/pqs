#!/usr/bin/env python
"""Revoke a research candidate (Phase E-0 R3).

Usage:
    python scripts/revoke_candidate.py \
        --candidate-id <id> \
        --reason <reason> \
        [--memo-path <path>]

Reasons (from core.research.candidate_registry.RevokeReason):
    leakage_found           # structural leakage detected after promote
    reproducibility_failed  # spec can't be re-run; returns to S0, not S5
    benchmark_misaligned    # benchmark-relative summary invalidated
    candidate_superseded    # newer/better candidate replaces it
    spec_unreproducible     # frozen spec itself won't load / run
    other                   # general; memo required

Memo: strongly recommended. A plain-text markdown file explaining the
decision, supporting artifacts, and what future candidates should avoid.
If --memo-path is not provided, this script writes a minimal stub at
data/research_candidates/<candidate_id>_revoke_<timestamp>.md and
records that path.

This script does NOT delete any data. It updates the registry row.
The original frozen spec and decision memo remain on disk for audit.

Design rationale: revoke is the most valuable new governance primitive
(per auditor). R15 leakage audit would have been a revoke event.
Making revoke explicit means the system can recover from false-positive
acceptances without overwriting history.

Related PRDs:
    docs/20260424-prd_phase_e_execution.md §2 E0-R3
    docs/20260424-prd_research_to_paper_promote_standard.md §12
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.logging_setup import get_logger, setup_logging
from core.research.candidate_registry import (
    CandidateNotFoundError,
    CandidateRegistry,
    CandidateStatus,
    InvalidTransitionError,
    RevokeReason,
)

setup_logging()
logger = get_logger("revoke_candidate")


_DEFAULT_REGISTRY = "data/research_candidates/registry.db"
_MEMO_DIR = Path("data/research_candidates")


def _reason_choices() -> list[str]:
    return [r.value for r in RevokeReason]


def _write_stub_memo(candidate_id: str, reason: RevokeReason) -> Path:
    """Write a minimal stub revoke memo and return its path."""
    _MEMO_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _MEMO_DIR / f"{candidate_id}_revoke_{ts}.md"
    path.write_text(
        f"""# Revoke memo — {candidate_id}

**Revoked at**: {datetime.now(timezone.utc).isoformat()}
**Reason**: `{reason.value}`
**Memo author**: (auto-generated stub — replace with actual justification)

## Supporting artifacts
<!-- list artifact paths / commit hashes / test outputs here -->

## Decision rationale
<!-- explain why revoke was warranted -->

## Impact
<!-- what downstream work is affected -->

## Follow-up
<!-- future candidates should avoid ... -->
"""
    )
    logger.warning("Auto-generated stub memo at %s — please edit", path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Revoke a research candidate (Phase E-0 R3)",
    )
    parser.add_argument("--candidate-id", required=True,
                        help="Candidate ID as registered in the registry")
    parser.add_argument("--reason", required=True, choices=_reason_choices(),
                        help="Revoke reason (enum)")
    parser.add_argument("--memo-path", default=None,
                        help="Path to revoke memo markdown. If omitted, a "
                             "stub is auto-generated under "
                             "data/research_candidates/")
    parser.add_argument("--registry-db", default=_DEFAULT_REGISTRY,
                        help="Registry DB path")
    args = parser.parse_args()

    registry = CandidateRegistry(args.registry_db)
    reason = RevokeReason(args.reason)

    try:
        current = registry.get(args.candidate_id)
    except CandidateNotFoundError:
        logger.error("Candidate %s not found in registry", args.candidate_id)
        return 1

    if current.status == CandidateStatus.S5_DEPRECATED:
        logger.error(
            "Candidate %s already revoked (reason=%s, at=%s)",
            args.candidate_id, current.revoke_reason, current.revoked_at,
        )
        return 1

    # Memo handling — use provided path or auto-stub
    memo_path_str: str | None = args.memo_path
    if memo_path_str:
        memo_path = Path(memo_path_str)
        if not memo_path.exists():
            logger.error("Memo path does not exist: %s", memo_path)
            return 1
        memo_path_str = str(memo_path)
    else:
        stub = _write_stub_memo(args.candidate_id, reason)
        memo_path_str = str(stub)

    # Revoke
    try:
        updated = registry.revoke(
            args.candidate_id, reason=reason, memo_path=memo_path_str,
        )
    except InvalidTransitionError as e:
        logger.error("Revoke rejected: %s", e)
        return 1

    print("=" * 70)
    print(f"Candidate revoked: {args.candidate_id}")
    print("=" * 70)
    print(f"  Previous status:  {current.status.value}")
    print(f"  New status:       {updated.status.value}")
    print(f"  Reason:           {reason.value}")
    print(f"  Memo:             {memo_path_str}")
    print(f"  Revoked at:       {updated.revoked_at}")
    if reason == RevokeReason.REPRODUCIBILITY_FAILED:
        print("\nNote: reproducibility_failed reverts candidate to S0")
        print("(retry path); revoke_reason still recorded for audit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
