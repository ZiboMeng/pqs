#!/usr/bin/env python3
"""F PRD step 4: backfill a `config_snapshot` onto pre-PRD-F forward manifests.

Background
----------
Before PRD F shipped, `init()` did not pin a `ConfigSnapshot` on the
manifest. Existing TD001-TD003 manifests for `rcm_v1_defensive_composite_01`
and `candidate_2_orthogonal_01` therefore have `config_snapshot=None`.
At observe time, `revalidate_manifest()` correctly skips drift detection
for those legacy manifests (lazy-migration boundary, PRD F §5.6).

This utility lets the user OPT IN to drift detection on a legacy
manifest by stamping a `ConfigSnapshot` of the **current** config tree.

Contract (PRD F §5.6 + codex round-18 §3 follow-up)
---------------------------------------------------
- **Idempotent**: re-running on a manifest that already has a
  `config_snapshot` is a no-op (utility refuses to overwrite without
  `--force`).
- **Migration-note marker**: the stamped snapshot records
  `migration_note="backfilled_YYYY-MM-DD_assumed_unchanged_since_init"`
  so future drift events can be reasoned about — the snapshot was NOT
  pinned at init time; it represents the user's assertion that "as of
  the backfill date, the live config has not drifted from init's
  config".
- **No retroactive hash claim**: snapshot fields hold today's hashes,
  not init-time hashes. The migration_note is the audit-trail honesty
  signal.
- **Dry-run by default safe**: `--dry-run` previews changes without
  writing.

Usage
-----
::

    # Preview what would change (NO disk write)
    python dev/scripts/forward/backfill_config_snapshot.py \\
        --manifest data/research_candidates/rcm_v1_defensive_composite_01_forward_manifest.json \\
        --dry-run

    # Stamp the snapshot on disk
    python dev/scripts/forward/backfill_config_snapshot.py \\
        --manifest data/research_candidates/rcm_v1_defensive_composite_01_forward_manifest.json

    # Force overwrite an existing config_snapshot (rare; bumps the
    # migration_note timestamp)
    python dev/scripts/forward/backfill_config_snapshot.py \\
        --manifest data/research_candidates/rcm_v1_defensive_composite_01_forward_manifest.json \\
        --force

After backfill, the next `forward observe` run includes config drift
detection for that candidate.

PRD: docs/prd/20260428-config_universe_snapshot_hardening_prd.md §5.6 + §7.4
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.research.forward.manifest_io import load_manifest, save_manifest
from core.research.forward.manifest_schema import ConfigSnapshot
from core.research.forward.runner import _DEFAULT_CONFIG_DIR, _build_config_snapshot


def _build_migration_note(today: date) -> str:
    return f"backfilled_{today.isoformat()}_assumed_unchanged_since_init"


def backfill_one(
    manifest_path: Path,
    *,
    config_dir: Path = _DEFAULT_CONFIG_DIR,
    force: bool = False,
    dry_run: bool = False,
    today: date | None = None,
) -> dict:
    """Backfill `config_snapshot` on a single manifest.

    Returns a status dict for CLI display + test introspection:

    .. code-block:: python

        {
            "manifest_path": str,
            "candidate_id": str,
            "action": "backfilled" | "skipped_already_present" | "force_overwritten" | "dry_run_preview",
            "migration_note": str,                 # the new note, if applicable
            "snapshot_before_was_none": bool,      # True iff the pre-state was a legacy manifest
        }
    """
    today = today or date.today()
    manifest = load_manifest(manifest_path)

    pre_was_none = manifest.config_snapshot is None
    if not pre_was_none and not force:
        return {
            "manifest_path": str(manifest_path),
            "candidate_id": manifest.candidate_id,
            "action": "skipped_already_present",
            "migration_note": manifest.config_snapshot.migration_note,
            "snapshot_before_was_none": False,
        }

    new_snapshot_template = _build_config_snapshot(Path(config_dir))
    migration_note = _build_migration_note(today)
    new_snapshot = new_snapshot_template.model_copy(
        update={"migration_note": migration_note}
    )

    if dry_run:
        return {
            "manifest_path": str(manifest_path),
            "candidate_id": manifest.candidate_id,
            "action": "dry_run_preview",
            "migration_note": migration_note,
            "snapshot_before_was_none": pre_was_none,
        }

    new_manifest = manifest.model_copy(update={"config_snapshot": new_snapshot})
    save_manifest(new_manifest, manifest_path)

    return {
        "manifest_path": str(manifest_path),
        "candidate_id": manifest.candidate_id,
        "action": "force_overwritten" if not pre_was_none else "backfilled",
        "migration_note": migration_note,
        "snapshot_before_was_none": pre_was_none,
    }


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument(
        "--manifest", required=True,
        help="path to a forward_run_manifest.json to backfill",
    )
    p.add_argument(
        "--config-dir", default=str(_DEFAULT_CONFIG_DIR),
        help="root config dir (default: config/). Same contract as init/observe.",
    )
    p.add_argument(
        "--force", action="store_true",
        help="overwrite an existing config_snapshot (bumps migration_note timestamp).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="preview the change without writing to disk.",
    )
    args = p.parse_args(argv)

    result = backfill_one(
        Path(args.manifest),
        config_dir=Path(args.config_dir),
        force=args.force,
        dry_run=args.dry_run,
    )
    print(
        f"[{result['action']}] candidate={result['candidate_id']!r}\n"
        f"  manifest={result['manifest_path']}\n"
        f"  pre_was_legacy={result['snapshot_before_was_none']}\n"
        f"  migration_note={result['migration_note']}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(_main())
