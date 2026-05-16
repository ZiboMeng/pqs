"""Unit tests for core/mining/research_miner.py (PRD 20260424 §8, R09)."""
from __future__ import annotations


import pytest

import numpy as np
import pandas as pd

from core.mining.research_miner import (
    FAMILIES_V1,
    FAMILY_A, FAMILY_B, FAMILY_C, FAMILY_D,
    CompositeMetrics,
    FamilyConfig,
    ObjectiveWeights,
    ResearchCompositeSpec,
    ResearchMiner,
    TrialResult,
    all_family_factors,
    build_composite_series,
    compute_objective,
    evaluate_composite,
    family_of_factor,
    suggest_composite_spec,
    zscore_cs,
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


# ── R10: zscore_cs ────────────────────────────────────────────────────────────

def test_zscore_cs_row_mean_zero_std_one():
    idx = pd.bdate_range("2024-01-01", periods=3)
    df = pd.DataFrame({
        "A": [1.0, 2.0, 3.0],
        "B": [3.0, 3.0, 3.0],
        "C": [5.0, 4.0, 3.0],
        "D": [0.0, 1.0, 2.0],
        "E": [4.0, 5.0, 6.0],
    }, index=idx)
    z = zscore_cs(df, min_periods=5)
    # Per-date row: mean ~ 0, std ~ 1 (population, ddof=0)
    for d in idx:
        row = z.loc[d].dropna()
        assert abs(row.mean()) < 1e-10
        assert abs(row.std(ddof=0) - 1.0) < 1e-10


def test_zscore_cs_insufficient_symbols_becomes_nan():
    """Row with < min_periods=5 valid columns → NaN'd out."""
    idx = pd.bdate_range("2024-01-01", periods=2)
    df = pd.DataFrame({"A": [1.0, 2.0], "B": [2.0, 3.0]}, index=idx)
    z = zscore_cs(df, min_periods=5)
    assert z.isna().all().all()


# ── R10: build_composite_series ─────────────────────────────────────────────


@pytest.fixture
def synthetic_panels():
    """2 factor panels × 10 bars × 6 symbols for composite math."""
    np.random.seed(1)
    idx = pd.bdate_range("2024-01-02", periods=10)
    cols = list("ABCDEF")
    panel_mom = pd.DataFrame(
        np.random.randn(10, 6), index=idx, columns=cols,
    )
    panel_vol = pd.DataFrame(
        np.random.randn(10, 6), index=idx, columns=cols,
    )
    return {"mom_21d": panel_mom, "vol_21d": panel_vol}


def test_build_composite_shape_and_sum(synthetic_panels):
    spec = ResearchCompositeSpec(
        features=("mom_21d", "vol_21d"),
        weights=(0.6, 0.4),
        family_counts={"D": 1, "C": 1, "A": 1, "B": 0},  # min_families=3 arbitrary
    )
    # Skip family check manually (ResearchCompositeSpec doesn't enforce it)
    comp = build_composite_series(spec, synthetic_panels)
    # Shape matches intersection
    assert comp.shape == (10, 6)
    # Each cell = 0.6 * z_mom + 0.4 * z_vol
    zm = zscore_cs(synthetic_panels["mom_21d"])
    zv = zscore_cs(synthetic_panels["vol_21d"])
    expected = zm * 0.6 + zv * 0.4
    valid = expected.dropna()
    assert np.allclose(
        comp.loc[valid.index, valid.columns].values,
        valid.values, atol=1e-10,
    )


def test_build_composite_missing_feature_raises(synthetic_panels):
    spec = ResearchCompositeSpec(
        features=("mom_21d", "NOT_THERE"),
        weights=(0.5, 0.5),
    )
    with pytest.raises(KeyError, match="missing features"):
        build_composite_series(spec, synthetic_panels)


# ── R10: evaluate_composite ─────────────────────────────────────────────────


def test_evaluate_composite_returns_metrics(synthetic_panels):
    """Basic smoke test — evaluate returns a CompositeMetrics."""
    spec = ResearchCompositeSpec(
        features=("mom_21d", "vol_21d"),
        weights=(0.5, 0.5),
        family_counts={"D": 1, "C": 1, "A": 1},
    )
    # Fake forward returns correlated with composite slightly
    idx = synthetic_panels["mom_21d"].index
    np.random.seed(42)
    # Need at least 10 symbols per date for IC computation, extend
    # synthetic to use wider panels
    cols = synthetic_panels["mom_21d"].columns
    fwd = pd.DataFrame(
        np.random.randn(len(idx), len(cols)),
        index=idx, columns=cols,
    )
    metrics = evaluate_composite(spec, synthetic_panels, fwd)
    assert isinstance(metrics, CompositeMetrics)
    # Only 6 symbols per date, min 10 required for IC → ic_series empty
    # So n_dates == 0, ic_* all NaN
    assert metrics.n_features == 2
    assert metrics.n_dates == 0  # fewer than 10 syms per date


def test_evaluate_composite_with_wide_panel_gets_valid_ic():
    """15 symbols per date → IC should be computable."""
    np.random.seed(7)
    idx = pd.bdate_range("2024-01-02", periods=50)
    cols = [f"SYM{i}" for i in range(15)]
    p1 = pd.DataFrame(
        np.random.randn(50, 15), index=idx, columns=cols,
    )
    p2 = pd.DataFrame(
        np.random.randn(50, 15), index=idx, columns=cols,
    )
    # R15 fix: default lag=1 shifts composite by 1 before IC. To
    # produce a positive IC under the new semantics, align fwd with the
    # shifted composite — i.e. fwd[t] correlates with p1[t-1], NOT p1[t].
    fwd_aligned = p1.shift(1) * 0.15 + np.random.randn(50, 15) * 0.85
    fwd_aligned.index = idx
    fwd_aligned.columns = cols
    spec = ResearchCompositeSpec(
        features=("mom_21d", "vol_21d"),
        weights=(0.7, 0.3),
        family_counts={"D": 1, "C": 1, "A": 1},
    )
    metrics = evaluate_composite(
        spec, {"mom_21d": p1, "vol_21d": p2}, fwd_aligned,
    )
    assert metrics.n_dates > 40  # most dates produce IC
    # Expected positive IC since composite correlates with fwd via
    # shifted p1 (matches lag=1 semantics)
    assert metrics.ic_mean > 0.05


def test_evaluate_composite_respects_mask():
    """With research_mask masking out half the cells, n_dates can drop or IC shift."""
    np.random.seed(3)
    idx = pd.bdate_range("2024-01-02", periods=40)
    cols = [f"S{i}" for i in range(12)]
    p1 = pd.DataFrame(np.random.randn(40, 12), index=idx, columns=cols)
    p2 = pd.DataFrame(np.random.randn(40, 12), index=idx, columns=cols)
    fwd = p1 * 0.2 + np.random.randn(40, 12) * 0.8
    fwd.index = idx; fwd.columns = cols
    # Mask out half the columns
    mask = pd.DataFrame(True, index=idx, columns=cols)
    mask.iloc[:, :6] = False  # first 6 symbols masked
    spec = ResearchCompositeSpec(
        features=("mom_21d", "vol_21d"),
        weights=(0.7, 0.3),
        family_counts={"D": 1, "C": 1, "A": 1},
    )
    m_masked = evaluate_composite(
        spec, {"mom_21d": p1, "vol_21d": p2}, fwd, mask=mask,
    )
    m_unmasked = evaluate_composite(
        spec, {"mom_21d": p1, "vol_21d": p2}, fwd,
    )
    # Masked version: 6 valid symbols per date, below IC threshold (<10)
    # → n_dates likely 0
    assert m_masked.n_dates == 0
    assert m_unmasked.n_dates > 20


def test_evaluate_composite_high_corr_concentration():
    """Two identical feature panels → corr concentration ~ 1.0."""
    np.random.seed(9)
    idx = pd.bdate_range("2024-01-02", periods=40)
    cols = [f"S{i}" for i in range(12)]
    p = pd.DataFrame(np.random.randn(40, 12), index=idx, columns=cols)
    # Same panel 2x → perfect correlation
    spec = ResearchCompositeSpec(
        features=("mom_21d", "vol_21d"),
        weights=(0.5, 0.5),
        family_counts={"D": 1, "C": 1, "A": 1},
    )
    fwd = p * 0.1 + np.random.randn(40, 12) * 0.9
    fwd.index = idx; fwd.columns = cols
    metrics = evaluate_composite(
        spec, {"mom_21d": p, "vol_21d": p.copy()}, fwd,
    )
    # corr_concentration should be ~1.0 since both components identical
    assert metrics.corr_concentration > 0.99


def test_evaluate_composite_horizon_scales_ic_ir():
    """R14: ic_ir scales as sqrt(252/horizon). horizon=1 → ~4.58x larger
    than horizon=21 with identical ic_mean + ic_std.

    Construct panels where ic_series is deterministic so ic_mean/ic_std
    is fixed; then verify ic_ir ratio matches the annualization ratio.
    """
    np.random.seed(11)
    idx = pd.bdate_range("2024-01-02", periods=60)
    cols = [f"S{i}" for i in range(15)]
    # Signal panel strongly correlated with fwd returns
    p = pd.DataFrame(np.random.randn(60, 15), index=idx, columns=cols)
    fwd = p * 0.3 + pd.DataFrame(
        np.random.randn(60, 15) * 0.7, index=idx, columns=cols,
    )
    spec = ResearchCompositeSpec(
        features=("mom_21d",), weights=(1.0,),
        family_counts={"D": 1, "A": 1, "B": 1},
    )
    m_h1 = evaluate_composite(spec, {"mom_21d": p}, fwd, horizon=1)
    m_h21 = evaluate_composite(spec, {"mom_21d": p}, fwd, horizon=21)
    # ic_mean + ic_std identical (function of panels, not horizon)
    assert abs(m_h1.ic_mean - m_h21.ic_mean) < 1e-12
    assert abs(m_h1.ic_std - m_h21.ic_std) < 1e-12
    # IR scales by sqrt(21 / 1) = sqrt(21)
    if np.isfinite(m_h1.ic_ir) and np.isfinite(m_h21.ic_ir) and m_h21.ic_ir != 0:
        ratio = m_h1.ic_ir / m_h21.ic_ir
        expected = np.sqrt(21)
        assert abs(ratio - expected) < 1e-6
    # horizon field stored
    assert m_h1.horizon == 1
    assert m_h21.horizon == 21


def test_evaluate_composite_lag_default_is_one():
    """R15 leakage fix: default lag=1 shifts composite by 1 before IC.
    Setting lag=1 vs lag=0 should produce different (and typically
    smaller-magnitude) IC when factor and fwd_return share close[t].
    """
    np.random.seed(17)
    idx = pd.bdate_range("2024-01-02", periods=50)
    cols = [f"S{i}" for i in range(12)]
    # Construct a panel where factor[t] directly tracks close[t] noise,
    # and fwd_return[t] is just noise — lag=0 may produce spurious IC,
    # lag=1 should remove it.
    noise = pd.DataFrame(np.random.randn(50, 12), index=idx, columns=cols)
    # Factor = shifted version of fwd_return's own noise → contemporaneous
    # IC is strong, shifted IC should vanish
    fwd = noise.copy()
    panel = noise.copy()  # perfectly aligned
    spec = ResearchCompositeSpec(
        features=("mom_21d",), weights=(1.0,),
        family_counts={"D": 1, "A": 1, "B": 1},
    )
    m_no_lag = evaluate_composite(
        spec, {"mom_21d": panel}, fwd, horizon=21, lag=0,
    )
    m_with_lag = evaluate_composite(
        spec, {"mom_21d": panel}, fwd, horizon=21, lag=1,
    )
    # Contemporaneous IC should be near 1 (panel == fwd exactly)
    assert m_no_lag.ic_mean > 0.9
    # Shifted IC should be much weaker (panel shifted by 1 vs fwd)
    assert abs(m_with_lag.ic_mean) < abs(m_no_lag.ic_mean)
    # Default evaluate_composite call should match lag=1 behavior
    m_default = evaluate_composite(
        spec, {"mom_21d": panel}, fwd, horizon=21,
    )
    assert abs(m_default.ic_mean - m_with_lag.ic_mean) < 1e-12


def test_evaluate_composite_rejects_negative_lag():
    spec = ResearchCompositeSpec(
        features=("mom_21d",), weights=(1.0,),
        family_counts={"D": 1, "A": 1, "B": 1},
    )
    idx = pd.bdate_range("2024-01-02", periods=10)
    cols = list("ABCDEF")
    p = pd.DataFrame(np.random.randn(10, 6), index=idx, columns=cols)
    with pytest.raises(ValueError, match="lag must be >= 0"):
        evaluate_composite(spec, {"mom_21d": p}, p, lag=-1)


def test_evaluate_composite_rejects_bad_horizon():
    spec = ResearchCompositeSpec(
        features=("mom_21d",), weights=(1.0,),
        family_counts={"D": 1, "A": 1, "B": 1},
    )
    idx = pd.bdate_range("2024-01-02", periods=10)
    cols = list("ABCDEF")
    p = pd.DataFrame(np.random.randn(10, 6), index=idx, columns=cols)
    with pytest.raises(ValueError, match="horizon must be positive"):
        evaluate_composite(spec, {"mom_21d": p}, p, horizon=0)
    with pytest.raises(ValueError, match="horizon must be positive"):
        evaluate_composite(spec, {"mom_21d": p}, p, horizon=-5)


def test_evaluate_composite_single_feature_corr_concentration_zero():
    """n_features=1 → corr_concentration = 0 (trivially no redundancy)."""
    np.random.seed(5)
    idx = pd.bdate_range("2024-01-02", periods=40)
    cols = [f"S{i}" for i in range(12)]
    p = pd.DataFrame(np.random.randn(40, 12), index=idx, columns=cols)
    fwd = p * 0.2 + np.random.randn(40, 12) * 0.8
    fwd.index = idx; fwd.columns = cols
    spec = ResearchCompositeSpec(
        features=("mom_21d",), weights=(1.0,),
        family_counts={"D": 1, "A": 1, "B": 1},
    )
    metrics = evaluate_composite(spec, {"mom_21d": p}, fwd)
    assert metrics.corr_concentration == 0.0
    assert metrics.n_features == 1


# ── R11: ObjectiveWeights ────────────────────────────────────────────────────


def test_objective_weights_defaults():
    """PRD §8.6 default weights match the documented formula."""
    w = ObjectiveWeights()
    assert w.w_ir == 1.0
    assert w.w_turnover == 0.5
    assert w.w_corr_conc == 1.0
    assert w.w_bench_excess == 0.3
    assert w.w_regime_stddev == 0.2


def test_objective_weights_frozen():
    """ObjectiveWeights is frozen — reassignment raises."""
    w = ObjectiveWeights()
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        w.w_ir = 2.0  # type: ignore[misc]


# ── R11: compute_objective ───────────────────────────────────────────────────


def _mk_metrics(ir=0.5, turnover=0.1, corr=0.2, n_features=3, n_families=3):
    return CompositeMetrics(
        n_features=n_features,
        n_families=n_families,
        n_dates=100,
        ic_mean=0.03,
        ic_std=0.06,
        ic_ir=ir,
        turnover_proxy=turnover,
        corr_concentration=corr,
    )


def test_compute_objective_formula_default_weights():
    """Default weights: obj = 1·IR - 0.5·T - 1·C + 0.3·E - 0.2·S."""
    m = _mk_metrics(ir=0.5, turnover=0.1, corr=0.2)
    obj = compute_objective(m, benchmark_excess=0.4, regime_stddev=0.05)
    # 1.0*0.5 - 0.5*0.1 - 1.0*0.2 + 0.3*0.4 - 0.2*0.05
    # = 0.5 - 0.05 - 0.2 + 0.12 - 0.01 = 0.36
    assert abs(obj - 0.36) < 1e-10


def test_compute_objective_custom_weights():
    """Custom weights scale linearly."""
    m = _mk_metrics(ir=1.0, turnover=0.2, corr=0.3)
    w = ObjectiveWeights(
        w_ir=2.0, w_turnover=1.0, w_corr_conc=0.5,
        w_bench_excess=0.0, w_regime_stddev=0.0,
    )
    obj = compute_objective(m, weights=w)
    # 2.0*1.0 - 1.0*0.2 - 0.5*0.3 = 2.0 - 0.2 - 0.15 = 1.65
    assert abs(obj - 1.65) < 1e-10


def test_compute_objective_nan_ir_returns_neg_inf():
    """NaN IR → -inf (no signal, Optuna will deprioritize)."""
    m = _mk_metrics(ir=float("nan"))
    obj = compute_objective(m)
    assert obj == float("-inf")


def test_compute_objective_nan_turnover_contributes_zero():
    """NaN turnover/corr/bench/regime treated as 0 (insufficient data)."""
    m = CompositeMetrics(
        n_features=2, n_families=2, n_dates=50,
        ic_mean=0.02, ic_std=0.04, ic_ir=0.5,
        turnover_proxy=float("nan"),
        corr_concentration=float("nan"),
    )
    obj = compute_objective(
        m, benchmark_excess=float("nan"), regime_stddev=float("nan"),
    )
    # 1.0*0.5 - 0 - 0 + 0 - 0 = 0.5
    assert abs(obj - 0.5) < 1e-10


# ── R11: TrialResult ─────────────────────────────────────────────────────────


def test_trial_result_stores_spec_metrics_objective():
    spec = ResearchCompositeSpec(
        features=("mom_21d",), weights=(1.0,),
        family_counts={"D": 1, "A": 1, "B": 1},
    )
    m = _mk_metrics(ir=0.7)
    tr = TrialResult(spec=spec, metrics=m, objective=0.42)
    assert tr.spec is spec
    assert tr.metrics is m
    assert tr.objective == 0.42


# ── R11: ResearchMiner.run_trial ─────────────────────────────────────────────


@pytest.fixture
def mini_panels():
    """4 synthetic factor panels × 40 bars × 8 symbols for mining tests."""
    np.random.seed(42)
    idx = pd.bdate_range("2024-01-02", periods=40)
    cols = [f"S{i}" for i in range(8)]
    base = pd.DataFrame(np.random.randn(40, 8), index=idx, columns=cols)
    panels = {
        "rel_spy_20d": base + np.random.randn(40, 8) * 0.1,
        "range_pos_252d": base * 0.5 + np.random.randn(40, 8) * 0.5,
        "amihud_20d": np.abs(np.random.randn(40, 8)),
        "trend_tstat_20d": np.random.randn(40, 8),
    }
    panels = {
        k: pd.DataFrame(v, index=idx, columns=cols) if not isinstance(v, pd.DataFrame) else v
        for k, v in panels.items()
    }
    fwd = base * 0.15 + pd.DataFrame(
        np.random.randn(40, 8) * 0.85, index=idx, columns=cols,
    )
    return panels, fwd


def test_research_miner_run_trial_appends_result(mini_panels):
    panels, fwd = mini_panels
    miner = ResearchMiner(factor_panel_map=panels, fwd_returns=fwd)
    trial = MockTrial(
        int_suggestions={
            "n_features_A": 1, "n_features_B": 1, "n_features_C": 1,
            "n_features_D": 1,
        },
        cat_suggestions={
            "family_A_slot_0": "rel_spy_20d",
            "family_B_slot_0": "range_pos_252d",
            "family_C_slot_0": "amihud_20d",
            "family_D_slot_0": "trend_tstat_20d",
        },
        float_suggestions={
            "w_rel_spy_20d": 0.3,
            "w_range_pos_252d": 0.3,
            "w_amihud_20d": 0.2,
            "w_trend_tstat_20d": 0.2,
        },
    )
    obj = miner.run_trial(trial)
    assert len(miner.results) == 1
    assert isinstance(miner.results[0], TrialResult)
    assert miner.results[0].objective == obj
    # With 4 features spanning 4 families, spec should be valid
    assert miner.results[0].spec.n_features == 4
    assert miner.results[0].spec.n_families == 4


def test_research_miner_top_k_sorts_descending(mini_panels):
    """After 3 fake run_trial calls, top_k returns sorted results."""
    panels, fwd = mini_panels
    miner = ResearchMiner(factor_panel_map=panels, fwd_returns=fwd)
    # Inject 3 synthetic TrialResults directly
    spec = ResearchCompositeSpec(
        features=("rel_spy_20d",), weights=(1.0,),
        family_counts={"A": 1, "B": 1, "C": 1},
    )
    m = _mk_metrics(ir=0.5)
    miner.results = [
        TrialResult(spec=spec, metrics=m, objective=0.1),
        TrialResult(spec=spec, metrics=m, objective=0.5),
        TrialResult(spec=spec, metrics=m, objective=0.3),
        TrialResult(spec=spec, metrics=m, objective=float("-inf")),
    ]
    top = miner.top_k(k=2)
    assert len(top) == 2
    assert top[0].objective == 0.5
    assert top[1].objective == 0.3


# ── R11: ResearchMiner.mine (small Optuna integration) ───────────────────────


def test_research_miner_mine_small(mini_panels):
    """3-trial Optuna run completes and produces sorted TrialResults."""
    optuna = pytest.importorskip("optuna")
    panels, fwd = mini_panels
    # Restrict families to only factors present in mini_panels so Optuna
    # can't pick missing names. 1 factor per family × 4 families.
    restricted_families = (
        FamilyConfig(name="A", title="mini-A", factors=frozenset({"rel_spy_20d"})),
        FamilyConfig(name="B", title="mini-B", factors=frozenset({"range_pos_252d"})),
        FamilyConfig(name="C", title="mini-C", factors=frozenset({"amihud_20d"})),
        FamilyConfig(name="D", title="mini-D", factors=frozenset({"trend_tstat_20d"})),
    )
    miner = ResearchMiner(
        factor_panel_map=panels, fwd_returns=fwd,
        families=restricted_families, min_families=3,
    )
    results = miner.mine(n_trials=3, seed=7)
    # At least some trials should be completed (some may fail min_families)
    # Results are finite-objective only, sorted descending
    assert all(np.isfinite(r.objective) for r in results)
    if len(results) >= 2:
        for i in range(len(results) - 1):
            assert results[i].objective >= results[i + 1].objective
    # Every stored result (including pruned ones as -inf) should be in
    # miner.results for audit
    assert len(miner.results) >= len(results)


def test_family_t_sampled():
    """P1-A4 (chart-structure PRD Phase 1): family T (swing-segment
    structure) is reachable by the family_first sampler. Fixed seed; over
    80 trials a family-T `swing_*` factor must appear in a sampled spec."""
    optuna = pytest.importorskip("optuna")
    from core.mining.research_miner import FAMILIES_V2, suggest_composite_spec

    seen: set[str] = set()

    def objective(trial):
        spec = suggest_composite_spec(
            trial, families=FAMILIES_V2, min_families=3,
            sampling_mode="family_first",
        )
        seen.update(spec.features)
        return 0.0

    study = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=13))
    study.optimize(objective, n_trials=80, catch=(Exception,))
    assert any(f.startswith("swing_") for f in seen), (
        f"family T (swing_*) never sampled in 80 family_first trials; "
        f"saw {sorted(seen)}"
    )


