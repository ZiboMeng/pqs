"""Unit tests for PRD 20260424 Family C (liquidity/risk) + D (trend quality)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_generator import (
    generate_all_factors,
    _family_c_liquidity_risk,
    _family_d_trend_quality,
)


@pytest.fixture
def ohlcv_panel():
    """Synthetic 120-bar panel with 2 symbols + volume."""
    np.random.seed(11)
    idx = pd.bdate_range("2024-01-01", periods=120)
    price = pd.DataFrame({
        "A": 100 + np.cumsum(np.random.randn(120) * 0.5),
        "B": 50 + np.cumsum(np.random.randn(120) * 0.3),
    }, index=idx)
    volume = pd.DataFrame({
        "A": np.random.uniform(1e6, 5e6, 120),
        "B": np.random.uniform(5e5, 2e6, 120),
    }, index=idx)
    return {"price": price, "volume": volume}


# ── Family C: amihud_20d ──────────────────────────────────────────────────────

def test_amihud_20d_omitted_when_no_volume(ohlcv_panel):
    factors = _family_c_liquidity_risk(ohlcv_panel["price"], volume_df=None)
    assert "amihud_20d" not in factors
    # But the other 2 features still present
    assert "downside_vol_20d" in factors
    assert "vol_ratio_5_20" in factors


def test_amihud_20d_shape_and_sign(ohlcv_panel):
    factors = _family_c_liquidity_risk(
        ohlcv_panel["price"], volume_df=ohlcv_panel["volume"],
    )
    f = factors["amihud_20d"]
    assert f.shape == ohlcv_panel["price"].shape
    # Post-warmup values are non-negative (|ret|/$vol is non-negative)
    valid = f.iloc[15:].dropna()
    assert (valid.values >= 0).all()


def test_amihud_20d_low_volume_stock_higher(ohlcv_panel):
    """Stock B has lower volume → should have higher amihud (less liquid)."""
    factors = _family_c_liquidity_risk(
        ohlcv_panel["price"], volume_df=ohlcv_panel["volume"],
    )
    f = factors["amihud_20d"]
    # Compare tail means (post warmup)
    mean_a = f["A"].iloc[-50:].mean()
    mean_b = f["B"].iloc[-50:].mean()
    # Lower-volume stock B should have higher Amihud (less liquid per $)
    # B is ~50 * 1M = 50M $vol; A is 100 * 3M = 300M $vol
    # Same return volatility → B's amihud ~ 6x A's
    assert mean_b > mean_a


# ── Family C: downside_vol_20d ────────────────────────────────────────────────

def test_downside_vol_20d_shape(ohlcv_panel):
    factors = _family_c_liquidity_risk(
        ohlcv_panel["price"], volume_df=ohlcv_panel["volume"],
    )
    f = factors["downside_vol_20d"]
    assert f.shape == ohlcv_panel["price"].shape


def test_downside_vol_20d_below_total_vol(ohlcv_panel):
    """Downside-only std ≤ total std (fewer observations AND only neg side)."""
    factors = _family_c_liquidity_risk(
        ohlcv_panel["price"], volume_df=ohlcv_panel["volume"],
    )
    downside = factors["downside_vol_20d"]
    daily_ret = ohlcv_panel["price"].pct_change()
    total_std = daily_ret.rolling(20, min_periods=10).std()
    # At any valid date, downside_vol ≤ total_vol (strictly less-than-or-equal)
    valid_dates = downside.dropna().index.intersection(total_std.dropna().index)
    for d in valid_dates[-30:]:  # sample last 30
        for col in downside.columns:
            if pd.notna(downside.loc[d, col]) and pd.notna(total_std.loc[d, col]):
                assert downside.loc[d, col] <= total_std.loc[d, col] + 1e-10


def test_downside_vol_20d_all_positive_returns_gives_nan():
    """Constant-up panel: no negative returns → downside_vol should be NaN."""
    idx = pd.bdate_range("2024-01-01", periods=60)
    # Strictly rising: every daily return positive
    price = pd.DataFrame({"A": np.arange(100, 160, dtype=float)}, index=idx)
    factors = _family_c_liquidity_risk(price, volume_df=None)
    f = factors["downside_vol_20d"]
    # With no negative returns ever, rolling std of masked series is NaN
    # (min_periods=5 means at least 5 negative obs needed)
    valid = f["A"].dropna()
    # Either all NaN or all very small (if some diff noise gives neg)
    assert len(valid) == 0 or valid.max() < 0.01


# ── Family C: vol_ratio_5_20 ──────────────────────────────────────────────────

def test_vol_ratio_5_20_around_1_for_random(ohlcv_panel):
    """For iid random returns, 5d/20d vol ratio should fluctuate around 1."""
    factors = _family_c_liquidity_risk(
        ohlcv_panel["price"], volume_df=None,
    )
    f = factors["vol_ratio_5_20"]
    valid = f.iloc[25:].dropna()
    # Expect median around 1 for iid Gaussian returns
    assert 0.7 < valid.median().median() < 1.4


def test_vol_ratio_5_20_compression_detection():
    """Designed panel: low vol final 5 bars → ratio < 1 at end."""
    np.random.seed(42)
    idx = pd.bdate_range("2024-01-01", periods=60)
    # First 50 bars: normal vol; last 10 bars: vol compressed 10x smaller
    rets = np.concatenate([
        np.random.normal(0, 0.02, 50),    # 2% daily std
        np.random.normal(0, 0.002, 10),   # 0.2% daily std
    ])
    price = pd.Series(100 * np.exp(np.cumsum(rets)), index=idx)
    panel = pd.DataFrame({"A": price})
    factors = _family_c_liquidity_risk(panel, volume_df=None)
    f = factors["vol_ratio_5_20"]
    # Last bar: 5d vol << 20d vol (includes high-vol bars)
    assert f["A"].iloc[-1] < 0.5


# ── Family D: trend_tstat_20d ─────────────────────────────────────────────────

def test_trend_tstat_20d_strictly_rising_gives_large_positive():
    """Monotonic rising log-close: tstat should be very large positive."""
    idx = pd.bdate_range("2024-01-01", periods=40)
    price = pd.DataFrame({
        "A": np.exp(np.arange(40) * 0.01),  # log-linear rising
    }, index=idx)
    factors = _family_d_trend_quality(price)
    f = factors["trend_tstat_20d"]
    # Linear log-close → residuals ~ 0 → tstat should be very large
    last = f["A"].iloc[-1]
    assert last > 50  # extreme tstat for clean trend


def test_trend_tstat_20d_flat_near_zero():
    """Flat close (no trend): tstat near 0 (or NaN)."""
    idx = pd.bdate_range("2024-01-01", periods=40)
    price = pd.DataFrame({"A": [100.0] * 40}, index=idx)
    factors = _family_d_trend_quality(price)
    f = factors["trend_tstat_20d"]
    valid = f["A"].iloc[20:].dropna()
    # log-close constant → residuals all 0 → tstat returns NaN (division by 0)
    # Either NaN or very small. Accept both.
    if len(valid) > 0:
        assert abs(valid).max() < 1e-6


def test_trend_tstat_20d_declining_gives_large_negative():
    """Monotonic declining log-close: tstat should be very large negative."""
    idx = pd.bdate_range("2024-01-01", periods=40)
    price = pd.DataFrame({
        "A": np.exp(-np.arange(40) * 0.01),  # log-linear declining
    }, index=idx)
    factors = _family_d_trend_quality(price)
    f = factors["trend_tstat_20d"]
    last = f["A"].iloc[-1]
    assert last < -50


def test_trend_tstat_20d_shape(ohlcv_panel):
    factors = _family_d_trend_quality(ohlcv_panel["price"])
    f = factors["trend_tstat_20d"]
    assert f.shape == ohlcv_panel["price"].shape


# ── End-to-end ────────────────────────────────────────────────────────────────

def test_generate_all_factors_produces_family_c_and_d(ohlcv_panel):
    factors = generate_all_factors(
        ohlcv_panel["price"], volume_df=ohlcv_panel["volume"],
    )
    for name in ("amihud_20d", "downside_vol_20d", "vol_ratio_5_20",
                 "trend_tstat_20d"):
        assert name in factors, f"{name} missing"


def test_generate_all_factors_amihud_omitted_no_volume(ohlcv_panel):
    """No volume_df → amihud_20d not in output (graceful)."""
    factors = generate_all_factors(ohlcv_panel["price"])
    assert "amihud_20d" not in factors
    # But other Family C + D features still present
    assert "downside_vol_20d" in factors
    assert "vol_ratio_5_20" in factors
    assert "trend_tstat_20d" in factors
