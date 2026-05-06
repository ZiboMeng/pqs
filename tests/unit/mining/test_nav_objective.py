"""Unit tests for core/mining/nav_objective.py (PRD-AC v1.1 Phase 2 §4.6)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core.mining.nav_objective import (
    build_universe_baseline_residual_returns,
    classify_cross_asset_spec,
    compute_spec_residual_pooled_raw_correlation,
)


# ── build_universe_baseline_residual_returns ─────────────────────────────────


def _make_panel(n_days: int = 100, n_syms: int = 5, seed: int = 0) -> pd.DataFrame:
    """Synthetic adjusted-close panel with cumulative returns."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    # Daily returns + market common factor (so SPY correlation is real)
    market = rng.normal(0, 0.01, size=n_days)
    sym_specific = rng.normal(0, 0.005, size=(n_days, n_syms))
    returns = market[:, None] + sym_specific
    prices = 100.0 * np.cumprod(1 + returns, axis=0)
    return pd.DataFrame(
        prices, index=dates, columns=[f"S{i}" for i in range(n_syms)],
    )


def _make_spy(panel: pd.DataFrame, seed: int = 1) -> pd.Series:
    """Synthetic SPY series correlated with the panel's market factor."""
    rng = np.random.default_rng(seed)
    n = len(panel)
    # Use the panel's avg as a proxy "market", + small idiosyncratic noise
    avg_ret = panel.pct_change().mean(axis=1).fillna(0).to_numpy()
    spy_ret = avg_ret + rng.normal(0, 0.002, size=n)
    spy_prices = 400.0 * np.cumprod(1 + spy_ret)
    return pd.Series(spy_prices, index=panel.index, name="SPY")


def test_build_anchor_returns_residual_series():
    """Anchor builder produces a non-empty residual series with same
    length as the joint non-null window."""
    panel = _make_panel()
    spy = _make_spy(panel)
    anchor = build_universe_baseline_residual_returns(panel, spy)
    assert isinstance(anchor, pd.Series)
    assert anchor.name == "universe_baseline_residual"
    assert len(anchor) > 0
    # Residual should have lower correlation with SPY than baseline does
    spy_ret = spy.pct_change().reindex(anchor.index).dropna()
    a = anchor.reindex(spy_ret.index).dropna()
    spy_aligned = spy_ret.reindex(a.index)
    assert abs(float(a.corr(spy_aligned))) < 0.30  # residual ⊥ to SPY by construction


def test_build_anchor_handles_empty_panel():
    """Empty panel returns empty Series."""
    panel = pd.DataFrame()
    spy = pd.Series([1.0, 1.01, 1.02])
    anchor = build_universe_baseline_residual_returns(panel, spy)
    assert anchor.empty


def test_build_anchor_handles_insufficient_overlap():
    """When joint non-null window < min_obs, returns NaN-filled Series."""
    panel = _make_panel(n_days=10)
    spy = _make_spy(panel)
    anchor = build_universe_baseline_residual_returns(panel, spy, min_obs=30)
    assert anchor.isna().all()


# ── compute_spec_residual_pooled_raw_correlation ─────────────────────────────


def test_spec_residual_correlation_against_anchor():
    """A spec that is strongly correlated with the anchor (after SPY-strip)
    produces a positive Pearson correlation."""
    panel = _make_panel(n_days=200)
    spy = _make_spy(panel)
    anchor = build_universe_baseline_residual_returns(panel, spy)
    # Spec returns = anchor + small noise → should correlate strongly
    rng = np.random.default_rng(42)
    spy_ret = spy.pct_change()
    # Reconstruct spec returns: spec = β_spec × spy + anchor_aligned + noise
    aligned_anchor = anchor.reindex(spy_ret.index).fillna(0)
    spec_returns = 1.1 * spy_ret + aligned_anchor + rng.normal(0, 0.001, size=len(spy_ret))
    spec_returns = spec_returns.dropna()
    corr = compute_spec_residual_pooled_raw_correlation(
        spec_returns, anchor, spy,
    )
    assert math.isfinite(corr)
    assert corr > 0.5, f"expected strong positive corr, got {corr}"


