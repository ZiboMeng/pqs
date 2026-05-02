"""Backfill candidate_role for pre-PRD forward manifests + registry rows.

Per Two-Stage Allocation Architecture PRD Phase C-PRD-1
(docs/prd/20260501-two_stage_allocation_architecture_prd.md):

Pre-PRD candidates (RCMv1, Cand-2 + any other forward-active before
2026-05-01) had no candidate_role field. Schema lazy-migration sets
default = legacy_decay_verification on read; this script makes that
EXPLICIT in the persisted artifacts so:
1. Manual inspection sees role tag without relying on default
2. Forward observation tools that emit role-conditional reports
   show the correct role
3. Audit trail records when role was assigned

Idempotent: skips manifests that already have candidate_role set.
Idempotent: skips registry rows that already have role != default.

Usage:
    python dev/scripts/forward/backfill_candidate_role.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJ = Path("/home/zibo/Documents/projects/pqs")
sys.path.insert(0, str(PROJ))

from core.research.candidate_registry import (
    CandidateRegistry, _VALID_ROLES,
)
from core.research.forward import runner
from core.research.forward.manifest_schema import CandidateRole

# Pre-PRD candidates known to be active forward-observed.
# Conservative default: all legacy candidates → role=legacy_decay_verification.
LEGACY_CANDIDATES = [
    "rcm_v1_defensive_composite_01",
    "candidate_2_orthogonal_01",
]


def backfill_manifest(candidate_id: str, dry_run: bool = False) -> dict:
    """Set candidate_role + soft_warn_flags on existing manifest if absent.

    Returns: {action: 'noop'|'updated'|'missing', current_role, manifest_path}
    """
    output_dir = runner.DEFAULT_OUTPUT_DIR
    mp = runner.manifest_path(candidate_id, output_dir)
    if not mp.exists():
        return {"action": "missing", "manifest_path": str(mp)}

    manifest = runner.load_manifest(mp)
    current_role = manifest.candidate_role.value
    flags = list(manifest.soft_warn_flags)

    # If role is non-default and flags present, no-op
    if current_role != "legacy_decay_verification":
        return {"action": "noop_already_set", "current_role": current_role,
                "manifest_path": str(mp)}

    # Manifest may have role=legacy_decay_verification implicitly (lazy
    # migration default). Check raw JSON to know if it was EXPLICITLY set
    # vs default-on-load.
    raw = json.loads(mp.read_text())
    if "candidate_role" in raw and raw["candidate_role"] == current_role:
        return {"action": "noop_already_explicit", "current_role": current_role,
                "manifest_path": str(mp)}

    # Backfill: re-save manifest with candidate_role written explicitly
    if dry_run:
        return {"action": "would_update", "new_role": "legacy_decay_verification",
                "manifest_path": str(mp)}

    runner.save_manifest(manifest, mp)
    return {"action": "updated", "new_role": "legacy_decay_verification",
            "manifest_path": str(mp)}


def backfill_registry_row(candidate_id: str, dry_run: bool = False) -> dict:
    """Update registry row's role column if still at default.

    Returns: {action, current_role}
    """
    registry = CandidateRegistry()
    try:
        rec = registry.get(candidate_id)
    except Exception as exc:
        return {"action": "missing", "error": str(exc)}

    if rec.role != "legacy_decay_verification":
        return {"action": "noop_already_set", "current_role": rec.role}

    if dry_run:
        return {"action": "would_set", "current_role": rec.role,
                "would_set_to": "legacy_decay_verification"}

    # Direct UPDATE — registry doesn't expose mutate_role API yet (intentional;
    # role is supposed to be immutable post-init). Backfill is the one
    # legitimate exception.
    with sqlite3.connect(str(registry.db_path)) as conn:
        conn.execute(
            "UPDATE research_candidates SET role = ?, updated_at = datetime('now') "
            "WHERE candidate_id = ? AND role = 'legacy_decay_verification'",
            ("legacy_decay_verification", candidate_id),
        )
        conn.commit()
    return {"action": "no_change_default_already_correct"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print actions without modifying files")
    args = ap.parse_args()

    print(f"[backfill] Phase C-PRD-1 backfill_candidate_role")
    print(f"[backfill] Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print(f"[backfill] Legacy candidates: {LEGACY_CANDIDATES}")
    print()

    for cid in LEGACY_CANDIDATES:
        print(f"[backfill] === {cid} ===")
        m = backfill_manifest(cid, dry_run=args.dry_run)
        print(f"  manifest: {m['action']} (role={m.get('current_role') or m.get('new_role')})")
        r = backfill_registry_row(cid, dry_run=args.dry_run)
        print(f"  registry: {r['action']} (current_role={r.get('current_role')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
