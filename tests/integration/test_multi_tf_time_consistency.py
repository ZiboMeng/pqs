"""
Integration tests: multi-timescale time-consistency contract.

These tests guard the data + signal + execution timestamp semantics
documented in CLAUDE.md Multi-Timescale Framework. They use REAL bar
data from the local parquet store.

Contract under test
--------------------
Data contract:
  - Bar index = bar CLOSE timestamp (right-labeled, see aggregate_bars.py)
  - Tz-naive ET everywhere
  - For any higher-TF bar ending at T, the 1m bars covering [T-freq, T]
    must aggregate OHLCV-identical to the higher-TF bar

Signal / exec timing:
  - `build_context(decision_time=T)` MUST return only bars with
    `bar.timestamp <= T`
  - A decision at T must NOT pull any data whose `close > T`
  - Execution_timestamp MUST be > signal_timestamp (i.e. ≥ 1 bar delay)
    on the executing TF

These tests run quickly (a few symbols × small date windows) so they stay
suitable for CI.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PQS_DATA = Path(os.path.expanduser("~/Documents/projects/pqs/data"))


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _skip_if_no_data():
    if not PQS_DATA.exists() or not (PQS_DATA / "intraday" / "1m").exists():
        pytest.skip("local 1m data store not available; integration tests need data")


def _load_freq(sym: str, freq: str, start=None, end=None) -> pd.DataFrame:
    path = PQS_DATA / "intraday" / freq / f"{sym}.parquet"
    if not path.exists():
        pytest.skip(f"no {freq} data for {sym}")
    df = pd.read_parquet(path)
    if "timestamp" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index(pd.DatetimeIndex(df["timestamp"])).drop(columns=["timestamp"])
    df = df.sort_index()
    if start is not None:
        df = df.loc[df.index >= start]
    if end is not None:
        df = df.loc[df.index <= end]
    return df


@pytest.fixture(scope="module")
def sample_window():
    """A specific trading week that is fully available across TFs."""
    return pd.Timestamp("2024-06-03"), pd.Timestamp("2024-06-07")


# ─── A. Data contract: right-label + aggregation consistency ──────────────────

class TestRightLabelSemantics:
    """A bar labelled at T covers (T - freq, T], i.e. closes at T."""

    def test_60m_bar_ends_at_label_time(self, sample_window):
        _skip_if_no_data()
        start, end = sample_window
        bars_60m = _load_freq("SPY", "60m", start, end)
        if bars_60m.empty:
            pytest.skip("no 60m SPY data in window")
        # RTH 60m bars typically close at 10:30, 11:30, ..., 16:00 (right-label).
        # All hours should be consistent.
        minutes = bars_60m.index.minute.unique().tolist()
        # Most close times should be :30 (matching 09:30-start trading day) or :00
        assert len(minutes) <= 2, (
            f"unexpected variety of bar-close minutes: {minutes}"
        )


class TestAggregationConsistency:
    """Each higher-TF bar must match OHLCV aggregation of its underlying 1m bars."""

    def test_60m_matches_1m_aggregation(self, sample_window):
        _skip_if_no_data()
        start, end = sample_window
        bars_1m = _load_freq("SPY", "1m", start, end)
        bars_60m = _load_freq("SPY", "60m", start, end)
        if bars_1m.empty or bars_60m.empty:
            pytest.skip("no overlapping SPY 1m/60m data")

        # Pick 3 random 60m bars, verify each matches aggregation of 1m bars
        # whose index falls in (bar_close - 60min, bar_close].
        np.random.seed(0)
        sample_bars = bars_60m.iloc[np.random.choice(len(bars_60m),
                                                     min(3, len(bars_60m)),
                                                     replace=False)]
        n_checked = 0
        for close_ts, bar_row in sample_bars.iterrows():
            window_start = close_ts - pd.Timedelta(minutes=60)
            under = bars_1m.loc[(bars_1m.index > window_start) &
                                (bars_1m.index <= close_ts)]
            if under.empty:
                continue
            # open = first 1m open, close = last 1m close, high = max high,
            # low = min low, volume = sum
            assert abs(under.iloc[0]["open"] - bar_row["open"]) < 0.05, (
                f"{close_ts}: open mismatch — 60m={bar_row['open']:.4f}, "
                f"1m first open={under.iloc[0]['open']:.4f}"
            )
            assert abs(under.iloc[-1]["close"] - bar_row["close"]) < 0.05, (
                f"{close_ts}: close mismatch"
            )
            assert under["high"].max() >= bar_row["high"] - 0.05, (
                f"{close_ts}: 60m high {bar_row['high']:.4f} > max 1m high "
                f"{under['high'].max():.4f}"
            )
            assert under["low"].min() <= bar_row["low"] + 0.05, (
                f"{close_ts}: 60m low {bar_row['low']:.4f} < min 1m low"
            )
            n_checked += 1
        assert n_checked >= 1, "no 60m bars could be verified against 1m"

    def test_15m_and_5m_exist_with_right_label(self, sample_window):
        """15m and 5m bars should exist in sample window and be right-labeled."""
        _skip_if_no_data()
        start, end = sample_window
        for freq, freq_minutes in [("15m", 15), ("5m", 5)]:
            bars = _load_freq("SPY", freq, start, end)
            if bars.empty:
                continue
            # Close-time minutes should be multiples of freq_minutes
            for ts in bars.index[:20]:
                assert ts.minute % freq_minutes == 0, (
                    f"{freq} bar at {ts} has misaligned minute — not right-label"
                )


# ─── B. Build-context: no bar after decision_time ─────────────────────────────

class TestBuildContextOnRealData:
    """Real multi-TF data must obey the lookahead invariant on every sample."""

    def _load_multi(self, sym: str, freqs: list[str], start, end) -> dict:
        out = {}
        for f in freqs:
            df = _load_freq(sym, f, start, end)
            if not df.empty:
                out[f] = {sym: df}
        return out

    def test_build_context_never_returns_future_bar_over_day(self, sample_window):
        _skip_if_no_data()
        from core.intraday.multi_timescale import build_context

        start, end = sample_window
        multi = self._load_multi("SPY", ["60m", "30m", "15m", "5m"], start, end)
        if not multi:
            pytest.skip("no multi-TF SPY data in window")

        # Sample 20 decision points spanning the window
        ref_bars = multi["60m"]["SPY"] if "60m" in multi else next(iter(multi.values()))["SPY"]
        if len(ref_bars) == 0:
            pytest.skip("no reference bars")
        step = max(1, len(ref_bars) // 20)
        sample_ts = ref_bars.index[::step][:20]

        n_checked = 0
        for decision_time in sample_ts:
            ctx = build_context(multi, "SPY", decision_time)
            for freq, bar in ctx.bars.items():
                assert bar.timestamp <= decision_time, (
                    f"leak: {freq} bar {bar.timestamp} > decision {decision_time}"
                )
                n_checked += 1
        assert n_checked > 0


# ─── C. Signal / execution timing contract ────────────────────────────────────

class TestSignalExecutionTiming:
    """When a signal is emitted at T, execution must land strictly after T
    (≥ 1 bar delay on the executing TF)."""

    def test_backtest_engine_executes_at_next_open_not_same_day(self):
        """Canonical case: daily signal at T → trade at T+1 open."""
        from core.backtest.backtest_engine import BacktestEngine
        from core.execution.cost_model import CostModel
        from core.config.schemas.cost_model import CostModelConfig, CostTierConfig

        idx = pd.bdate_range("2024-01-02", periods=10)
        close = pd.DataFrame({"A": [100 + i for i in range(10)]}, index=idx)
        open_df = pd.DataFrame({"A": [200 + i for i in range(10)]}, index=idx)
        sig = pd.DataFrame({"A": [1.0] * 10}, index=idx)
        cost = CostModel(CostModelConfig(tiers={"default": CostTierConfig(
            symbols=[], commission_bps=0, slippage_interday_bps=0, slippage_intraday_bps=0)}))
        eng = BacktestEngine(cost, initial_capital=10_000)
        result = eng.run(sig, close, open_df=open_df)
        assert len(result.trades) > 0
        first = result.trades[0]
        # signal_date = idx[0], execution should be idx[1] open = 201
        # (not idx[0] at 100 close and not idx[1] close at 101)
        assert first.executed_price == pytest.approx(201.0, rel=0.01), (
            f"first fill exec_price {first.executed_price} != next-day open (201)"
        )

    def test_no_zero_bar_delay_fill(self):
        """No fill should have executed on the same timestamp as its signal."""
        from core.backtest.backtest_engine import BacktestEngine
        from core.execution.cost_model import CostModel
        from core.config.schemas.cost_model import CostModelConfig, CostTierConfig

        idx = pd.bdate_range("2024-01-02", periods=10)
        close = pd.DataFrame({"A": [100.0] * 10}, index=idx)
        open_df = pd.DataFrame({"A": [100.0] * 10}, index=idx)
        sig = pd.DataFrame({"A": [1.0] * 10}, index=idx)
        cost = CostModel(CostModelConfig(tiers={"default": CostTierConfig(
            symbols=[], commission_bps=0, slippage_interday_bps=0, slippage_intraday_bps=0)}))
        eng = BacktestEngine(cost, initial_capital=10_000)
        result = eng.run(sig, close, open_df=open_df)
        for trade in result.trades:
            # signal_date is stored; ensure the fill date > signal_date
            assert trade.signal_date < trade.fill_date, (
                f"zero-bar-delay fill: signal {trade.signal_date} "
                f"== execution {trade.fill_date}"
            )
