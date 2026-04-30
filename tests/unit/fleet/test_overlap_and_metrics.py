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


# ---------------------------------------------------------------------------
# Audit BUG #B4 regression (2026-04-29 R1) — NaN in throttle input
# ---------------------------------------------------------------------------


def test_overlap_throttle_rejects_nan():
    """BUG #B4: NaN > cap is False so NaN cells were silently passing through
    and ending up in the manifest as NaN allocations. Defense in depth — even
    if compose rejects NaN upstream, throttle is a public API and must reject
    too."""
    import numpy as np
    alloc = _alloc(max_fleet_symbol_weight=0.20)
    fleet = pd.DataFrame(
        {"AAPL": [0.30, np.nan]},
        index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
    )
    with pytest.raises(ValueError, match="NaN"):
        alloc.apply_overlap_throttle(fleet)


# ---------------------------------------------------------------------------
# Codex R25 P0.1 throttle defense in depth (2026-04-29)
# ---------------------------------------------------------------------------


def test_overlap_throttle_rejects_negative_cells():
    """Codex R25 P0.1 defense in depth: throttle is a public API; if a
    non-Track-B caller feeds it a dirty matrix with negative cells,
    fail-close (clipping a negative against a positive cap is nonsense)."""
    alloc = _alloc(max_fleet_symbol_weight=0.20)
    fleet = pd.DataFrame(
        {"AAPL": [0.30, -0.05]},
        index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
    )
    with pytest.raises(ValueError, match="negative"):
        alloc.apply_overlap_throttle(fleet)


# ---------------------------------------------------------------------------
# Codex R25 P0.2 — schema integration (2026-04-29)
# ---------------------------------------------------------------------------


def test_compute_concentration_metrics_feeds_directly_into_schema():
    """Codex R25 P0.2 lesson: my Round 24 audit had a manifest round-trip
    test, but never tried feeding compute_concentration_metrics() output
    INTO ConcentrationSnapshot. The schema was missing
    m12_n_dates_with_weights, so the integration was broken.

    This test pins the contract: compute output → ConcentrationSnapshot
    → FleetRebalance → save_fleet_manifest → load_fleet_manifest must
    round-trip without manual key surgery.
    """
    import tempfile
    from datetime import date, datetime, timezone
    from pathlib import Path

    from core.fleet import (
        FleetCandidate,
        FleetManifest,
        FleetRebalance,
        load_fleet_manifest,
        save_fleet_manifest,
    )
    from core.fleet.manifest_schema import ConcentrationSnapshot

    alloc = _alloc(max_fleet_symbol_weight=0.20)
    fleet = pd.DataFrame(
        {"AAPL": [0.18, 0.16], "MSFT": [0.12, 0.14], "GOOG": [0.05, 0.10]},
        index=pd.to_datetime(["2026-04-28", "2026-04-29"]),
    )
    metrics = alloc.compute_concentration_metrics(fleet)

    # Critical: build ConcentrationSnapshot directly from the dict.
    snap = ConcentrationSnapshot(**metrics)
    assert snap.m12_n_dates_with_weights == 2

    # Round-trip through manifest
    manifest = FleetManifest(
        fleet_id="r25_audit_test",
        candidates=[FleetCandidate(candidate_id="c1", role="core", base_weight=1.0)],
        rebalances=[
            FleetRebalance(
                rebalance_date=date(2026, 4, 29),
                candidate_weights={"c1": 1.0},
                fleet_weight_matrix_hash="a" * 64,
                throttle_factor=1.0,
                concentration_metrics=snap,
            ),
        ],
        created_at_utc=datetime(2026, 4, 29, tzinfo=timezone.utc),
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "manifest.json"
        save_fleet_manifest(manifest, p)
        loaded = load_fleet_manifest(p)
        assert loaded.rebalances[0].concentration_metrics.m12_n_dates_with_weights == 2
