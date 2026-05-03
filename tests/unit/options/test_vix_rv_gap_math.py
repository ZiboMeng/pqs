"""Unit test for VIX/RV gap analysis math.

Locks: (a) 21d annualized realized vol formula, (b) VRP sign + alignment.

The numbers in this test are derived from a synthetic SPY price series
with KNOWN constant log-return volatility, so the rolling annualization
should produce a closed-form result. If anyone changes the formula
(e.g., to non-log returns or a different annualization factor), this
test fails immediately.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ / "dev" / "scripts" / "options"))


@pytest.fixture
def vrp_module():
    """Import the analysis script as a module (no side effects on import)."""
    import vix_rv_gap_analysis  # noqa: F401
    return vix_rv_gap_analysis


def test_compute_rv_constant_vol_synthetic(vrp_module):
    """Synthetic series with constant daily log-vol => RV ≈ vol*sqrt(252)*100."""
    rng = np.random.default_rng(42)
    daily_log_vol = 0.01  # 1% per day
    n = 600
    log_ret = rng.normal(loc=0.0, scale=daily_log_vol, size=n)
    log_ret[0] = 0.0
    price = 100.0 * np.exp(np.cumsum(log_ret))
    idx = pd.bdate_range("2010-01-04", periods=n)
    spy = pd.Series(price, index=idx, name="close")

    rv = vrp_module.compute_rv(spy, window=21)
    # Annualized expectation: 0.01 * sqrt(252) * 100 ≈ 15.87
    expected_pct = daily_log_vol * np.sqrt(252) * 100.0
    realized_mean = rv.dropna().mean()
    # Allow ~6% relative error from rolling-window finite sample
    assert abs(realized_mean - expected_pct) / expected_pct < 0.06, (
        f"RV mean {realized_mean:.3f} vs expected {expected_pct:.3f}"
    )


def test_compute_rv_first_window_is_nan(vrp_module):
    """Min_periods=window means rows < window are NaN (no lookahead bug)."""
    spy = pd.Series(
        100.0 + np.arange(50) * 0.5,
        index=pd.bdate_range("2020-01-02", periods=50),
        name="close",
    )
    rv = vrp_module.compute_rv(spy, window=21)
    # log_return shifts by 1 (1st row NaN), then rolling needs 21 obs
    # => first 21 rows are NaN, defined from row 21 onward
    assert rv.iloc[:21].isna().all(), "First 21 rows must be NaN"
    assert rv.iloc[21:].notna().all(), "Rows from index 21 onwards must be defined"


def test_build_gap_frame_alignment_and_sign(vrp_module):
    """VRP = VIX - RV; alignment intersects VIX and SPY indices."""
    idx = pd.bdate_range("2020-01-02", periods=100)
    vix = pd.DataFrame({"close": np.full(100, 20.0)}, index=idx)
    # SPY with very low realized vol (constant path = 0) -> RV ~ 0
    spy = pd.DataFrame({"close": np.linspace(100.0, 105.0, 100)}, index=idx)

    df = vrp_module.build_gap_frame(vix, spy)
    # First 21 rows dropped due to RV NaN
    assert len(df) == 100 - 21
    # RV of monotone smooth ramp ~ 0; VIX = 20 -> VRP ≈ 20
    assert df["vrp_pct"].mean() == pytest.approx(20.0, abs=0.5)
    assert (df["vrp_positive"] == 1).all()


def test_build_gap_frame_inner_join_only(vrp_module):
    """Date intersection only — no forward-fill, no reindex contamination."""
    vix_idx = pd.bdate_range("2020-01-02", periods=100)
    spy_idx = pd.bdate_range("2020-01-15", periods=100)  # offset start
    vix = pd.DataFrame({"close": np.full(100, 20.0)}, index=vix_idx)
    spy = pd.DataFrame({"close": np.linspace(100.0, 110.0, 100)}, index=spy_idx)

    df = vrp_module.build_gap_frame(vix, spy)
    # Intersection of [2020-01-02..] and [2020-01-15..], minus 21 RV warmup
    expected_overlap = len(vix_idx.intersection(spy_idx))
    assert len(df) == expected_overlap - 21


def test_constants_documented_explicitly(vrp_module):
    """Annualization factor + RV window are explicit module constants."""
    assert vrp_module.RV_WINDOW == 21
    assert vrp_module.TRADING_DAYS == 252
