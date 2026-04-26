"""Forward OOS manifest module — SCHEMA ONLY (PRD v3 §B / execution PRD §3 R5).

This package intentionally ships no runner. PRD v3 §B: the MVP only
defines the ``forward_run_manifest.json`` schema; it does not wire a
forward runner or automation. Forward execution is out-of-scope until
a future PRD round.
"""
from .manifest_schema import (
    CheckpointCadence,
    CostAssumptions,
    ForwardRun,
    ForwardRunManifest,
    ForwardRunStatus,
)

__all__ = [
    "CheckpointCadence",
    "CostAssumptions",
    "ForwardRun",
    "ForwardRunManifest",
    "ForwardRunStatus",
]
