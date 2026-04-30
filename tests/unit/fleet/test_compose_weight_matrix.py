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
    """Build a date × symbol weight DataFrame from a dict of dicts."""
    return pd.DataFrame.from_dict(rows, orient="index")


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
    assert sorted(fleet.index) == ["2026-01-02", "2026-01-03", "2026-01-06"]
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
