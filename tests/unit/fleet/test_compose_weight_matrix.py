"""Track B Step 3 — compose_weight_matrix tests.

Verifies that fleet weight = Σ split[i] * candidate_weight[i]:
- exact arithmetic on identical date+symbol grids
- outer-join across mismatched date / symbol grids
- mismatched splits/matrices keys hard-error
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.fleet import FleetAllocator, FleetCandidate, FleetConfig


def _alloc(*candidates):
    cfg = FleetConfig(candidates=list(candidates))
    return FleetAllocator(cfg)


def _wm(rows: dict) -> pd.DataFrame:
    """Build a date × symbol weight DataFrame from a dict of dicts.

    Audit BUG #B5 fix (2026-04-29 R2): compose_weight_matrix now requires
    a DatetimeIndex; coerce string keys via pd.to_datetime to match the
    real-world calling pattern.
    """
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index = pd.to_datetime(df.index)
    return df


# ---------------------------------------------------------------------------
# Basic compose
# ---------------------------------------------------------------------------


def test_compose_two_candidates_equal_split():
    """Two candidates, identical date+symbol grid, equal capital split."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    splits = {"c1": 0.5, "c2": 0.5}
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0, "MSFT": 0.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": 0.0, "MSFT": 1.0}}),
    }
    fleet = alloc.compose_weight_matrix(cw, splits=splits)
    # 0.5 * (AAPL=1, MSFT=0) + 0.5 * (AAPL=0, MSFT=1) = (AAPL=0.5, MSFT=0.5)
    assert fleet.loc["2026-01-02", "AAPL"] == pytest.approx(0.5)
    assert fleet.loc["2026-01-02", "MSFT"] == pytest.approx(0.5)


def test_compose_unequal_split():
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.7),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.3),
    )
    splits = {"c1": 0.7, "c2": 0.3}
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": 1.0}}),
    }
    fleet = alloc.compose_weight_matrix(cw, splits=splits)
    assert fleet.loc["2026-01-02", "AAPL"] == pytest.approx(1.0)


def test_compose_default_equal_split_when_splits_none():
    """splits=None → equal weighting across the candidates passed in."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": 1.0}}),
    }
    fleet = alloc.compose_weight_matrix(cw)  # splits=None
    assert fleet.loc["2026-01-02", "AAPL"] == pytest.approx(1.0)


def test_compose_disjoint_symbols_outer_joined():
    """c1 trades AAPL/MSFT, c2 trades GOOG. Fleet has all three symbols."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    splits = {"c1": 0.5, "c2": 0.5}
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 0.6, "MSFT": 0.4}}),
        "c2": _wm({"2026-01-02": {"GOOG": 1.0}}),
    }
    fleet = alloc.compose_weight_matrix(cw, splits=splits)
    assert set(fleet.columns) == {"AAPL", "MSFT", "GOOG"}
    assert fleet.loc["2026-01-02", "AAPL"] == pytest.approx(0.3)
    assert fleet.loc["2026-01-02", "MSFT"] == pytest.approx(0.2)
    assert fleet.loc["2026-01-02", "GOOG"] == pytest.approx(0.5)


