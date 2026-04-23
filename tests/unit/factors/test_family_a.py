"""Unit tests for PRD 20260424 Family A benchmark-relative factors."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_generator import (
    generate_all_factors,
    _family_a_benchmark_relative,
)


@pytest.fixture
def panel_with_benchmarks():
    """Panel including SPY, QQQ, and 3 stocks over 150 bars."""
    np.random.seed(42)
    idx = pd.bdate_range("2023-07-01", periods=150)
    # Benchmarks with different paths
    spy = 400 + np.cumsum(np.random.randn(150) * 1.0)
    qqq = 350 + np.cumsum(np.random.randn(150) * 1.5)
    # Stocks: one beta≈1, one beta≈1.3, one near-idiosyncratic
    stock_a = 100 + np.cumsum(np.random.randn(150) * 0.5 + 0.001 * np.diff(
        np.concatenate([[400], spy]),
    ))
    stock_b = 50 + np.cumsum(np.random.randn(150) * 0.8)
    stock_c = 75 + np.cumsum(np.random.randn(150) * 0.3)
    return pd.DataFrame({
        "SPY": spy, "QQQ": qqq, "AAPL": stock_a, "MSFT": stock_b, "GOOGL": stock_c,
    }, index=idx)


# ── rel_spy_20d ───────────────────────────────────────────────────────────────

def test_rel_spy_20d_produced_when_spy_present(panel_with_benchmarks):
    factors = _family_a_benchmark_relative(panel_with_benchmarks)
    assert "rel_spy_20d" in factors
    f = factors["rel_spy_20d"]
    # SPY column in output equals 0 (self-relative)
    valid = f["SPY"].dropna()
    assert np.allclose(valid.values, 0.0, atol=1e-12)


def test_rel_spy_20d_first_20_bars_nan(panel_with_benchmarks):
    factors = _family_a_benchmark_relative(panel_with_benchmarks)
    f = factors["rel_spy_20d"]
    # First 20 bars NaN (pct_change(20) warmup)
    assert f.iloc[:20].isna().all().all()


# ── rel_qqq_20d ───────────────────────────────────────────────────────────────

def test_rel_qqq_20d_produced_when_qqq_present(panel_with_benchmarks):
    factors = _family_a_benchmark_relative(panel_with_benchmarks)
    assert "rel_qqq_20d" in factors
    f = factors["rel_qqq_20d"]
    valid = f["QQQ"].dropna()
    assert np.allclose(valid.values, 0.0, atol=1e-12)


def test_rel_qqq_20d_omitted_when_qqq_missing(panel_with_benchmarks):
    panel = panel_with_benchmarks.drop(columns=["QQQ"])
    factors = _family_a_benchmark_relative(panel)
    assert "rel_qqq_20d" not in factors
    # But rel_spy_20d still produced (SPY still present)
    assert "rel_spy_20d" in factors


# ── beta_spy_60d ──────────────────────────────────────────────────────────────

def test_beta_spy_60d_shape_and_warmup(panel_with_benchmarks):
    factors = _family_a_benchmark_relative(panel_with_benchmarks)
    assert "beta_spy_60d" in factors
    f = factors["beta_spy_60d"]
    # Must match panel shape
    assert f.shape == panel_with_benchmarks.shape
    # Long warmup (min_periods defaults to max(20, 60//2)=30) → first 29 NaN
    assert f.iloc[:29].isna().all().all()
    # Non-warmup rows should have some finite values
    assert f.iloc[60:].notna().any().any()


def test_beta_spy_60d_self_equals_one(panel_with_benchmarks):
    """SPY's beta vs itself must be ~1.0."""
    factors = _family_a_benchmark_relative(panel_with_benchmarks)
    f = factors["beta_spy_60d"]
    valid = f["SPY"].dropna()
    assert np.allclose(valid.values, 1.0, atol=1e-6)


# ── residual_mom_spy_20d ──────────────────────────────────────────────────────

def test_residual_mom_spy_20d_shape_and_warmup(panel_with_benchmarks):
    factors = _family_a_benchmark_relative(panel_with_benchmarks)
    assert "residual_mom_spy_20d" in factors
    f = factors["residual_mom_spy_20d"]
    assert f.shape == panel_with_benchmarks.shape
    # Combined warmup: beta-60d needs ≥30 bars + rolling-20d sum needs ≥10
    # so early bars should be NaN
    assert f.iloc[:30].isna().all().all()
    assert f.iloc[80:].notna().any().any()


def test_residual_mom_spy_20d_self_near_zero(panel_with_benchmarks):
    """SPY's residual momentum vs itself should be ~0 (beta=1 → residual=0)."""
    factors = _family_a_benchmark_relative(panel_with_benchmarks)
    f = factors["residual_mom_spy_20d"]
    valid = f["SPY"].dropna()
    # Each daily residual ~ 0; 20d sum also ~ 0
    assert abs(valid.mean()) < 1e-4


# ── End-to-end via generate_all_factors ──────────────────────────────────────

def test_generate_all_factors_produces_family_a(panel_with_benchmarks):
    """Confirm all 4 Family A features ship via generate_all_factors."""
    factors = generate_all_factors(panel_with_benchmarks)
    for name in ("rel_spy_20d", "rel_qqq_20d",
                 "beta_spy_60d", "residual_mom_spy_20d"):
        assert name in factors, f"{name} missing from generator output"


def test_generate_all_factors_family_a_via_benchmark_map(panel_with_benchmarks):
    """P1 + Family A composition: caller panel WITHOUT SPY/QQQ; supply via map."""
    stocks_only = panel_with_benchmarks.drop(columns=["SPY", "QQQ"])
    spy_series = panel_with_benchmarks["SPY"]
    qqq_series = panel_with_benchmarks["QQQ"]
    factors = generate_all_factors(
        stocks_only,
        benchmark_map={"SPY": spy_series, "QQQ": qqq_series},
    )
    # All 4 Family A features produced
    for name in ("rel_spy_20d", "rel_qqq_20d",
                 "beta_spy_60d", "residual_mom_spy_20d"):
        assert name in factors
    # But trimmed to caller's columns (no SPY/QQQ leaking)
    f = factors["rel_spy_20d"]
    assert set(f.columns) == {"AAPL", "MSFT", "GOOGL"}
    assert "SPY" not in f.columns
    assert "QQQ" not in f.columns
