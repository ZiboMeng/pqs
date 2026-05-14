"""T1a.2 unit tests for IntradayReversalRunner bridge.

Synthetic-data tests verify the bridge correctly converts
IntradayReversalStrategy daily setup/confirm logic into entry/exit
signals + confirmation_predicate consumed by SignalDrivenBacktest.

No 60m intraday bar dependency. Real-data validation is T1a.3+.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.backtest.intraday_reversal_runner import IntradayReversalRunner
from core.backtest.backtest_engine import BacktestResult
from core.signals.signal_state import SignalStatus
from core.signals.strategies.intraday_reversal import (
    IntradayReversalStrategy, IntradayReversalConfig,
)


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


def _mk_dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range(start="2024-01-02", periods=n)


def _mk_panel(dates, symbols, fill_value: float = np.nan) -> pd.DataFrame:
    return pd.DataFrame(fill_value, index=dates, columns=symbols, dtype=float)


def _mk_prices(dates, symbols, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.01, size=(len(dates), len(symbols)))
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=dates, columns=symbols)


# ──────────────────────────────────────────────────────────────────────────
# A. Construction validation
# ──────────────────────────────────────────────────────────────────────────


class TestConstruction:
    def test_01_init_with_aligned_panels(self):
        dates = _mk_dates(30)
        syms = ["AAA", "BBB"]
        wr = _mk_panel(dates, syms, fill_value=0.0)
        vol = _mk_panel(dates, syms, fill_value=0.1)
        iv = _mk_panel(dates, syms, fill_value=0.0)
        er = _mk_panel(dates, syms, fill_value=0.0)
        prices = _mk_prices(dates, syms)
        strat = IntradayReversalStrategy(IntradayReversalConfig(top_n=5))
        runner = IntradayReversalRunner(
            strategy=strat,
            weekly_reversal_signal_5d=wr, vol_21d=vol,
            intraday_volume_60m_zscore=iv, early_session_return_pct=er,
            price_df=prices,
        )
        assert runner is not None

    def test_02_misaligned_dates_rejected(self):
        d_a = _mk_dates(30)
        d_b = pd.bdate_range(start="2024-02-01", periods=30)
        syms = ["AAA"]
        wr = _mk_panel(d_a, syms, 0.0)
        vol = _mk_panel(d_b, syms, 0.1)  # mismatched index
        iv = _mk_panel(d_a, syms, 0.0)
        er = _mk_panel(d_a, syms, 0.0)
        prices = _mk_prices(d_a, syms)
        strat = IntradayReversalStrategy()
        with pytest.raises(ValueError, match=r"vol_21d.*index"):
            IntradayReversalRunner(
                strategy=strat,
                weekly_reversal_signal_5d=wr, vol_21d=vol,
                intraday_volume_60m_zscore=iv, early_session_return_pct=er,
                price_df=prices,
            )


# ──────────────────────────────────────────────────────────────────────────
# B. Entry signal construction
# ──────────────────────────────────────────────────────────────────────────


class TestEntrySignals:
    def test_03_entry_signals_match_detect_setups(self):
        """Test 03: precomputed entry_signals row at T = strategy.detect_setups(T)."""
        dates = _mk_dates(30)
        syms = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        rng = np.random.default_rng(7)
        # Cross-sectional weekly reversal: lower values = more reversal candidate
        wr = pd.DataFrame(rng.uniform(-0.05, 0.05, size=(len(dates), len(syms))),
                          index=dates, columns=syms)
        # Vol_21d: all syms above filter
        vol = pd.DataFrame(0.5, index=dates, columns=syms)
        iv = _mk_panel(dates, syms, 0.0)
        er = _mk_panel(dates, syms, 0.0)
        prices = _mk_prices(dates, syms)

        cfg = IntradayReversalConfig(
            setup_quantile_threshold=0.40,  # bottom 40% quantile (so 2 syms armed)
            vol_filter_min_pct=0.0,         # no vol filter
            top_n=5,
        )
        strat = IntradayReversalStrategy(cfg)
        runner = IntradayReversalRunner(
            strategy=strat,
            weekly_reversal_signal_5d=wr, vol_21d=vol,
            intraday_volume_60m_zscore=iv, early_session_return_pct=er,
            price_df=prices,
        )
        entry_signals = runner._build_entry_signals()
        # Check at a sample bar
        sample_date = dates[10]
        expected = strat.detect_setups(wr, vol, sample_date)
        actual = entry_signals.loc[sample_date]
        actual_true = sorted(actual[actual].index.tolist())
        assert actual_true == sorted(expected), (
            f"entry_signals at {sample_date}: expected {expected}, got {actual_true}"
        )


# ──────────────────────────────────────────────────────────────────────────
# C. Exit signal construction (max_holding_days approximation)
# ──────────────────────────────────────────────────────────────────────────


class TestExitSignals:
    def test_04_exit_signal_at_setup_plus_offset(self):
        """Test 04: exit signal at T_setup + ttl + delay + hold.

        Use 3 syms with stable cross-section + AAA only dips to bottom
        quantile at bar 5; quantile filter excludes AAA on all other bars.
        """
        dates = _mk_dates(30)
        syms = ["AAA", "BBB", "CCC"]
        # Stable cross-section: BBB always lowest (gets setup every bar), CCC mid, AAA always highest
        # EXCEPT at bar 5 where AAA dips below BBB (so AAA also gets setup at bar 5)
        wr = pd.DataFrame(
            np.zeros((len(dates), len(syms))),
            index=dates, columns=syms,
        )
        wr["AAA"] = 0.9  # always high (not bottom)
        wr["BBB"] = 0.1  # always lowest (always setup)
        wr["CCC"] = 0.5  # middle
        wr.iloc[5, 0] = -1.0  # AAA dips at bar 5 → bottom quantile at bar 5
        vol = _mk_panel(dates, syms, 0.5)
        iv = _mk_panel(dates, syms, 0.0)
        er = _mk_panel(dates, syms, 0.0)
        prices = _mk_prices(dates, syms)
        cfg = IntradayReversalConfig(
            setup_quantile_threshold=0.40,  # bottom 40% → 1 sym per bar
            vol_filter_min_pct=0.0,
            confirmation_ttl_bars=1,
            execution_delay_bars=1,
            holding_period_max_days=5,
        )
        strat = IntradayReversalStrategy(cfg)
        runner = IntradayReversalRunner(
            strategy=strat,
            weekly_reversal_signal_5d=wr, vol_21d=vol,
            intraday_volume_60m_zscore=iv, early_session_return_pct=er,
            price_df=prices,
        )
        _ = runner._build_entry_signals()
        exit_signals = runner._build_exit_signals()
        # AAA setup at bar 5 → exit at bar 5 + 1 + 1 + 5 = bar 12
        expected_exit_date = dates[12]
        assert exit_signals.loc[expected_exit_date, "AAA"] == True
        # AAA has exactly 1 exit signal (only one setup)
        assert exit_signals["AAA"].sum() == 1


# ──────────────────────────────────────────────────────────────────────────
# D. Confirmation predicate
# ──────────────────────────────────────────────────────────────────────────


class TestConfirmationPredicate:
    def test_05_predicate_false_at_age_zero(self):
        """Test 05: predicate returns False at bar T (age 0); only fires at age=ttl."""
        dates = _mk_dates(10)
        syms = ["AAA"]
        wr = _mk_panel(dates, syms, 0.0)
        wr.iloc[3, 0] = -1.0
        vol = _mk_panel(dates, syms, 0.5)
        # Volume surge + positive early ret available at age=0 (the setup bar itself)
        iv = _mk_panel(dates, syms, 2.0)
        er = _mk_panel(dates, syms, 0.01)
        prices = _mk_prices(dates, syms)
        cfg = IntradayReversalConfig(
            setup_quantile_threshold=0.50, vol_filter_min_pct=0.0,
            confirmation_ttl_bars=1,
            volume_surge_at_open_60m_min=1.5,
        )
        strat = IntradayReversalStrategy(cfg)
        runner = IntradayReversalRunner(
            strategy=strat,
            weekly_reversal_signal_5d=wr, vol_21d=vol,
            intraday_volume_60m_zscore=iv, early_session_return_pct=er,
            price_df=prices,
        )
        # Build state at armed_at_bar=3 (setup bar)
        runner._build_entry_signals()
        predicate = runner._make_confirmation_predicate()

        class _S:
            symbol = "AAA"
            armed_at_bar = 3
        # At bar 3 (age=0) — predicate should return False
        assert predicate(_S(), 3, {}) == False
        # At bar 4 (age=1=ttl) — predicate should return True
        assert predicate(_S(), 4, {}) == True

    def test_06_predicate_false_when_volume_low(self):
        """Test 06: predicate False when volume surge < threshold."""
        dates = _mk_dates(10)
        syms = ["AAA"]
        wr = _mk_panel(dates, syms, 0.0)
        vol = _mk_panel(dates, syms, 0.5)
        iv = _mk_panel(dates, syms, 1.0)  # below 1.5 threshold
        er = _mk_panel(dates, syms, 0.01)
        prices = _mk_prices(dates, syms)
        strat = IntradayReversalStrategy(IntradayReversalConfig(
            volume_surge_at_open_60m_min=1.5, confirmation_ttl_bars=1,
        ))
        runner = IntradayReversalRunner(
            strategy=strat,
            weekly_reversal_signal_5d=wr, vol_21d=vol,
            intraday_volume_60m_zscore=iv, early_session_return_pct=er,
            price_df=prices,
        )
        runner._build_entry_signals()
        predicate = runner._make_confirmation_predicate()

        class _S:
            symbol = "AAA"
            armed_at_bar = 3
        assert predicate(_S(), 4, {}) == False

    def test_07_predicate_false_when_return_negative(self):
        """Test 07: predicate False when early session return ≤ 0."""
        dates = _mk_dates(10)
        syms = ["AAA"]
        wr = _mk_panel(dates, syms, 0.0)
        vol = _mk_panel(dates, syms, 0.5)
        iv = _mk_panel(dates, syms, 2.0)
        er = _mk_panel(dates, syms, -0.01)  # negative
        prices = _mk_prices(dates, syms)
        strat = IntradayReversalStrategy(IntradayReversalConfig(
            confirmation_ttl_bars=1, volume_surge_at_open_60m_min=1.5,
        ))
        runner = IntradayReversalRunner(
            strategy=strat,
            weekly_reversal_signal_5d=wr, vol_21d=vol,
            intraday_volume_60m_zscore=iv, early_session_return_pct=er,
            price_df=prices,
        )
        runner._build_entry_signals()
        predicate = runner._make_confirmation_predicate()

        class _S:
            symbol = "AAA"
            armed_at_bar = 3
        assert predicate(_S(), 4, {}) == False


# ──────────────────────────────────────────────────────────────────────────
# E. End-to-end synthetic backtest
# ──────────────────────────────────────────────────────────────────────────


class TestEndToEnd:
    def test_08_full_run_returns_backtest_result(self):
        """Test 08: runner.run() produces a BacktestResult."""
        dates = _mk_dates(60)
        syms = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        rng = np.random.default_rng(11)
        wr = pd.DataFrame(rng.uniform(-0.05, 0.05, size=(len(dates), len(syms))),
                          index=dates, columns=syms)
        vol = pd.DataFrame(0.5, index=dates, columns=syms)
        iv = pd.DataFrame(rng.uniform(0.0, 3.0, size=(len(dates), len(syms))),
                          index=dates, columns=syms)
        er = pd.DataFrame(rng.uniform(-0.02, 0.02, size=(len(dates), len(syms))),
                          index=dates, columns=syms)
        prices = _mk_prices(dates, syms)
        strat = IntradayReversalStrategy(IntradayReversalConfig(
            setup_quantile_threshold=0.20,
            vol_filter_min_pct=0.0,
            confirmation_ttl_bars=1,
            volume_surge_at_open_60m_min=1.5,
            holding_period_max_days=5,
            top_n=5,
        ))
        runner = IntradayReversalRunner(
            strategy=strat,
            weekly_reversal_signal_5d=wr, vol_21d=vol,
            intraday_volume_60m_zscore=iv, early_session_return_pct=er,
            price_df=prices,
            initial_capital=100_000.0,
        )
        result = runner.run()
        assert isinstance(result, BacktestResult)

    def test_09_setups_recorded_at_run(self):
        """Test 09: setups_by_date populated after run."""
        dates = _mk_dates(30)
        syms = ["AAA", "BBB", "CCC"]
        rng = np.random.default_rng(13)
        wr = pd.DataFrame(rng.uniform(-0.05, 0.05, size=(len(dates), len(syms))),
                          index=dates, columns=syms)
        vol = pd.DataFrame(0.5, index=dates, columns=syms)
        iv = pd.DataFrame(0.0, index=dates, columns=syms)
        er = pd.DataFrame(0.0, index=dates, columns=syms)
        prices = _mk_prices(dates, syms)
        strat = IntradayReversalStrategy(IntradayReversalConfig(
            setup_quantile_threshold=0.40, vol_filter_min_pct=0.0,
        ))
        runner = IntradayReversalRunner(
            strategy=strat,
            weekly_reversal_signal_5d=wr, vol_21d=vol,
            intraday_volume_60m_zscore=iv, early_session_return_pct=er,
            price_df=prices,
        )
        runner.run()
        setups = runner.setups_by_date()
        assert len(setups) == len(dates)
        # At least some dates produced setups
        non_empty = [d for d, s in setups.items() if len(s) > 0]
        assert len(non_empty) > 5

    def test_10_confirmation_drives_fills(self):
        """Test 10: with always-pass confirmation conditions, setups → fills."""
        dates = _mk_dates(40)
        syms = ["AAA", "BBB", "CCC"]
        # Force AAA to always be the bottom-quantile setup
        wr = pd.DataFrame(0.5, index=dates, columns=syms)
        wr["AAA"] = -1.0
        vol = pd.DataFrame(0.5, index=dates, columns=syms)
        # Force confirmation conditions to always pass
        iv = pd.DataFrame(2.5, index=dates, columns=syms)  # > 1.5 threshold
        er = pd.DataFrame(0.005, index=dates, columns=syms)  # > 0
        prices = _mk_prices(dates, syms)
        cfg = IntradayReversalConfig(
            setup_quantile_threshold=0.50, vol_filter_min_pct=0.0,
            confirmation_ttl_bars=1,
            volume_surge_at_open_60m_min=1.5,
            holding_period_max_days=5,
            top_n=5,
        )
        strat = IntradayReversalStrategy(cfg)
        runner = IntradayReversalRunner(
            strategy=strat,
            weekly_reversal_signal_5d=wr, vol_21d=vol,
            intraday_volume_60m_zscore=iv, early_session_return_pct=er,
            price_df=prices,
        )
        runner.run()
        history = runner.signal_history()
        confirmed = [s for s in history if s.status == SignalStatus.CONFIRMED]
        # AAA should have been confirmed multiple times
        assert any(s.symbol == "AAA" for s in confirmed)
        # Confirmed at age=1 (T+1)
        for s in confirmed:
            assert s.confirmed_at_bar - s.armed_at_bar == 1

    def test_11_no_setups_produces_empty_history(self):
        """Test 11: weekly_reversal_signal_5d all NaN → no setups → no history."""
        dates = _mk_dates(30)
        syms = ["AAA", "BBB"]
        wr = _mk_panel(dates, syms)  # all NaN
        vol = _mk_panel(dates, syms, 0.5)
        iv = _mk_panel(dates, syms, 0.0)
        er = _mk_panel(dates, syms, 0.0)
        prices = _mk_prices(dates, syms)
        strat = IntradayReversalStrategy(IntradayReversalConfig(
            setup_quantile_threshold=0.20, vol_filter_min_pct=0.0,
        ))
        runner = IntradayReversalRunner(
            strategy=strat,
            weekly_reversal_signal_5d=wr, vol_21d=vol,
            intraday_volume_60m_zscore=iv, early_session_return_pct=er,
            price_df=prices,
        )
        runner.run()
        assert len(runner.signal_history()) == 0

    def test_12_exit_signal_after_holding_period(self):
        """Test 12: position closed after holding_period_max_days from setup.

        Use 3-sym cross-section to enable quantile filter on only-AAA-at-5.
        """
        dates = _mk_dates(40)
        syms = ["AAA", "BBB", "CCC"]
        wr = pd.DataFrame(0.0, index=dates, columns=syms)
        # Differentiated wr values so quantile(0.40) selects only 1 sym per bar.
        # Default: AAA=0.9 (highest, never selected), BBB=0.7 (always bottom),
        # CCC=0.8 (middle). At bar 5: AAA dips to -1.0 → AAA bottom at bar 5.
        wr["AAA"] = 0.9
        wr["BBB"] = 0.7
        wr["CCC"] = 0.8
        wr.iloc[5, 0] = -1.0  # AAA setup at bar 5 only
        # Confirmation conditions: ONLY AAA at bar 6 (T+1) passes; others fail
        vol = _mk_panel(dates, syms, 0.5)
        iv = pd.DataFrame(0.0, index=dates, columns=syms)
        iv.iloc[6, 0] = 2.5  # AAA volume surge at bar 6 only
        er = pd.DataFrame(0.0, index=dates, columns=syms)
        er.iloc[6, 0] = 0.01  # AAA positive early return at bar 6 only
        prices = _mk_prices(dates, syms)
        cfg = IntradayReversalConfig(
            setup_quantile_threshold=0.40, vol_filter_min_pct=0.0,
            confirmation_ttl_bars=1,
            volume_surge_at_open_60m_min=1.5,
            execution_delay_bars=1,
            holding_period_max_days=5,
        )
        strat = IntradayReversalStrategy(cfg)
        runner = IntradayReversalRunner(
            strategy=strat,
            weekly_reversal_signal_5d=wr, vol_21d=vol,
            intraday_volume_60m_zscore=iv, early_session_return_pct=er,
            price_df=prices,
        )
        runner.run()
        weights = runner.weight_panel()
        # Setup AAA at bar 5 → ARMED → confirmed at bar 6 (predicate True at age=1)
        # → fill scheduled bar 7 → weight at bar 7 onward should be > 0
        # Exit signal at bar 12 (5+1+1+5) → exit fill at bar 13 → weight back to 0
        # Position open bars 7-12
        assert weights.iloc[8]["AAA"] > 0  # held
        assert weights.iloc[14]["AAA"] == 0  # closed after holding window
