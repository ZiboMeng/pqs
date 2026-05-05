"""Tests for volume profile / POC computation
(core/intraday/sr_volume_profile.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.intraday.sr_volume_profile import (
    VolumeProfile,
    compute_daily_volume_profile,
    compute_session_volume_profile,
    position_within_value_area,
)


def _bars(closes: list[float], volumes: list[float],
          start: str = "2026-04-27 09:30") -> pd.DataFrame:
    """Build a 1m bar frame at 09:30 ET on a single day."""
    n = len(closes)
    idx = pd.date_range(start=start, periods=n, freq="1min")
    return pd.DataFrame(
        {"close": closes, "volume": volumes,
         "open": closes, "high": closes, "low": closes},
        index=idx,
    )


# ── compute_session_volume_profile ───────────────────────────────


def test_session_profile_single_price_concentrates_poc():
    """If 90% of volume is at $100, POC must be $100."""
    closes = [100.0] * 18 + [99.0, 101.0]
    volumes = [1000.0] * 18 + [50.0, 50.0]
    bars = _bars(closes, volumes)
    vp = compute_session_volume_profile(bars, bucket_size=0.5)
    assert vp is not None
    assert abs(vp.poc_price - 100.0) < 0.5  # within bucket of 100
    assert vp.total_volume == sum(volumes)


def test_session_profile_value_area_captures_target_pct():
    """Value area must capture at least value_area_pct of total volume."""
    np.random.seed(7)
    n = 200
    # Bell-curve-ish: more volume near the median
    closes = (100.0 + np.random.standard_normal(n).cumsum() * 0.05).tolist()
    volumes = np.random.uniform(500, 2000, n).tolist()
    bars = _bars(closes, volumes)
    vp = compute_session_volume_profile(bars, value_area_pct=0.70)
    assert vp is not None
    # Compute captured volume manually: sum volumes whose close is in [val, vah]
    in_va = [v for c, v in zip(closes, volumes) if vp.val <= c <= vp.vah]
    captured_pct = sum(in_va) / sum(volumes)
    # Must be >= 0.70 (we expand outward until target reached).
    assert captured_pct >= 0.69  # tiny slack for boundary buckets


def test_session_profile_vwap_weighted_by_volume():
    """VWAP = sum(close * volume) / sum(volume)."""
    closes = [99.0, 100.0, 101.0]
    volumes = [1000.0, 5000.0, 4000.0]
    expected_vwap = sum(c * v for c, v in zip(closes, volumes)) / sum(volumes)
    bars = _bars(closes, volumes)
    vp = compute_session_volume_profile(bars, bucket_size=1.0)
    assert vp is not None
    assert abs(vp.vwap - expected_vwap) < 1e-9


def test_session_profile_zero_volume_returns_none():
    """All-NaN or all-zero-volume → None."""
    bars = _bars([100.0, 100.0, 100.0], [0.0, 0.0, 0.0])
    assert compute_session_volume_profile(bars) is None


def test_session_profile_validation():
    bars = _bars([100.0], [1000.0])
    # Mutually exclusive bucket flags
    with pytest.raises(ValueError):
        compute_session_volume_profile(bars, bucket_size=1.0,
                                       bucket_size_pct_of_close=0.001)
    # Bad value_area_pct
    with pytest.raises(ValueError):
        compute_session_volume_profile(bars, value_area_pct=0.0)
    with pytest.raises(ValueError):
        compute_session_volume_profile(bars, value_area_pct=1.0)
    # Missing column
    bad = pd.DataFrame({"close": [100.0]})
    with pytest.raises(ValueError):
        compute_session_volume_profile(bad)


def test_session_profile_vah_above_val():
    """By construction VAH >= POC >= VAL."""
    np.random.seed(13)
    closes = (100.0 + np.random.uniform(-1, 1, 100)).tolist()
    volumes = np.random.uniform(500, 2000, 100).tolist()
    bars = _bars(closes, volumes)
    vp = compute_session_volume_profile(bars)
    assert vp is not None
    assert vp.val <= vp.poc_price <= vp.vah


# ── compute_daily_volume_profile ─────────────────────────────────


def test_daily_profile_one_session_one_row():
    """Single trading day → single row."""
    closes = [100.0, 101.0, 100.5, 100.0]
    volumes = [1000.0, 2000.0, 1500.0, 1000.0]
    bars = _bars(closes, volumes)
    daily = compute_daily_volume_profile(bars)
    assert len(daily) == 1
    assert daily.index[0].date() == pd.Timestamp("2026-04-27").date()


def test_daily_profile_multi_day():
    """Two distinct trading days → two rows."""
    day1 = _bars([100, 101, 100.5], [1000, 2000, 1500],
                 start="2026-04-27 09:30")
    day2 = _bars([102, 103, 102.5], [1200, 2200, 1700],
                 start="2026-04-28 09:30")
    bars = pd.concat([day1, day2])
    daily = compute_daily_volume_profile(bars)
    assert len(daily) == 2
    # Day 1 POC near 101 (max volume at 101)
    assert abs(daily.iloc[0]["poc_price"] - 101) < 0.5
    # Day 2 POC near 103
    assert abs(daily.iloc[1]["poc_price"] - 103) < 0.5
    # Total volume column matches
    assert daily.iloc[0]["total_volume"] == 1000 + 2000 + 1500
    assert daily.iloc[1]["total_volume"] == 1200 + 2200 + 1700


def test_daily_profile_index_is_datetime():
    bars = _bars([100, 101], [1000, 2000])
    daily = compute_daily_volume_profile(bars)
    assert isinstance(daily.index, pd.DatetimeIndex)


def test_daily_profile_skips_empty_sessions():
    """Sessions with all-zero volume are dropped."""
    day1 = _bars([100, 101], [1000, 2000], start="2026-04-27 09:30")
    day2 = _bars([102, 103], [0, 0], start="2026-04-28 09:30")
    bars = pd.concat([day1, day2])
    daily = compute_daily_volume_profile(bars)
    assert len(daily) == 1


def test_daily_profile_validation():
    # Non-DatetimeIndex
    bad = pd.DataFrame({"close": [100], "volume": [1000]})
    with pytest.raises(ValueError):
        compute_daily_volume_profile(bad)


def test_daily_profile_empty_input():
    """Empty input → empty output (no error)."""
    empty = pd.DataFrame(
        {"close": [], "volume": []},
        index=pd.DatetimeIndex([]),
    )
    daily = compute_daily_volume_profile(empty)
    assert daily.empty
    assert "poc_price" in daily.columns


# ── position_within_value_area ───────────────────────────────────


def test_position_within_value_area_at_boundaries():
    """Price at VAL = 0; at VAH = 1; midpoint = 0.5."""
    assert position_within_value_area(100.0, val=100.0, vah=110.0) == 0.0
    assert position_within_value_area(110.0, val=100.0, vah=110.0) == 1.0
    assert position_within_value_area(105.0, val=100.0, vah=110.0) == 0.5


def test_position_within_value_area_outside_band():
    """Below VAL → < 0; above VAH → > 1."""
    assert position_within_value_area(95.0, val=100.0, vah=110.0) == -0.5
    assert position_within_value_area(115.0, val=100.0, vah=110.0) == 1.5


def test_position_within_value_area_degenerate():
    """val == vah → NaN."""
    p = position_within_value_area(100.0, val=100.0, vah=100.0)
    assert np.isnan(p)


def test_position_within_value_area_nan_inputs():
    assert np.isnan(position_within_value_area(100.0, val=float("nan"), vah=110.0))
    assert np.isnan(position_within_value_area(100.0, val=100.0, vah=float("nan")))
