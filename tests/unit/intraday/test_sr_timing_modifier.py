"""Tests for S/R-aware timing modifier (PRD 20260505 Step 3).

Covers:
  - Default behavior preserved when enable_sr_timing=False
  - Opt-in flag + sr_levels=None → graceful no-op
  - sr_levels with no resistance → no scale change
  - Close near resistance (within threshold) → scale-down + sr_60m vote
  - Close far from resistance → no scale change
  - 60m + 30m + S/R compose multiplicatively
  - compute_sr_levels_at handles short history / NaN gracefully
  - make_timing_target_provider honors enable_sr_timing flag
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.intraday.multi_timescale import (
    MultiTimescaleContext,
    SRLevels,
    TimescaleBar,
    TimingThresholds,
    compute_sr_levels_at,
    decide_timing,
    make_timing_target_provider,
)


# ── helpers ─────────────────────────────────────────────────────


def _bar(direction: int, freq: str, close: float = 101.5) -> TimescaleBar:
    o = 100.0
    if direction == 1:
        c = close
    elif direction == -1:
        c = 98.5
    else:
        c = 100.0
    return TimescaleBar(
        timestamp=pd.Timestamp("2025-04-01 10:30"),
        freq=freq, open=o, high=max(o, c) + 1, low=min(o, c) - 1,
        close=c, volume=1e5,
    )


def _ctx(close: float = 101.5, **kwargs) -> MultiTimescaleContext:
    bars = {}
    for freq, direction in kwargs.items():
        if direction is not None:
            bars[freq] = _bar(direction, freq, close=close)
    return MultiTimescaleContext(
        decision_time=pd.Timestamp("2025-04-01 10:30"), bars=bars,
    )


def _sr(close: float, resistance=None, support=None) -> SRLevels:
    return SRLevels(
        freq="60m",
        decision_time=pd.Timestamp("2025-04-01 10:30"),
        current_close=close,
        resistance=resistance,
        support=support,
    )


# ── default-off invariant ───────────────────────────────────────


class TestDefaultBehaviorPreserved:

    def test_default_thresholds_have_sr_disabled(self):
        """Existing callers see no change — flag default False."""
        th = TimingThresholds()
        assert th.enable_sr_timing is False

    def test_60m_bull_unchanged_when_sr_disabled_with_levels_passed(self):
        """Even if caller passes sr_levels, modifier no-ops when flag off."""
        sr = {"60m": _sr(close=101.5, resistance=101.6)}  # 0.1% to R
        d_no_sr = decide_timing(_ctx(**{"60m": 1}), "X", base_weight=0.3)
        d_with_sr = decide_timing(_ctx(**{"60m": 1}), "X", base_weight=0.3,
                                  sr_levels=sr)
        assert d_with_sr.timing_scale == d_no_sr.timing_scale
        assert "sr_60m" not in d_with_sr.higher_tf_vote


# ── enabled but no resistance / no levels ───────────────────────


class TestEnabledNoEffect:

    def _th_on(self):
        return TimingThresholds(enable_sr_timing=True,
                                sr_near_resistance_pct=0.005,
                                sr_scale_when_near_resistance=0.5)

    def test_sr_levels_none_no_op(self):
        """enable_sr_timing=True but sr_levels=None → graceful skip."""
        d = decide_timing(_ctx(**{"60m": 1}), "X", base_weight=0.3,
                          thresholds=self._th_on(), sr_levels=None)
        assert d.timing_scale == 1.0
        assert "sr_60m" not in d.higher_tf_vote

    def test_no_60m_in_sr_levels_no_op(self):
        """sr_levels missing 60m → modifier doesn't fire."""
        d = decide_timing(_ctx(**{"60m": 1}), "X", base_weight=0.3,
                          thresholds=self._th_on(), sr_levels={})
        assert d.timing_scale == 1.0
        assert "sr_60m" not in d.higher_tf_vote

    def test_resistance_none_no_op(self):
        """SRLevels.resistance=None (no qualifying swing) → no scale change."""
        sr = {"60m": _sr(close=101.5, resistance=None)}
        d = decide_timing(_ctx(**{"60m": 1}), "X", base_weight=0.3,
                          thresholds=self._th_on(), sr_levels=sr)
        assert d.timing_scale == 1.0
        assert "sr_60m" not in d.higher_tf_vote

    def test_resistance_below_close_no_op(self):
        """If resistance is BELOW close, gap_frac ≤ 0 → not a near-R event."""
        sr = {"60m": _sr(close=101.5, resistance=99.0)}  # below close
        d = decide_timing(_ctx(**{"60m": 1}), "X", base_weight=0.3,
                          thresholds=self._th_on(), sr_levels=sr)
        assert d.timing_scale == 1.0
        assert "sr_60m" not in d.higher_tf_vote


# ── core modifier semantics ──────────────────────────────────────


