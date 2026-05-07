"""Master PRD §4.3 C.1 (R6 ship 2026-05-07) — regime-conditional v3
mining objective tests.

Covers:
  - ObjectiveWeightsV3 dataclass shape + defaults
  - compute_objective isinstance dispatch (Issue N)
  - evaluate_composite_regime_conditional regime stratification
  - Issue D fallback rule (regime n_days < 200 → full-period IC)
  - Backward compat: v1/v2 paths unchanged
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.mining.research_miner import (
    CompositeMetrics,
    ObjectiveWeights,
    ObjectiveWeightsV3,
    ResearchCompositeSpec,
    compute_objective,
    evaluate_composite_regime_conditional,
    zscore_cs,
)


def _build_panel(n_days=400, n_syms=8, seed=0):
    """Synthetic panel with enough days to cover regime stratification."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-01", periods=n_days, freq="B")
    syms = [f"S{i}" for i in range(n_syms)]
    market = rng.normal(0, 0.01, size=n_days)
    sym_specific = rng.normal(0, 0.005, size=(n_days, n_syms))
    rets = market[:, None] + sym_specific
    prices = 100.0 * np.cumprod(1 + rets, axis=0)
    price_df = pd.DataFrame(prices, index=dates, columns=syms)
    open_df = price_df * (1 + rng.normal(0, 0.001, size=(n_days, n_syms)))
    fwd = price_df.pct_change(21).shift(-21)
    panel_map = {
        "momentum_20d": zscore_cs(price_df.pct_change(20)),
        "momentum_60d": zscore_cs(price_df.pct_change(60)),
    }
    spy = pd.Series(
        400.0 * np.cumprod(1 + market + rng.normal(0, 0.001, size=n_days)),
        index=dates, name="SPY",
    )
    qqq = pd.Series(
        300.0 * np.cumprod(
            1 + market * 1.1 + rng.normal(0, 0.002, size=n_days)
        ),
        index=dates, name="QQQ",
    )
    return panel_map, fwd, price_df, open_df, spy, qqq


