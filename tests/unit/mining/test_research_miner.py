"""Unit tests for core/mining/research_miner.py (PRD 20260424 §8, R09)."""
from __future__ import annotations

from typing import Any

import pytest

from core.mining.research_miner import (
    FAMILIES_V1,
    FAMILY_A, FAMILY_B, FAMILY_C, FAMILY_D,
    FamilyConfig,
    ResearchCompositeSpec,
    all_family_factors,
    family_of_factor,
    suggest_composite_spec,
)


# ── FamilyConfig ──────────────────────────────────────────────────────────────

def test_family_configs_have_required_factors():
    """Each of 4 PRD families owns the expected PRD-new factors."""
    a_new = {"rel_spy_20d", "rel_qqq_20d", "beta_spy_60d", "residual_mom_spy_20d"}
    b_new = {"range_pos_252d", "days_since_52w_high",
             "breakout_20d_strength", "dist_from_new_high_252"}
    c_new = {"amihud_20d", "downside_vol_20d", "vol_ratio_5_20"}
    d_new = {"trend_tstat_20d"}
    assert a_new.issubset(FAMILY_A.factors)
    assert b_new.issubset(FAMILY_B.factors)
    assert c_new.issubset(FAMILY_C.factors)
    assert d_new.issubset(FAMILY_D.factors)


def test_family_config_empty_factors_rejected():
    with pytest.raises(ValueError):
        FamilyConfig(name="X", title="empty test", factors=frozenset())


def test_family_of_factor_lookup():
    assert family_of_factor("rel_spy_20d") == "A"
    assert family_of_factor("range_pos_252d") == "B"
    assert family_of_factor("amihud_20d") == "C"
    assert family_of_factor("trend_tstat_20d") == "D"
    # Not in any family
    assert family_of_factor("bogus_factor") is None


def test_all_family_factors_union():
    all_f = all_family_factors()
    # Contains all 12 PRD new features
    for feat in ("rel_spy_20d", "beta_spy_60d", "range_pos_252d",
                 "days_since_52w_high", "amihud_20d", "vol_ratio_5_20",
                 "trend_tstat_20d"):
        assert feat in all_f


def test_families_are_disjoint():
    """No factor should appear in two families (family-aware uniqueness)."""
    for i, fam_i in enumerate(FAMILIES_V1):
        for fam_j in FAMILIES_V1[i + 1:]:
            overlap = fam_i.factors & fam_j.factors
            assert not overlap, (
                f"Family {fam_i.name} and {fam_j.name} share: {overlap}"
            )


# ── ResearchCompositeSpec ─────────────────────────────────────────────────────

def test_spec_valid_construction():
    spec = ResearchCompositeSpec(
        features=("rel_spy_20d", "range_pos_252d", "amihud_20d"),
        weights=(0.5, 0.3, 0.2),
        family_counts={"A": 1, "B": 1, "C": 1, "D": 0},
    )
    assert spec.n_features == 3
    assert spec.n_families == 3


def test_spec_weights_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1.0"):
        ResearchCompositeSpec(
            features=("rel_spy_20d", "amihud_20d"),
            weights=(0.3, 0.3),  # sums to 0.6
        )


def test_spec_weights_non_negative():
    with pytest.raises(ValueError, match="non-negative"):
        ResearchCompositeSpec(
            features=("rel_spy_20d", "amihud_20d"),
            weights=(-0.2, 1.2),
        )


def test_spec_length_mismatch():
    with pytest.raises(ValueError, match="length mismatch"):
        ResearchCompositeSpec(
            features=("rel_spy_20d", "amihud_20d", "range_pos_252d"),
            weights=(0.5, 0.5),
        )


def test_spec_empty_features_rejected():
    with pytest.raises(ValueError, match="at least 1"):
        ResearchCompositeSpec(features=(), weights=())


# ── suggest_composite_spec sampler ────────────────────────────────────────────

class MockTrial:
    """Stub that mimics Optuna Trial for deterministic testing."""

    def __init__(self, int_suggestions, cat_suggestions, float_suggestions):
        # dicts keyed by param name
        self._int = int_suggestions
        self._cat = cat_suggestions
        self._float = float_suggestions

    def suggest_int(self, name: str, low: int, high: int) -> int:
        return self._int[name]

    def suggest_categorical(self, name: str, choices: list[str]) -> str:
        return self._cat[name]

    def suggest_float(self, name: str, low: float, high: float,
                      step: float = None) -> float:
        return self._float[name]


