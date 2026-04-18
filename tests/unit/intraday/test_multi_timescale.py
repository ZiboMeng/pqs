"""Tests for multi-timescale data contract and signal alignment."""

import numpy as np
import pandas as pd
import pytest

from core.intraday.multi_timescale import (
    TimescaleBar, MultiTimescaleContext,
    get_latest_completed_bar, build_context, check_higher_tf_alignment,
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
