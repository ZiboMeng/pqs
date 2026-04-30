"""Track B Fleet Allocator (PRD docs/prd/20260428-candidate_fleet_allocator_prd.md v1.1).

Shipped:
  - Schema (FleetManifest pydantic + fleet.yaml validator) + atomic manifest I/O
  - Step 2: capital split (C1) — equal_weight + manual_overrides
  - Step 3: compose_weight_matrix (Σ split × per-cand weights; finite /
    long-only / row-sum invariants enforced)
  - Step 4: apply_overlap_throttle (C3 cash-clip v1) +
    compute_concentration_metrics (M12 top1 / top3 / n_dates)
  - Step 5: check_correlation_budget (C2) — pure-functional;
    no manifest mutation

Frozen until explicit-go:
  - Step 6 (C5 DD throttle), Step 7 (C4 role caps + C6 removal/parking),
    Step 8 (observe writes fleet_manifest.json), Step 9 (shadow → live)

Public API:
- ``FleetAllocator``
- ``load_fleet_config(path)`` → ``FleetConfig``
- Schemas: ``FleetManifest`` / ``FleetRebalance`` / ``FleetEvent`` /
  ``ConcentrationSnapshot`` / ``CorrelationBudgetStatus`` / ``CorrelationPair``
- ``load_fleet_manifest`` / ``save_fleet_manifest``
- ``track_a_role_to_fleet_role`` (Track A core/diversifier ↔ Fleet core/satellite)
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
