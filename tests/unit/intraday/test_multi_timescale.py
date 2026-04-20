"""Tests for multi-timescale data contract and signal alignment."""

import numpy as np
import pandas as pd
import pytest

from core.intraday.multi_timescale import (
    TimescaleBar, MultiTimescaleContext, CrossTFSignal,
    get_latest_completed_bar, build_context, check_higher_tf_alignment,
    evaluate_cross_tf_signal,
)


def _make_bars(n=10, freq_minutes=60, start="2025-04-01 09:30", base=100):
    idx = pd.date_range(start, periods=n, freq=f"{freq_minutes}min")
    close = base + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": close - np.random.rand(n) * 0.3,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": np.random.uniform(1e5, 5e5, n),
    }, index=idx)


class TestGetLatestCompletedBar:
    def test_returns_latest_before_timestamp(self):
        np.random.seed(42)
        bars = _make_bars(n=7, freq_minutes=60, start="2025-04-01 09:30")
        bar = get_latest_completed_bar(bars, pd.Timestamp("2025-04-01 12:00"))
        assert bar is not None
        assert bar.timestamp <= pd.Timestamp("2025-04-01 12:00")

    def test_returns_none_for_empty(self):
        assert get_latest_completed_bar(pd.DataFrame(), pd.Timestamp("2025-04-01 12:00")) is None

    def test_returns_none_before_first_bar(self):
        np.random.seed(42)
        bars = _make_bars(n=3, start="2025-04-01 10:00")
        assert get_latest_completed_bar(bars, pd.Timestamp("2025-04-01 09:00")) is None

    def test_no_future_bar(self):
        """Must NOT return a bar after as_of."""
        np.random.seed(42)
        bars = _make_bars(n=7, freq_minutes=60, start="2025-04-01 09:30")
        bar = get_latest_completed_bar(bars, pd.Timestamp("2025-04-01 11:00"))
        assert bar.timestamp <= pd.Timestamp("2025-04-01 11:00")


class TestMultiTFLookaheadInvariant:
    """Build-context must never return a bar whose close time > decision_time.
    This is the fundamental multi-timescale leakage gate."""

    def _make_right_labeled(self, start, n, freq_minutes):
        """Make right-labeled bars: index = bar close time."""
        idx = pd.date_range(start, periods=n, freq=f"{freq_minutes}min")
        return pd.DataFrame({
            "open":   [100.0 + i for i in range(n)],
            "high":   [101.0 + i for i in range(n)],
            "low":    [99.0 + i for i in range(n)],
            "close":  [100.5 + i for i in range(n)],
            "volume": [1e5] * n,
        }, index=idx)

    def test_build_context_excludes_future_bars(self):
        bars_60m = self._make_right_labeled("2025-04-01 10:30", 6, 60)
        bars_15m = self._make_right_labeled("2025-04-01 09:45", 24, 15)
        multi = {"60m": {"SPY": bars_60m}, "15m": {"SPY": bars_15m}}

        # Decide at 11:30 — 60m bar closed at 11:30 should be included, but
        # 60m bar at 12:30 (not yet closed) MUST NOT be.
        ctx = build_context(multi, "SPY", pd.Timestamp("2025-04-01 11:30"))
        assert ctx.has("60m") and ctx.has("15m")
        for freq, bar in ctx.bars.items():
            assert bar.timestamp <= pd.Timestamp("2025-04-01 11:30"), (
                f"{freq} bar {bar.timestamp} > decision 11:30 — leakage"
            )

    def test_build_context_at_exact_bar_close_includes_just_closed(self):
        """Bar closed AT decision_time: include it (data available)."""
        bars = self._make_right_labeled("2025-04-01 10:30", 5, 60)
        multi = {"60m": {"SPY": bars}}
        decision = pd.Timestamp("2025-04-01 12:30")
        ctx = build_context(multi, "SPY", decision)
        assert ctx.has("60m")
        assert ctx.bars["60m"].timestamp == decision

    def test_build_context_empty_when_no_closed_bar(self):
        """Decision before any bar closes → no context."""
        bars = self._make_right_labeled("2025-04-01 12:30", 3, 60)
        multi = {"60m": {"SPY": bars}}
        ctx = build_context(multi, "SPY", pd.Timestamp("2025-04-01 10:00"))
        assert not ctx.has("60m")

    def test_decision_mid_bar_excludes_incomplete_bar(self):
        """Decision at 10:45 (mid 60m bar [09:30, 10:30] already closed at
        10:30, but bar [10:30, 11:30] not yet closed): only 10:30 bar should
        be in context, not the 11:30 one."""
        # Right-labeled: bars close at 10:30, 11:30, 12:30, ...
        bars = self._make_right_labeled("2025-04-01 10:30", 6, 60)
        multi = {"60m": {"SPY": bars}}
        ctx = build_context(multi, "SPY", pd.Timestamp("2025-04-01 10:45"))
        assert ctx.has("60m")
        # Should have the 10:30 bar (just closed), not 11:30
        assert ctx.bars["60m"].timestamp == pd.Timestamp("2025-04-01 10:30")