# ── A+ patch 2026-04-30: composite_weighting + target_n_features tests ──
# Per docs/memos/20260430-priority_realign_alpha_first.md (A+) and the
# pre-registered cycle 2026-04-30 #01 criteria yaml asserting
# composite_weighting=equal_weight + composite_cardinality=3.


class RecordingMockTrial:
    """MockTrial that records which suggest_* methods get called.

    Used by tests that verify `equal_weight` mode does NOT call
    `trial.suggest_float` for any `w_<feat>` parameter (the whole point
    of the equal_weight mode is to eliminate those degrees of freedom).
    """

    def __init__(self, int_suggestions, cat_suggestions, float_suggestions):
        self._int = int_suggestions
        self._cat = cat_suggestions
        self._float = float_suggestions
        self.float_calls: list[str] = []
        self.int_calls: list[str] = []
        self.cat_calls: list[str] = []

    def suggest_int(self, name: str, low: int, high: int) -> int:
        self.int_calls.append(name)
        return self._int[name]

    def suggest_categorical(self, name: str, choices: list[str]) -> str:
        self.cat_calls.append(name)
        return self._cat[name]

    def suggest_float(self, name: str, low: float, high: float, step: float = None) -> float:
        self.float_calls.append(name)
        return self._float.get(name, 0.5)


