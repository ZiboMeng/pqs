"""FleetAllocator (Track B). Methods land per PRD step.

PRD: docs/prd/20260428-candidate_fleet_allocator_prd.md v1.1 §5.4

Shipped (live):
  - Step 2: ``compute_capital_split``           (C1)
  - Step 3: ``compose_weight_matrix``           (capital × per-cand weights)
  - Step 4: ``compute_concentration_metrics`` + ``apply_overlap_throttle`` (C3 cash-clip + M12)
  - Step 5: ``check_correlation_budget``        (C2 — pure-functional;
            no manifest mutation; observe() wiring belongs to Step 8)

Frozen (raise NotImplementedError("frozen") until explicit-go):
  - Step 6: ``apply_dd_throttle``               (C5)
  - Step 7: ``apply_role_caps`` + ``apply_removal_rules`` (C4 + C6)
  - Step 8: ``observe``                         (writes fleet_manifest.json)
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
            # Codex R27 P2 (2026-04-29): non-numeric dtype → domain ValueError
            # before downstream comparisons would raise raw TypeError.
            mat_values = mat.to_numpy()
            if mat_values.dtype == object or not _np.issubdtype(mat_values.dtype, _np.number):
                raise ValueError(
                    f"candidate {cid!r} weight matrix has non-numeric dtype "
                    f"{mat_values.dtype}; expected numeric (float / int). "
                    f"Coerce upstream with .astype(float)."
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
            if (mat_values < 0).any():
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

        # Codex R25 P0.1 fix (2026-04-29): validate every split COMPONENT, not
        # just the sum. Round 24 only checked sum; a long/short vector like
        # {c1: 1.2, c2: -0.2} sums to 1.0 but violates long-only no-margin
        # by producing leverage in c1's symbols and shorts in c2's. Reject:
        #   - non-numeric type (codex R27 P2: string / None / object → domain
        #     ValueError instead of np.isfinite()'s raw TypeError)
        #   - non-finite values (NaN / inf)
        #   - values < 0 (short)
        #   - values > 1 (single-candidate over-allocation)
        for cid, val in splits.items():
            if isinstance(val, bool) or not isinstance(val, (int, float, _np.integer, _np.floating)):
                raise ValueError(
                    f"splits[{cid!r}] = {val!r} (type {type(val).__name__}); "
                    f"split components must be numeric (int / float). Got "
                    f"non-numeric — fail-closed before np.isfinite() raw "
                    f"TypeError to surface the contract clearly."
                )
            if not _np.isfinite(val):
                raise ValueError(
                    f"splits[{cid!r}] = {val!r}; must be finite. Non-finite "
                    f"split components corrupt the entire fleet matrix."
                )
            if val < 0.0:
                raise ValueError(
                    f"splits[{cid!r}] = {val} < 0; long-only no-margin "
                    f"invariant requires every split component >= 0. A "
                    f"long/short split vector summing to 1.0 still creates "
                    f"leverage in some symbols and shorts in others."
                )
            if val > 1.0 + 1e-9:
                raise ValueError(
                    f"splits[{cid!r}] = {val} > 1.0; no single candidate "
                    f"may exceed full allocation. Combined with another "
                    f"positive split this would imply leverage even before "
                    f"the sum check."
                )

        # Sum check (Round 24 BUG #B2/B3) still runs after component check —
        # both must hold.
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

        # Codex R25 P0.1 fix (2026-04-29): post-compose invariants. Even
        # with valid components and inputs, defensive checks catch any
        # arithmetic surprise (mostly pandas alignment edge cases).
        if not _np.isfinite(fleet.values).all():
            n_bad = int((~_np.isfinite(fleet.values)).sum())
            raise ValueError(
                f"composed fleet matrix contains {n_bad} non-finite cell(s) "
                f"(NaN / inf); arithmetic surprise that input validation did "
                f"not catch. This is a defensive guard — please file a bug "
                f"with reproducer."
            )
        if (fleet.values < 0).any():
            n_neg = int((fleet.values < 0).sum())
            raise ValueError(
                f"composed fleet matrix contains {n_neg} negative cell(s); "
                f"long-only invariant violated. Either a candidate matrix "
                f"slipped through with negatives, or split components were "
                f"negative — both are caught upstream now, this is the "
                f"defensive last line."
            )
        # Row sums must be <= 1.0 + tolerance (sum of split-weighted candidate
        # rows; assumes per-candidate row sums <= 1 which is the upstream
        # contract — see PRD §5.4 D8 discussion). Tolerance accommodates float
        # accumulation across many candidates and symbols.
        row_sums = fleet.sum(axis=1)
        max_row_sum = float(row_sums.max()) if len(row_sums) else 0.0
        if max_row_sum > 1.0 + 1e-6:
            offenders = row_sums[row_sums > 1.0 + 1e-6].head(3)
            raise ValueError(
                f"composed fleet matrix has row sum {max_row_sum} > 1.0 + "
                f"1e-6 tolerance on at least one date "
                f"(e.g. {offenders.to_dict()}); over-allocation indicates "
                f"a per-candidate matrix violated its row-sum-<=-1 contract."
            )

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

        Codex R27 P1 carryover #1 (2026-04-29): public API; rejects dirty
        matrices upfront. Pre-fix used ``.abs()`` to coerce negatives,
        which silently masked short exposures as concentration; non-finite
        cells produced NaN metrics → ConcentrationSnapshot validation
        downstream blew up with opaque pydantic errors. Now: NaN/inf and
        negatives are rejected at the boundary with domain messages.
        """
        import pandas as _pd
        import numpy as _np
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

        values = fleet_weight_matrix.to_numpy()
        if values.dtype == object or not _np.issubdtype(values.dtype, _np.number):
            raise TypeError(
                f"fleet_weight_matrix has non-numeric dtype {values.dtype}; "
                f"expected a numeric (float / int) DataFrame."
            )
        if not _np.isfinite(values).all():
            n_bad = int((~_np.isfinite(values)).sum())
            raise ValueError(
                f"fleet_weight_matrix contains {n_bad} non-finite cell(s) "
                f"(NaN / inf); concentration metrics undefined. Compose with "
                f"clean candidate matrices upstream."
            )
        if (values < 0).any():
            n_neg = int((values < 0).sum())
            raise ValueError(
                f"fleet_weight_matrix contains {n_neg} negative cell(s); "
                f"long-only invariant violated. .abs() masking would let "
                f"shorts silently inflate concentration metrics — refusing."
            )

        per_date_top1 = fleet_weight_matrix.max(axis=1)
        per_date_top3 = fleet_weight_matrix.apply(
            lambda row: row.nlargest(min(3, len(row))).sum(), axis=1
        )
        active = (fleet_weight_matrix.sum(axis=1) > 0).sum()

        return {
            "m12_top1_weight_max": float(per_date_top1.max()) if len(per_date_top1) else 0.0,
            "m12_top3_weight_max": float(per_date_top3.max()) if len(per_date_top3) else 0.0,
            "m12_n_dates_with_weights": int(active),
        }

    def apply_overlap_throttle(self, fleet_weight_matrix):
        """C3 single-symbol cash-clip overlap throttle (PRD §4.3 v1).

        For each date, if any symbol's weight exceeds
        ``config.max_fleet_symbol_weight``, clip that symbol's weight to
        the cap. Other symbols are NOT renormalised — the row sum on
        that date drops below 1.0 by exactly the trim amount. The
        excess mass becomes **implicit cash** (the fleet under-allocates
        rather than redistributing concentration into other names).

        Per PRD §4.3 v1.1: this is the "cash-clip v1" semantics chosen
        over the original v1.0 "contribution-aware proportional trim"
        wording. Rationale (PRD §4.3): cash-clip is conservative,
        matches long-only no-margin, and preserves M12 concentration
        diagnostics by date. A v2 proportional redistribution path is
        deferred until production evidence shows cash-clip leaves
        material unallocated mass.

        Returns the throttled DataFrame plus a ``trim_events`` list
        describing what was clipped.
        """
        import pandas as _pd
        import numpy as _np
        if not isinstance(fleet_weight_matrix, _pd.DataFrame):
            raise TypeError(
                f"fleet_weight_matrix must be DataFrame, got {type(fleet_weight_matrix).__name__}"
            )
        # Codex R27 P2 (2026-04-29): non-numeric dtype → domain ValueError
        # before downstream `< cap` would raise raw TypeError on object dtype.
        _values = fleet_weight_matrix.to_numpy()
        if _values.dtype == object or not _np.issubdtype(_values.dtype, _np.number):
            raise ValueError(
                f"fleet_weight_matrix has non-numeric dtype {_values.dtype}; "
                f"expected numeric (float / int). Coerce upstream with "
                f".astype(float)."
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
        # Codex R25 P0.1 fix (2026-04-29): defense in depth — reject negative
        # cells too. Compose now rejects negatives upstream, but throttle is
        # a public API and a non-Track-B caller could feed it a dirty matrix.
        # Negative weights would produce nonsense throttle behavior (clipping
        # only positive cells; negatives leak through unflagged).
        if (fleet_weight_matrix.values < 0).any():
            n_neg = int((fleet_weight_matrix.values < 0).sum())
            raise ValueError(
                f"fleet_weight_matrix contains {n_neg} negative cell(s); "
                f"long-only invariant violated. Throttle cannot meaningfully "
                f"clip a negative weight against a positive cap."
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

    def check_correlation_budget(self, returns_df) -> "CorrelationBudgetStatus":
        """C2 pairwise correlation budget (PRD §4.2 / §5.4).

        ``returns_df`` is a date × candidate_id DataFrame of *realized
        candidate daily returns* (NOT IC, per codex round-25 boundary).
        Each column is one candidate's daily return series; index is a
        DatetimeIndex.

        Returns ``CorrelationBudgetStatus`` describing aggregate level
        (``ok`` / ``warn`` / ``reject`` / ``insufficient_data``), the
        max pairwise correlation, and per-pair detail. The aggregate
        level is the worst per-pair level: any ``reject`` pair flips
        the aggregate to ``reject``; any ``warn`` pair (no rejects)
        flips it to ``warn``; otherwise ``ok``.

        Lookback: only the most recent ``corr_lookback_days`` rows are
        used. After the lookback slice, correlation is computed on the
        intersection of finite observations across all candidates;
        if fewer than ``corr_min_overlap_days`` rows remain, returns
        level=``insufficient_data`` with a reason — composition layer
        must fail-closed (do not assume "ok" by absence of evidence).

        Step 5 is pure-functional: this method does NOT mutate the
        manifest. Step 8 wiring (frozen) will translate a ``reject``
        or ``warn`` status into a ``c2_corr_violation`` FleetEvent.
        """
        import pandas as _pd
        import numpy as _np
        from core.fleet.manifest_schema import (
            CorrelationBudgetStatus,
            CorrelationPair,
        )

        if not isinstance(returns_df, _pd.DataFrame):
            raise TypeError(
                f"returns_df must be DataFrame, got {type(returns_df).__name__}"
            )
        if returns_df.shape[1] < 2:
            raise ValueError(
                f"returns_df must have >= 2 candidate columns; got "
                f"{returns_df.shape[1]}. Pairwise correlation requires "
                f"at least one pair."
            )
        if not isinstance(returns_df.index, _pd.DatetimeIndex):
            raise ValueError(
                f"returns_df.index must be a DatetimeIndex; got "
                f"{type(returns_df.index).__name__}. Wrap with "
                f"pd.to_datetime() upstream."
            )
        if returns_df.index.has_duplicates:
            dup = returns_df.index[returns_df.index.duplicated(keep=False)].unique().tolist()
            raise ValueError(
                f"returns_df has duplicate index entries: {dup[:5]}"
                f"{'...' if len(dup) > 5 else ''}. Aggregate or drop duplicates "
                f"upstream."
            )
        values = returns_df.to_numpy()
        if values.dtype == object or not _np.issubdtype(values.dtype, _np.number):
            raise ValueError(
                f"returns_df has non-numeric dtype {values.dtype}; "
                f"expected numeric (float / int)."
            )
        if _np.isinf(values).any():
            n_inf = int(_np.isinf(values).sum())
            raise ValueError(
                f"returns_df contains {n_inf} inf cell(s); correlation "
                f"is undefined on inf. Replace or drop upstream."
            )
        # NaN is tolerated — we'll use pairwise complete observations
        # (pandas .corr() default behavior). But all-NaN columns are
        # rejected: no signal at all is operator error, not data hygiene.
        all_nan_cols = returns_df.columns[returns_df.isna().all()].tolist()
        if all_nan_cols:
            raise ValueError(
                f"returns_df has all-NaN columns: {all_nan_cols}. Cannot "
                f"compute correlation on a candidate with zero observations."
            )

        # Audit R2.6 (2026-04-29): sort BOTH the column axis AND the row index
        # to canonical order BEFORE any downstream pandas op. Sorting only the
        # pair-iteration list (R2.6 first iteration) was insufficient — pandas
        # .corr() internally computes column-by-column, and float accumulation
        # drifts at ~1e-17 between input column orderings. Sorting the
        # DataFrame columns + reindexing first guarantees byte-identical
        # CorrelationBudgetStatus across semantically-equal-but-reordered
        # returns_df, which is required for fleet manifest event hashing
        # determinism once Step 8 lands.
        candidate_ids = sorted(returns_df.columns)
        canonical = returns_df.reindex(columns=candidate_ids).sort_index()
        lookback = self.config.corr_lookback_days
        sliced = canonical.iloc[-lookback:]

        # Minimum-overlap check on the intersection of observations.
        # ``.dropna(how="any")`` gives the rows where every candidate has
        # a finite return; correlation is meaningful only on this set.
        complete = sliced.dropna(how="any")
        n_obs = int(complete.shape[0])
        min_overlap = self.config.corr_min_overlap_days

        if n_obs < min_overlap:
            return CorrelationBudgetStatus(
                level="insufficient_data",
                max_pairwise_corr=None,
                n_observations=n_obs,
                lookback_requested=lookback,
                pairs=[],
                reason=(
                    f"only {n_obs} fully-overlapping observation(s) across "
                    f"all {len(candidate_ids)} candidate(s); "
                    f"corr_min_overlap_days={min_overlap}. Composition "
                    f"layer must fail-closed."
                ),
            )

        # Pairwise correlation matrix (Pearson on the complete-overlap subset).
        corr_matrix = complete.corr(method="pearson")
        warn_t = self.config.max_pairwise_corr_warn
        reject_t = self.config.max_pairwise_corr_reject

        pairs = []
        max_corr = float("-inf")
        for i, ca in enumerate(candidate_ids):
            for cb in candidate_ids[i + 1:]:
                rho = float(corr_matrix.loc[ca, cb])
                # Defensive: pandas may produce NaN on degenerate constant
                # series even after dropna (zero variance). Treat as inf-
                # divergence — fail-closed at the pair level.
                if not _np.isfinite(rho):
                    raise ValueError(
                        f"pairwise correlation between {ca!r} and {cb!r} "
                        f"is non-finite ({rho}); likely a zero-variance "
                        f"return column. Fix returns upstream."
                    )
                if rho >= reject_t:
                    pair_level = "reject"
                elif rho >= warn_t:
                    pair_level = "warn"
                else:
                    pair_level = "ok"
                pairs.append(CorrelationPair(
                    candidate_a=ca, candidate_b=cb, correlation=rho,
                    level=pair_level,
                ))
                if rho > max_corr:
                    max_corr = rho

        if any(p.level == "reject" for p in pairs):
            agg_level = "reject"
            reason = (
                f"{sum(1 for p in pairs if p.level == 'reject')} pair(s) "
                f">= reject threshold {reject_t}; max corr {max_corr}. "
                f"Composition must not proceed without manual override."
            )
        elif any(p.level == "warn" for p in pairs):
            agg_level = "warn"
            reason = (
                f"{sum(1 for p in pairs if p.level == 'warn')} pair(s) "
                f">= warn threshold {warn_t}; max corr {max_corr}."
            )
        else:
            agg_level = "ok"
            reason = None

        return CorrelationBudgetStatus(
            level=agg_level,
            max_pairwise_corr=float(max_corr),
            n_observations=n_obs,
            lookback_requested=lookback,
            pairs=pairs,
            reason=reason,
        )

    def apply_dd_throttle(self, fleet_nav_series, spy_series=None):
        """C5 DD throttle (Step 6; codex-frozen)."""
        raise NotImplementedError("apply_dd_throttle lands in Step 6 (frozen)")

    def observe(self, as_of_date) -> None:
        """Daily fleet observation → fleet_manifest.json (Step 8; codex-frozen)."""
        raise NotImplementedError("observe lands in Step 8 (frozen)")