class TestMultiTimescaleContext:
    def test_build_context_multi_freq(self):
        np.random.seed(42)
        multi = {
            "60m": {"SPY": _make_bars(7, 60, "2025-04-01 09:30")},
            "30m": {"SPY": _make_bars(14, 30, "2025-04-01 09:30")},
        }
        ctx = build_context(multi, "SPY", pd.Timestamp("2025-04-01 12:00"))
        assert ctx.has("60m")
        assert ctx.has("30m")
        assert len(ctx.available_freqs) == 2

    def test_missing_symbol(self):
        multi = {"60m": {"SPY": _make_bars(5, 60)}}
        ctx = build_context(multi, "AAPL", pd.Timestamp("2025-04-01 12:00"))
        assert not ctx.has("60m")

    def test_direction(self):
        bar = TimescaleBar(
            timestamp=pd.Timestamp("2025-04-01 10:30"),
            freq="60m", open=100, high=102, low=99, close=101.5, volume=1e5,
        )
        ctx = MultiTimescaleContext(
            decision_time=pd.Timestamp("2025-04-01 10:30"),
            bars={"60m": bar},
        )
        assert ctx.get_direction("60m") == 1  # close > open


class TestHigherTFAlignment:
    def test_agreement(self):
        bars = {
            "60m": TimescaleBar(pd.Timestamp("2025-04-01 10:30"), "60m", 100, 102, 99, 101.5, 1e5),
            "30m": TimescaleBar(pd.Timestamp("2025-04-01 10:30"), "30m", 100, 101, 99, 100.8, 1e5),
        }
        ctx = MultiTimescaleContext(decision_time=pd.Timestamp("2025-04-01 10:30"), bars=bars)
        alignment = check_higher_tf_alignment(ctx)
        assert alignment["30m"] is True

    def test_disagreement(self):
        bars = {
            "60m": TimescaleBar(pd.Timestamp("2025-04-01 10:30"), "60m", 100, 102, 99, 101.5, 1e5),
            "30m": TimescaleBar(pd.Timestamp("2025-04-01 10:30"), "30m", 100, 101, 98, 98.5, 1e5),
        }
        ctx = MultiTimescaleContext(decision_time=pd.Timestamp("2025-04-01 10:30"), bars=bars)
        alignment = check_higher_tf_alignment(ctx)
        assert alignment["30m"] is False

    def test_no_60m_returns_empty(self):
        bars = {"30m": TimescaleBar(pd.Timestamp("2025-04-01 10:30"), "30m", 100, 101, 99, 100.5, 1e5)}
        ctx = MultiTimescaleContext(decision_time=pd.Timestamp("2025-04-01 10:30"), bars=bars)
        assert check_higher_tf_alignment(ctx) == {}


