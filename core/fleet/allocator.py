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

    # ── Step 3: compose_weight_matrix ────────────────────────────────────

    def compose_weight_matrix(
        self,
        candidate_weight_matrices: dict,
        splits: Optional[dict] = None,
    ):
        """Compose the unconstrained fleet weight matrix.

        ``candidate_weight_matrices`` is ``dict[candidate_id, pd.DataFrame]``
        where each DataFrame is date × symbol weights for that candidate
        (each row should sum to 1.0; this layer does NOT validate
        per-row sums — upstream owns per-candidate normalisation).

        ``splits`` is the C1 capital allocation (output of
        ``compute_capital_split``). If None, equal_weight across the
        candidates passed in is used. ``splits.values()`` MUST sum to
        1.0 (within 1e-9). > 1.0 violates the long-only no-margin
        invariant; < 1.0 is silent under-allocation. Both fail closed.

        Returns a date × symbol DataFrame: ``fleet_weight = Σ split[i] *
        candidate_weight[i]``. Symbols missing from one candidate are
        treated as zero weight from that candidate (outer-join on
        columns; outer-join on dates with the union of indexes).

        Audit BUG #B1-B6 fixes (2026-04-29 R1+R2):
          - NaN values in any candidate matrix → ValueError (silent
            propagation would corrupt fleet, M12, manifest)
          - splits.sum() != 1.0 → ValueError
          - duplicate index entries in candidate matrix → ValueError
          - non-DatetimeIndex on candidate matrix → ValueError
          - heterogeneous index types across candidates → ValueError
          - Negative weights → ValueError (long-only invariant)

        Constraints layered on top:
          - Step 4 adds C3 overlap throttle (single-symbol cap)
          - Step 5 adds C2 correlation budget rejection
          - Step 6 adds C5 DD throttle (multiplies the whole matrix)
        """
        import pandas as _pd
        import numpy as _np

        if not candidate_weight_matrices:
            raise ValueError("candidate_weight_matrices is empty")

        # Type + structural validation per candidate matrix
        for cid, mat in candidate_weight_matrices.items():
            if not isinstance(mat, _pd.DataFrame):
                raise TypeError(
                    f"candidate {cid!r} weight matrix must be a DataFrame, "
                    f"got {type(mat).__name__}"
                )
            if not isinstance(mat.index, _pd.DatetimeIndex):
                raise ValueError(
                    f"candidate {cid!r} weight matrix index must be a "
                    f"DatetimeIndex; got {type(mat.index).__name__}. Wrap "
                    f"with pd.to_datetime() upstream."
                )
            if mat.index.has_duplicates:
                dup = mat.index[mat.index.duplicated(keep=False)].unique().tolist()
                raise ValueError(
                    f"candidate {cid!r} weight matrix has duplicate index "
                    f"entries: {dup[:5]}{'...' if len(dup) > 5 else ''}. "
                    f"Aggregate or drop duplicates upstream."
                )
            if mat.isna().any().any():
                # Audit BUG #B1: NaN in candidate matrix would silently
                # propagate to fleet weights, then to M12 metrics + manifest.
                # Reject upfront with a pointer to the offending cells.
                na_count = int(mat.isna().sum().sum())
                raise ValueError(
                    f"candidate {cid!r} weight matrix contains {na_count} "
                    f"NaN value(s); NaN would silently corrupt fleet weights. "
                    f"Fill or drop upstream (e.g. .fillna(0.0) for "
                    f"missing-signal-as-zero, or .dropna() for missing-day-skip)."
                )
            # Long-only invariant — values must be non-negative.
            if (mat.values < 0).any():
                raise ValueError(
                    f"candidate {cid!r} weight matrix contains negative "
                    f"weights; long-only system has no shorts. Clip or "
                    f"reject upstream."
                )

        if splits is None:
            n = len(candidate_weight_matrices)
            splits = {cid: 1.0 / n for cid in candidate_weight_matrices.keys()}

        # Validate every candidate in splits is in matrices and vice versa
        matrix_ids = set(candidate_weight_matrices.keys())
        split_ids = set(splits.keys())
        if matrix_ids != split_ids:
            missing_in_splits = sorted(matrix_ids - split_ids)
            missing_in_matrices = sorted(split_ids - matrix_ids)
            raise ValueError(
                "candidate_weight_matrices and splits must have matching keys; "
                f"in matrices but not splits: {missing_in_splits}; "
                f"in splits but not matrices: {missing_in_matrices}"
            )

        # Audit BUG #B2/B3: splits.values() must sum to 1.0 (within tolerance).
        # > 1.0 implies leverage; < 1.0 is silent under-allocation.
        split_sum = sum(splits.values())
        if abs(split_sum - 1.0) > 1e-9:
            raise ValueError(
                f"splits.values() sum to {split_sum} (must be exactly 1.0 "
                f"within 1e-9); > 1.0 violates long-only no-margin invariant; "
                f"< 1.0 is silent under-allocation. Pass output of "
                f"compute_capital_split(active_candidates=...) which is "
                f"guaranteed to sum to 1.0."
            )

        # Outer-join all date indexes, outer-join all symbols. After upfront
        # validation we know all indexes are DatetimeIndex (sortable / mergeable).
        all_dates = _pd.DatetimeIndex(sorted(set().union(
            *(m.index for m in candidate_weight_matrices.values())
        )))
        all_syms = sorted(set().union(*(m.columns for m in candidate_weight_matrices.values())))

        fleet = _pd.DataFrame(0.0, index=all_dates, columns=all_syms)
        for cid, mat in candidate_weight_matrices.items():
            # Reindex to fleet's date+symbol grid; missing → 0 (no signal).
            # NaN was rejected upfront, so reindex won't introduce one.
            reindexed = mat.reindex(index=all_dates, columns=all_syms, fill_value=0.0)
            fleet = fleet + splits[cid] * reindexed

        return fleet

    # ── Step 4: M12 fleet metrics + C3 overlap throttle ──────────────────

    def compute_concentration_metrics(self, fleet_weight_matrix) -> dict:
        """M12 fleet-level concentration metrics (PRD §5.3 schema).

        Returns ``{"m12_top1_weight_max": float, "m12_top3_weight_max":
        float, "m12_n_dates_with_weights": int}``.

        - ``m12_top1_weight_max``: max single-symbol weight observed
          across the entire date × symbol grid.
        - ``m12_top3_weight_max``: max sum-of-top-3 weights observed
          across all dates (top-3 computed per date, then maxed).
        - ``m12_n_dates_with_weights``: number of dates where any
          symbol has weight > 0 (sanity counter).

        Empty / all-zero matrix → all metrics 0 with n_dates_with_weights=0.
        """
        import pandas as _pd
        if not isinstance(fleet_weight_matrix, _pd.DataFrame):
            raise TypeError(
                f"fleet_weight_matrix must be DataFrame, got {type(fleet_weight_matrix).__name__}"
            )
        if fleet_weight_matrix.empty:
            return {
                "m12_top1_weight_max": 0.0,
                "m12_top3_weight_max": 0.0,
                "m12_n_dates_with_weights": 0,
            }

        # Per-date top1 and top3 (using absolute value — long-only system,
        # so weights should be non-negative anyway, but defensive).
        abs_weights = fleet_weight_matrix.abs()
        per_date_top1 = abs_weights.max(axis=1)
        # Top3 sum per date: sort each row descending, take first 3, sum
        per_date_top3 = abs_weights.apply(
            lambda row: row.nlargest(min(3, len(row))).sum(), axis=1
        )
        active = (abs_weights.sum(axis=1) > 0).sum()

        return {
            "m12_top1_weight_max": float(per_date_top1.max()) if len(per_date_top1) else 0.0,
            "m12_top3_weight_max": float(per_date_top3.max()) if len(per_date_top3) else 0.0,
            "m12_n_dates_with_weights": int(active),
        }

    def apply_overlap_throttle(self, fleet_weight_matrix):
        """C3 single-symbol-cap proportional trim.

        For each date, if any symbol's weight exceeds
        ``config.max_fleet_symbol_weight``, clip that symbol's weight to
        the cap. Other symbols are NOT renormalised — the fleet weight
        sum on that date drops below 1.0, which is the intended behavior
        (the trimmed mass goes to cash, not redistributed to risk).

        This is the simplest semantically-correct interpretation of the
        PRD §4.3 ``proportional trim``: clip the offending column. A more
        elaborate "proportional redistribution" version is deferred to
        future iteration if the operator wants to preserve invested
        notional — for v1, dropping concentration into cash is more
        conservative and matches the long-only no-margin invariant.

        Returns the throttled DataFrame plus a ``trim_events`` list
        describing what was clipped.
        """
        import pandas as _pd
        if not isinstance(fleet_weight_matrix, _pd.DataFrame):
            raise TypeError(
                f"fleet_weight_matrix must be DataFrame, got {type(fleet_weight_matrix).__name__}"
            )
        # Audit BUG #B4 fix (2026-04-29 R1): NaN cells in the fleet weight
        # matrix would pass through silently (NaN > cap is False) and end up
        # in the manifest as NaN allocations. Reject upfront — combined with
        # compose_weight_matrix's NaN rejection (BUG #B1) this prevents the
        # full propagation chain.
        if fleet_weight_matrix.isna().any().any():
            na_count = int(fleet_weight_matrix.isna().sum().sum())
            raise ValueError(
                f"fleet_weight_matrix contains {na_count} NaN value(s); "
                f"throttle cannot reason about NaN cells. Compose with "
                f"clean candidate matrices upstream."
            )
        cap = self.config.max_fleet_symbol_weight
        # Find (date, symbol) cells exceeding the cap
        exceeded_mask = fleet_weight_matrix > cap
        trim_events = []
        if exceeded_mask.any().any():
            for col in fleet_weight_matrix.columns:
                col_mask = exceeded_mask[col]
                if col_mask.any():
                    affected = fleet_weight_matrix.loc[col_mask, col]
                    for dt, original in affected.items():
                        trim_events.append({
                            "date": dt,
                            "symbol": col,
                            "original_weight": float(original),
                            "trimmed_to": cap,
                            "delta": float(original - cap),
                        })
            trimmed = fleet_weight_matrix.where(~exceeded_mask, cap)
        else:
            trimmed = fleet_weight_matrix.copy()

        return trimmed, trim_events

    def check_correlation_budget(self, returns_df):
        """C2 pairwise correlation check (Step 5; codex-frozen)."""
        raise NotImplementedError("check_correlation_budget lands in Step 5 (frozen)")

    def apply_dd_throttle(self, fleet_nav_series, spy_series=None):
        """C5 DD throttle (Step 6; codex-frozen)."""
        raise NotImplementedError("apply_dd_throttle lands in Step 6 (frozen)")

    def observe(self, as_of_date) -> None:
        """Daily fleet observation → fleet_manifest.json (Step 8; codex-frozen)."""
        raise NotImplementedError("observe lands in Step 8 (frozen)")
