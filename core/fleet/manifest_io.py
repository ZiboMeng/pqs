"""Atomic load + save for the fleet manifest (Track B Step 1).

Single-writer assumption (parallel to fetch_session_log Round 19 audit
finding): atomic via tempfile + replace, but lost-update race possible
under concurrent writers. Per-pid + per-tid suffix on the temp filename
prevents the FileNotFoundError crash from concurrent renames.

If the fleet allocator graduates to scheduled / parallel execution, add
a fcntl lock here.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import TypeAdapter

from core.fleet.manifest_schema import FleetManifest


_DEFAULT_MANIFEST_PATH = Path("data/fleet_runs/fleet_manifest.json")


class _DateAwareEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, _date):
            return obj.isoformat()
        return super().default(obj)


def load_fleet_manifest(path: Optional[str | Path] = None) -> Optional[FleetManifest]:
    """Load the fleet manifest. Returns None if not found.

    Schema version mismatch raises pydantic ValidationError — caller
    decides whether to migrate or refuse.
    """
    p = Path(path) if path is not None else _DEFAULT_MANIFEST_PATH
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return FleetManifest.model_validate(raw)


def save_fleet_manifest(
    manifest: FleetManifest,
    path: Optional[str | Path] = None,
) -> None:
    """Atomic write via per-pid+tid temp file + rename.

    Schema enforcement happens at the model layer; this function only
    serialises. Caller is responsible for constructing a valid
    ``FleetManifest`` (which is already pydantic-validated by construction).
    """
    p = Path(path) if path is not None else _DEFAULT_MANIFEST_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".json.tmp.{os.getpid()}.{threading.get_ident()}")
    payload = manifest.model_dump(mode="json")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True, cls=_DateAwareEncoder)
        tmp.replace(p)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