class TestCrossTFSignal:
    """Test the cross-timeframe signal evaluation protocol."""

    def _make_ctx(self, dir_60, dir_30=None, dir_15=None):
        bars = {}
        ts = pd.Timestamp("2025-04-01 10:30")
        if dir_60 is not None:
            o60 = 100
            c60 = 101.5 if dir_60 == 1 else (98.5 if dir_60 == -1 else 100)
            bars["60m"] = TimescaleBar(ts, "60m", o60, 102, 98, c60, 1e5)
        if dir_30 is not None:
            o30 = 100
            c30 = 101 if dir_30 == 1 else (99 if dir_30 == -1 else 100)
            bars["30m"] = TimescaleBar(ts, "30m", o30, 101, 99, c30, 1e5)
        if dir_15 is not None:
            o15 = 100
            c15 = 100.5 if dir_15 == 1 else (99.5 if dir_15 == -1 else 100)
            bars["15m"] = TimescaleBar(ts, "15m", o15, 101, 99, c15, 1e5)
        return MultiTimescaleContext(decision_time=ts, bars=bars)

    def test_bullish_confirmed(self):
        """60m bull + 30m bull → full strength signal."""
        ctx = self._make_ctx(dir_60=1, dir_30=1)
        sig = evaluate_cross_tf_signal(ctx, "SPY")
        assert sig.direction == 1
        assert sig.strength >= 0.9
        assert not sig.vetoed

    def test_60m_bearish_reduces_not_vetoes(self):
        """60m bearish → reduces strength but follows daily direction (C-mode)."""
        ctx_bull = self._make_ctx(dir_60=1, dir_30=1)
        ctx_bear = self._make_ctx(dir_60=-1, dir_30=1)
        s_bull = evaluate_cross_tf_signal(ctx_bull, "SPY")
        s_bear = evaluate_cross_tf_signal(ctx_bear, "SPY")
        assert s_bear.direction == 1
        assert not s_bear.vetoed
        assert s_bear.strength < s_bull.strength

    def test_30m_contradicts_60m_reduces(self):
        """60m bull but 30m bear → soft reduction (not hard veto)."""
        ctx_confirmed = self._make_ctx(dir_60=1, dir_30=1)
        ctx_contradicted = self._make_ctx(dir_60=1, dir_30=-1)
        s_full = evaluate_cross_tf_signal(ctx_confirmed, "SPY")
        s_reduced = evaluate_cross_tf_signal(ctx_contradicted, "SPY")
        assert s_reduced.direction == 1
        assert not s_reduced.vetoed
        assert s_reduced.strength < s_full.strength * 0.5

    def test_no_60m_vetoes(self):
        """No 60m context → veto."""
        ctx = self._make_ctx(dir_60=None, dir_30=1)
        sig = evaluate_cross_tf_signal(ctx, "SPY")
        assert sig.vetoed

    def test_neutral_60m_reduces_strength(self):
        """60m neutral → reduced strength."""
        ctx_bull = self._make_ctx(dir_60=1, dir_30=1)
        ctx_neut = self._make_ctx(dir_60=0, dir_30=1)
        s_bull = evaluate_cross_tf_signal(ctx_bull, "SPY")
        s_neut = evaluate_cross_tf_signal(ctx_neut, "SPY")
        assert s_neut.direction == 1
        assert s_neut.strength < s_bull.strength

    def test_15m_boosts_when_aligned(self):
        """15m bullish → slight boost."""
        ctx_no15 = self._make_ctx(dir_60=1, dir_30=1)
        ctx_15 = self._make_ctx(dir_60=1, dir_30=1, dir_15=1)
        s1 = evaluate_cross_tf_signal(ctx_no15, "SPY")
        s2 = evaluate_cross_tf_signal(ctx_15, "SPY")
        assert s2.strength >= s1.strength

    def test_15m_reduces_when_opposed(self):
        """15m bearish → reduces strength but doesn't veto."""
        ctx = self._make_ctx(dir_60=1, dir_30=1, dir_15=-1)
        sig = evaluate_cross_tf_signal(ctx, "SPY")
        assert sig.direction == 1
        assert sig.strength < 0.7


class TestRealDataAlignment:
    """Test with actual downloaded data if available."""

    def test_60m_30m_alignment_on_real_data(self):
        from core.data.market_data_store import MarketDataStore
        from pathlib import Path
        store = MarketDataStore(data_dir=Path("data"))

        spy_60 = store.read("SPY", "60m")
        spy_30 = store.read("SPY", "30m")

        if spy_60 is None or spy_30 is None or spy_60.empty or spy_30.empty:
            pytest.skip("No 60m/30m data available")

        # Find overlapping period
        common_start = max(spy_60.index[0], spy_30.index[0])
        common_end = min(spy_60.index[-1], spy_30.index[-1])

        multi = {
            "60m": {"SPY": spy_60.loc[common_start:common_end]},
            "30m": {"SPY": spy_30.loc[common_start:common_end]},
        }

        # Pick a timestamp in the middle of the overlap
        mid = common_start + (common_end - common_start) / 2
        ctx = build_context(multi, "SPY", mid)

        assert ctx.has("60m"), "Should have 60m bar"
        assert ctx.has("30m"), "Should have 30m bar"
        # 60m bar timestamp should be <= 30m bar timestamp (both before mid)
        assert ctx.bars["60m"].timestamp <= mid
        assert ctx.bars["30m"].timestamp <= mid
