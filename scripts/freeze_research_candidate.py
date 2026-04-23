#!/usr/bin/env python
"""Freeze a rcm_archive trial into a research candidate (Phase E-1 R5).

Pipeline:
    rcm_archive.rcm_trials[trial_id]
        -> FrozenStrategySpec (R4 schema)
            -> data/research_candidates/<candidate_id>.yaml
            -> candidate_registry row at status S0_research_prototype

Usage:
    # freeze a specific trial
    python scripts/freeze_research_candidate.py \
        --trial-id f24aefecc91a \
        --candidate-id my_candidate_v1 \
        --decision-memo docs/20260425-memo.md

    # freeze the Nth-best trial in a lineage (0 = top-1)
    python scripts/freeze_research_candidate.py \
        --lineage-tag post-2026-04-24-rcm-v1-lag1 \
        --top-k-index 0 \
        --candidate-id rcm_v1_defensive_02

This script produces a **S0 prototype candidate**. Moving to S1 requires
`scripts/research_promote.py` (R6) with full acceptance evidence.

Refusal cases:
  - --candidate-id already exists in registry -> exit 1 (use
    scripts/revoke_candidate.py first if replacing)
  - source trial not found in archive -> exit 1
  - strategy_version malformed -> exit 1 (caught by FrozenSpecError)

PRD: docs/20260424-prd_phase_e_execution.md §2 E1-R5
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.logging_setup import get_logger, setup_logging
from core.research.candidate_registry import (
    CandidateRegistry,
    CandidateStatus,
    DuplicateCandidateError,
)
from core.research.frozen_spec import (
    FeatureEntry,
    FrozenSpecError,
    FrozenStrategySpec,
)

setup_logging()
logger = get_logger("freeze_research_candidate")


_DEFAULT_ARCHIVE_DB = "data/mining/rcm_archive.db"
_DEFAULT_REGISTRY_DB = "data/research_candidates/registry.db"
_SPEC_DIR = Path("data/research_candidates")


def _load_trial(archive_db: str, trial_id: Optional[str],
                lineage_tag: Optional[str],
                top_k_index: int) -> dict[str, Any]:
    """Return the trial row as a dict. Resolve via explicit trial_id OR
    lineage_tag+top_k_index."""
    if not (trial_id or lineage_tag):
        raise ValueError(
            "Must provide either --trial-id or --lineage-tag"
        )
    conn = sqlite3.connect(archive_db)
    conn.row_factory = sqlite3.Row
    try:
        if trial_id:
            row = conn.execute(
                "SELECT * FROM rcm_trials WHERE trial_id = ?",
                (trial_id,),
            ).fetchone()
        else:
            # top_k_index-th by objective (0 = top-1)
            row = conn.execute(
                "SELECT * FROM rcm_trials WHERE lineage_tag = ? "
                "AND objective IS NOT NULL "
                "ORDER BY objective DESC LIMIT 1 OFFSET ?",
                (lineage_tag, top_k_index),
            ).fetchone()
        if row is None:
            src = f"trial_id={trial_id!r}" if trial_id else \
                f"lineage_tag={lineage_tag!r} top_k_index={top_k_index}"
            raise LookupError(
                f"No trial found for {src} in {archive_db}"
            )
        return dict(row)
    finally:
        conn.close()


def _build_frozen_spec(
    trial: dict[str, Any],
    *,
    candidate_id: str,
    strategy_version: str,
    decision_memo: str,
) -> FrozenStrategySpec:
    """Map a rcm_trials row into a FrozenStrategySpec (R4 schema)."""
    # Parse the spec_json stored in rcm_trials
    try:
        spec_payload = json.loads(trial["spec_json"])
    except (KeyError, TypeError, json.JSONDecodeError) as e:
        raise FrozenSpecError(
            f"rcm_trial.spec_json malformed for trial_id="
            f"{trial.get('trial_id')}: {e}"
        )

    features = spec_payload.get("features", [])
    weights = spec_payload.get("weights", [])
    if len(features) != len(weights):
        raise FrozenSpecError(
            f"features/weights length mismatch: {len(features)} vs {len(weights)}"
        )
    feature_set = [
        FeatureEntry(name=str(name), weight=float(w))
        for name, w in zip(features, weights)
    ]

    # Derive minimal summary stubs from archive metadata. These are
    # "weak evidence" stubs — research_promote.py (R6) will require
    # fuller acceptance evidence to transition S0 -> S1.
    benchmark_relative_summary = {
        "note": "stub derived from rcm_archive at freeze time; "
                "full benchmark-relative report required for S1 promote",
        "corr_concentration": trial.get("corr_concentration"),
    }
    oos_holdout_summary = {
        "note": "stub derived from rcm_archive at freeze time; "
                "full walk-forward + holdout required for S1 promote",
        "ic_mean_full_period": trial.get("ic_mean"),
        "ic_std_full_period": trial.get("ic_std"),
        "ic_ir_full_period": trial.get("ic_ir"),
        "n_dates": trial.get("n_dates"),
    }
    robustness_summary = {
        "note": "stub derived from rcm_archive at freeze time; "
                "weight sensitivity + regime stability required for S1 promote",
        "turnover_proxy": trial.get("turnover_proxy"),
        "corr_concentration": trial.get("corr_concentration"),
        "objective": trial.get("objective"),
    }

    # Optional: family_counts from spec_payload
    family_counts = spec_payload.get("family_counts")

    spec = FrozenStrategySpec(
        candidate_id=candidate_id,
        strategy_version=strategy_version,
        source_trial_id=str(trial["trial_id"]),
        feature_set=feature_set,
        benchmark_relative_summary=benchmark_relative_summary,
        oos_holdout_summary=oos_holdout_summary,
        robustness_summary=robustness_summary,
        decision_memo=decision_memo,
        # Optional provenance
        source={
            "trial_id": str(trial["trial_id"]),
            "lineage_tag": trial.get("lineage_tag"),
            "study_id": trial.get("study_id"),
            "archive_db": _DEFAULT_ARCHIVE_DB,
            "family_counts": family_counts,
        },
        strategy_type="single_factor_composite",
        family="research_composite",
        transforms={
            "standardization": "zscore_cross_sectional",
            "implementation": "core/mining/research_miner.py::zscore_cs",
        },
        composite_rule={
            "method": "weighted_sum",
            "implementation":
                "core/mining/research_miner.py::build_composite_series",
        },
        notes=(
            f"Frozen from rcm_archive trial {trial['trial_id']} on "
            f"{datetime.now(timezone.utc).isoformat()}. "
            "Summary fields are STUBS at S0 freeze time; R6 promote "
            "requires full acceptance evidence."
        ),
    )
    return spec


def _default_strategy_version(candidate_id: str) -> str:
    """If the user didn't provide --strategy-version, derive one from
    the candidate_id + UTC date."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Keep candidate_id as the version prefix so they're co-referent.
    # Regex in FrozenStrategySpec: ^[a-zA-Z][\w\-.]{1,}$
    return f"{candidate_id}-{today}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze an rcm_archive trial into a research "
                    "candidate (Phase E-1 R5)",
    )
    # Source: exactly one of --trial-id or --lineage-tag
    parser.add_argument("--trial-id", default=None,
                        help="Explicit rcm_archive trial_id to freeze")
    parser.add_argument("--lineage-tag", default=None,
                        help="Lineage tag; picks top-K by objective "
                             "(see --top-k-index)")
    parser.add_argument("--top-k-index", type=int, default=0,
                        help="When using --lineage-tag, freeze this "
                             "0-indexed rank (default 0 = top-1)")
    # Required identity
    parser.add_argument("--candidate-id", required=True,
                        help="Unique candidate identifier")
    parser.add_argument("--strategy-version", default=None,
                        help="Optional; defaults to "
                             "<candidate-id>-<YYYY-MM-DD>")
    # Decision memo (path recommended; can be inline text)
    parser.add_argument("--decision-memo", default=None,
                        help="Path to decision memo markdown (or inline "
                             "string). Required at S0; R6 promote will "
                             "require non-stub content.")
    parser.add_argument("--archive-db", default=_DEFAULT_ARCHIVE_DB)
    parser.add_argument("--registry-db", default=_DEFAULT_REGISTRY_DB)
    parser.add_argument("--out-path", default=None,
                        help="Frozen YAML output path; default "
                             "data/research_candidates/<candidate-id>.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build + validate but don't write / register")

    args = parser.parse_args()

    # Validate source args
    if bool(args.trial_id) == bool(args.lineage_tag):
        logger.error(
            "Provide exactly one of --trial-id or --lineage-tag "
            "(got: trial_id=%s, lineage_tag=%s)",
            args.trial_id, args.lineage_tag,
        )
        return 1

    # Decision memo default: auto-stub path
    decision_memo = args.decision_memo
    if decision_memo is None:
        # Point at a stub location; the actual memo content should be
        # authored before R6 promote. We use a placeholder path that's
        # valid for the schema but flags future work.
        decision_memo = (
            f"TODO: author decision memo for {args.candidate_id} "
            f"before research_promote.py"
        )

    strategy_version = args.strategy_version or _default_strategy_version(
        args.candidate_id,
    )

    # Load source trial
    try:
        trial = _load_trial(
            args.archive_db, args.trial_id, args.lineage_tag,
            args.top_k_index,
        )
    except LookupError as e:
        logger.error("%s", e)
        return 1

    logger.info("Source trial: %s (lineage=%s, objective=%.4f, ic_ir=%.4f)",
                trial["trial_id"], trial.get("lineage_tag"),
                trial.get("objective") or 0.0, trial.get("ic_ir") or 0.0)

    # Registry duplicate check (before building spec for clearer error)
    registry = CandidateRegistry(args.registry_db)
    if registry.exists(args.candidate_id):
        existing = registry.get(args.candidate_id)
        logger.error(
            "candidate_id=%s already exists (status=%s, source_trial=%s). "
            "Use scripts/revoke_candidate.py first if replacing.",
            args.candidate_id, existing.status.value, existing.source_trial_id,
        )
        return 1

    # Build FrozenStrategySpec
    try:
        spec = _build_frozen_spec(
            trial,
            candidate_id=args.candidate_id,
            strategy_version=strategy_version,
            decision_memo=decision_memo,
        )
    except FrozenSpecError as e:
        logger.error("FrozenSpec validation failed: %s", e)
        return 1

    # Resolve output path
    out_path = Path(args.out_path) if args.out_path else (
        _SPEC_DIR / f"{args.candidate_id}.yaml"
    )

    if args.dry_run:
        print("=" * 70)
        print(f"DRY-RUN: would freeze trial {trial['trial_id']} -> "
              f"candidate {args.candidate_id}")
        print("=" * 70)
        print(f"Frozen YAML output : {out_path}")
        print(f"Registry row       : status=S0_research_prototype")
        print(f"\nYAML preview (first 40 lines):")
        print("\n".join(spec.to_yaml().splitlines()[:40]))
        return 0

    # Write YAML
    spec.to_yaml_file(out_path)
    logger.info("Frozen spec written to %s", out_path)

    # Register at S0
    try:
        rec = registry.register(
            candidate_id=args.candidate_id,
            source_trial_id=trial["trial_id"],
            source_lineage_tag=trial.get("lineage_tag") or "",
            status=CandidateStatus.S0_PROTOTYPE,
            frozen_spec_path=str(out_path),
            decision_memo_path=(
                decision_memo if decision_memo.endswith(".md") else None
            ),
        )
    except DuplicateCandidateError:
        # Race condition (shouldn't happen after exists check above)
        logger.error(
            "candidate_id=%s registered by a concurrent process",
            args.candidate_id,
        )
        return 1

    print("=" * 70)
    print(f"Frozen candidate: {args.candidate_id}")
    print("=" * 70)
    print(f"  Source trial       : {trial['trial_id']}")
    print(f"  Source lineage_tag : {trial.get('lineage_tag')}")
    print(f"  Strategy version   : {strategy_version}")
    print(f"  N features         : {len(spec.feature_set)}")
    print(f"  Status             : {rec.status.value}")
    print(f"  Frozen YAML        : {out_path}")
    print(f"  Next step          : edit decision memo, then run "
          f"scripts/research_promote.py (R6)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
