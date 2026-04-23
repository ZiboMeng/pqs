#!/usr/bin/env python
"""Promote a research candidate from S0 to S1 (Phase E-1 R6).

Pipeline (S0 Research Prototype -> S1 Research Candidate):

    registry[candidate_id].status == S0
        + frozen_spec_path loads as valid FrozenStrategySpec
        + summary fields are REAL (no "stub" marker)
        + decision_memo_path is a real file on disk, non-empty
        + acceptance JSON outcome == "promote_to_paper"
            -> transition S0 -> S1
            -> record decision_memo_path on registry row

Hard invariants:
  - NEVER writes to config/production_strategy.yaml
  - NEVER writes to PRODUCTION_FACTORS
  - Scope: research governance only; this is NOT production_promote

Usage:
    python scripts/research_promote.py \
        --candidate-id rcm_v1_defensive_composite_01 \
        --decision-memo-path docs/20260424-rcm_v1_s1_candidate_memo.md
    # optional:
    #   --acceptance-json <path>   # default: auto-discover by trial_id
    #   --force                    # skip stub-detection (discouraged)

The RCMv1 candidate is already at S1 via R3 migration; running this
against it is rejected ("already at S1"), which is the correct no-op
for idempotency.

Forbidden outputs (enforced by test):
  - no writes to config/production_strategy.yaml
  - no writes to PRODUCTION_FACTORS
  - no touch of core/mining/archive.db (production archive)

PRD: docs/20260424-prd_phase_e_execution.md §2 E1-R6
     docs/20260424-prd_research_to_paper_promote_standard.md §8 hard blocks
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.logging_setup import get_logger, setup_logging
from core.research.candidate_registry import (
    CandidateRegistry,
    CandidateStatus,
    InvalidTransitionError,
)
from core.research.frozen_spec import FrozenSpecError, FrozenStrategySpec

setup_logging()
logger = get_logger("research_promote")


_DEFAULT_REGISTRY_DB = "data/research_candidates/registry.db"
_DEFAULT_ARTIFACT_ROOT = Path("data/ml/research_miner")


def _auto_discover_acceptance(source_trial_id: str,
                              root: Path = _DEFAULT_ARTIFACT_ROOT) -> Optional[Path]:
    """Find the latest acceptance JSON for a source_trial_id.

    Searches `<root>/<study>/acceptance/acceptance_<trial_id>.json` and
    returns the most recently modified match.
    """
    if not root.exists():
        return None
    matches = list(root.glob(f"*/acceptance/acceptance_{source_trial_id}.json"))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def _contains_stub(summary: Any) -> bool:
    """Detect the 'stub' marker set by freeze_research_candidate.py.

    R6 hard block: a candidate whose evidence is still the freeze-time
    stub has not had real acceptance run; S1 promote is refused.
    """
    if isinstance(summary, dict):
        note = summary.get("note", "")
        if isinstance(note, str) and "stub" in note.lower():
            return True
    if isinstance(summary, str):
        if "stub" in summary.lower() or "TODO" in summary:
            return True
    return False


def _check_decision_memo(memo_path_str: str) -> tuple[bool, str]:
    """Validate --decision-memo-path. Returns (ok, error_message)."""
    # Auto-detect placeholder from freeze CLI
    if memo_path_str.startswith("TODO") or "TODO: author" in memo_path_str:
        return False, (
            "decision_memo is still a freeze-time placeholder; author a "
            "real markdown memo and pass it via --decision-memo-path"
        )
    p = Path(memo_path_str)
    if not p.exists():
        return False, f"decision memo path does not exist: {memo_path_str}"
    if not p.is_file():
        return False, f"decision memo is not a file: {memo_path_str}"
    content = p.read_text().strip()
    if len(content) < 50:
        return False, (
            f"decision memo too short ({len(content)} chars); require "
            "substantive content (>= 50 chars)"
        )
    return True, ""


def _check_acceptance(acceptance_path: Optional[Path]) -> tuple[bool, str]:
    """Validate acceptance JSON outcome. Returns (ok, error_message)."""
    if acceptance_path is None:
        return False, (
            "no acceptance JSON found; pass --acceptance-json or run "
            "scripts/acceptance_research_composite.py first"
        )
    try:
        data = json.loads(acceptance_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return False, f"cannot read acceptance JSON: {e}"
    decision = data.get("decision", {})
    outcome = decision.get("outcome")
    if outcome != "promote_to_paper":
        reasons = decision.get("blocking_reasons", [])
        return False, (
            f"acceptance outcome={outcome!r} (required: "
            f"'promote_to_paper'); blocking_reasons={reasons}"
        )
    return True, ""


def _assert_no_production_writes(registry_db_path: Path) -> None:
    """Pre-run: assert we're not about to write to production config.

    This is a guardrail check. The implementation does not have any
    call to config/production_strategy.yaml; this function is the
    belt-and-suspenders documentation of that invariant.
    """
    forbidden = [
        Path("config/production_strategy.yaml"),
        Path("config/universe.yaml"),
    ]
    # We only check the paths aren't the destination; actual integrity
    # is guaranteed by the implementation (we simply don't write there).
    for p in forbidden:
        if str(p) == str(registry_db_path):
            raise RuntimeError(
                f"Registry path conflicts with forbidden production "
                f"config path: {p}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote a research candidate S0 -> S1 "
                    "(Phase E-1 R6). Never touches production config.",
    )
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--decision-memo-path", required=True,
                        help="Path to markdown decision memo (must exist, "
                             ">= 50 chars)")
    parser.add_argument("--acceptance-json", default=None,
                        help="Acceptance JSON path; default: auto-discover "
                             "by source_trial_id")
    parser.add_argument("--registry-db", default=_DEFAULT_REGISTRY_DB)
    parser.add_argument("--force", action="store_true",
                        help="Skip stub-detection (discouraged; use only "
                             "if you understand why a stub summary is OK)")
    args = parser.parse_args()

    # Guardrail: we're not writing to production
    _assert_no_production_writes(Path(args.registry_db))

    # Load candidate
    registry = CandidateRegistry(args.registry_db)
    try:
        rec = registry.get(args.candidate_id)
    except Exception as e:
        logger.error("Candidate not found: %s", e)
        return 1

    # Idempotency: already S1 -> no-op success
    if rec.status == CandidateStatus.S1_CANDIDATE:
        logger.info("Candidate %s already at S1 (promoted_at=%s). No-op.",
                    args.candidate_id, rec.promoted_at)
        print(f"Already at S1 (no-op). promoted_at={rec.promoted_at}")
        return 0

    # Must be at S0 to promote
    if rec.status != CandidateStatus.S0_PROTOTYPE:
        logger.error(
            "Cannot promote from %s (must be S0_research_prototype). "
            "If this candidate was revoked, use a new candidate_id.",
            rec.status.value,
        )
        return 1

    # Validate frozen spec still loads
    if not rec.frozen_spec_path:
        logger.error("Candidate has no frozen_spec_path in registry")
        return 1
    try:
        spec = FrozenStrategySpec.from_yaml_file(rec.frozen_spec_path)
    except FrozenSpecError as e:
        logger.error("Frozen spec no longer validates: %s", e)
        return 1
    except FileNotFoundError:
        logger.error("Frozen spec file missing: %s", rec.frozen_spec_path)
        return 1

    # Hard block: stub summaries (unless --force)
    if not args.force:
        for name in ("benchmark_relative_summary", "oos_holdout_summary",
                     "robustness_summary"):
            if _contains_stub(getattr(spec, name)):
                logger.error(
                    "HARD BLOCK: %s still contains freeze-time stub. "
                    "Run scripts/acceptance_research_composite.py to "
                    "produce real evidence, edit the frozen YAML to "
                    "replace the stub, then re-run promote. "
                    "(Use --force to skip this check; discouraged.)",
                    name,
                )
                return 1

    # Validate decision memo
    ok, err = _check_decision_memo(args.decision_memo_path)
    if not ok:
        logger.error("decision memo rejected: %s", err)
        return 1

    # Validate acceptance JSON (auto-discover if not provided)
    accept_path: Optional[Path] = None
    if args.acceptance_json:
        accept_path = Path(args.acceptance_json)
    else:
        accept_path = _auto_discover_acceptance(spec.source_trial_id)
        if accept_path is None:
            logger.error(
                "No acceptance JSON auto-discovered for source_trial_id=%s. "
                "Pass --acceptance-json or run "
                "scripts/acceptance_research_composite.py first.",
                spec.source_trial_id,
            )
            return 1
        logger.info("Auto-discovered acceptance JSON: %s", accept_path)

    ok, err = _check_acceptance(accept_path)
    if not ok:
        logger.error("acceptance rejected: %s", err)
        return 1

    # Transition S0 -> S1
    try:
        updated = registry.transition(
            args.candidate_id, CandidateStatus.S1_CANDIDATE,
        )
    except InvalidTransitionError as e:
        logger.error("Transition failed: %s", e)
        return 1

    # Record the decision memo path
    registry.update_paths(
        args.candidate_id,
        decision_memo_path=args.decision_memo_path,
    )

    print("=" * 70)
    print(f"Research promote: {args.candidate_id}")
    print("=" * 70)
    print(f"  Prev status        : {rec.status.value}")
    print(f"  New status         : S1_research_candidate")
    print(f"  promoted_at        : {updated.promoted_at}")
    print(f"  Source trial       : {rec.source_trial_id}")
    print(f"  Source lineage     : {rec.source_lineage_tag}")
    print(f"  Frozen spec        : {rec.frozen_spec_path}")
    print(f"  Decision memo      : {args.decision_memo_path}")
    print(f"  Acceptance artifact: {accept_path}")
    print(f"\nNOTE: this does NOT modify config/production_strategy.yaml.")
    print(f"S2 (paper_enter) available via scripts/paper_enter.py (R11).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
