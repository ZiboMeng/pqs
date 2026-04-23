"""Unit tests for PRD 20260424 Family B position/breakout factors."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_generator import (
    generate_all_factors,
    _family_b_position_breakout,
)


@pytest.fixture
def rising_panel():
    """Strictly increasing close: 100, 101, ..., 359 (260 bars)."""
    idx = pd.bdate_range("2023-01-02", periods=260)
    price = pd.Series(range(100, 360), index=idx, dtype=float)
    return pd.DataFrame({"A": price.values}, index=idx)


@pytest.fixture
def peak_then_drop_panel():
    """Rises to peak at bar 150, then monotonic drop. 260 bars."""
    idx = pd.bdate_range("2023-01-02", periods=260)
    rising = np.arange(100, 250, dtype=float)        # 100 to 249 over 150 bars
    falling = np.arange(249, 139, -1, dtype=float)   # 249 to 140 over 110 bars
    price = np.concatenate([rising, falling])
    return pd.DataFrame({"A": price}, index=idx)


# ── range_pos_252d ────────────────────────────────────────────────────────────

def test_range_pos_252d_strictly_rising_hits_1(rising_panel):
    """Strictly-up series: every new-high bar has range_pos = 1.0."""
    factors = _family_b_position_breakout(rising_panel)
    f = factors["range_pos_252d"]
    # After warmup (min_periods=60), monotonic rising → always at top of range
    valid = f["A"].iloc[60:].dropna()
    assert np.allclose(valid.values, 1.0, atol=1e-12)


def test_range_pos_252d_peak_then_drop(peak_then_drop_panel):
    """After peak, range_pos decreases below 1.0."""
    factors = _family_b_position_breakout(peak_then_drop_panel)
    f = factors["range_pos_252d"]
    # At peak (bar 149 = last rising bar), range_pos = 1.0
    assert f["A"].iloc[149] == pytest.approx(1.0, abs=1e-12)
    # After drop, should be < 1
    assert f["A"].iloc[200] < 1.0
    assert f["A"].iloc[-1] < 0.5


def test_range_pos_252d_in_unit_interval(peak_then_drop_panel):
    factors = _family_b_position_breakout(peak_then_drop_panel)
    f = factors["range_pos_252d"]
    valid = f["A"].dropna()
    assert valid.min() >= -1e-12  # allow float noise
    assert valid.max() <= 1 + 1e-12


# ── days_since_52w_high ───────────────────────────────────────────────────────

def test_days_since_52w_high_new_high_is_zero(rising_panel):
    """Strictly rising → every bar is a new high → days_since = 0."""
    factors = _family_b_position_breakout(rising_panel)
    f = factors["days_since_52w_high"]
    valid = f["A"].iloc[60:].dropna()
    assert np.allclose(valid.values, 0.0, atol=1e-12)


def test_days_since_52w_high_counts_days_after_peak(peak_then_drop_panel):
    """After peak at bar 149, days_since should equal bars since peak."""
    factors = _family_b_position_breakout(peak_then_drop_panel)
    f = factors["days_since_52w_high"]
    # At bar 149 (peak): days_since = 0
    assert f["A"].iloc[149] == pytest.approx(0.0, abs=1e-12)
    # At bar 159: 10 days since peak
    assert f["A"].iloc[159] == pytest.approx(10.0, abs=1e-12)
    # At bar 200: 51 days since peak
    assert f["A"].iloc[200] == pytest.approx(51.0, abs=1e-12)


# ── breakout_20d_strength ─────────────────────────────────────────────────────

def test_breakout_20d_strength_rising_is_positive(rising_panel):
    """Rising series closes above prior 20d max every bar → positive breakout."""
    factors = _family_b_position_breakout(rising_panel)
    f = factors["breakout_20d_strength"]
    valid = f["A"].iloc[30:].dropna()
    # Every bar exceeds prior 20d max → all positive
    assert (valid > 0).all()


def test_breakout_20d_strength_flat_is_zero(rising_panel):
    """Constant close → close equals prior 20d max → breakout = 0."""
    flat = pd.DataFrame(
        {"A": [100.0] * 100},
        index=pd.bdate_range("2024-01-01", periods=100),
    )
    factors = _family_b_position_breakout(flat)
    f = factors["breakout_20d_strength"]
    valid = f["A"].iloc[25:].dropna()
    assert np.allclose(valid.values, 0.0, atol=1e-12)


# ── dist_from_new_high_252 ────────────────────────────────────────────────────

def test_dist_from_new_high_252_rising_is_positive(rising_panel):
    """Rising series: every bar exceeds prior 252d max → positive."""
    factors = _family_b_position_breakout(rising_panel)
    f = factors["dist_from_new_high_252"]
    # Need > 60 bars warmup (min_periods=60 on 252d rolling)
    valid = f["A"].iloc[65:].dropna()
    assert (valid > 0).all()


def test_dist_from_new_high_252_after_drawdown_is_negative(peak_then_drop_panel):
    """After peak + drop, close < prior max → negative."""
    factors = _family_b_position_breakout(peak_then_drop_panel)
    f = factors["dist_from_new_high_252"]
    # Bar 250 (deep into drawdown)
    assert f["A"].iloc[250] < 0


# ── End-to-end ────────────────────────────────────────────────────────────────

def test_generate_all_factors_produces_family_b():
    np.random.seed(7)
    idx = pd.bdate_range("2023-01-02", periods=400)
    panel = pd.DataFrame(
        100 + np.cumsum(np.random.randn(400, 3) * 0.5, axis=0),
        index=idx, columns=["AAPL", "MSFT", "NVDA"],
    )
    factors = generate_all_factors(panel)
    for name in ("range_pos_252d", "days_since_52w_high",
                 "breakout_20d_strength", "dist_from_new_high_252"):
        assert name in factors, f"{name} missing"
        assert factors[name].shape == panel.shape


def test_family_b_shapes_match_input(peak_then_drop_panel):
    """All 4 features preserve panel shape."""
    factors = _family_b_position_breakout(peak_then_drop_panel)
    for name in ("range_pos_252d", "days_since_52w_high",
                 "breakout_20d_strength", "dist_from_new_high_252"):
        assert factors[name].shape == peak_then_drop_panel.shape
