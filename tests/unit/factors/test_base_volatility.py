"""Unit tests for core/factors/base_volatility.py (PRD 20260423 Step 1 R02)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.base_volatility import hl_range, dollar_volume_ma


@pytest.fixture
def ohlcv_panel():
    """5-bar × 2-symbol OHLCV panel."""
    idx = pd.bdate_range("2024-01-02", periods=5)
    high = pd.DataFrame(
        {"A": [101, 103, 102, 105, 107], "B": [52, 54, 53, 55, 54]},
        index=idx, dtype=float,
    )
    low = pd.DataFrame(
        {"A": [99, 100, 99, 101, 103], "B": [50, 51, 51, 52, 51]},
        index=idx, dtype=float,
    )
    close = pd.DataFrame(
        {"A": [100, 102, 101, 104, 106], "B": [51, 53, 52, 54, 52]},
        index=idx, dtype=float,
    )
    volume = pd.DataFrame(
        {"A": [1_000_000] * 5, "B": [500_000] * 5},
        index=idx, dtype=float,
    )
    return {"high": high, "low": low, "close": close, "volume": volume}


# ── hl_range ──────────────────────────────────────────────────────────────────

def test_hl_range_normalized_first_bar_is_nan(ohlcv_panel):
    r = hl_range(ohlcv_panel["high"], ohlcv_panel["low"], ohlcv_panel["close"])
    # normalize=True divides by prev_close → first row NaN
    assert r.iloc[0].isna().all()


def test_hl_range_normalized_values(ohlcv_panel):
    r = hl_range(ohlcv_panel["high"], ohlcv_panel["low"], ohlcv_panel["close"])
    # Day 2 A: (103 - 100) / prev_close 100 = 0.03
    assert r.iloc[1, 0] == pytest.approx(0.03)
    # Day 5 B: (54 - 51) / prev_close 54 ≈ 0.0556
    assert r.iloc[4, 1] == pytest.approx(3.0 / 54.0, abs=1e-6)


def test_hl_range_unnormalized_returns_raw(ohlcv_panel):
    r = hl_range(
        ohlcv_panel["high"], ohlcv_panel["low"], ohlcv_panel["close"],
        normalize=False,
    )
    # Day 1 A: 101 - 99 = 2  (no NaN on first bar when not normalized)
    assert r.iloc[0, 0] == 2.0
    assert r.iloc[0, 1] == 2.0
    # No NaN first row when normalize=False
    assert not r.iloc[0].isna().any()


def test_hl_range_shape_preserved(ohlcv_panel):
    r = hl_range(ohlcv_panel["high"], ohlcv_panel["low"], ohlcv_panel["close"])
    assert r.shape == ohlcv_panel["high"].shape
    assert list(r.columns) == list(ohlcv_panel["high"].columns)


# ── dollar_volume_ma ──────────────────────────────────────────────────────────

def test_dollar_volume_ma_window_1_equals_close_times_volume(ohlcv_panel):
    r = dollar_volume_ma(
        ohlcv_panel["close"], ohlcv_panel["volume"], window=1,
    )
    expected = ohlcv_panel["close"] * ohlcv_panel["volume"]
    assert np.allclose(r.values, expected.values, equal_nan=True)


def test_dollar_volume_ma_window_3(ohlcv_panel):
    r = dollar_volume_ma(
        ohlcv_panel["close"], ohlcv_panel["volume"], window=3,
    )
    # Day 3 A (min_periods defaults to ceil(3/2)=1):
    # mean(close[0:3] * volume[0:3]) for A = mean(100e6, 102e6, 101e6) = 101e6
    assert r.iloc[2, 0] == pytest.approx(101_000_000.0)


def test_dollar_volume_ma_zero_window_rejected(ohlcv_panel):
    with pytest.raises(ValueError):
        dollar_volume_ma(ohlcv_panel["close"], ohlcv_panel["volume"], window=0)


def test_dollar_volume_ma_preserves_shape(ohlcv_panel):
    r = dollar_volume_ma(
        ohlcv_panel["close"], ohlcv_panel["volume"], window=3,
    )
    assert r.shape == ohlcv_panel["close"].shape
    assert list(r.columns) == list(ohlcv_panel["close"].columns)


# ── Alias behavior (PRD §D3 / §3.1.C) ────────────────────────────────────────

def test_aliases_present_in_generator_output():
    """vol_20d and volume_ratio_20d must be aliased to existing canonicals
    and appear in the generator's output dict when those canonicals are
    produced."""
    from core.factors.factor_generator import generate_all_factors
    idx = pd.bdate_range("2024-01-01", periods=150)
    np.random.seed(0)
    price = pd.DataFrame(
        100 + np.cumsum(np.random.randn(150, 3) * 0.5, axis=0),
        index=idx, columns=["SPY", "AAPL", "MSFT"],
    )
    volume = pd.DataFrame(
        np.random.uniform(1e6, 1e8, (150, 3)),
        index=idx, columns=["SPY", "AAPL", "MSFT"],
    )
    factors = generate_all_factors(price, volume)
    assert "vol_20d" in factors
    assert "vol_21d" in factors
    # Same DataFrame reference (no copy)
    assert factors["vol_20d"] is factors["vol_21d"]

    assert "volume_ratio_20d" in factors
    assert "volume_surge_20d" in factors
    assert factors["volume_ratio_20d"] is factors["volume_surge_20d"]