def test_compose_mismatched_dates_outer_joined():
    """c1 has dates A+B, c2 has dates B+C. Fleet covers all three;
    missing dates from a candidate contribute 0."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    splits = {"c1": 0.5, "c2": 0.5}
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}, "2026-01-03": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-03": {"AAPL": 1.0}, "2026-01-06": {"AAPL": 1.0}}),
    }
    fleet = alloc.compose_weight_matrix(cw, splits=splits)
    assert sorted(fleet.index.strftime("%Y-%m-%d")) == [
        "2026-01-02", "2026-01-03", "2026-01-06"
    ]
    # Day with only c1 → 0.5 * 1.0 = 0.5
    assert fleet.loc["2026-01-02", "AAPL"] == pytest.approx(0.5)
    # Day with both → 0.5 + 0.5 = 1.0
    assert fleet.loc["2026-01-03", "AAPL"] == pytest.approx(1.0)
    # Day with only c2 → 0.5 * 1.0 = 0.5
    assert fleet.loc["2026-01-06", "AAPL"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Adversarial
# ---------------------------------------------------------------------------


def test_compose_empty_input_rejected():
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=1.0),
    )
    with pytest.raises(ValueError, match="empty"):
        alloc.compose_weight_matrix({})


def test_compose_mismatched_keys_rejected():
    """splits has c1+c2, matrices has c1+c3 → hard error.

    A real-world bug class: operator passes the wrong active set; without
    this check we'd silently drop c3's signals.
    """
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    splits = {"c1": 0.5, "c2": 0.5}
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c3": _wm({"2026-01-02": {"AAPL": 1.0}}),
    }
    with pytest.raises(ValueError, match="matching keys"):
        alloc.compose_weight_matrix(cw, splits=splits)


def test_compose_non_dataframe_input_rejected():
    """Lists / arrays / dicts must not slip through where DataFrame expected."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=1.0),
    )
    with pytest.raises(TypeError, match="DataFrame"):
        alloc.compose_weight_matrix({"c1": [[0.5, 0.5]]})


def test_compose_all_zero_signals_returns_zero_matrix():
    """All candidates have zero weights on a given date → fleet weight is 0."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    splits = {"c1": 0.5, "c2": 0.5}
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 0.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": 0.0}}),
    }
    fleet = alloc.compose_weight_matrix(cw, splits=splits)
    assert fleet.loc["2026-01-02", "AAPL"] == 0.0


# ---------------------------------------------------------------------------
# Audit BUG #B1-B6 regressions (2026-04-29 R1+R2)
# ---------------------------------------------------------------------------


def test_compose_rejects_nan_in_candidate_matrix():
    """BUG #B1: NaN in candidate matrix would silently propagate to fleet
    weights, then to M12 metrics + manifest. Reject upfront with clear error."""
    import numpy as np
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": np.nan}}),
    }
    with pytest.raises(ValueError, match="NaN"):
        alloc.compose_weight_matrix(cw)


def test_compose_rejects_negative_weight():
    """Long-only invariant: weights must be non-negative."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=1.0),
    )
    cw = {"c1": _wm({"2026-01-02": {"AAPL": -0.1}})}
    with pytest.raises(ValueError, match="negative"):
        alloc.compose_weight_matrix(cw)


def test_compose_rejects_splits_sum_below_one():
    """BUG #B2: splits sum < 1.0 silently under-allocates fleet."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": 1.0}}),
    }
    with pytest.raises(ValueError, match="sum to"):
        alloc.compose_weight_matrix(cw, splits={"c1": 0.3, "c2": 0.3})


def test_compose_rejects_splits_sum_above_one():
    """BUG #B3: splits sum > 1.0 violates long-only no-margin invariant."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": 1.0}}),
    }
    with pytest.raises(ValueError, match="sum to"):
        alloc.compose_weight_matrix(cw, splits={"c1": 0.7, "c2": 0.7})


def test_compose_rejects_splits_within_tolerance():
    """1e-9 tolerance: 0.5 + 0.5 + 1e-10 still accepted; 0.5 + 0.5 + 1e-8 rejected."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": 1.0}}),
    }
    # Within tolerance — accepted
    alloc.compose_weight_matrix(cw, splits={"c1": 0.5, "c2": 0.5 + 1e-10})
    # Outside tolerance — rejected
    with pytest.raises(ValueError, match="sum to"):
        alloc.compose_weight_matrix(cw, splits={"c1": 0.5, "c2": 0.5 + 1e-8})


def test_compose_rejects_non_datetime_index():
    """BUG #B5: string-keyed DataFrame is operator-error; reject upfront with
    a clear domain error, not opaque pandas TypeError."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=1.0),
    )
    cw = {"c1": pd.DataFrame({"AAPL": [1.0]}, index=["2026-01-02"])}
    with pytest.raises(ValueError, match="DatetimeIndex"):
        alloc.compose_weight_matrix(cw)


