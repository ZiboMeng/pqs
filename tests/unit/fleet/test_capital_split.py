"""Track B Step 2 — C1 capital split tests.

PRD §4.1: equal_weight default; manual_overrides exact-sum-1.0.
"""
from __future__ import annotations

import pytest

from core.fleet import FleetAllocator, FleetCandidate, FleetConfig


def _config(candidates, split_policy="equal_weight"):
    return FleetConfig(candidates=candidates, split_policy=split_policy)


# ---------------------------------------------------------------------------
# equal_weight
# ---------------------------------------------------------------------------


def test_equal_weight_two_candidates():
    cfg = _config([
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.5),
    ])
    alloc = FleetAllocator(cfg)
    splits = alloc.compute_capital_split()
    assert splits == {"c1": 0.5, "c2": 0.5}
    assert sum(splits.values()) == pytest.approx(1.0)


def test_equal_weight_three_candidates():
    cfg = _config([
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.4),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.4),
        FleetCandidate(candidate_id="s1", role="satellite", base_weight=0.2),
    ])
    alloc = FleetAllocator(cfg)
    splits = alloc.compute_capital_split()
    third = 1 / 3
    assert all(v == pytest.approx(third) for v in splits.values())
    assert sum(splits.values()) == pytest.approx(1.0)
    assert set(splits) == {"c1", "c2", "s1"}


def test_equal_weight_ignores_base_weight():
    """equal_weight is supposed to be 1/N regardless of declared base_weight
    (the operator's intent is "split evenly", not the configured weights)."""
    cfg = _config([
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.9),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.1),
    ])
    alloc = FleetAllocator(cfg)
    splits = alloc.compute_capital_split()
    assert splits == {"c1": 0.5, "c2": 0.5}


# ---------------------------------------------------------------------------
# manual_overrides
# ---------------------------------------------------------------------------


def test_manual_overrides_uses_base_weight():
    cfg = _config([
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.7),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.3),
    ], split_policy="manual_overrides")
    alloc = FleetAllocator(cfg)
    splits = alloc.compute_capital_split()
    assert splits == {"c1": 0.7, "c2": 0.3}


def test_manual_overrides_sum_not_one_fails_at_config_load():
    """Audit D7 (2026-04-29 R2): config-load now rejects manual_overrides
    with sum != 1.0; the runtime check is a defense in depth (covers
    `active_candidates` subset case below)."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="sum.*base_weight"):
        _config([
            FleetCandidate(candidate_id="c1", role="core", base_weight=0.6),
            FleetCandidate(candidate_id="c2", role="core", base_weight=0.3),
            # missing 0.1 — operator forgot the third candidate
        ], split_policy="manual_overrides")


def test_manual_overrides_partial_active_subset_must_still_sum_to_one():
    """If the operator opts into manual_overrides AND filters active candidates
    to a subset, the SUBSET's weights must sum to 1.0 (re-prune the config or
    do equal_weight if the subset isn't pre-validated)."""
    cfg = _config([
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.4),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.6),
    ], split_policy="manual_overrides")
    alloc = FleetAllocator(cfg)
    with pytest.raises(ValueError, match="must be exactly 1.0"):
        alloc.compute_capital_split(active_candidates=["c1"])


# ---------------------------------------------------------------------------
# active_candidates filter
# ---------------------------------------------------------------------------


def test_active_candidates_subset_equal_weight():
    cfg = _config([
        FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
        FleetCandidate(candidate_id="c2", role="core", base_weight=0.3),
        FleetCandidate(candidate_id="c3", role="core", base_weight=0.2),
    ])
    alloc = FleetAllocator(cfg)
    # Drop c3 (e.g. C5 DD throttle parked it)
    splits = alloc.compute_capital_split(active_candidates=["c1", "c2"])
    assert splits == {"c1": 0.5, "c2": 0.5}


def test_active_candidates_unknown_id_raises():
    cfg = _config([
        FleetCandidate(candidate_id="c1", role="core", base_weight=1.0),
    ])
    alloc = FleetAllocator(cfg)
    with pytest.raises(ValueError, match="not declared"):
        alloc.compute_capital_split(active_candidates=["c1", "ghost_candidate"])


def test_active_candidates_empty_raises():
    cfg = _config([
        FleetCandidate(candidate_id="c1", role="core", base_weight=1.0),
    ])
    alloc = FleetAllocator(cfg)
    with pytest.raises(ValueError, match="empty fleet"):
        alloc.compute_capital_split(active_candidates=[])