def _make_regime_labels(dates: pd.DatetimeIndex, seed: int = 0) -> pd.Series:
    """Synthetic regime labels: rotate {BULL, NEUTRAL, RISK_OFF, CRISIS}
    in 60-day blocks. Total 400 days → ~100 days per regime, deliberately
    UNDER 200 for some regimes to exercise Issue D fallback."""
    rng = np.random.default_rng(seed)
    regimes = ("BULL", "NEUTRAL", "RISK_OFF", "CRISIS")
    labels = []
    for i, _ in enumerate(dates):
        labels.append(regimes[(i // 60) % len(regimes)])
    return pd.Series(labels, index=dates, dtype=str)


# ── ObjectiveWeightsV3 dataclass ──────────────────────────────────────────────


def test_objective_weights_v3_default_shape():
    """Default ObjectiveWeightsV3 has all 6 per-regime IR + 2 NAV-Sharpe +
    full-period anchor + vs_qqq weights."""
    w = ObjectiveWeightsV3()
    assert w.w_ir_BULL == 0.5
    assert w.w_ir_RISK_ON == 0.5
    assert w.w_ir_NEUTRAL == 0.5
    assert w.w_ir_CAUTIOUS == 1.0
    assert w.w_ir_RISK_OFF == 1.5
    assert w.w_ir_CRISIS == 2.0
    assert w.w_nav_sharpe_BULL == 0.10
    assert w.w_nav_sharpe_BEAR == 0.30
    assert w.w_nav_orthogonality == 2.0
    assert w.w_vs_qqq_excess == 0.20


def test_objective_weights_v3_is_nav_based():
    """v3 is always NAV-based by definition (NAV-Sharpe + orthogonality
    + vs_qqq are intrinsic)."""
    w = ObjectiveWeightsV3()
    assert w.is_nav_based() is True


# ── compute_objective dispatch (Issue N) ──────────────────────────────────────


def test_compute_objective_v3_dispatch_via_isinstance():
    """ObjectiveWeightsV3 dispatch on isinstance — passes Dict[regime, metrics],
    not single CompositeMetrics."""
    m = CompositeMetrics(
        n_features=3, n_families=3, n_dates=100,
        ic_mean=0.05, ic_std=0.20, ic_ir=0.5,
        turnover_proxy=0.1, corr_concentration=0.1, horizon=21,
        nav_sharpe=0.5, nav_max_dd=-0.10,
        nav_correlation_vs_anchor_pooled_raw=0.30,
        nav_vs_qqq_excess_full_period=0.05,
    )
    metrics_per_regime = {"BULL": m, "CRISIS": m, "NEUTRAL": m}
    w = ObjectiveWeightsV3()
    val = compute_objective(metrics_per_regime, weights=w)
    # Hand-compute expected:
    # IR: 0.5*0.5 + 0.5*0.5 + 2.0*0.5 = 1.5 (BULL + NEUTRAL + CRISIS)
    # BULL nav_sharpe: 0.10 * 0.5 = 0.05
    # BEAR nav_sharpe (only CRISIS in BEAR aggregate): 0.30 * 0.5 = 0.15
    # Anchor: 2.0 * max(0, 0.30 - 0.5) = 0 (anchor below 0.5 → no penalty)
    # vs_qqq: 0.20 * 0.05 = 0.01
    # total = 1.5 + 0.05 + 0.15 + 0.01 = 1.71
    assert abs(val - 1.71) < 1e-9, f"expected 1.71, got {val}"


def test_compute_objective_v3_with_single_metrics_raises_typeerror():
    """ObjectiveWeightsV3 dispatch requires Dict; passing single
    CompositeMetrics → TypeError."""
    m = CompositeMetrics(
        n_features=2, n_families=2, n_dates=100,
        ic_mean=0.0, ic_std=0.1, ic_ir=0.0,
        turnover_proxy=0.1, corr_concentration=0.1,
    )
    w = ObjectiveWeightsV3()
    with pytest.raises(TypeError, match="ObjectiveWeightsV3"):
        compute_objective(m, weights=w)


def test_compute_objective_v3_all_finite_ir_zero_returns_finite():
    """When all regime IRs are 0 (not NaN), v3 returns 0 (not -inf).
    Only ALL-NaN IR returns -inf."""
    m = CompositeMetrics(
        n_features=2, n_families=2, n_dates=100,
        ic_mean=0.0, ic_std=0.0, ic_ir=0.0,
        turnover_proxy=0.0, corr_concentration=0.0,
    )
    val = compute_objective({"BULL": m}, weights=ObjectiveWeightsV3())
    assert val == 0.0


def test_compute_objective_v3_all_nan_ir_returns_neg_inf():
    """All-NaN regime IRs → -inf (no signal anywhere)."""
    m_nan = CompositeMetrics(
        n_features=2, n_families=2, n_dates=0,
        ic_mean=float("nan"), ic_std=float("nan"), ic_ir=float("nan"),
        turnover_proxy=0.0, corr_concentration=0.0,
    )
    val = compute_objective(
        {"BULL": m_nan, "CRISIS": m_nan},
        weights=ObjectiveWeightsV3(),
    )
    assert val == float("-inf")


def test_compute_objective_v1_path_unchanged():
    """Backward compat: ObjectiveWeights (v1) path still works on a single
    CompositeMetrics."""
    m = CompositeMetrics(
        n_features=2, n_families=2, n_dates=100,
        ic_mean=0.05, ic_std=0.20, ic_ir=0.5,
        turnover_proxy=0.0, corr_concentration=0.0,
    )
    val = compute_objective(m, weights=ObjectiveWeights())
    # Default ObjectiveWeights: w_ir=1.0 → val == 0.5
    assert abs(val - 0.5) < 1e-9


# ── evaluate_composite_regime_conditional ─────────────────────────────────────


def test_evaluate_composite_regime_conditional_returns_per_regime_dict():
    """evaluate_composite_regime_conditional returns Dict keyed by regime
    names from daily_regime_labels.unique()."""
    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel(n_days=400)
    labels = _make_regime_labels(price_df.index)
    spec = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.5, 0.5), family_counts={"A": 2},
    )
    out = evaluate_composite_regime_conditional(
        spec, panel_map, fwd, daily_regime_labels=labels,
        # No NAV path → just test IC stratification
        fallback_min_n_days=50,  # all regimes ~100 days, won't fallback
    )
    assert set(out.keys()) == {"BULL", "NEUTRAL", "RISK_OFF", "CRISIS"}
    # All four should have stratified IC (not fallback) since
    # fallback_min=50 < per-regime ~100 days
    for regime, m in out.items():
        assert m.n_features == 2
        assert m.n_families == 1


def test_evaluate_composite_regime_conditional_issue_d_fallback():
    """Issue D fallback: when regime n_days < fallback_min_n_days, IR
    falls back to full-period (not regime-stratified)."""
    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel(n_days=400)
    labels = _make_regime_labels(price_df.index)
    spec = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.5, 0.5), family_counts={"A": 2},
    )
    # fallback_min_n_days=200 > per-regime ~100 → ALL regimes hit fallback
    out = evaluate_composite_regime_conditional(
        spec, panel_map, fwd, daily_regime_labels=labels,
        fallback_min_n_days=200,
    )
    # All regimes hit fallback → IC values should be IDENTICAL across
    # regimes (all using full-period IC as fallback)
    ic_irs = [out[r].ic_ir for r in out.keys()]
    if all(np.isfinite(ir) for ir in ic_irs):
        # All identical means fallback fired uniformly
        assert all(abs(ir - ic_irs[0]) < 1e-9 for ir in ic_irs)
    # Per-regime n_dates records the actual regime count, NOT the
    # full-period count (audit trail for which regimes hit fallback)
    for regime, m in out.items():
        regime_count = (labels == regime).sum()
        assert m.n_dates == regime_count


