"""Tests for IntradayReversalStrategy ↔ BacktestEngine bridge module.

Per design memo `docs/memos/20260512-deferred_execution_bt_integration_design.md`
Phase 2 D1 scope.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.backtest.intraday_reversal_bridge import (
    IntradayReversalBridgeState,
    build_intraday_reversal_signals,
    estimate_alt_a_turnover,
)
from core.signals.strategies.intraday_reversal import (
    IntradayReversalConfig, IntradayReversalStrategy,
)


@pytest.fixture
def sample_panels_20d():
    """20-day panel × 5 symbols with realistic alt-A inputs."""
    dates = pd.date_range("2024-01-02", periods=20, freq="B")
    syms = ["AAA", "BBB", "CCC", "DDD", "EEE"]

    # weekly_reversal_signal_5d: A and B periodically have low values
    # (setup-armed candidates); C/D/E mostly above 0
    rng = np.random.default_rng(42)
    wr_data = rng.normal(0, 1, (len(dates), len(syms)))
    wr_data[:, 0] -= 2.0  # AAA: always low (setup-armed)
    wr_data[:, 1] -= 1.5  # BBB: usually low
    wr = pd.DataFrame(wr_data, index=dates, columns=syms)

    # vol_21d: all symbols above filter threshold
    vol = pd.DataFrame(0.25, index=dates, columns=syms)

    # intraday volume z-score: AAA + BBB always surge; others never
    iv = pd.DataFrame(0.5, index=dates, columns=syms)
    iv["AAA"] = 2.5  # confirms volume surge
    iv["BBB"] = 2.0

    # early session return: positive for AAA + BBB
    er = pd.DataFrame(-0.005, index=dates, columns=syms)
    er["AAA"] = 0.01
    er["BBB"] = 0.008

    return wr, vol, iv, er, dates, syms


class TestBridgeStateAging:
    def test_aged_out_after_5d(self):
        state = IntradayReversalBridgeState()
        entry = pd.Timestamp("2024-01-02")
        state.record_entry("AAA", entry)
        # 4 days held: NOT aged out
        assert not state.aged_out("AAA", entry + pd.Timedelta(days=4), hold_days=5)
        # 5 days held: aged out
        assert state.aged_out("AAA", entry + pd.Timedelta(days=5), hold_days=5)
        # 7 days held: aged out
        assert state.aged_out("AAA", entry + pd.Timedelta(days=7), hold_days=5)

    def test_unknown_symbol_not_aged(self):
        state = IntradayReversalBridgeState()
        assert not state.aged_out("ZZZ", pd.Timestamp("2024-01-10"), hold_days=5)

    def test_clear_drops_entry(self):
        state = IntradayReversalBridgeState()
        state.record_entry("AAA", pd.Timestamp("2024-01-02"))
        state.clear("AAA")
        assert not state.aged_out("AAA", pd.Timestamp("2024-01-10"), hold_days=5)


class TestBuildSignalsDF:
    def test_returns_correct_shape(self, sample_panels_20d):
        wr, vol, iv, er, dates, syms = sample_panels_20d
        strat = IntradayReversalStrategy(
            IntradayReversalConfig(
                setup_quantile_threshold=0.20,
                vol_filter_min_pct=0.0,
                volume_surge_at_open_60m_min=1.5,
                top_n=3,
                holding_period_max_days=5,
            )
        )
        signals = build_intraday_reversal_signals(
            strat, wr, vol, iv, er, dates,
        )
        assert signals.shape == (len(dates), len(syms))
        assert (signals.index == dates).all()

    def test_armed_symbols_appear_in_signals(self, sample_panels_20d):
        wr, vol, iv, er, dates, syms = sample_panels_20d
        strat = IntradayReversalStrategy(
            IntradayReversalConfig(
                setup_quantile_threshold=0.40,  # generous
                vol_filter_min_pct=0.0,
                volume_surge_at_open_60m_min=1.5,
                top_n=3,
                holding_period_max_days=5,
            )
        )
        signals = build_intraday_reversal_signals(
            strat, wr, vol, iv, er, dates,
        )
        # AAA and BBB should both have non-zero weights at some point
        assert signals["AAA"].sum() > 0
        assert signals["BBB"].sum() > 0
        # CCC/DDD/EEE: setup might trigger but confirmation predicate
        # (intraday volume z + positive early return) blocks them in fixture
        assert signals["CCC"].sum() == 0  # confirm predicate fails
        assert signals["DDD"].sum() == 0
        assert signals["EEE"].sum() == 0

    def test_weights_sum_le_1(self, sample_panels_20d):
        wr, vol, iv, er, dates, syms = sample_panels_20d
        strat = IntradayReversalStrategy(
            IntradayReversalConfig(
                setup_quantile_threshold=0.80,  # very generous to test cap
                vol_filter_min_pct=0.0,
                volume_surge_at_open_60m_min=0.0,  # always confirms
                top_n=5,  # could fill all 5
                holding_period_max_days=5,
            )
        )
        # Override iv + er so ALL syms confirm
        iv2 = pd.DataFrame(3.0, index=dates, columns=syms)
        er2 = pd.DataFrame(0.01, index=dates, columns=syms)
        signals = build_intraday_reversal_signals(
            strat, wr, vol, iv2, er2, dates,
        )
        # Each row sum ≤ 1.0 (per PRD §3 no-leverage)
        row_sums = signals.sum(axis=1)
        assert (row_sums <= 1.0 + 1e-9).all()

    def test_aged_positions_drop(self, sample_panels_20d):
        wr, vol, iv, er, dates, syms = sample_panels_20d
        # Configure AAA to be armed ONLY on day 0; days 1+ AAA is high
        # (above peer quantile) so re-arming is blocked → pure aging test.
        wr2 = pd.DataFrame(0.5, index=dates, columns=syms)
        wr2.iloc[0, 0] = -3.0   # AAA day 0: extreme low → armed
        wr2.iloc[1:, 0] = 1.5    # AAA day 1+: above peers → NOT armed
        strat = IntradayReversalStrategy(
            IntradayReversalConfig(
                setup_quantile_threshold=0.10,  # only most-extreme
                vol_filter_min_pct=0.0,
                volume_surge_at_open_60m_min=1.5,
                top_n=5,
                holding_period_max_days=5,
            )
        )
        signals = build_intraday_reversal_signals(
            strat, wr2, vol, iv, er, dates,
        )
        # AAA should be present on first few days then drop via aging.
        # Bridge uses calendar-day arithmetic; 5-day holding cap → aged
        # out within ~7 calendar days (5d + weekend).
        aaa_held = signals["AAA"] > 0
        held_days = aaa_held.sum()
        assert held_days >= 1   # at least day 0
        assert held_days <= 8   # 5d hold + weekend tolerance


class TestEdgeCases:
    def test_empty_dates(self):
        empty = pd.DatetimeIndex([])
        strat = IntradayReversalStrategy()
        wr = pd.DataFrame(columns=["A"])
        vol = pd.DataFrame(columns=["A"])
        iv = pd.DataFrame(columns=["A"])
        er = pd.DataFrame(columns=["A"])
        signals = build_intraday_reversal_signals(strat, wr, vol, iv, er, empty)
        assert signals.empty

    def test_missing_panel_dates_graceful(self):
        dates = pd.date_range("2024-01-02", periods=5, freq="B")
        syms = ["AAA"]
        wr = pd.DataFrame(-2.0, index=dates, columns=syms)
        vol = pd.DataFrame(0.25, index=dates, columns=syms)
        # iv has only first 3 dates; later dates absent
        iv = pd.DataFrame(2.5, index=dates[:3], columns=syms)
        er = pd.DataFrame(0.01, index=dates[:3], columns=syms)
        strat = IntradayReversalStrategy(
            IntradayReversalConfig(setup_quantile_threshold=1.0,
                                    vol_filter_min_pct=0.0,
                                    volume_surge_at_open_60m_min=1.5,
                                    top_n=3, holding_period_max_days=5)
        )
        # Should not crash; later dates with missing iv just don't confirm
        signals = build_intraday_reversal_signals(strat, wr, vol, iv, er, dates)
        assert signals.shape == (5, 1)


class TestTurnoverEstimate:
    def test_zero_signals_zero_turnover(self):
        dates = pd.date_range("2024-01-02", periods=10, freq="B")
        signals = pd.DataFrame(0.0, index=dates, columns=["A", "B"])
        assert estimate_alt_a_turnover(signals) == 0.0

    def test_realistic_signals_high_turnover(self):
        # 5-sym; alternates +1/0 weights each day → ~ daily full turnover
        dates = pd.date_range("2024-01-02", periods=20, freq="B")
        signals = pd.DataFrame(0.0, index=dates, columns=["A", "B"])
        signals.loc[dates[0::2], "A"] = 0.5
        signals.loc[dates[1::2], "B"] = 0.5
        turn = estimate_alt_a_turnover(signals)
        # Each day ~1.0 abs change; annualized ≈ 252 × ~1.0 = ~252
        assert 200 < turn < 300

    def test_empty_returns_zero(self):
        assert estimate_alt_a_turnover(pd.DataFrame()) == 0.0
        assert estimate_alt_a_turnover(pd.DataFrame(index=[pd.Timestamp("2024-01-02")])) == 0.0
