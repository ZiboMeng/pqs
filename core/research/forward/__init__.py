"""Forward OOS manifest + runner.

R5 (OOS MVP): shipped manifest schema only.
R-fwd-1 (post-MVP, user-authorized): adds runner with init / status /
observe / decide. PRD: docs/prd/20260426-forward_oos_runner_prd.md.
"""
from .manifest_io import load_manifest, manifest_path, save_manifest
from .manifest_schema import (
    CheckpointCadence,
    CostAssumptions,
    ForwardRun,
    ForwardRunManifest,
    ForwardRunStatus,
)
from .runner import (
    ForwardHaltError,
    decide,
    init,
    observe,
    status,
)

__all__ = [
    "CheckpointCadence",
    "CostAssumptions",
    "ForwardHaltError",
    "ForwardRun",
    "ForwardRunManifest",
    "ForwardRunStatus",
    "decide",
    "init",
    "load_manifest",
    "manifest_path",
    "observe",
    "save_manifest",
    "status",
]
