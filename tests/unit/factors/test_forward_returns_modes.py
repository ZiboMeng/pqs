"""Unit tests for compute_forward_returns mode extension (PRD 20260423 R04)."""
from __future__ import annotations

import pandas as pd
import pytest

from core.factors.factor_generator import compute_forward_returns


@pytest.fixture
def ohlc_panel():
    """10-bar × 2-symbol panel with distinct open/close series.

    A: close trends up steadily, open lags close by 0.5 each bar.
    B: close flat, open = close-1 (gap-down every day).
    """
    idx = pd.bdate_range("2024-01-02", periods=10)
    close = pd.DataFrame({
        "A": [100.0, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        "B": [50.0] * 10,
    }, index=idx)
    open_ = pd.DataFrame({
        "A": [99.5, 100.5, 101.5, 102.5, 103.5,
              104.5, 105.5, 106.5, 107.5, 108.5],
        "B": [49.0] * 10,
    }, index=idx)
    return {"close": close, "open": open_}


# ── cc mode (backward-compat) ─────────────────────────────────────────────────

def test_cc_default_mode_matches_old_behavior(ohlc_panel):
    """Default mode = 'cc', signature unchanged."""
    fwd = compute_forward_returns(ohlc_panel["close"], [5])
    # result[5].loc[bar 0] = close[5] / close[0] - 1 = 105/100 - 1 = 0.05
    assert fwd[5].iloc[0, 0] == pytest.approx(0.05)


def test_cc_explicit_mode_same_as_default(ohlc_panel):
    fwd_default = compute_forward_returns(ohlc_panel["close"], [3])
    fwd_cc = compute_forward_returns(ohlc_panel["close"], [3], mode="cc")
    pd.testing.assert_frame_equal(fwd_default[3], fwd_cc[3])


def test_cc_last_h_bars_are_nan(ohlc_panel):
    """Forward return at bar T requires close[T+h]; last h bars NaN."""
    fwd = compute_forward_returns(ohlc_panel["close"], [3])[3]
    assert fwd.iloc[-3:].isna().all().all()


# ── oc mode ───────────────────────────────────────────────────────────────────

def test_oc_mode_requires_open_df(ohlc_panel):
    with pytest.raises(ValueError, match="requires open_df"):
        compute_forward_returns(ohlc_panel["close"], [1], mode="oc")


def test_oc_mode_value(ohlc_panel):
    """result[h].loc[t] = close[t+h] / open[t+h] - 1"""
    fwd = compute_forward_returns(
        ohlc_panel["close"], [1], mode="oc", open_df=ohlc_panel["open"],
    )
    # At bar 0, h=1 → close[1]/open[1] - 1 = 101/100.5 - 1 ≈ 0.00498
    assert fwd[1].iloc[0, 0] == pytest.approx(101/100.5 - 1, abs=1e-6)
    # B: close[1]/open[1] - 1 = 50/49 - 1 ≈ 0.02041
    assert fwd[1].iloc[0, 1] == pytest.approx(50/49 - 1, abs=1e-6)


def test_oc_mode_last_h_nan(ohlc_panel):
    fwd = compute_forward_returns(
        ohlc_panel["close"], [2], mode="oc", open_df=ohlc_panel["open"],
    )
    assert fwd[2].iloc[-2:].isna().all().all()


# ── oo mode ───────────────────────────────────────────────────────────────────

def test_oo_mode_requires_open_df(ohlc_panel):
    with pytest.raises(ValueError, match="requires open_df"):
        compute_forward_returns(ohlc_panel["close"], [1], mode="oo")


def test_oo_mode_value(ohlc_panel):
    """result[h].loc[t] = open[t+h] / open[t] - 1"""
    fwd = compute_forward_returns(
        ohlc_panel["close"], [1], mode="oo", open_df=ohlc_panel["open"],
    )
    # At bar 0, h=1 → open[1]/open[0] - 1 = 100.5/99.5 - 1 ≈ 0.01005
    assert fwd[1].iloc[0, 0] == pytest.approx(100.5/99.5 - 1, abs=1e-6)
    # B is flat open → 49/49 - 1 = 0
    assert fwd[1].iloc[0, 1] == pytest.approx(0.0, abs=1e-12)


def test_oo_mode_preserves_shape(ohlc_panel):
    fwd = compute_forward_returns(
        ohlc_panel["close"], [2, 5], mode="oo", open_df=ohlc_panel["open"],
    )
    assert set(fwd.keys()) == {2, 5}
    assert fwd[2].shape == ohlc_panel["close"].shape
    assert fwd[5].shape == ohlc_panel["close"].shape


# ── Validation ────────────────────────────────────────────────────────────────

def test_invalid_mode_rejected(ohlc_panel):
    with pytest.raises(ValueError, match="mode must be one of"):
        compute_forward_returns(ohlc_panel["close"], [1], mode="cx")


def test_zero_horizon_rejected(ohlc_panel):
    with pytest.raises(ValueError, match=">= 1"):
        compute_forward_returns(ohlc_panel["close"], [0])