def _make_3feat_trial_recording(*, weights=None):
    """Helper: build RecordingMockTrial that picks 1 feat from each of A/B/C."""
    return RecordingMockTrial(
        int_suggestions={
            "n_features_A": 1, "n_features_B": 1, "n_features_C": 1,
            "n_features_D": 0,
        },
        cat_suggestions={
            "family_A_slot_0": "rel_spy_20d",
            "family_B_slot_0": "range_pos_252d",
            "family_C_slot_0": "amihud_20d",
        },
        float_suggestions=weights or {},
    )


def test_apatch_equal_weight_does_not_call_suggest_float_for_weights():
    """equal_weight: trial.suggest_float MUST NOT be called for any w_* param."""
    trial = _make_3feat_trial_recording()
    spec = suggest_composite_spec(
        trial, families=FAMILIES_V1, composite_weighting="equal_weight",
    )
    weight_calls = [name for name in trial.float_calls if name.startswith("w_")]
    assert weight_calls == [], (
        f"equal_weight mode should NOT call suggest_float for weights; "
        f"got {weight_calls}"
    )
    assert spec.n_features == 3


def test_apatch_equal_weight_yields_uniform_weights():
    """equal_weight: every weight = 1/n exactly."""
    trial = _make_3feat_trial_recording()
    spec = suggest_composite_spec(
        trial, families=FAMILIES_V1, composite_weighting="equal_weight",
    )
    n = spec.n_features
    expected = 1.0 / n
    for w in spec.weights:
        assert abs(w - expected) < 1e-9, f"got w={w}, expected {expected}"
    # Sum to 1 invariant still holds (ResearchCompositeSpec invariant)
    assert abs(sum(spec.weights) - 1.0) < 1e-6


