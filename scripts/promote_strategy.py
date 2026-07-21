#!/usr/bin/env python
"""Promote a mining archive spec_id to production (PRD M2).

Workflow:
  1. Run acceptance pack on spec_id (via core.mining.acceptance_pack)
  2. If overall_passed, atomically rewrite config/production_strategy.yaml
     with status=active, source.mode=promoted_from_archive, fingerprints
     computed from current repo state
  3. User must `git diff config/production_strategy.yaml` and `git commit`
     to make the promotion effective

Safety:
  - Without --promote flag, only shows dry-run diff
  - Automatic gates cannot be bypassed with --force
  - Promotion requires candidate-bound lookahead/overfit/alignment evidence

Usage:
  python scripts/promote_strategy.py --spec-id 81f5 --dry-run --promotion-evidence path.json
  python scripts/promote_strategy.py --spec-id X --promote --promotion-evidence path.json
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.mining.acceptance_pack import (
    AcceptancePackError,
    AcceptancePackResult,
    run_acceptance_pack,
)
from core.research.promotion.fingerprints import (
    compute_fingerprints as _compute_fingerprints_util,
)


_MFS_PARAM_KEYS = [
    "top_n", "rebalance_monthly", "score_weighted", "min_holding_days",
    "lookback_mom", "lookback_quality", "lookback_vol", "apply_extra_shift",
]


def _compute_fingerprints(universe_name: str = "executable") -> dict:
    """Snapshot current repo state into artifact fingerprints.

    Delegates to ``core.research.promotion.fingerprints.compute_fingerprints``
    (PRD #3 P3.5 reusable utility). Byte-for-byte identical to the
    pre-extraction inline helper for ``universe_name in {executable,
    expanded_v1}`` with the production registry (D6/P4-A2 invariant —
    every pre-existing promote produces the same hash).
    """
    return _compute_fingerprints_util(
        universe_name=universe_name, registry="production"
    )


def _build_promoted_yaml(
    pack: AcceptancePackResult,
    rationale: str,
    universe_name: str = "executable",
) -> dict:
    """Produce the dict that will be written to production_strategy.yaml as active."""
    # Separate MFS ctor params from factor_weights in archived params
    params = dict(pack.params)
    factor_weights = params.pop("factor_weights", None)
    if factor_weights is None:
        # Some archives use 'weights' key
        factor_weights = params.pop("weights", None)
    if factor_weights is None:
        # MultiFactorSpace.suggest() stores weights as w_<factor_name>
        w_keys = [k for k in list(params.keys()) if k.startswith("w_")]
        if w_keys:
            factor_weights = {k[2:]: params.pop(k) for k in w_keys}
    if not factor_weights:
        raise AcceptancePackError(
            f"spec_id {pack.spec_id} has no factor_weights in archive params; "
            f"cannot promote."
        )

    # Keep only canonical params (drop mining-specific keys)
    canonical_params = {k: params[k] for k in _MFS_PARAM_KEYS if k in params}
    # Fill defaults for keys not in archive (older mining rows may lack these)
    canonical_params.setdefault("apply_extra_shift", False)

    fingerprints = _compute_fingerprints(universe_name)
    now = datetime.now(timezone.utc).isoformat()

    gates = {gate.name: gate for gate in pack.gates}
    qqq_diagnostic = gates.get("qqq_hard_gate_archive")
    return {
        "schema_version": "1.0",
        "status": "active",
        "strategy_type": pack.strategy_type,
        "source": {
            "mode": "promoted_from_archive",
            "spec_id": pack.spec_id,
            "lineage_tag": pack.lineage_tag,
            "promoted_at": now,
            "rationale": rationale,
        },
        "params": canonical_params,
        "factor_weights": factor_weights,
        "validation": {
            "post_fix_validated": True,
            "passed_oos_gate": True,
            "passed_spy_gate": gates["full_period_fresh_backtest"].passed,
            "passed_qqq_gate": bool(
                qqq_diagnostic and qqq_diagnostic.passed
            ),
            "passed_paper_backtest_alignment": gates[
                "paper_backtest_alignment"
            ].passed,
            "promotion_evidence_path": pack.promotion_evidence_path,
            "promotion_evidence_sha256": pack.promotion_evidence_sha256,
            "notes": f"Promoted via scripts/promote_strategy.py at {now} after acceptance pack PASS.",
        },
        "fingerprints": fingerprints,
    }


def _show_dry_run(proposed: dict, current_path: Path) -> None:
    """Print the diff between current yaml and proposed yaml."""
    print("=" * 70)
    print("PROPOSED production_strategy.yaml contents:")
    print("=" * 70)
    print(yaml.safe_dump(proposed, default_flow_style=False, sort_keys=False))
    if current_path.exists():
        current = yaml.safe_load(current_path.read_text())
        cur_status = current.get("status", "(missing)")
        print("=" * 70)
        print(f"Current status: {cur_status}  →  Proposed: {proposed['status']}")
        print(f"Current weights: {current.get('factor_weights')}")
        print(f"Proposed weights: {proposed['factor_weights']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote archived spec_id to production (PRD M2)")
    parser.add_argument("--spec-id", required=True,
                        help="Archive spec_id (prefix match allowed)")
    parser.add_argument("--archive-db", default="data/mining/archive.db")
    parser.add_argument("--target", default="config/production_strategy.yaml",
                        help="Path to production_strategy.yaml to rewrite")
    parser.add_argument("--rationale", default="",
                        help="Why this spec_id was promoted (stored in source.rationale)")
    parser.add_argument("--universe", choices=["executable", "expanded_v1", "expanded_v2"],
                        default="executable",
                        help="universe the candidate was mined on (P4-A1 "
                             "propagation: universe_hash + recorded universe "
                             "field computed from the matching yaml). Default "
                             "executable = config/universe.yaml byte-for-byte "
                             "unchanged (D6/P4-A2). Cross-check against the "
                             "mining run_summary.json 'universe' field.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show the proposed yaml + diff, do not write")
    parser.add_argument("--promote", action="store_true",
                        help="Actually write the new yaml (requires --dry-run complement)")
    parser.add_argument("--force", action="store_true",
                        help="Deprecated and refused: automatic gates cannot be bypassed")
    parser.add_argument("--yes-i-know-what-im-doing", action="store_true",
                        dest="confirm_force")
    parser.add_argument("--skip-fresh-backtest", action="store_true",
                        help="Deprecated and refused: fresh SPY check is mandatory")
    parser.add_argument(
        "--promotion-evidence",
        default=None,
        help="Candidate-bound promotion evidence JSON (required for --promote)",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.promote:
        print("ERROR: must pass --dry-run or --promote", file=sys.stderr)
        return 2
    if args.skip_fresh_backtest:
        print("ERROR: automatic promotion cannot skip the fresh SPY backtest", file=sys.stderr)
        return 2
    if args.force or args.confirm_force:
        print(
            "ERROR: automatic promotion gates cannot be bypassed; a manual "
            "exception requires a separately reviewed governance decision",
            file=sys.stderr,
        )
        return 2
    if args.promote:
        tracked_changes = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            text=True,
        ).strip()
        if tracked_changes:
            print(
                "ERROR: tracked worktree must be clean before automatic promotion",
                file=sys.stderr,
            )
            return 2
    if not args.promotion_evidence:
        print(
            "ERROR: --promotion-evidence is required for promotion dry-run or write",
            file=sys.stderr,
        )
        return 2

    # Run acceptance pack
    try:
        pack = run_acceptance_pack(
            args.spec_id, archive_db=args.archive_db,
            run_fresh_backtest=True,
            automatic_promotion=True,
            promotion_evidence_path=args.promotion_evidence,
            repo_root=ROOT,
        )
    except AcceptancePackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(pack.summary_line())
    for g in pack.gates:
        mark = "✅" if g.passed else ("❌" if g.binding else "ℹ️")
        print(f"  {mark} {g.name}")

    # Verdict
    if not pack.overall_passed:
        print(
            "\nRefusing to promote — one or more binding gates failed. "
            "The candidate remains REVIEW_HOLD.",
            file=sys.stderr,
        )
        return 1

    # Build proposed yaml
    rationale = args.rationale or (
        f"Promoted from archive (spec_id={pack.spec_id[:12]}, "
        f"lineage={pack.lineage_tag}). Acceptance pack "
        f"PASSED on "
        f"{datetime.now(timezone.utc).isoformat()}."
    )
    try:
        proposed = _build_promoted_yaml(pack, rationale, args.universe)
    except AcceptancePackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    target_path = ROOT / args.target if not Path(args.target).is_absolute() else Path(args.target)

    if args.dry_run and not args.promote:
        _show_dry_run(proposed, target_path)
        print("\nDry run complete. Re-run with --promote to write.")
        return 0

    # Actual write
    _show_dry_run(proposed, target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.", dir=target_path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(
                proposed,
                handle,
                default_flow_style=False,
                sort_keys=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target_path)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"\n✅ Wrote {target_path}")
    print("Next steps:")
    print("  1. git diff config/production_strategy.yaml   # review change")
    print("  2. pytest -q                                   # sanity")
    print(
        "  3. git add config/production_strategy.yaml "
        f"{pack.promotion_evidence_path}"
    )
    print(f'  4. git commit -m "promote {pack.spec_id[:12]} to production"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
