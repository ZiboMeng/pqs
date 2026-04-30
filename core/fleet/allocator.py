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

    # ── Step 2: C1 capital split ─────────────────────────────────────────

    def compute_capital_split(
        self, active_candidates: Optional[list] = None
    ) -> dict:
        """C1 capital split between active candidates.

        Returns a dict mapping ``candidate_id`` → fraction in [0, 1] that
        sums to 1.0.

        Two policies (declared in ``config.split_policy``):

        - ``equal_weight``: each active candidate gets ``1 / N`` regardless
          of ``base_weight``. This is the v1 default — equal-weight is
          dimensionally correct under the codex round-14 sleeve reframe
          (no per-candidate floors).

        - ``manual_overrides``: each active candidate gets its declared
          ``base_weight``. The active subset's base_weights MUST sum to
          1.0 (within float tolerance). If not, raise ``ValueError`` —
          silently renormalising would hide an operator-input bug.

        ``active_candidates`` is an optional list of candidate IDs to
        include. None (default) means every configured candidate
        participates. An ID not declared in ``config.candidates`` is a
        hard error. Step 6+ uses this to drop candidates when the C5 DD
        throttle parks them.
        """
        configured_ids = [c.candidate_id for c in self.config.candidates]
        if active_candidates is None:
            ids = list(configured_ids)
        else:
            unknown = sorted(set(active_candidates) - set(configured_ids))
            if unknown:
                raise ValueError(
                    f"active_candidates contains IDs not declared in fleet "
                    f"config: {unknown}; configured: {configured_ids}"
                )
            ids = [cid for cid in configured_ids if cid in set(active_candidates)]

        if not ids:
            raise ValueError(
                "no active candidates: cannot compute capital split with empty fleet"
            )

        if self.config.split_policy == "equal_weight":
            w = 1.0 / len(ids)
            return {cid: w for cid in ids}

        if self.config.split_policy == "manual_overrides":
            # Filter base_weights to active subset, then verify sum == 1.0
            id_to_weight = {c.candidate_id: c.base_weight
                            for c in self.config.candidates}
            weights = {cid: id_to_weight[cid] for cid in ids}
            total = sum(weights.values())
            if abs(total - 1.0) > 1e-9:
                raise ValueError(
                    f"manual_overrides: active candidates' base_weights sum to "
                    f"{total} (must be exactly 1.0). Active set: {ids}; "
                    f"weights: {weights}. Fix base_weight values or filter the "
                    f"active set differently — silent renormalisation is unsafe."
                )
            return weights

        # Should be unreachable due to Literal validator, but defensive:
        raise ValueError(f"unknown split_policy: {self.config.split_policy!r}")

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