def test_suggest_produces_valid_spec_3_families():
    """Mock trial that picks 1 feat each from A, B, C (3 families)."""
    trial = MockTrial(
        int_suggestions={
            "n_features_A": 1, "n_features_B": 1, "n_features_C": 1,
            "n_features_D": 0,
        },
        cat_suggestions={
            "family_A_slot_0": "rel_spy_20d",
            "family_B_slot_0": "range_pos_252d",
            "family_C_slot_0": "amihud_20d",
        },
        float_suggestions={
            "w_rel_spy_20d": 0.5,
            "w_range_pos_252d": 0.3,
            "w_amihud_20d": 0.2,
        },
    )
    spec = suggest_composite_spec(trial, families=FAMILIES_V1)
    assert spec.n_features == 3
    assert spec.n_families == 3
    assert abs(sum(spec.weights) - 1.0) < 1e-6
    assert set(spec.features) == {"rel_spy_20d", "range_pos_252d", "amihud_20d"}


def test_suggest_rejects_fewer_than_min_families():
    """Only 2 families selected → should raise."""
    trial = MockTrial(
        int_suggestions={
            "n_features_A": 1, "n_features_B": 1,
            "n_features_C": 0, "n_features_D": 0,
        },
        cat_suggestions={
            "family_A_slot_0": "rel_spy_20d",
            "family_B_slot_0": "range_pos_252d",
        },
        float_suggestions={
            "w_rel_spy_20d": 0.5,
            "w_range_pos_252d": 0.5,
        },
    )
    # optuna available → TrialPruned; else ValueError
    with pytest.raises((Exception,)) as excinfo:
        suggest_composite_spec(trial, families=FAMILIES_V1, min_families=3)
    # Must be either optuna.TrialPruned or ValueError
    exc_type_name = type(excinfo.value).__name__
    assert exc_type_name in ("TrialPruned", "ValueError"), (
        f"expected TrialPruned or ValueError, got {exc_type_name}"
    )


def test_suggest_weights_normalize_to_1():
    """Raw weights 2.0, 3.0, 5.0 → normalized 0.2, 0.3, 0.5."""
    trial = MockTrial(
        int_suggestions={
            "n_features_A": 1, "n_features_B": 1, "n_features_C": 1,
            "n_features_D": 0,
        },
        cat_suggestions={
            "family_A_slot_0": "rel_spy_20d",
            "family_B_slot_0": "range_pos_252d",
            "family_C_slot_0": "amihud_20d",
        },
        float_suggestions={
            "w_rel_spy_20d": 2.0,  # raw; will renorm
            "w_range_pos_252d": 3.0,
            "w_amihud_20d": 5.0,
        },
    )
    spec = suggest_composite_spec(trial)
    # normalized: 2/10, 3/10, 5/10 = 0.2, 0.3, 0.5
    # (feature order depends on iteration; weights should correspond)
    wdict = dict(zip(spec.features, spec.weights))
    assert abs(wdict["rel_spy_20d"] - 0.2) < 1e-6
    assert abs(wdict["range_pos_252d"] - 0.3) < 1e-6
    assert abs(wdict["amihud_20d"] - 0.5) < 1e-6


def test_suggest_zero_raw_weights_falls_back_to_uniform():
    """All raw weights = 0 → fallback to uniform."""
    trial = MockTrial(
        int_suggestions={
            "n_features_A": 1, "n_features_B": 1, "n_features_C": 1,
            "n_features_D": 0,
        },
        cat_suggestions={
            "family_A_slot_0": "rel_spy_20d",
            "family_B_slot_0": "range_pos_252d",
            "family_C_slot_0": "amihud_20d",
        },
        float_suggestions={
            "w_rel_spy_20d": 0.0,
            "w_range_pos_252d": 0.0,
            "w_amihud_20d": 0.0,
        },
    )
    spec = suggest_composite_spec(trial)
    # Uniform: 1/3 each
    for w in spec.weights:
        assert abs(w - 1/3) < 1e-6


def test_suggest_dedup_when_same_feature_picked_twice():
    """If trial picks same factor in 2 slots of same family, dedup."""
    trial = MockTrial(
        int_suggestions={
            "n_features_A": 2,  # 2 slots in A
            "n_features_B": 1, "n_features_C": 1, "n_features_D": 0,
        },
        cat_suggestions={
            "family_A_slot_0": "rel_spy_20d",
            "family_A_slot_1": "rel_spy_20d",  # same factor! dedup
            "family_B_slot_0": "range_pos_252d",
            "family_C_slot_0": "amihud_20d",
        },
        float_suggestions={
            "w_rel_spy_20d": 0.4,
            "w_range_pos_252d": 0.3,
            "w_amihud_20d": 0.3,
        },
    )
    spec = suggest_composite_spec(trial)
    # 3 unique features
    assert spec.n_features == 3
    assert len(set(spec.features)) == 3
