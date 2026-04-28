"""Forward OOS manifest + runner.

R5 (OOS MVP): shipped manifest schema only.
R-fwd-1 (post-MVP, user-authorized): adds runner with init / status /
observe / decide. PRD: docs/prd/20260426-forward_oos_runner_prd.md.
"""
from .bar_hash import (
    ContractResolutionError,
    FactorInputContract,
    max_lookback,
    resolve_factor_input_contract,
    union_attributes,
    union_benchmark_symbols,
)
from .manifest_io import load_manifest, manifest_path, save_manifest
from .manifest_schema import (
    BarHashInputs,
    CheckpointCadence,
    CostAssumptions,
    DataRevisionEvent,
    ForwardRun,
    ForwardRunManifest,
    ForwardRunStatus,
    PerScopeHashInputs,
    SourceLayerBreakdown,
    SourceLayerView,
)
from .readiness import ReadinessReport, check_readiness
from .runner import (
    ForwardHaltError,
    decide,
    init,
    observe,
    status,
)

__all__ = [
    "BarHashInputs",
    "CheckpointCadence",
    "ContractResolutionError",
    "CostAssumptions",
    "DataRevisionEvent",
    "FactorInputContract",
    "ForwardHaltError",
    "ForwardRun",
    "ForwardRunManifest",
    "ForwardRunStatus",
    "PerScopeHashInputs",
    "ReadinessReport",
    "SourceLayerBreakdown",
    "SourceLayerView",
    "check_readiness",
    "decide",
    "init",
    "load_manifest",
    "manifest_path",
    "max_lookback",
    "observe",
    "resolve_factor_input_contract",
    "save_manifest",
    "status",
    "union_attributes",
    "union_benchmark_symbols",
]
