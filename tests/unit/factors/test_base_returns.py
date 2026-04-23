"""Unit tests for core/factors/base_returns.py (PRD 20260423 Step 1)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.base_returns import (
    simple_return,
    overnight_return_raw,
    intraday_return_raw,
)


@pytest.fixture
def close_df():
    """3-bar × 2-symbol close panel."""
    return pd.DataFrame(
        {"A": [100.0, 101.0, 103.0], "B": [50.0, 52.0, 51.0]},
        index=pd.bdate_range("2024-01-02", periods=3),
    )


@pytest.fixture
def open_df():
    """Open panel aligned to close_df (gap-up for A, flat for B)."""
    return pd.DataFrame(
        {"A": [99.5, 101.5, 102.0], "B": [50.0, 52.0, 50.5]},
        index=pd.bdate_range("2024-01-02", periods=3),
    )


# ── simple_return ─────────────────────────────────────────────────────────────

def test_simple_return_1d(close_df):
    r = simple_return(close_df, 1)
    assert np.isnan(r.iloc[0, 0])
    # A: 101/100 - 1 = 0.01
    assert r.iloc[1, 0] == pytest.approx(0.01)
    # B: 51/52 - 1 ≈ -0.01923
    assert r.iloc[2, 1] == pytest.approx(-0.01923, abs=1e-4)


def test_simple_return_2d(close_df):
    r = simple_return(close_df, 2)
    assert np.isnan(r.iloc[0, 0])
    assert np.isnan(r.iloc[1, 0])
    # A: 103/100 - 1 = 0.03
    assert r.iloc[2, 0] == pytest.approx(0.03)
    # B: 51/50 - 1 = 0.02
    assert r.iloc[2, 1] == pytest.approx(0.02)


def test_simple_return_zero_lookback_rejected(close_df):
    with pytest.raises(ValueError):
        simple_return(close_df, 0)


def test_simple_return_preserves_shape(close_df):
    r = simple_return(close_df, 1)
    assert r.shape == close_df.shape
    assert list(r.columns) == list(close_df.columns)


# ── overnight_return_raw ──────────────────────────────────────────────────────

def test_overnight_return_raw_first_bar_is_nan(open_df, close_df):
    ovn = overnight_return_raw(open_df, close_df)
    # First bar has no prior close → NaN
    assert ovn.iloc[0].isna().all()


def test_overnight_return_raw_values(open_df, close_df):
    ovn = overnight_return_raw(open_df, close_df)
    # Day 2 A: open 101.5 / prev_close 100 - 1 = 0.015
    assert ovn.iloc[1, 0] == pytest.approx(0.015)
    # Day 3 A: open 102 / prev_close 101 - 1 ≈ 0.0099
    assert ovn.iloc[2, 0] == pytest.approx(0.009900, abs=1e-5)
    # Day 2 B: open 52 / prev_close 50 - 1 = 0.04
    assert ovn.iloc[1, 1] == pytest.approx(0.04)


# ── intraday_return_raw ───────────────────────────────────────────────────────

def test_intraday_return_raw_values(open_df, close_df):
    intra = intraday_return_raw(open_df, close_df)
    # Day 1 A: close 100 / open 99.5 - 1 ≈ 0.00503
    assert intra.iloc[0, 0] == pytest.approx(0.00503, abs=1e-4)
    # Day 2 A: close 101 / open 101.5 - 1 ≈ -0.00493
    assert intra.iloc[1, 0] == pytest.approx(-0.00493, abs=1e-4)
    # Day 3 B: close 51 / open 50.5 - 1 ≈ 0.00990
    assert intra.iloc[2, 1] == pytest.approx(0.00990, abs=1e-4)


def test_intraday_return_complements_overnight(open_df, close_df):
    """Over a single bar: (1+overnight)(1+intraday) = close[t]/close[t-1]."""
    ovn = overnight_return_raw(open_df, close_df)
    intra = intraday_return_raw(open_df, close_df)
    cc = simple_return(close_df, 1)
    # Day 2 check: (1 + overnight)(1 + intraday) ≈ close/prev_close
    combined = (1 + ovn) * (1 + intra) - 1
    # Drop leading-NaN rows, compare finite values only
    cc_finite = cc.dropna()
    combined_finite = combined.reindex_like(cc_finite)
    assert np.allclose(
        combined_finite.values, cc_finite.values, atol=1e-10
    )
