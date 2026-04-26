"""Forward manifest IO (R-fwd-1).

All read/write paths for ``forward_run_manifest.json`` go through
``ForwardRunManifest.model_validate`` — this is the schema-bypass
guard. Raw ``json.dump`` of an unvalidated dict is forbidden because
it would let a bad actor (or careless refactor) silently flip
``evidence_class`` away from ``forward_oos``.

PRD: docs/prd/20260426-forward_oos_runner_prd.md §4.2
"""
from __future__ import annotations

import json
from pathlib import Path

from .manifest_schema import ForwardRunManifest


def manifest_path(candidate_id: str, candidates_dir: Path) -> Path:
    """Canonical filesystem path for a candidate's forward manifest."""
    return candidates_dir / f"{candidate_id}_forward_manifest.json"


def load_manifest(path: Path) -> ForwardRunManifest:
    """Load + validate a forward manifest from disk.

    Raises ``FileNotFoundError`` if the path doesn't exist;
    ``ValidationError`` if the on-disk JSON fails schema validation.
    """
    payload = json.loads(Path(path).read_text())
    return ForwardRunManifest.model_validate(payload)


def save_manifest(manifest: ForwardRunManifest, path: Path) -> Path:
    """Atomically write a validated manifest to disk.

    The manifest object passed in is already a validated
    ``ForwardRunManifest``; this function re-runs ``model_validate``
    on the dump to catch any drift introduced by serialization
    (defense in depth — should be a no-op).
    """
    payload = manifest.model_dump(mode="json")
    # Round-trip validate — guarantees the disk artifact passes the
    # same checks any reader would apply on load.
    ForwardRunManifest.model_validate(payload)

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str, sort_keys=False))
    tmp.replace(p)
    return p
