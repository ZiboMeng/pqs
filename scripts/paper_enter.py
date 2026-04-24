#!/usr/bin/env python
"""Transition a research candidate S1 → S2 (Phase E-2 R11).

Pipeline (S1 Research Candidate → S2 Paper Candidate):

    registry[candidate_id].status == S1
        + at least 1 paper run directory exists under
          data/paper_runs/<candidate_id>/ (i.e. the candidate has
          actually been dry-run through run_paper_candidate.py, not
          just sitting frozen)
        + optionally: at least 1 drift_report_*.md exists in a paper
          run dir (reproducibility verified)
            -> transition S1 -> S2

Hard invariants:
  - NEVER writes to config/production_strategy.yaml
  - NEVER writes to PRODUCTION_FACTORS
  - S2 -> S3 explicitly NotImplementedError (Phase F scope)

Usage:
    # Happy path — candidate has at least one paper run + drift report
    python scripts/paper_enter.py \
        --candidate-id rcm_v1_defensive_composite_01

    # Bypass drift-report check (e.g. for a fresh candidate)
    python scripts/paper_enter.py \
        --candidate-id my_cand \
        --skip-drift-report-check

The RCMv1 candidate is already at S1 via R3 migration. This script
transitions it to S2 once paper artifacts + drift report exist (which
they do after R8 + R10).

PRDs:
    docs/20260424-prd_phase_e_execution.md §2 E2-R11
    docs/20260424-prd_phase_e_governance_and_paper.md §E-2 promote-
        criteria
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.logging_setup import get_logger, setup_logging
from core.research.candidate_registry import (
    CandidateRegistry,
    CandidateStatus,
    InvalidTransitionError,
)

setup_logging()
logger = get_logger("paper_enter")


_DEFAULT_REGISTRY_DB = "data/research_candidates/registry.db"
_DEFAULT_PAPER_ROOT = Path("data/paper_runs")


def _has_paper_run(candidate_id: str) -> tuple[bool, Optional[Path]]:
    """Return (has_run, latest_run_dir). Latest = most-recently-modified."""
    base = _DEFAULT_PAPER_ROOT / candidate_id
    if not base.exists():
        return False, None
    dirs = [d for d in base.iterdir() if d.is_dir()]
    if not dirs:
        return False, None
    return True, max(dirs, key=lambda d: d.stat().st_mtime)


def _has_drift_report(run_dir: Path) -> bool:
    """Check if a paper run dir has at least one drift_report markdown."""
    return any(run_dir.glob("drift_report_*.md"))


def _assert_s3_path_is_blocked() -> None:
    """Test-accessible: S2 → S3 attempt raises NotImplementedError.

    Phase E explicitly scopes S3/S4 as design-only. Any code that
    attempts a real S2 → S3 transition must stop at this guard and
    pause for Phase F. Tested via test_s3_transition_raises.
    """
    raise NotImplementedError(
        "S2 → S3 (Deployment Candidate) transition is out of Phase E "
        "scope. Production-layer tooling (broker adapter, live feed, "
        "kill switch, monitoring) is Phase F. See "
        "docs/20260424-prd_layered_quant_architecture.md §7."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transition a research candidate S1 → S2 "
                    "(Phase E-2 R11). S2 → S3 out of scope this phase.",
    )
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--registry-db", default=_DEFAULT_REGISTRY_DB)
    parser.add_argument(
        "--skip-paper-run-check", action="store_true",
        help="Bypass the 'paper run must exist' gate. Use only if the "
             "candidate has a documented reason to skip paper "
             "validation before S2.",
    )
    parser.add_argument(
        "--skip-drift-report-check", action="store_true",
        help="Bypass the 'drift report must exist' gate. Allowed when "
             "the candidate is fresh and reproducibility is not yet "
             "at stake.",
    )
    args = parser.parse_args()

    registry = CandidateRegistry(args.registry_db)
    try:
        rec = registry.get(args.candidate_id)
    except Exception as e:
        logger.error("Candidate not found: %s", e)
        return 1

    # Idempotent: already S2 → no-op success
    if rec.status == CandidateStatus.S2_PAPER:
        logger.info(
            "Candidate %s already at S2 (updated_at=%s). No-op.",
            args.candidate_id, rec.updated_at,
        )
        print(f"Already at S2 (no-op). updated_at={rec.updated_at}")
        return 0

    # Must be at S1
    if rec.status != CandidateStatus.S1_CANDIDATE:
        logger.error(
            "Cannot paper_enter from %s (must be S1_research_candidate). "
            "Use scripts/research_promote.py (R6) to reach S1 first.",
            rec.status.value,
        )
        return 1

    # Paper run gate
    has_run, run_dir = _has_paper_run(args.candidate_id)
    if not has_run and not args.skip_paper_run_check:
        logger.error(
            "No paper run directory found under %s/%s. Run "
            "scripts/run_paper_candidate.py first, or pass "
            "--skip-paper-run-check with documented justification.",
            _DEFAULT_PAPER_ROOT, args.candidate_id,
        )
        return 1
    if has_run:
        logger.info("Found paper run: %s", run_dir)

    # Drift report gate
    if has_run and not args.skip_drift_report_check:
        if not _has_drift_report(run_dir):
            logger.error(
                "Paper run %s has no drift_report_*.md. Run "
                "scripts/paper_drift_report.py first, or pass "
                "--skip-drift-report-check.",
                run_dir,
            )
            return 1
        logger.info("Drift report found; proceeding with transition.")

    # Transition S1 → S2
    try:
        updated = registry.transition(
            args.candidate_id, CandidateStatus.S2_PAPER,
        )
    except InvalidTransitionError as e:
        logger.error("Transition failed: %s", e)
        return 1

    print("=" * 70)
    print(f"Paper enter: {args.candidate_id}")
    print("=" * 70)
    print(f"  Prev status        : {rec.status.value}")
    print(f"  New status         : S2_paper_candidate")
    print(f"  updated_at         : {updated.updated_at}")
    print(f"  Source trial       : {rec.source_trial_id}")
    print(f"  Source lineage     : {rec.source_lineage_tag}")
    print(f"  Frozen spec        : {rec.frozen_spec_path}")
    if has_run:
        print(f"  Latest paper run   : {run_dir}")
    print()
    print("S2 → S3 (Deployment Candidate) is NOT available in Phase E.")
    print("Production promote requires Phase F (broker adapter + live")
    print("feed + kill switch + monitoring) which is future scope.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