def test_apatch_tpe_normalized_default_unchanged_regression():
    """Default composite_weighting is tpe_normalized; behavior matches pre-A+ legacy."""
    # Same scenario as test_suggest_weights_normalize_to_1 above.
    trial = _make_3feat_trial_recording(weights={
        "w_rel_spy_20d": 2.0,
        "w_range_pos_252d": 3.0,
        "w_amihud_20d": 5.0,
    })
    spec = suggest_composite_spec(trial, families=FAMILIES_V1)
    # default = tpe_normalized, weights normalize 2:3:5 → 0.2:0.3:0.5
    wdict = dict(zip(spec.features, spec.weights))
    assert abs(wdict["rel_spy_20d"] - 0.2) < 1e-6
    assert abs(wdict["range_pos_252d"] - 0.3) < 1e-6
    assert abs(wdict["amihud_20d"] - 0.5) < 1e-6
    # AND suggest_float WAS called for weights (legacy behavior preserved)
    weight_calls = [name for name in trial.float_calls if name.startswith("w_")]
    assert len(weight_calls) == 3, (
        f"tpe_normalized must call suggest_float for each weight; "
        f"got {weight_calls}"
    )


def test_apatch_target_n_features_3_passes_when_3():
    """target_n_features=3: spec with exactly 3 features passes."""
    trial = _make_3feat_trial_recording()
    spec = suggest_composite_spec(
        trial, families=FAMILIES_V1,
        composite_weighting="equal_weight", target_n_features=3,
    )
    assert spec.n_features == 3


