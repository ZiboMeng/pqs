"""Tests for swing-extrema-based S/R detection (core/intraday/sr_swing.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.intraday.sr_swing import (
    SwingConfig,
    compute_nearest_sr,
    detect_swing_extrema,
    distance_to_sr,
)


def _make_bars(
    highs: list[float],
    lows: list[float],
    closes: list[float] | None = None,
) -> pd.DataFrame:
    """Build a synthetic OHLC frame with auto-incrementing date index."""
    if closes is None:
        closes = [(h + l) / 2.0 for h, l in zip(highs, lows)]
    n = len(highs)
    idx = pd.bdate_range("2026-01-02", periods=n)
    return pd.DataFrame(
        {
            "high": highs,
            "low": lows,
            "close": closes,
            "open": closes,
            "volume": [1_000_000.0] * n,
        },
        index=idx,
    )


# ── detect_swing_extrema ─────────────────────────────────────────


def test_detect_swing_extrema_basic_peak_and_trough():
    """A clean V-shape around a peak should mark the peak as swing high
    and the surrounding troughs as swing lows."""
    # Highs: 100, 101, 105, 102, 99, 100, 103
    # Lows:   95,  96,  99,  97, 92,  93,  98
    bars = _make_bars(
        highs=[100, 101, 105, 102, 99, 100, 103],
        lows=[95, 96, 99, 97, 92, 93, 98],
    )
    result = detect_swing_extrema(bars, n=2)
    # Index 2 (high=105) is strict max over [0,1] and [3,4] → swing high.
    assert result.iloc[2]["is_swing_high"]
    # Index 4 (low=92) is strict min over [2,3] and [5,6] → swing low.
    assert result.iloc[4]["is_swing_low"]
    # Edge bars cannot be swing extrema with n=2 (need 2 bars on each side)
    assert not result.iloc[0]["is_swing_high"]
    assert not result.iloc[0]["is_swing_low"]
    assert not result.iloc[-1]["is_swing_high"]
    assert not result.iloc[-1]["is_swing_low"]


def test_detect_swing_extrema_strict_inequality():
    """Flat-top with equal highs must NOT register as swing high (strict >)."""
    # Highs: 100, 105, 105, 105, 100  — middle 105 ties with neighbors
    bars = _make_bars(
        highs=[100, 105, 105, 105, 100],
        lows=[95, 100, 100, 100, 95],
    )
    result = detect_swing_extrema(bars, n=1)
    # None of the 105s are strict-greater than their neighbors.
    assert not result["is_swing_high"].any()


def test_detect_swing_extrema_n_window_size():
    """Larger n requires the extremum to dominate a wider window."""
    # Local 105 at index 3, but with n=3 we need it strictly > [0,1,2,4,5,6]
    bars = _make_bars(
        highs=[100, 101, 102, 105, 102, 101, 100],
        lows=[95, 96, 97, 100, 97, 96, 95],
    )
    r1 = detect_swing_extrema(bars, n=1)
    r3 = detect_swing_extrema(bars, n=3)
    # n=1: index 3 high=105 vs neighbors [102, 102] → swing high
    assert r1.iloc[3]["is_swing_high"]
    # n=3: index 3 vs [100,101,102,102,101,100] → still strict max → swing high
    assert r3.iloc[3]["is_swing_high"]
    # But index 1 (high=101): with n=3 the window extends to index 4 (high=102)
    # so 101 < 102 → not a swing high
    assert not r3.iloc[1]["is_swing_high"]


def test_detect_swing_extrema_short_input():
    """Input shorter than 2n+1 gets no swing extrema (insufficient window)."""
    bars = _make_bars(highs=[100, 101], lows=[95, 96])
    result = detect_swing_extrema(bars, n=2)  # need 5 bars, have 2
    assert not result["is_swing_high"].any()
    assert not result["is_swing_low"].any()


def test_detect_swing_extrema_nan_handling():
    """NaN in window invalidates extremum detection (cannot prove strict)."""
    bars = _make_bars(
        highs=[100, np.nan, 105, 102, 99, 100, 103],
        lows=[95, 96, 99, 97, 92, 93, 98],
    )
    result = detect_swing_extrema(bars, n=2)
    # Index 2 has NaN at index 1 in its left window → cannot confirm swing high
    assert not result.iloc[2]["is_swing_high"]


def test_detect_swing_extrema_validation():
    bars = _make_bars(highs=[100, 101], lows=[95, 96])
    with pytest.raises(ValueError):
        detect_swing_extrema(bars, n=0)
    with pytest.raises(ValueError):
        detect_swing_extrema(pd.DataFrame({"close": [1, 2]}), n=2)


# ── compute_nearest_sr ───────────────────────────────────────────


def test_compute_nearest_sr_picks_closest_in_price():
    """Multiple historical swings → pick the one closest in price to current."""
    # Build: swing high 110 at idx=3 (confirmed at idx=5);
    #        swing high 108 at idx=8 (confirmed at idx=10);
    #        current close at idx=12 = 100. Both are above 100;
    #        108 is closer (8) than 110 (10) → resistance = 108.
    highs = [102, 103, 104, 110, 105, 104, 105, 106, 108, 105, 102, 101, 100]
    lows = [96, 97, 98, 100, 95, 94, 95, 96, 100, 96, 95, 94, 95]
    closes = [100] * 13
    closes[12] = 100
    bars = _make_bars(highs=highs, lows=lows, closes=closes)
    sr = compute_nearest_sr(bars, n=2, lookback=15)
    assert sr.iloc[12]["resistance"] == 108
    assert sr.iloc[12]["resistance_lag_bars"] == 4


def test_compute_nearest_sr_no_qualifying_extremum_returns_nan():
    """If all swing highs in lookback are BELOW current close → R = NaN."""
    # Construct: swings exist below current close, current close above all.
    highs = [98, 99, 100, 105, 100, 99, 98, 97]
    lows = [90, 91, 92, 98, 92, 91, 90, 89]
    closes = [110] * 8
    bars = _make_bars(highs=highs, lows=lows, closes=closes)
    sr = compute_nearest_sr(bars, n=2, lookback=10)
    # No high in lookback exceeds 110 → resistance = NaN at last bar
    assert pd.isna(sr.iloc[-1]["resistance"])


def test_compute_nearest_sr_lookback_bounds_search():
    """Swings outside the lookback window must be ignored."""
    # 30 bars long with one big swing at idx=5 that's above current close,
    # and a smaller swing at idx=20 that's also above. With lookback=10, the
    # idx=5 swing is out of scope at idx=29.
    highs = [100] * 30
    lows = [95] * 30
    highs[5] = 130
    highs[20] = 115
    closes = [110] * 30
    bars = _make_bars(highs=highs, lows=lows, closes=closes)
    sr = compute_nearest_sr(bars, n=2, lookback=10)
    # At idx=29, lookback covers [19, 27); idx=20 swing high (115) qualifies.
    # idx=5 swing is far out of scope.
    assert sr.iloc[29]["resistance"] == 115


def test_compute_nearest_sr_confirmation_lag():
    """A swing at index i is only available from i+n onward (need n future
    bars to confirm strict extremum)."""
    highs = [100, 101, 110, 102, 100, 99]
    lows = [95, 96, 100, 97, 95, 94]
    closes = [100] * 6
    bars = _make_bars(highs=highs, lows=lows, closes=closes)
    # n=2: swing at idx=2 confirmed only at idx=4. At idx=3 it's not yet
    # available. With lookback=5, R should still be NaN at idx=3.
    sr = compute_nearest_sr(bars, n=2, lookback=10)
    assert pd.isna(sr.iloc[3]["resistance"])  # not yet confirmed
    # By idx=5, the swing high at idx=2 is confirmed and visible.
    assert sr.iloc[5]["resistance"] == 110


# ── distance_to_sr ───────────────────────────────────────────────


def test_distance_to_sr_signs_and_compression():
    """Signed % distances are non-negative when defined; sr_range_pct is
    R-S as % of close."""
    highs = [100, 105, 110, 105, 100, 95, 100]
    lows = [90, 95, 100, 95, 90, 85, 90]
    closes = [97] * 7
    bars = _make_bars(highs=highs, lows=lows, closes=closes)
    out = distance_to_sr(bars, n=2, lookback=10)
    last = out.iloc[-1]
    if pd.notna(last["resistance"]):
        # R - close should be positive (R is above close)
        assert last["resistance"] > 97
        assert last["dist_to_resistance_pct"] >= 0
    if pd.notna(last["support"]):
        # close - S should be positive (S is below close)
        assert last["support"] < 97
        assert last["dist_to_support_pct"] >= 0
    if pd.notna(last["sr_range_pct"]):
        assert last["sr_range_pct"] > 0


def test_distance_to_sr_round_trip_columns():
    """All expected columns present + index preserved."""
    bars = _make_bars(
        highs=[100, 102, 105, 103, 101] * 4,
        lows=[95, 97, 100, 98, 96] * 4,
    )
    out = distance_to_sr(bars, n=2, lookback=10)
    expected = {
        "dist_to_resistance_pct", "dist_to_support_pct", "sr_range_pct",
        "resistance", "support", "resistance_lag_bars", "support_lag_bars",
    }
    assert set(out.columns) == expected
    assert (out.index == bars.index).all()


def test_swing_config_defaults():
    """SwingConfig defaults match the function defaults."""
    cfg = SwingConfig()
    assert cfg.n_window == 5
    assert cfg.lookback == 20
    assert cfg.min_swing_separation_pct == 0.0


# ── monotonic invariant: distance is consistent with level vs close ──


def test_invariant_resistance_above_close_when_defined():
    """Whenever resistance is defined, it MUST be >= close (by construction)."""
    np.random.seed(42)
    highs = (100 + np.random.standard_normal(50).cumsum()).tolist()
    lows = [h - np.random.uniform(0.5, 2.0) for h in highs]
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    bars = _make_bars(highs=highs, lows=lows, closes=closes)
    out = distance_to_sr(bars, n=3, lookback=20)
    defined = out[out["resistance"].notna()]
    if not defined.empty:
        # resistance >= close by construction (we filter h > c)
        assert (defined["resistance"] >= bars.loc[defined.index, "close"]).all()
    defined_s = out[out["support"].notna()]
    if not defined_s.empty:
        assert (defined_s["support"] <= bars.loc[defined_s.index, "close"]).all()
