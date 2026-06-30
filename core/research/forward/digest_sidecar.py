"""Per-cell digest sidecar IO (storage offload for track_per_cell=True).

When a candidate opts into ``evidence_config.track_signal_input_per_cell``,
the forward observer writes a full per-cell digest grid
(``per_cell_digest`` on each run's signal_input / execution_nav /
benchmark bar-hash inputs) at every TD-write. Stored inline in the
manifest JSON this balloons fast: a 79-symbol × 252-day single-attr
grid is ~20K cells/TD, and revalidate needs EVERY prior TD's grid (it
re-checks each entry), so a 28-TD soak inlined ~47-69 MB of pretty-
printed JSON — past GitHub's per-file limits before a 60-TD soak even
finishes.

This module offloads the digests to a columnar parquet sidecar next to
the manifest (``<cid>_forward_manifest.digests.parquet``), zstd-
compressed. The highly repetitive 8-char hex digests / symbol / date
columns dictionary-encode + compress to a fraction of the JSON size.

Contract:
- ``save_manifest`` calls ``offload_digests(payload, sidecar)`` which
  pulls all non-empty per_cell_digest grids into the parquet AND empties
  them in the JSON payload (so the on-disk manifest stays lean). If no
  grid is populated (the legacy default — RCMv1 / Cand-2 / trial9 / pead
  and any track_per_cell=False candidate), NO sidecar is written and the
  payload is returned byte-identical → legacy manifests are unchanged.
- ``load_manifest`` calls ``hydrate_digests(payload, sidecar)`` which
  re-populates the grids from the parquet before schema validation, so
  the in-memory ForwardRunManifest is identical to the pre-offload model
  and revalidate / runner logic need ZERO changes.

Runs are keyed by positional index in ``runs[]`` — save always rewrites
the manifest and sidecar together from one payload, so positions stay
consistent between the two artifacts.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# Only ``signal_input`` is offloaded: with track_per_cell=True it is the
# 79×252 grid (~20K cells/TD) that drives the multi-MB bloat. The
# execution_nav (~1 ring of held names) and benchmark (2 syms) grids are
# always populated but tiny (hundreds of cells total across a soak), so
# they stay inline — which keeps every track_per_cell=False (legacy)
# manifest byte-identical (no signal_input cells → no sidecar → payload
# untouched). The schema is still scope-keyed so re-widening later is a
# one-line change.
_OFFLOAD_SCOPES = ("signal_input",)
_COLUMNS = ["run_idx", "scope", "symbol", "iso_date", "attr", "digest"]


def sidecar_path(manifest_path: Path | str) -> Path:
    """``<cid>_forward_manifest.json`` → ``<cid>_forward_manifest.digests.parquet``."""
    s = str(manifest_path)
    if s.endswith(".json"):
        s = s[: -len(".json")]
    return Path(s + ".digests.parquet")


def offload_digests(payload: dict, sidecar: Path) -> bool:
    """Extract per_cell_digest grids from ``payload`` into ``sidecar``.

    Mutates ``payload`` in place: every non-empty ``per_cell_digest`` is
    emptied to ``{}`` so the dumped manifest JSON stays lean. The payload
    passed in is a fresh ``model_dump`` dict, so mutating it does NOT
    touch the caller's in-memory manifest object.

    Returns True if a sidecar was written (≥1 grid populated), False if
    nothing to offload (legacy path — payload returned byte-identical,
    any stale sidecar removed).
    """
    rows: list[tuple] = []
    for ri, run in enumerate(payload.get("runs", []) or []):
        bhi = run.get("bar_hash_inputs")
        if not isinstance(bhi, dict):
            continue
        for scope in _OFFLOAD_SCOPES:
            sc = bhi.get(scope)
            if not isinstance(sc, dict):
                continue
            pcd = sc.get("per_cell_digest")
            if not pcd:
                continue
            for sym, by_date in pcd.items():
                for iso, attrs in by_date.items():
                    for attr, dig in attrs.items():
                        rows.append((ri, scope, sym, iso, attr, dig))
            sc["per_cell_digest"] = {}

    if not rows:
        # Legacy / track_per_cell=False: leave payload untouched and make
        # sure no stale sidecar lingers to be hydrated next load.
        sp = Path(sidecar)
        if sp.exists():
            sp.unlink()
        return False

    df = pd.DataFrame(rows, columns=_COLUMNS)
    sp = Path(sidecar)
    sp.parent.mkdir(parents=True, exist_ok=True)
    tmp = sp.with_suffix(sp.suffix + ".tmp")
    df.to_parquet(tmp, compression="zstd", index=False)
    tmp.replace(sp)
    return True


def hydrate_digests(payload: dict, sidecar: Path) -> None:
    """Re-populate per_cell_digest grids in ``payload`` from ``sidecar``.

    No-op if the sidecar does not exist (legacy manifest — grids stay as
    serialized in the JSON, i.e. empty). Called before schema validation
    so the resulting in-memory model matches the pre-offload manifest.
    """
    sp = Path(sidecar)
    if not sp.exists():
        return
    df = pd.read_parquet(sp)
    if df.empty:
        return
    runs = payload.get("runs") or []
    for (ri, scope), grp in df.groupby(["run_idx", "scope"], sort=False):
        ri = int(ri)
        if ri >= len(runs):
            continue
        nested: dict = {}
        for sym, iso, attr, dig in zip(
            grp["symbol"], grp["iso_date"], grp["attr"], grp["digest"]
        ):
            nested.setdefault(sym, {}).setdefault(iso, {})[attr] = dig
        bhi = runs[ri].get("bar_hash_inputs")
        if not isinstance(bhi, dict):
            continue
        sc = bhi.get(scope)
        if not isinstance(sc, dict):
            continue
        sc["per_cell_digest"] = nested