def test_compose_rejects_duplicate_index_entries():
    """BUG #B6: duplicate-index DataFrame ambiguous which row applies; reject."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=1.0),
    )
    dup_idx = pd.to_datetime(["2026-01-02", "2026-01-02"])
    cw = {"c1": pd.DataFrame({"AAPL": [0.5, 0.5]}, index=dup_idx)}
    with pytest.raises(ValueError, match="duplicate index"):
        alloc.compose_weight_matrix(cw)


def test_compose_default_splits_pass_validation():
    """splits=None default uses 1/N which always sums to 1.0 exactly."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c3", role="core", base_weight=0.0),  # equal_weight ignores this
    )
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c3": _wm({"2026-01-02": {"AAPL": 1.0}}),
    }
    # No splits → equal_weight 1/3 each → sum=1.0 (within float precision)
    fleet = alloc.compose_weight_matrix(cw)
    assert fleet.loc[pd.Timestamp("2026-01-02"), "AAPL"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Codex R25 P0.1 regressions (2026-04-29)
# ---------------------------------------------------------------------------


def test_compose_rejects_split_components_summing_to_one_with_short():
    """Codex R25 P0.1: {c1: 1.2, c2: -0.2} sums to 1.0 ✓ but produces
    long/short fleet weights. Round 24 only checked sum; this test pins
    the component-level rejection."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-02": {"MSFT": 1.0}}),
    }
    with pytest.raises(ValueError, match=r"< 0|> 1\.0"):
        alloc.compose_weight_matrix(cw, splits={"c1": 1.2, "c2": -0.2})


def test_compose_rejects_negative_split_component():
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": 1.0}}),
    }
    with pytest.raises(ValueError, match="< 0"):
        alloc.compose_weight_matrix(cw, splits={"c1": -0.1, "c2": 1.1})


def test_compose_rejects_split_above_one():
    """One candidate getting > 100% allocation is not legal v1 (would imply
    leverage even if combined with a small second positive split)."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": 1.0}}),
    }
    # 1.5 > 1.0 — rejected even though sum check would let some configs through
    with pytest.raises(ValueError, match=r"> 1\.0"):
        alloc.compose_weight_matrix(cw, splits={"c1": 1.5, "c2": -0.5})


def test_compose_rejects_nan_split():
    import math
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": 1.0}}),
    }
    with pytest.raises(ValueError, match="must be finite"):
        alloc.compose_weight_matrix(cw, splits={"c1": math.nan, "c2": 1.0})


def test_compose_rejects_inf_split():
    import math
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    )
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 1.0}}),
        "c2": _wm({"2026-01-02": {"AAPL": 1.0}}),
    }
    with pytest.raises(ValueError, match="must be finite"):
        alloc.compose_weight_matrix(cw, splits={"c1": math.inf, "c2": -math.inf + 1.0})


def test_compose_post_invariant_row_sum_validated():
    """If a candidate matrix violates its row-sum-<=-1 contract (e.g. row
    sums to 1.5), the post-compose row-sum guard catches it even though
    the per-cell non-negative check passes.

    PRD §5.4 D8: per-row-sum-<=-1 is upstream's contract; this guard is
    defense in depth to prevent silent over-allocation."""
    alloc = _alloc(
        FleetCandidate(candidate_id="c1", role="core", base_weight=1.0),
    )
    # c1 has row sum 1.5 (over-allocated) but no negatives or NaN.
    cw = {
        "c1": _wm({"2026-01-02": {"AAPL": 0.8, "MSFT": 0.7}}),
    }
    # splits = {c1: 1.0}; fleet row sum = 1.5 → post-compose check catches.
    with pytest.raises(ValueError, match=r"row sum"):
        alloc.compose_weight_matrix(cw, splits={"c1": 1.0})