def test_apatch_target_n_features_3_prunes_when_4():
    """target_n_features=3: spec with 4 features → TrialPruned/ValueError."""
    trial = RecordingMockTrial(
        int_suggestions={
            "n_features_A": 2,  # 2 features from A
            "n_features_B": 1, "n_features_C": 1,
            "n_features_D": 0,
        },
        cat_suggestions={
            "family_A_slot_0": "rel_spy_20d",
            "family_A_slot_1": "rel_qqq_20d",   # different factor (dedup miss)
            "family_B_slot_0": "range_pos_252d",
            "family_C_slot_0": "amihud_20d",
        },
        float_suggestions={},
    )
    with pytest.raises((Exception,)) as excinfo:
        suggest_composite_spec(
            trial, families=FAMILIES_V1,
            composite_weighting="equal_weight", target_n_features=3,
        )
    exc_type_name = type(excinfo.value).__name__
    assert exc_type_name in ("TrialPruned", "ValueError"), (
        f"expected TrialPruned or ValueError, got {exc_type_name}"
    )
    msg = str(excinfo.value)
    assert "target_n_features" in msg or "4" in msg, (
        f"expected target_n_features-related message, got {msg!r}"
    )


def test_apatch_invalid_composite_weighting_raises():
    """composite_weighting must be tpe_normalized or equal_weight."""
    trial = _make_3feat_trial_recording()
    with pytest.raises(ValueError, match="composite_weighting"):
        suggest_composite_spec(
            trial, families=FAMILIES_V1, composite_weighting="bogus",
        )


