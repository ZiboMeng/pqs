"""Unit tests for core/factors/base_relative.py (PRD 20260423 Step 1 R03)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.base_relative import dist_from_rolling_max, relative_return


@pytest.fixture
def trend_panel():
    """10-bar × 3-symbol close panel: A strictly up, B up-then-down,
    C flat. SPY included to serve as benchmark."""
    idx = pd.bdate_range("2024-01-02", periods=10)
    return pd.DataFrame({
        "SPY": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        "A":   [100, 102, 104, 106, 108, 110, 112, 114, 116, 118],
        "B":   [100, 103, 106, 108, 106, 104, 102, 101, 100,  99],
        "C":   [100, 100, 100, 100, 100, 100, 100, 100, 100, 100],
    }, index=idx, dtype=float)


# ── dist_from_rolling_max ─────────────────────────────────────────────────────

def test_dist_from_rolling_max_nonpositive(trend_panel):
    """Output must be ≤ 0 everywhere (close can't exceed its own max)."""
    d = dist_from_rolling_max(trend_panel, window=5)
    valid = d.dropna()
    assert (valid.values <= 1e-12).all()


def test_dist_from_rolling_max_zero_at_new_high(trend_panel):
    """A strictly rises → every bar IS the rolling max → dist == 0."""
    d = dist_from_rolling_max(trend_panel, window=5)
    valid_A = d["A"].dropna()
    assert np.allclose(valid_A.values, 0.0, atol=1e-12)


def test_dist_from_rolling_max_negative_below_peak(trend_panel):
    """B peaks at bar 3 (108) then falls; after the peak dist < 0."""
    d = dist_from_rolling_max(trend_panel, window=5)
    # Bar 9 B=99, rolling 5d max from bars 5-9 = max(104,102,101,100,99)=104
    # dist = 99/104 - 1 ≈ -0.04808
    assert d["B"].iloc[9] == pytest.approx(99/104 - 1, abs=1e-6)


def test_dist_from_rolling_max_window_default_252():
    """Default window is 252 per PRD §D4."""
    np.random.seed(0)
    idx = pd.bdate_range("2020-01-01", periods=300)
    price = pd.DataFrame(
        100 + np.cumsum(np.random.randn(300, 2) * 0.5, axis=0),
        index=idx, columns=["A", "B"],
    )
    d = dist_from_rolling_max(price)
    # Last bar uses the full 252d window; verify value matches manual calc
    expected = price.iloc[-1] / price.iloc[-252:].max() - 1.0
    assert np.allclose(d.iloc[-1].values, expected.values, atol=1e-12)


def test_dist_from_rolling_max_zero_window_rejected(trend_panel):
    with pytest.raises(ValueError):
        dist_from_rolling_max(trend_panel, window=0)


# ── relative_return ───────────────────────────────────────────────────────────

def test_relative_return_benchmark_column_is_zero(trend_panel):
    """Benchmark's own column: stock_ret - bench_ret = 0."""
    r = relative_return(trend_panel, "SPY", lookback=3)
    valid = r["SPY"].dropna()
    assert np.allclose(valid.values, 0.0, atol=1e-12)


def test_relative_return_strong_stock_beats_benchmark(trend_panel):
    """A rises 2/bar, SPY rises 1/bar → A's 3d rel-ret > 0."""
    r = relative_return(trend_panel, "SPY", lookback=3)
    valid_A = r["A"].dropna()
    # A 3d ret at bar 3: 106/100 - 1 = 0.06; SPY: 103/100 - 1 = 0.03; diff 0.03
    assert r["A"].iloc[3] == pytest.approx(0.06 - 0.03, abs=1e-10)


def test_relative_return_weak_stock_below_benchmark(trend_panel):
    """B falls after peak while SPY keeps rising → B rel-ret < 0 in tail."""
    r = relative_return(trend_panel, "SPY", lookback=5)
    # At bar 9 with lookback=5, prev reference is iloc[9-5]=iloc[4]:
    # B: 99/106 - 1 ≈ -0.0660; SPY: 109/104 - 1 ≈ 0.0481; diff ≈ -0.1141
    expected = (99/106 - 1) - (109/104 - 1)
    assert r["B"].iloc[9] == pytest.approx(expected, abs=1e-6)
    assert r["B"].iloc[9] < 0


def test_relative_return_missing_benchmark_rejected(trend_panel):
    with pytest.raises(KeyError):
        relative_return(trend_panel, "DOES_NOT_EXIST", lookback=5)


def test_relative_return_zero_lookback_rejected(trend_panel):
    with pytest.raises(ValueError):
        relative_return(trend_panel, "SPY", lookback=0)