def test_spec_residual_correlation_orthogonal_returns_near_zero():
    """A spec whose residual is orthogonal to the anchor returns ~0."""
    panel = _make_panel(n_days=300)
    spy = _make_spy(panel)
    anchor = build_universe_baseline_residual_returns(panel, spy)
    # Spec returns = β × SPY + independent noise (no shared anchor structure)
    rng = np.random.default_rng(123)
    spy_ret = spy.pct_change().dropna()
    spec_returns = 1.0 * spy_ret + pd.Series(
        rng.normal(0, 0.005, size=len(spy_ret)), index=spy_ret.index,
    )
    corr = compute_spec_residual_pooled_raw_correlation(
        spec_returns, anchor, spy,
    )
    assert math.isfinite(corr)
    assert abs(corr) < 0.30, f"expected near-zero, got {corr}"


def test_spec_residual_correlation_handles_empty_input():
    """Empty inputs return NaN."""
    spy = pd.Series([1.0, 1.01], index=pd.date_range("2020-01-01", periods=2))
    corr = compute_spec_residual_pooled_raw_correlation(
        pd.Series(dtype="float64"), pd.Series(dtype="float64"), spy,
    )
    assert math.isnan(corr)


def test_spec_residual_correlation_handles_min_obs_floor():
    """Insufficient overlap returns NaN."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    spec = pd.Series(np.random.default_rng(0).normal(0, 0.01, size=10), index=dates)
    anchor = pd.Series(np.random.default_rng(1).normal(0, 0.01, size=10), index=dates)
    spy = pd.Series(np.cumprod(1 + np.random.default_rng(2).normal(0, 0.01, size=10)), index=dates)
    corr = compute_spec_residual_pooled_raw_correlation(spec, anchor, spy, min_obs=30)
    assert math.isnan(corr)


# ── mask_train_boundary_returns (PRD §6 Phase 2 I9 fix) ─────────────────────


def test_mask_train_boundary_returns_zeroes_gap_days():
    """Returns at days where the prior trading day is > 30 days earlier
    are zeroed; in-segment returns are preserved."""
    from core.mining.nav_objective import mask_train_boundary_returns

    seg_a = pd.date_range("2017-01-02", "2017-12-29", freq="B")
    seg_b = pd.date_range("2020-01-02", "2020-12-31", freq="B")
    idx = seg_a.union(seg_b)
    rets = pd.Series(0.001, index=idx)
    rets.loc[pd.Timestamp("2020-01-02")] = 0.10  # the dirty boundary day
    masked = mask_train_boundary_returns(rets)
    assert masked.loc[pd.Timestamp("2020-01-02")] == 0.0
    # In-segment days unchanged
    assert masked.loc[pd.Timestamp("2017-06-15")] == 0.001


def test_mask_train_boundary_returns_preserves_in_segment_holidays():
    """Long-weekend / Christmas-week gaps (≤30 days) are NOT masked."""
    from core.mining.nav_objective import mask_train_boundary_returns

    # 4-day Christmas gap: 2020-12-24 (Thu) → 2020-12-28 (Mon) is normal
    # market behavior, not a train_year boundary
    idx = pd.DatetimeIndex([
        "2020-12-23", "2020-12-24", "2020-12-28", "2020-12-29",
    ])
    rets = pd.Series(0.005, index=idx)
    masked = mask_train_boundary_returns(rets, gap_threshold_days=30)
    assert (masked == rets).all(), "holiday gap incorrectly masked"


def test_mask_train_boundary_returns_handles_short_series():
    """Series with < 2 elements returns a copy unchanged."""
    from core.mining.nav_objective import mask_train_boundary_returns

    one = pd.Series([0.01], index=[pd.Timestamp("2020-01-01")])
    masked = mask_train_boundary_returns(one)
    assert (masked == one).all()


def test_recompute_nav_metrics_train_only_excludes_gap_returns():
    """Sharpe / max_dd / vs_qqq computed on masked returns differ from
    raw values when the input has a gap-day spike."""
    from core.mining.nav_objective import recompute_nav_metrics_train_only

    seg_a = pd.date_range("2017-01-02", "2017-12-29", freq="B")
    seg_b = pd.date_range("2020-01-02", "2020-06-30", freq="B")
    idx = seg_a.union(seg_b)
    np.random.seed(0)
    rets = pd.Series(np.random.normal(0.0005, 0.005, size=len(idx)), index=idx)
    rets.loc[pd.Timestamp("2020-01-02")] = 0.10  # +10% gap-day spike
    out_with_gap = recompute_nav_metrics_train_only(rets)
    # Without our fix, the spike would dominate. With fix, sharpe should
    # not be inflated by the spike.
    rets_clean = rets.copy()
    rets_clean.loc[pd.Timestamp("2020-01-02")] = 0.0
    out_no_gap = recompute_nav_metrics_train_only(rets_clean)
    assert abs(out_with_gap["sharpe"] - out_no_gap["sharpe"]) < 1e-6, (
        "mask did not zero out gap return: "
        f"{out_with_gap['sharpe']} vs {out_no_gap['sharpe']}"
    )


def test_recompute_nav_metrics_train_only_with_qqq_benchmark():
    """vs_qqq computed on masked returns excludes gap days for both
    spec AND QQQ (consistent comparison)."""
    from core.mining.nav_objective import recompute_nav_metrics_train_only

    seg_a = pd.date_range("2017-01-02", "2017-12-29", freq="B")
    seg_b = pd.date_range("2020-01-02", "2020-06-30", freq="B")
    idx = seg_a.union(seg_b)
    rets = pd.Series(0.001, index=idx)
    rets.loc[pd.Timestamp("2020-01-02")] = 0.05  # spec spike
    qqq_prices = pd.Series(
        np.cumprod(1 + np.full(len(idx), 0.0008)) * 300.0, index=idx,
    )
    qqq_prices.loc[pd.Timestamp("2020-01-02")] *= 1.08  # QQQ spike at boundary
    out = recompute_nav_metrics_train_only(rets, qqq_series=qqq_prices)
    # vs_qqq is finite even after masking both legs
    assert math.isfinite(out["vs_qqq"])


# ── classify_cross_asset_spec ────────────────────────────────────────────────


def test_classify_cross_asset_pure_equity_returns_false():
    """100% equity portfolio is NOT cross-asset."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    weights = pd.DataFrame(
        {"AAPL": [0.5] * 10, "MSFT": [0.5] * 10}, index=dates,
    )
    # Default lookup will map both to "equities" (real cluster map)
    assert classify_cross_asset_spec(weights) is False