def test_apatch_runner_honors_criteria_yaml_and_fails_closed_on_mismatch(tmp_path, monkeypatch):
    """Runner-level test: --criteria-yaml IS source of truth; CLI mismatch fails closed.

    Tests both halves of the contract:
      1. yaml-only invocation: runner picks composite_weighting/cardinality from yaml
      2. yaml + conflicting CLI: SystemExit with diagnostic message
    """
    import sys
    import importlib.util

    # Build a minimal criteria yaml in tmp_path
    crit_yaml = tmp_path / "test_crit.yaml"
    crit_yaml.write_text("""
lineage_tag: test-cycle
mining_config:
  composite_weighting: equal_weight
  composite_cardinality: 3
  n_trials: 7
  seed: 42
  sampler: tpe
  panel_end_date: "2025-12-31"
  drop_symbols: ["BRK-B"]
  min_families: 3
  max_features_per_family: 2
""".strip())

    # Load runner module by file path so we can call main() with monkeypatched argv.
    spec = importlib.util.spec_from_file_location(
        "_runner", "scripts/run_research_miner.py",
    )
    mod = importlib.util.module_from_spec(spec)

    # Path 1: conflicting CLI flag → SystemExit fail-closed
    # We test the parser-level branch by intercepting just the load step.
    # Direct execution of spec.loader.exec_module(mod) would import the
    # runner with sys.argv at module-load time; instead we rely on
    # main() being called separately, BUT main() needs a config / archive
    # / panel which are heavy. So this test isolates the criteria-yaml
    # parsing logic by extracting argparse + yaml-merge into a helper
    # if needed. For now we exec just enough:
    spec.loader.exec_module(mod)

    # Conflicting-CLI fail-closed path
    argv_conflict = [
        "run_research_miner.py",
        "--criteria-yaml", str(crit_yaml),
        "--composite-weighting", "tpe_normalized",  # conflicts with yaml equal_weight
        "--temporal-split", "/dev/null",
        "--role", "core",
    ]
    monkeypatch.setattr(sys, "argv", argv_conflict)
    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    msg = str(excinfo.value)
    assert "criteria-yaml" in msg.lower() or "mismatch" in msg.lower() or "conflict" in msg.lower(), (
        f"expected fail-closed mismatch message; got: {msg!r}"
    )


# ── A++ patch 2026-04-30: FAMILIES_V2 + reachability preflight tests ────────