class TestNearResistanceScaleDown:

    def _th_on(self, near_pct=0.005, scale=0.5):
        return TimingThresholds(enable_sr_timing=True,
                                sr_near_resistance_pct=near_pct,
                                sr_scale_when_near_resistance=scale)

    def test_close_within_threshold_scales_down(self):
        """Close 30 bps below R, threshold 50 bps → fire, halve scale."""
        sr = {"60m": _sr(close=101.50, resistance=101.80)}  # gap 0.30%
        d = decide_timing(_ctx(**{"60m": 1}), "X", base_weight=0.3,
                          thresholds=self._th_on(), sr_levels=sr)
        # 60m=1 → scale=1.0, then *0.5 from S/R modifier → 0.5
        assert abs(d.timing_scale - 0.5) < 1e-6
        assert d.higher_tf_vote["sr_60m"] == "near_resistance"

    def test_close_at_threshold_boundary_fires(self):
        """gap == sr_near_resistance_pct (50 bps exactly) → fires."""
        sr = {"60m": _sr(close=100.0, resistance=100.5)}  # exactly 50 bps
        d = decide_timing(_ctx(**{"60m": 1}), "X", base_weight=0.3,
                          thresholds=self._th_on(near_pct=0.005), sr_levels=sr)
        assert "sr_60m" in d.higher_tf_vote
        assert abs(d.timing_scale - 0.5) < 1e-6

    def test_close_above_threshold_no_op(self):
        """gap = 80 bps > 50 bps threshold → no modifier."""
        sr = {"60m": _sr(close=100.0, resistance=100.8)}  # 80 bps gap
        d = decide_timing(_ctx(**{"60m": 1}), "X", base_weight=0.3,
                          thresholds=self._th_on(near_pct=0.005), sr_levels=sr)
        assert d.timing_scale == 1.0
        assert "sr_60m" not in d.higher_tf_vote

    def test_modifier_composes_with_30m_neutral(self):
        """60m=1, 30m=neutral, S/R near → all multiply: 1.0 × 0.8 × 0.5."""
        sr = {"60m": _sr(close=101.50, resistance=101.80)}
        d = decide_timing(_ctx(**{"60m": 1, "30m": 0}), "X", base_weight=0.3,
                          thresholds=self._th_on(), sr_levels=sr)
        # 1.0 * 0.8 (30m neutral) * 0.5 (SR) = 0.4
        assert abs(d.timing_scale - 0.4) < 1e-3


# ── compute_sr_levels_at ─────────────────────────────────────────


class TestComputeSRLevels:

    def _bars(self, n=30, base=100):
        idx = pd.date_range("2025-04-01 09:30", periods=n, freq="1h")
        # Saw-tooth pattern to produce swings
        closes = []
        for i in range(n):
            offset = 5 if i % 7 == 3 else (-5 if i % 7 == 0 else 0)
            closes.append(base + offset)
        df = pd.DataFrame({
            "open": closes,
            "high": [c + 2 for c in closes],
            "low":  [c - 2 for c in closes],
            "close": closes,
            "volume": [1e5] * n,
        }, index=idx)
        return df

    def test_returns_none_for_short_history(self):
        """Fewer than 2n+1 bars → None."""
        bars = self._bars(n=5)
        sr = compute_sr_levels_at(bars, bars.index[-1], freq="60m", n=5)
        assert sr is None

    def test_returns_none_for_empty_input(self):
        empty = pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": [], "volume": []},
            index=pd.DatetimeIndex([]),
        )
        assert compute_sr_levels_at(empty, pd.Timestamp("2025-04-01"),
                                    freq="60m") is None

    def test_returns_none_for_none_input(self):
        assert compute_sr_levels_at(None, pd.Timestamp("2025-04-01"),
                                    freq="60m") is None

    def test_returns_levels_with_real_swings(self):
        bars = self._bars(n=30)
        sr = compute_sr_levels_at(bars, bars.index[-1], freq="60m",
                                  n=2, lookback=20)
        assert sr is not None
        assert sr.freq == "60m"
        assert sr.current_close == bars["close"].iloc[-1]
        # With saw-tooth pattern + lookback 20, expect either R or S to be
        # defined (at least one swing in lookback)
        assert sr.resistance is not None or sr.support is not None

    def test_truncates_at_as_of(self):
        """as_of in the middle of bars → only history up to that point used."""
        bars = self._bars(n=30)
        mid_ts = bars.index[15]
        sr = compute_sr_levels_at(bars, mid_ts, freq="60m", n=2, lookback=20)
        assert sr is not None
        assert sr.decision_time <= mid_ts


# ── provider integration ────────────────────────────────────────


class TestProviderHonorsSRFlag:

    def test_provider_skips_sr_when_flag_off(self):
        """Default-off provider produces same outputs as no-S/R caller."""
        idx = pd.date_range("2025-04-01 10:00", periods=10, freq="1h")
        bars = pd.DataFrame({
            "open": [100.0] * 10,
            "high": [101.0] * 10,
            "low":  [99.0] * 10,
            "close": [100.5] * 10,
            "volume": [1e5] * 10,
        }, index=idx)
        multi_bars = {"60m": {"AAPL": bars}}
        provider = make_timing_target_provider(
            multi_bars=multi_bars,
            daily_base_weights={"AAPL": 0.3},
            thresholds=TimingThresholds(enable_sr_timing=False),
        )
        out = provider(idx[-1], positions={}, cash=10000.0)
        # AAPL should be present at full base_weight (60m flat → mild scaling
        # but execute=True for non-deferring path).
        assert "AAPL" in out
        # No S/R modifier applied
        assert out["AAPL"] > 0


def test_thresholds_from_config_lazy_migrates_legacy():
    """Legacy IntradayTimingConfig (yaml without S/R fields) loads with
    defaults; TimingThresholds.from_config consumes via getattr."""
    class LegacyCfg:
        min_timing_scale          = 0.0
        execute_threshold         = 0.15
        scale_when_60m_contradict = 0.5
        scale_when_60m_neutral    = 0.8
        mult_30m_contradict       = 0.5
        mult_30m_neutral          = 0.8
        # No SR fields — getattr falls back to default
    th = TimingThresholds.from_config(LegacyCfg())
    assert th.enable_sr_timing is False
    assert th.sr_near_resistance_pct == 0.005
    assert th.sr_scale_when_near_resistance == 0.5
    assert th.sr_swing_n == 5
    assert th.sr_lookback_bars == 20
