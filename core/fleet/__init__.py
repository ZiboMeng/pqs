"""Track B Fleet Allocator (PRD docs/prd/20260428-candidate_fleet_allocator_prd.md v1.1).

Step 1 ships: schema (FleetManifest pydantic + fleet.yaml validator),
empty allocator skeleton, manifest I/O atomic-write helper.

Steps 2-4 (capital split, compose_weight_matrix, C3 overlap throttle)
ship in subsequent commits. Steps 5-9 (correlation budget, DD throttle,
role caps, integration touchpoints, shadow→live) are deferred until
explicit-go from codex / user.

Public API:
- ``FleetAllocator`` (skeleton; methods land per step)
- ``load_fleet_config(path)`` → ``FleetConfig``
- ``FleetManifest`` / ``FleetRebalance`` pydantic schemas
- ``load_fleet_manifest`` / ``save_fleet_manifest``
"""
from core.fleet.manifest_schema import (
    ConcentrationSnapshot,
    CorrelationBudgetStatus,
    CorrelationPair,
    FleetCandidate,
    FleetConfig,
    FleetEvent,
    FleetManifest,
    FleetRebalance,
    TRACK_A_TO_FLEET_ROLE_MAP,
    load_fleet_config,
    track_a_role_to_fleet_role,
)
from core.fleet.manifest_io import load_fleet_manifest, save_fleet_manifest
from core.fleet.allocator import FleetAllocator

__all__ = [
    "ConcentrationSnapshot",
    "CorrelationBudgetStatus",
    "CorrelationPair",
    "FleetCandidate",
    "FleetConfig",
    "FleetEvent",
    "FleetManifest",
    "FleetRebalance",
    "TRACK_A_TO_FLEET_ROLE_MAP",
    "load_fleet_config",
    "load_fleet_manifest",
    "save_fleet_manifest",
    "track_a_role_to_fleet_role",
    "FleetAllocator",
]