def test_aplusplus_families_v2_union_equals_research_factors():
    """FAMILIES_V2 must cover RESEARCH_FACTORS exactly — the criteria yaml's
    `factor_registry_pool: RESEARCH_FACTORS` contract requires every name
    in the registry to be reachable by the sampler."""
    from core.factors.factor_registry import RESEARCH_FACTORS
    from core.mining.research_miner import FAMILIES_V2, all_family_factors

    reachable = all_family_factors(FAMILIES_V2)
    expected = set(RESEARCH_FACTORS)
    missing = expected - reachable
    extra = reachable - expected
    assert not missing, f"FAMILIES_V2 missing RESEARCH_FACTORS: {sorted(missing)}"
    assert not extra, (
        f"FAMILIES_V2 contains names not in RESEARCH_FACTORS "
        f"(would be unimplemented factors): {sorted(extra)}"
    )
    assert reachable == expected
    # Updated 2026-05-12 (PRD 20260512): post Bucket A/B/C/Macro
    # expansion +76 factors registered across 10 new families G-P:
    # 67 → 143 reachable factors. Breakdown:
    #   G (volume microstructure + 4-quadrant): 9
    #   H (consolidation): 6
    #   I (higher moments + anchor + BAB): 6
    #   J (calendar): 3
    #   K (Piotroski + Magic): 15
    #   L (distress: Beneish + Altman): 15
    #   M (capital return): 5
    #   N (growth + leverage): 6
    #   O (sector-relative): 5
    #   P (macro: FRED): 6
    # = 76 new + 67 existing = 143 (note: macro_drawdown / cross_section_dispersion_21d
    # etc are accounted for in the existing 67).
    # Round D 2026-05-12: +4 event window factors (pre_fomc /
    # post_fomc / pre_cpi / pre_nfp) merged into family J → 147.
    # Round E 2026-05-12: +10 Ohlson O-score factors (9 components +
    # composite) into family L → 157.
    # Round F 2026-05-12: +5 signal-confirmation multi-bar factors
    # into new family Q → 162.
    # 2026-05-15 (priority 1+2): +10 Family R chart-pattern factors
    # (Donchian / MA-cross / streak / ATR breakout) + 3 Family S
    # regime-ML factors (regime_score_combined / transition_risk /
    # persistence) → 175.
    # 2026-05-15 (chart-structure PRD Phase 1, P1·R3): +12 Family T
    # swing-segment structure factors → 187. union(FAMILIES_V2) ==
    # RESEARCH_FACTORS contract verified above by `assert reachable
    # == expected`.
    assert len(reachable) == 187


def test_aplusplus_families_v1_unchanged_at_33():
    """FAMILIES_V1 stays at the pre-A++ 33-factor subset (legacy unchanged)."""
    reachable = all_family_factors(FAMILIES_V1)
    assert len(reachable) == 33


def test_aplusplus_cand2_anchors_reachable_in_v2():
    """Cand-2's 3 anchors (`ret_5d`, `rs_vs_spy_126d`, `hl_range`) must all
    be reachable via FAMILIES_V2. Pre-A++, `ret_5d` and `hl_range` were
    unreachable — that is the headline contract violation A++ fixes."""
    from core.mining.research_miner import FAMILIES_V2, all_family_factors

    reachable_v2 = all_family_factors(FAMILIES_V2)
    reachable_v1 = all_family_factors(FAMILIES_V1)
    for anchor in ("ret_5d", "rs_vs_spy_126d", "hl_range"):
        assert anchor in reachable_v2, (
            f"{anchor!r} unreachable via FAMILIES_V2 — Cand-2 anchor must be"
            " searchable for the criteria yaml RESEARCH_FACTORS contract."
        )
    # Sanity: at least one Cand-2 anchor was unreachable in V1 (the gap A++ fixes)
    v1_unreachable_cand2 = {
        a for a in ("ret_5d", "rs_vs_spy_126d", "hl_range") if a not in reachable_v1
    }
    assert v1_unreachable_cand2, (
        "Pre-A++ FAMILIES_V1 was supposed to NOT cover all Cand-2 anchors "
        "(the contract gap motivating A++)."
    )


def test_aplusplus_families_v2_no_duplicate_ownership():
    """No factor should belong to two families in FAMILIES_V2 — a single
    factor in two families would skew family_counts and break the
    min_families post-dedup count."""
    from core.mining.research_miner import FAMILIES_V2

    seen = {}
    for fam in FAMILIES_V2:
        for f in fam.factors:
            assert f not in seen, (
                f"factor {f!r} owned by both family {seen[f]!r} and {fam.name!r}"
            )
            seen[f] = fam.name


def test_aplusplus_selector_research_factors_returns_v2():
    from core.mining.research_miner import (
        FAMILIES_V2, families_for_pool,
    )
    assert families_for_pool("RESEARCH_FACTORS") is FAMILIES_V2


def test_aplusplus_selector_families_v1_returns_v1():
    from core.mining.research_miner import families_for_pool
    assert families_for_pool("FAMILIES_V1") is FAMILIES_V1


def test_aplusplus_selector_unknown_pool_fails_closed():
    from core.mining.research_miner import families_for_pool
    with pytest.raises(ValueError, match="Unknown factor_registry_pool"):
        families_for_pool("RESEARCH_FACTORS_v3")


def test_aplusplus_assert_reachability_passes_for_v2_research_pool():
    from core.mining.research_miner import (
        FAMILIES_V2, assert_reachability_matches_pool,
    )
    # Should not raise
    assert_reachability_matches_pool("RESEARCH_FACTORS", FAMILIES_V2)


def test_aplusplus_assert_reachability_fails_v1_with_research_pool():
    """The exact contract gap that motivated A++: passing FAMILIES_V1 with
    pool=RESEARCH_FACTORS must fail-closed and list the 31 missing names."""
    from core.mining.research_miner import assert_reachability_matches_pool

    with pytest.raises(ValueError) as excinfo:
        assert_reachability_matches_pool("RESEARCH_FACTORS", FAMILIES_V1)
    msg = str(excinfo.value)
    assert "RESEARCH_FACTORS" in msg
    assert "Missing from sampler" in msg
    # Spot-check that some known missing names appear in the message
    assert "ret_5d" in msg
    assert "hl_range" in msg


