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

from .digest_sidecar import hydrate_digests, offload_digests, sidecar_path
from .manifest_schema import ForwardRunManifest


def manifest_path(candidate_id: str, candidates_dir: Path) -> Path:
    """Canonical filesystem path for a candidate's forward manifest."""
    return candidates_dir / f"{candidate_id}_forward_manifest.json"


def load_manifest(path: Path) -> ForwardRunManifest:
    """Load + validate a forward manifest from disk.

    Raises ``FileNotFoundError`` if the path doesn't exist;
    ``ValidationError`` if the on-disk JSON fails schema validation.

    Per-cell digest grids (track_per_cell=True candidates) live in a
    parquet sidecar and are hydrated back into the payload before
    validation, so the in-memory model is identical to the pre-offload
    manifest (see ``digest_sidecar``). Legacy manifests have no sidecar
    and load unchanged.
    """
    payload = json.loads(Path(path).read_text())
    hydrate_digests(payload, sidecar_path(path))
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
    # same checks any reader would apply on load. Validate the FULL
    # payload (digests still inline) so the check matches the hydrated
    # load-time model exactly.
    ForwardRunManifest.model_validate(payload)

    p = Path(path)
    # Offload per-cell digest grids to a parquet sidecar (empties them in
    # `payload` so the manifest JSON stays lean). No-op + byte-identical
    # payload for legacy / track_per_cell=False candidates.
    offload_digests(payload, sidecar_path(p))

    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str, sort_keys=False))
    tmp.replace(p)
    return p