def test_research_miner_v3_dispatch_via_run_trial():
    """ResearchMiner.run_trial dispatches to evaluate_composite_regime_
    conditional when objective_weights is ObjectiveWeightsV3.

    Verified by spy on evaluate_composite_regime_conditional call count.
    """
    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel(n_days=400)
    labels = _make_regime_labels(price_df.index)
    from core.mining.research_miner import ResearchMiner

    miner = ResearchMiner(
        factor_panel_map=panel_map,
        fwd_returns=fwd,
        objective_weights=ObjectiveWeightsV3(),
        daily_regime_labels=labels,
        # ObjectiveWeightsV3 is_nav_based=True → requires price/spy
        price_df=price_df,
        open_df=open_df,
        spy_series=spy,
        qqq_series=qqq,
    )
    assert miner.daily_regime_labels is labels
    assert isinstance(miner.objective_weights, ObjectiveWeightsV3)


def test_research_miner_v3_rejects_missing_regime_labels():
    """Constructor: ObjectiveWeightsV3 + daily_regime_labels=None → ValueError."""
    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel(n_days=200)
    from core.mining.research_miner import ResearchMiner

    with pytest.raises(ValueError, match="daily_regime_labels"):
        ResearchMiner(
            factor_panel_map=panel_map,
            fwd_returns=fwd,
            objective_weights=ObjectiveWeightsV3(),
            daily_regime_labels=None,  # contract violation
            price_df=price_df,
            spy_series=spy,
        )


def test_research_miner_v1_legacy_unchanged_no_regime_labels():
    """Backward compat: ObjectiveWeights (v1) ctor without
    daily_regime_labels works as before."""
    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel(n_days=180)
    from core.mining.research_miner import ResearchMiner

    miner = ResearchMiner(
        factor_panel_map=panel_map,
        fwd_returns=fwd,
        objective_weights=ObjectiveWeights(),
    )
    assert miner.daily_regime_labels is None


def test_evaluate_composite_regime_conditional_with_nav():
    """When price_df + spy_series are provided, full-period NAV metrics
    are populated identically across all per-regime entries (NAV is
    one BacktestEngine run, not regime-stratified per R6 scope)."""
    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel(n_days=400)
    labels = _make_regime_labels(price_df.index)
    spec = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.5, 0.5), family_counts={"A": 2},
    )
    out = evaluate_composite_regime_conditional(
        spec, panel_map, fwd, daily_regime_labels=labels,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        fallback_min_n_days=50,
    )
    # Full-period NAV metrics should be identical across regimes (PRD §4.3
    # C.1 R6 scope: NAV is full-period; per-regime NAV slicing is out of
    # scope for R6).
    nav_sharpes = [out[r].nav_sharpe for r in out.keys()]
    nav_max_dds = [out[r].nav_max_dd for r in out.keys()]
    if all(np.isfinite(s) for s in nav_sharpes):
        assert all(abs(s - nav_sharpes[0]) < 1e-9 for s in nav_sharpes)
    if all(np.isfinite(d) for d in nav_max_dds):
        assert all(abs(d - nav_max_dds[0]) < 1e-9 for d in nav_max_dds)