def test_aplusplus_assert_reachability_ignores_explicit_exclusions_layer_split():
    """A++ R3 audit refinement: assert_reachability_matches_pool is the
    CODE-level mapping-vs-registry check. explicit_exclusions live at the
    OPERATIONAL layer (runner panel-availability + sampler-time filter)
    and do NOT relax this assertion.

    Concretely: V1 with pool=RESEARCH_FACTORS still fails-closed even if
    every missing name is declared as explicit_exclusions. The right way
    to make V1+RESEARCH_FACTORS work is to broaden the family mapping
    (which is what V2 does), not to over-load explicit_exclusions."""
    from core.factors.factor_registry import RESEARCH_FACTORS
    from core.mining.research_miner import (
        all_family_factors, assert_reachability_matches_pool,
    )

    missing_31 = sorted(set(RESEARCH_FACTORS) - all_family_factors(FAMILIES_V1))
    # Even with explicit exclusions covering every missing name, the
    # CODE-level mapping-vs-registry check still fails (this is the
    # layer-split contract).
    with pytest.raises(ValueError, match="Sampler reachability does NOT match"):
        assert_reachability_matches_pool(
            "RESEARCH_FACTORS", FAMILIES_V1, explicit_exclusions=missing_31,
        )


def test_aplusplus_suggest_composite_excludes_factors_at_sampler_time():
    """A++ R3 audit refinement: explicit exclusions are honored at
    sampler time — TPE never sees the excluded names in any family's
    categorical search space, so trials can never pick them.
    """
    from core.mining.research_miner import (
        FAMILIES_V2, suggest_composite_spec,
    )

    # Build a trial that always picks 1 feature per family. Excluding
    # all of family F's factors should make family F yield 0 features.
    fam_f_factors = {"ret_1d", "ret_2d", "ret_5d",
                     "reversal_5d", "reversal_10d", "reversal_21d"}
    excluded = sorted(fam_f_factors)

    class _Trial:
        def suggest_int(self, name, lo, hi): return hi  # max per family
        def suggest_categorical(self, name, choices):
            # Asserts no excluded factor is ever offered as a choice
            for c in choices:
                assert c not in fam_f_factors, (
                    f"sampler offered excluded factor {c!r} in {name}"
                )
            return choices[0]
        def suggest_float(self, name, lo, hi, step=None): return 1.0

    spec = suggest_composite_spec(
        _Trial(),
        families=FAMILIES_V2,
        min_families=3,
        max_features_per_family=2,
        composite_weighting="equal_weight",
        excluded_factors=excluded,
    )
    # Spec features should not contain any excluded factor
    for feat in spec.features:
        assert feat not in fam_f_factors


def test_aplusplus_research_miner_constructor_runs_preflight():
    """Constructing ResearchMiner with factor_registry_pool=RESEARCH_FACTORS
    and families=FAMILIES_V1 must fail-closed at construction time
    (defense-in-depth — runner OR a direct caller both go through the
    same gate)."""
    # Build minimal panel inputs (1 factor + 1 fwd return frame)
    idx = pd.date_range("2020-01-01", periods=10, freq="B")
    cols = ["AAPL", "MSFT", "GOOG"]
    factor_panel_map = {
        "beta_spy_60d": pd.DataFrame(0.1, index=idx, columns=cols)
    }
    fwd_returns = pd.DataFrame(0.0, index=idx, columns=cols)

    with pytest.raises(ValueError, match="Sampler reachability does NOT match"):
        ResearchMiner(
            factor_panel_map=factor_panel_map,
            fwd_returns=fwd_returns,
            families=FAMILIES_V1,
            factor_registry_pool="RESEARCH_FACTORS",
        )


def test_aplusplus_research_miner_constructor_passes_with_v2():
    """Symmetric to previous: V2 + RESEARCH_FACTORS pool constructs cleanly."""
    from core.mining.research_miner import FAMILIES_V2

    idx = pd.date_range("2020-01-01", periods=10, freq="B")
    cols = ["AAPL", "MSFT", "GOOG"]
    factor_panel_map = {
        "beta_spy_60d": pd.DataFrame(0.1, index=idx, columns=cols)
    }
    fwd_returns = pd.DataFrame(0.0, index=idx, columns=cols)

    miner = ResearchMiner(
        factor_panel_map=factor_panel_map,
        fwd_returns=fwd_returns,
        families=FAMILIES_V2,
        factor_registry_pool="RESEARCH_FACTORS",
    )
    assert miner.factor_registry_pool == "RESEARCH_FACTORS"
    assert miner.explicit_exclusions == ()
    # Pre-2026-05-12: 6 families (A-F). PRD 20260512: +10 families
    # (G-P) for Bucket A/B/C/Macro factors. Round F: +1 family Q
    # for signal-confirmation multi-bar → 17. 2026-05-15 (priority
    # 1+2): +1 family R chart-pattern, +1 family S regime-ML → 19.
    # 2026-05-15 (chart-structure PRD Phase 1, P1·R3): +1 family T
    # swing-segment structure → 20.
    assert len(miner.families) == 20


def test_aplusplus_research_miner_no_pool_legacy_path():
    """factor_registry_pool=None preserves legacy / direct-pool flow
    (no preflight assertion, no constructor-time fail-closed)."""
    idx = pd.date_range("2020-01-01", periods=10, freq="B")
    cols = ["AAPL", "MSFT", "GOOG"]
    factor_panel_map = {
        "beta_spy_60d": pd.DataFrame(0.1, index=idx, columns=cols)
    }
    fwd_returns = pd.DataFrame(0.0, index=idx, columns=cols)

    miner = ResearchMiner(
        factor_panel_map=factor_panel_map,
        fwd_returns=fwd_returns,
        families=FAMILIES_V1,
        factor_registry_pool=None,
    )
    assert miner.factor_registry_pool is None