def test_classify_cross_asset_above_threshold_returns_true():
    """≥30% non-equity (custom lookup) → True."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    weights = pd.DataFrame(
        {"AAPL": [0.5] * 10, "TLT": [0.5] * 10}, index=dates,
    )
    lookup = {"AAPL": "equities", "TLT": "bonds"}
    assert classify_cross_asset_spec(weights, asset_class_lookup=lookup) is True


def test_classify_cross_asset_at_threshold_boundary():
    """Exactly 30% non-equity → False (strict >)."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    weights = pd.DataFrame(
        {"AAPL": [0.7] * 10, "TLT": [0.3] * 10}, index=dates,
    )
    lookup = {"AAPL": "equities", "TLT": "bonds"}
    assert classify_cross_asset_spec(weights, asset_class_lookup=lookup) is False


def test_classify_cross_asset_empty_weights_returns_false():
    """Empty weights → False (conservative)."""
    assert classify_cross_asset_spec(pd.DataFrame()) is False


def test_classify_cross_asset_unknown_symbol_defaults_equities():
    """Unknown symbol falls back to 'equities' (no abort, conservative)."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    weights = pd.DataFrame(
        {"UNKNOWN_TICKER_XYZ": [1.0] * 10}, index=dates,
    )
    # No explicit lookup; default unified map will KeyError, defensive
    # fallback to equities → not cross-asset
    assert classify_cross_asset_spec(weights) is False


def test_classify_cross_asset_threshold_kwarg_override():
    """Threshold kwarg works as expected."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    weights = pd.DataFrame(
        {"AAPL": [0.85] * 10, "TLT": [0.15] * 10}, index=dates,
    )
    lookup = {"AAPL": "equities", "TLT": "bonds"}
    # 15% non-equity: not cross-asset at default 30%
    assert classify_cross_asset_spec(weights, asset_class_lookup=lookup) is False
    # But IS cross-asset at 10%
    assert classify_cross_asset_spec(
        weights, asset_class_lookup=lookup, non_equity_threshold=0.10,
    ) is True
