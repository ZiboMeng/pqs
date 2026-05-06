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
