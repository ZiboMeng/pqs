"""Tests for S/R swing factor family (factor_generator._sr_swing_factors).

PRD 20260505 Step 2. The registry drift test (test_factor_registry.py)
ensures the names match RESEARCH_FACTORS; this file covers the actual
numerical behavior.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_generator import _sr_swing_factors, generate_all_factors
from core.factors.factor_registry import RESEARCH_FACTORS


_SR_FACTOR_NAMES = (
    "dist_to_swing_high_20d",
    "dist_to_swing_low_20d",
    "sr_range_compression_20d",
)


def _make_panels_with_real_swings(n_days: int = 60, seed: int = 0):
    """Build (price_df, high_df, low_df) panels where each symbol has a
    visible saw-tooth pattern guaranteed to produce swing highs/lows.

    Saw-tooth: every 7 days, a clear local extremum.
    """
    np.random.seed(seed)
    syms = ["AAA", "BBB", "CCC"]
    idx = pd.bdate_range("2024-01-02", periods=n_days)

    base = 100.0
    closes = []
    highs = []
    lows = []
    for i in range(n_days):
        # Saw-tooth: peak at i % 7 == 3, trough at i % 7 == 0
        offset = 0.0
        if i % 7 == 3:
            offset = 5.0  # local high
        elif i % 7 == 0:
            offset = -5.0  # local low
        c = base + offset + np.random.normal(0, 0.3)
        h = c + abs(np.random.normal(0, 0.5)) + (3.0 if i % 7 == 3 else 0.5)
        low_v = c - abs(np.random.normal(0, 0.5)) - (3.0 if i % 7 == 0 else 0.5)
        closes.append([c + np.random.normal(0, 0.5) for _ in syms])
        highs.append([h + np.random.normal(0, 0.5) for _ in syms])
        lows.append([low_v + np.random.normal(0, 0.5) for _ in syms])

    price_df = pd.DataFrame(closes, index=idx, columns=syms)
    high_df = pd.DataFrame(highs, index=idx, columns=syms)
    low_df = pd.DataFrame(lows, index=idx, columns=syms)
    # Enforce high >= close >= low
    high_df = pd.concat([high_df, price_df]).groupby(level=0).max()
    low_df = pd.concat([low_df, price_df]).groupby(level=0).min()
    return price_df, high_df, low_df


def test_sr_swing_factors_returns_three_factor_names():
    price, high, low = _make_panels_with_real_swings()
    out = _sr_swing_factors(price, high, low, n=2, lookback=20)
    assert set(out.keys()) == set(_SR_FACTOR_NAMES)


def test_sr_swing_factors_produce_non_nan_when_swings_present():
    """With saw-tooth bars + 20-bar lookback, late dates should have
    defined R and S → non-NaN factor values."""
    price, high, low = _make_panels_with_real_swings(n_days=60)
    out = _sr_swing_factors(price, high, low, n=2, lookback=20)
    # Last 20 dates of each factor should have at least some non-NaN
    for name in _SR_FACTOR_NAMES:
        df = out[name]
        assert df.shape == price.shape
        late_finite = df.tail(20).notna().sum().sum()
        assert late_finite > 0, f"{name} all-NaN in tail; saw-tooth should produce values"


def test_sr_swing_factors_non_negative_when_defined():
    """Distance metrics + range compression are all non-negative when defined
    (by construction: |dist_R| = (R - close)/close where R > close)."""
    price, high, low = _make_panels_with_real_swings()
    out = _sr_swing_factors(price, high, low, n=2, lookback=20)
    for name in _SR_FACTOR_NAMES:
        df = out[name]
        finite = df[df.notna()]
        if finite.shape[0] > 0:
            assert (df.dropna(how="all").stack() >= 0).all(), (
                f"{name} contains negative values: "
                f"min={df.dropna(how='all').stack().min()}"
            )


def test_sr_swing_factors_omitted_when_high_low_missing():
    """CONDITIONAL: if high_df or low_df is None, return empty dict."""
    price, _high, _low = _make_panels_with_real_swings()
    assert _sr_swing_factors(price, None, None) == {}
    assert _sr_swing_factors(price, _high, None) == {}
    assert _sr_swing_factors(price, None, _low) == {}


def test_sr_swing_factors_in_research_registry():
    """Three names registered in RESEARCH_FACTORS (drift guard pre-check)."""
    for name in _SR_FACTOR_NAMES:
        assert name in RESEARCH_FACTORS, (
            f"{name} missing from RESEARCH_FACTORS — registry drift"
        )


def test_sr_swing_factors_via_generate_all_factors():
    """End-to-end: generate_all_factors with H/L panels emits the 3 factors."""
    np.random.seed(42)
    idx = pd.bdate_range("2024-01-01", periods=100)
    syms = ["SPY", "AAPL", "MSFT"]
    price = pd.DataFrame(
        100 + np.cumsum(np.random.randn(100, 3) * 0.5, axis=0),
        index=idx, columns=syms,
    )
    # Add intentional swing patterns to make detection meaningful
    for s in syms:
        for i in range(7, 100, 14):
            price.iloc[i, syms.index(s)] += 5  # peak
        for i in range(14, 100, 14):
            price.iloc[i, syms.index(s)] -= 5  # trough
    high = price * 1.01
    low = price * 0.99
    # Re-enforce high >= close >= low after the spike injection
    high = pd.concat([high, price]).groupby(level=0).max()
    low = pd.concat([low, price]).groupby(level=0).min()

    factors = generate_all_factors(
        price, volume_df=None, high_df=high, low_df=low,
    )
    for name in _SR_FACTOR_NAMES:
        assert name in factors, f"{name} missing from generate_all_factors output"
        assert factors[name].shape == price.shape


def test_sr_swing_factors_omitted_in_generate_all_when_no_hl():
    """generate_all_factors without H/L → S/R factors NOT in output."""
    np.random.seed(0)
    idx = pd.bdate_range("2024-01-01", periods=50)
    syms = ["SPY", "AAPL"]
    price = pd.DataFrame(
        100 + np.random.randn(50, 2).cumsum(axis=0),
        index=idx, columns=syms,
    )
    factors = generate_all_factors(price, volume_df=None)
    for name in _SR_FACTOR_NAMES:
        assert name not in factors, f"{name} unexpectedly present without H/L"


def test_sr_swing_factors_short_history_returns_nan_panels():
    """Insufficient bars (< 2n+1 = 5) → NaN panels (no detection possible)."""
    idx = pd.bdate_range("2024-01-01", periods=4)
    price = pd.DataFrame({"AAA": [100, 101, 100.5, 101]}, index=idx)
    high = price * 1.01
    low = price * 0.99
    out = _sr_swing_factors(price, high, low, n=2, lookback=10)
    for name in _SR_FACTOR_NAMES:
        assert out[name].isna().all().all(), f"{name} should be all-NaN with only 4 bars"
