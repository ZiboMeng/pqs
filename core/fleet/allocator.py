"""FleetAllocator (Track B Step 1: skeleton; methods land per step).

PRD: docs/prd/20260428-candidate_fleet_allocator_prd.md v1.1 §5.4

Step 1 ships the class shell. Methods raise NotImplementedError until
their owning step lands:

  - Step 2: ``compute_capital_split``  (C1)
  - Step 3: ``compose_weight_matrix``  (capital splits × per-cand weights)
  - Step 4: ``compute_concentration_metrics`` + C3 overlap throttle
  - Step 5: ``check_correlation_budget`` (C2)
  - Step 6: ``apply_dd_throttle``       (C5)
  - Step 7: ``apply_role_caps`` + ``apply_removal_rules`` (C4 + C6)
  - Step 8: ``observe`` (writes to fleet_manifest.json)

Steps 5-9 are codex-frozen until explicit-go.
"""
from __future__ import annotations

from typing import Optional

from core.fleet.manifest_schema import FleetConfig


class FleetAllocator:
    """Capital-split + composition layer for multi-candidate research fleet.

    Constructed from a validated ``FleetConfig``. Stateless across calls
    by design (no in-class memoization of past observations). Manifest
    state lives in ``data/fleet_runs/fleet_manifest.json`` and is
    written by ``observe()``.
    """

    def __init__(self, config: FleetConfig) -> None:
        if not isinstance(config, FleetConfig):
            raise TypeError(
                f"FleetAllocator requires a FleetConfig instance, got {type(config).__name__}"
            )
        self.config = config

    # ── Step 2: C1 capital split (NotImplemented in Step 1) ──────────────

    def compute_capital_split(self, active_candidates: Optional[list] = None) -> dict:
        """C1 capital split between active candidates.

        Returns a dict mapping ``candidate_id`` → fraction in [0, 1] that
        sums to 1.0 (modulo throttle factor in later steps).

        ``active_candidates`` (Step 6+ extension) limits the split to a
        subset; None means all configured candidates participate. Step 1
        ships the signature; Step 2 fills in the body.
        """
        raise NotImplementedError("compute_capital_split lands in Step 2")

    # ── Step 3: compose_weight_matrix (NotImplemented in Step 1) ─────────

    def compose_weight_matrix(self, candidate_weight_matrices, splits=None):
        """Compose the fleet-level weight matrix.

        ``candidate_weight_matrices`` is dict[candidate_id, DataFrame]
        where each DataFrame is date × symbol weights summing to 1 per
        date. ``splits`` is the C1 capital allocation. The fleet weight
        is the splits-weighted sum across candidates.

        Step 3 fills in the body (returning unconstrained weights). Step
        4 layers C3 overlap throttle on top.
        """
        raise NotImplementedError("compose_weight_matrix lands in Step 3")

    # ── Step 4+: throttles + concentration metrics ───────────────────────

    def compute_concentration_metrics(self, fleet_weight_matrix):
        """M12 fleet-level concentration (Step 4)."""
        raise NotImplementedError("compute_concentration_metrics lands in Step 4")

    def apply_overlap_throttle(self, fleet_weight_matrix):
        """C3 single-symbol-cap proportional trim (Step 4)."""
        raise NotImplementedError("apply_overlap_throttle lands in Step 4")

    def check_correlation_budget(self, returns_df):
        """C2 pairwise correlation check (Step 5; codex-frozen)."""
        raise NotImplementedError("check_correlation_budget lands in Step 5 (frozen)")

    def apply_dd_throttle(self, fleet_nav_series, spy_series=None):
        """C5 DD throttle (Step 6; codex-frozen)."""
        raise NotImplementedError("apply_dd_throttle lands in Step 6 (frozen)")

    def observe(self, as_of_date) -> None:
        """Daily fleet observation → fleet_manifest.json (Step 8; codex-frozen)."""
        raise NotImplementedError("observe lands in Step 8 (frozen)")
