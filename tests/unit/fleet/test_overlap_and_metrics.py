"""Track B Step 4 — C3 overlap throttle + M12 fleet concentration metrics.

PRD §4.3 + §5.3 + §5.4: fleet-level cap on single-symbol weight; M12
metrics (top1, top3) computed at fleet composition layer.
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.fleet import FleetAllocator, FleetCandidate, FleetConfig


def _alloc(max_fleet_symbol_weight=0.20):
    cfg = FleetConfig(
        candidates=[
            FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
            FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
        ],
        max_fleet_symbol_weight=max_fleet_symbol_weight,
    )
    return FleetAllocator(cfg)


# ---------------------------------------------------------------------------
# M12 concentration metrics
# ---------------------------------------------------------------------------


def test_m12_metrics_basic():
    alloc = _alloc()
    fleet = pd.DataFrame(
        {"AAPL": [0.10, 0.15], "MSFT": [0.20, 0.10], "GOOG": [0.05, 0.20]},
        index=["2026-01-02", "2026-01-03"],
    )
    m = alloc.compute_concentration_metrics(fleet)
    # Day 2: top1 = MSFT(0.20), top3 = 0.20+0.15+0.10 = 0.45
    # Day 3: top1 = GOOG(0.20), top3 = 0.20+0.15+0.10 = 0.45
    assert m["m12_top1_weight_max"] == pytest.approx(0.20)
    assert m["m12_top3_weight_max"] == pytest.approx(0.45)
    assert m["m12_n_dates_with_weights"] == 2


def test_m12_metrics_empty_dataframe():
    alloc = _alloc()
    m = alloc.compute_concentration_metrics(pd.DataFrame())
    assert m == {
        "m12_top1_weight_max": 0.0,
        "m12_top3_weight_max": 0.0,
        "m12_n_dates_with_weights": 0,
    }


def test_m12_metrics_all_zero_matrix():
    alloc = _alloc()
    fleet = pd.DataFrame(
        {"AAPL": [0.0, 0.0], "MSFT": [0.0, 0.0]},
        index=["2026-01-02", "2026-01-03"],
    )
    m = alloc.compute_concentration_metrics(fleet)
    assert m["m12_top1_weight_max"] == 0.0
    assert m["m12_n_dates_with_weights"] == 0


def test_m12_metrics_rejects_non_dataframe():
    alloc = _alloc()
    with pytest.raises(TypeError, match="DataFrame"):
        alloc.compute_concentration_metrics([[1, 2], [3, 4]])


def test_m12_metrics_with_fewer_than_3_symbols():
    """top3 sum should still work with only 1-2 symbols."""
    alloc = _alloc()
    fleet = pd.DataFrame({"AAPL": [0.6, 0.4]}, index=["d1", "d2"])
    m = alloc.compute_concentration_metrics(fleet)
    assert m["m12_top1_weight_max"] == pytest.approx(0.6)
    assert m["m12_top3_weight_max"] == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# C3 overlap throttle
# ---------------------------------------------------------------------------


def test_overlap_throttle_no_trim_when_under_cap():
    alloc = _alloc(max_fleet_symbol_weight=0.50)
    fleet = pd.DataFrame(
        {"AAPL": [0.30, 0.40], "MSFT": [0.30, 0.40]},
        index=["2026-01-02", "2026-01-03"],
    )
    trimmed, events = alloc.apply_overlap_throttle(fleet)
    pd.testing.assert_frame_equal(trimmed, fleet)
    assert events == []


def test_overlap_throttle_clips_single_offender():
    """One symbol over cap on one date → clip to cap, log event."""
    alloc = _alloc(max_fleet_symbol_weight=0.20)
    fleet = pd.DataFrame(
        {"AAPL": [0.30, 0.10], "MSFT": [0.10, 0.10]},
        index=["2026-01-02", "2026-01-03"],
    )
    trimmed, events = alloc.apply_overlap_throttle(fleet)
    assert trimmed.loc["2026-01-02", "AAPL"] == pytest.approx(0.20)
    assert trimmed.loc["2026-01-03", "AAPL"] == pytest.approx(0.10)
    assert trimmed.loc["2026-01-02", "MSFT"] == pytest.approx(0.10)
    assert len(events) == 1
    assert events[0]["symbol"] == "AAPL"
    assert events[0]["original_weight"] == pytest.approx(0.30)
    assert events[0]["trimmed_to"] == 0.20
    assert events[0]["delta"] == pytest.approx(0.10)


def test_overlap_throttle_multiple_offenders_same_day():
    alloc = _alloc(max_fleet_symbol_weight=0.20)
    fleet = pd.DataFrame(
        {"AAPL": [0.25], "MSFT": [0.30], "GOOG": [0.10]},
        index=["2026-01-02"],
    )
    trimmed, events = alloc.apply_overlap_throttle(fleet)
    assert trimmed.loc["2026-01-02", "AAPL"] == pytest.approx(0.20)
    assert trimmed.loc["2026-01-02", "MSFT"] == pytest.approx(0.20)
    assert trimmed.loc["2026-01-02", "GOOG"] == pytest.approx(0.10)
    assert len(events) == 2
    syms = sorted(e["symbol"] for e in events)
    assert syms == ["AAPL", "MSFT"]


def test_overlap_throttle_does_not_renormalize():
    """Trimmed mass should NOT be redistributed; the row sum drops.
    Fleet long-only no-margin → trimmed mass becomes implicit cash."""
    alloc = _alloc(max_fleet_symbol_weight=0.20)
    fleet = pd.DataFrame(
        {"AAPL": [0.50], "MSFT": [0.30], "GOOG": [0.20]},
        index=["2026-01-02"],
    )
    # original sum = 1.00; AAPL 0.50→0.20 trims 0.30; MSFT 0.30→0.20 trims 0.10
    # → new sum = 0.20 + 0.20 + 0.20 = 0.60
    trimmed, events = alloc.apply_overlap_throttle(fleet)
    row_sum = trimmed.loc["2026-01-02"].sum()
    assert row_sum == pytest.approx(0.60)
    # AAPL was 0.50 → 0.20, MSFT 0.30 → 0.20, GOOG unchanged
    assert trimmed.loc["2026-01-02", "AAPL"] == pytest.approx(0.20)
    assert trimmed.loc["2026-01-02", "GOOG"] == pytest.approx(0.20)


def test_overlap_throttle_rejects_non_dataframe():
    alloc = _alloc()
    with pytest.raises(TypeError, match="DataFrame"):
        alloc.apply_overlap_throttle({"AAPL": [1.0]})


def test_overlap_throttle_at_cap_not_clipped():
    """Weight exactly equal to cap → no event (strict >, not >=)."""
    alloc = _alloc(max_fleet_symbol_weight=0.20)
    fleet = pd.DataFrame(
        {"AAPL": [0.20, 0.20]},
        index=["2026-01-02", "2026-01-03"],
    )
    trimmed, events = alloc.apply_overlap_throttle(fleet)
    pd.testing.assert_frame_equal(trimmed, fleet)
    assert events == []
