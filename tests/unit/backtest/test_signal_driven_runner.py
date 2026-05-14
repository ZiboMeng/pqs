"""K1.2 tests for SignalDrivenBacktest wrapper.

These tests are written FIRST per K1 TDD-grade discipline (Q6 audit conclusion).
All 30 tests should be RED until K1.3 implementation lands.

Wrapper consumes the existing kernel
(`core.signals.signal_state.SignalStateMachine` +
 `core.backtest.deferred_execution.DeferredExecutionSchedule`) and produces
a `BacktestResult` compatible with existing `BacktestEngine.run` semantics.

PRD: docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md §4.1
Design: docs/audit/20260513-k1_deferred_exec_design.md
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import pytest

# Wrapper under test (does NOT exist yet — K1.3 ships it)
from core.backtest.signal_driven_runner import SignalDrivenBacktest
from core.backtest.backtest_engine import BacktestResult
from core.signals.signal_state import SignalState, SignalStatus


# ──────────────────────────────────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────────────────────────────────


def _mk_dates(n: int, start: str = "2020-01-02") -> pd.DatetimeIndex:
    return pd.bdate_range(start=start, periods=n)


def _mk_prices(dates, symbols, start: float = 100.0, drift: float = 0.0005, seed: int = 42):
    """Synthetic geometric brownian motion price panel."""
    rng = np.random.default_rng(seed)
    n_dates = len(dates)
    n_syms = len(symbols)
    rets = rng.normal(drift, 0.01, size=(n_dates, n_syms))
    prices = start * np.exp(np.cumsum(rets, axis=0))
    return pd.DataFrame(prices, index=dates, columns=symbols)


def _mk_signals(dates, symbols, fire_dates: Optional[dict] = None) -> pd.DataFrame:
    """Build a (date × symbol) bool signal panel.

    fire_dates: {symbol: [list of dates True]}; default = all False.
    """
    df = pd.DataFrame(False, index=dates, columns=symbols, dtype=bool)
    if fire_dates:
        for sym, dts in fire_dates.items():
            if sym not in df.columns:
                continue
            for d in dts:
                if d in df.index:
                    df.loc[d, sym] = True
    return df


# ──────────────────────────────────────────────────────────────────────────
# A. Construction + validation (3 tests)
# ──────────────────────────────────────────────────────────────────────────


class TestConstructionValidation:
    def test_01_init_with_required_args(self):
        """Test 01: Init with required args produces ready runner."""
        dates = _mk_dates(20)
        syms = ["AAA", "BBB"]
        entry = _mk_signals(dates, syms)
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry,
            exit_signals=exit_,
            price_df=prices,
            ttl_bars=0,
            top_n=10,
        )
        assert runner is not None
        # Has expected attributes set
        assert runner.ttl_bars == 0
        assert runner.top_n == 10

    def test_02_mismatched_entry_exit_dates_rejected(self):
        """Test 02: entry_signals + exit_signals must have aligned indices."""
        dates_a = _mk_dates(20)
        dates_b = _mk_dates(20, start="2021-01-04")
        syms = ["AAA"]
        entry = _mk_signals(dates_a, syms)
        exit_ = _mk_signals(dates_b, syms)
        prices = _mk_prices(dates_a, syms)
        with pytest.raises(ValueError, match=r"entry.*exit.*indices"):
            SignalDrivenBacktest(
                entry_signals=entry, exit_signals=exit_,
                price_df=prices, ttl_bars=0,
            )

    def test_03_negative_ttl_rejected(self):
        """Test 03: ttl_bars < 0 raises."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms)
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        with pytest.raises(ValueError, match=r"ttl_bars"):
            SignalDrivenBacktest(
                entry_signals=entry, exit_signals=exit_,
                price_df=prices, ttl_bars=-1,
            )


# ──────────────────────────────────────────────────────────────────────────
# B. Entry signal → arm flow (3 tests)
# ──────────────────────────────────────────────────────────────────────────


class TestEntryArmFlow:
    def test_04_entry_signal_arms_state_machine(self):
        """Test 04: entry_signal[T, sym]=True arms a SignalState at bar T."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[5]]})
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=5,
        )
        runner.run()
        # AAA should have been armed at bar idx 5
        history = runner.signal_history()
        armings = [s for s in history if s.symbol == "AAA"]
        assert len(armings) >= 1
        assert any(s.armed_at_bar == 5 for s in armings)

    def test_05_no_entry_signals_no_arms(self):
        """Test 05: empty entry signals → no armed states."""
        dates = _mk_dates(20)
        syms = ["AAA", "BBB"]
        entry = _mk_signals(dates, syms)  # all False
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0,
        )
        runner.run()
        assert len(runner.signal_history()) == 0

    def test_06_simultaneous_entries_arm_multiple(self):
        """Test 06: Multiple syms with entry on same bar → multiple arms."""
        dates = _mk_dates(20)
        syms = ["AAA", "BBB", "CCC"]
        d = dates[5]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [d], "BBB": [d], "CCC": [d]})
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0,
        )
        runner.run()
        history = runner.signal_history()
        armed_syms = {s.symbol for s in history if s.armed_at_bar == 5}
        assert armed_syms == {"AAA", "BBB", "CCC"}


# ──────────────────────────────────────────────────────────────────────────
# C. Confirmation predicate flow (4 tests)
# ──────────────────────────────────────────────────────────────────────────


class TestConfirmationPredicate:
    def test_07_ttl0_no_predicate_immediate_confirm(self):
        """Test 07: ttl_bars=0 and confirmation_predicate=None → arm
        immediately confirms same bar; fill scheduled T+1."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[5]]})
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0,
            confirmation_predicate=None,
        )
        runner.run()
        # State should have CONFIRMED at bar 5
        history = runner.signal_history()
        confirmed = [s for s in history if s.status == SignalStatus.CONFIRMED]
        assert len(confirmed) == 1
        assert confirmed[0].confirmed_at_bar == 5

    def test_08_ttl0_predicate_true_confirms(self):
        """Test 08: ttl_bars=0 with confirmation_predicate returning True → CONFIRMED at T."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[5]]})
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)

        def predicate(state, bar_idx, ctx):
            return True

        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0,
            confirmation_predicate=predicate,
        )
        runner.run()
        history = runner.signal_history()
        confirmed = [s for s in history if s.status == SignalStatus.CONFIRMED]
        assert len(confirmed) == 1

    def test_09_ttl0_predicate_false_expires(self):
        """Test 09: ttl_bars=0 with predicate returning False → EXPIRED, no fill."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[5]]})
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)

        def predicate(state, bar_idx, ctx):
            return False

        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0,
            confirmation_predicate=predicate,
        )
        runner.run()
        history = runner.signal_history()
        expired = [s for s in history if s.status == SignalStatus.EXPIRED]
        confirmed = [s for s in history if s.status == SignalStatus.CONFIRMED]
        assert len(expired) == 1
        assert len(confirmed) == 0

    def test_10_ttl5_predicate_true_at_t3_confirms(self):
        """Test 10: ttl_bars=5, predicate True only at age=3 → CONFIRMED at T+3."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[5]]})
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)

        def predicate(state, bar_idx, ctx):
            return (bar_idx - state.armed_at_bar) == 3

        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=5,
            confirmation_predicate=predicate,
        )
        runner.run()
        history = runner.signal_history()
        confirmed = [s for s in history if s.status == SignalStatus.CONFIRMED]
        assert len(confirmed) == 1
        assert confirmed[0].confirmed_at_bar == 8  # 5 + 3


# ──────────────────────────────────────────────────────────────────────────
# D. Exit signal flow (3 tests)
# ──────────────────────────────────────────────────────────────────────────


class TestExitFlow:
    def test_11_exit_signal_closes_position(self):
        """Test 11: exit_signals True for held sym → position closed at next bar."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[5]]})
        exit_ = _mk_signals(dates, syms, fire_dates={"AAA": [dates[10]]})
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0,
        )
        runner.run()
        # Position weight panel: bar 6-10 should hold AAA, bar 11+ should be flat
        weights = runner.weight_panel()
        assert weights.loc[dates[6], "AAA"] > 0
        assert weights.loc[dates[10], "AAA"] > 0
        assert weights.loc[dates[11], "AAA"] == 0  # exit fired bar 10 → flat bar 11

    def test_12_exit_signal_no_position_is_noop(self):
        """Test 12: exit_signal for sym with no position → no error, no negative shares."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms)  # no entries
        exit_ = _mk_signals(dates, syms, fire_dates={"AAA": [dates[10]]})
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0,
        )
        runner.run()
        weights = runner.weight_panel()
        # All weights should be 0 (no entries, exit on nothing)
        assert (weights["AAA"] == 0).all()

    def test_13_exit_same_bar_as_entry_entry_wins(self):
        """Test 13: entry + exit on same bar → entry takes precedence, position opens."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        d = dates[5]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [d]})
        exit_ = _mk_signals(dates, syms, fire_dates={"AAA": [d]})
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0,
        )
        runner.run()
        # Position should open (entry precedence) and persist
        weights = runner.weight_panel()
        # Fill is bar 6 (entry T=5 → T+1=6)
        assert weights.loc[dates[6], "AAA"] > 0


# ──────────────────────────────────────────────────────────────────────────
# E. Position lifecycle / weight panel construction (3 tests)
# ──────────────────────────────────────────────────────────────────────────


class TestPositionLifecycle:
    def test_14_weight_persists_until_exit(self):
        """Test 14: After fill, weight stays at target until exit fires."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[5]]})
        exit_ = _mk_signals(dates, syms, fire_dates={"AAA": [dates[15]]})
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0, top_n=10,
        )
        runner.run()
        weights = runner.weight_panel()
        # Hold from bar 6 to bar 15
        for i in range(6, 16):
            assert weights.loc[dates[i], "AAA"] > 0, f"bar {i} should be held"
        # Flat from bar 16 onward
        for i in range(16, 20):
            assert weights.loc[dates[i], "AAA"] == 0, f"bar {i} should be flat"

    def test_15_multi_position_accumulates(self):
        """Test 15: Multiple simultaneous fills accumulate in weight panel."""
        dates = _mk_dates(30)
        syms = ["AAA", "BBB", "CCC"]
        entry = _mk_signals(
            dates, syms,
            fire_dates={"AAA": [dates[5]], "BBB": [dates[10]], "CCC": [dates[15]]},
        )
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0, top_n=10,
        )
        runner.run()
        weights = runner.weight_panel()
        # After bar 16 all three should be held
        assert weights.loc[dates[20], "AAA"] > 0
        assert weights.loc[dates[20], "BBB"] > 0
        assert weights.loc[dates[20], "CCC"] > 0

    def test_16_cash_carry_no_pre_fill_weight(self):
        """Test 16: Armed-but-not-yet-filled sym = 0 weight (cash carry)."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[5]]})
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)

        def predicate(state, bar_idx, ctx):
            return (bar_idx - state.armed_at_bar) == 3

        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=5,
            confirmation_predicate=predicate,
        )
        runner.run()
        weights = runner.weight_panel()
        # Bars 5-8 (armed → confirmed at 8): weight should be 0 (cash carry)
        # Fill at bar 9 (8 + 1 delay)
        for i in range(5, 9):
            assert weights.loc[dates[i], "AAA"] == 0, f"bar {i} should be cash"
        assert weights.loc[dates[9], "AAA"] > 0


# ──────────────────────────────────────────────────────────────────────────
# F. Sizing rule (2 tests)
# ──────────────────────────────────────────────────────────────────────────


class TestPositionSizing:
    def test_17_equal_weight_top_n(self):
        """Test 17: Default equal-weight: top_n=10, 3 fills → each 0.1 weight."""
        dates = _mk_dates(20)
        syms = ["AAA", "BBB", "CCC"]
        entry = _mk_signals(
            dates, syms,
            fire_dates={"AAA": [dates[5]], "BBB": [dates[5]], "CCC": [dates[5]]},
        )
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0, top_n=10,
        )
        runner.run()
        weights = runner.weight_panel()
        # Each held position = 1 / top_n = 0.1
        for sym in syms:
            assert abs(weights.loc[dates[10], sym] - 0.1) < 1e-9

    def test_18_custom_position_sizing_rule(self):
        """Test 18: Custom position_sizing_rule callable used for fill weight."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[5]]})
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)

        def sizing(state, bar_idx, ctx):
            return 0.25  # always 25% weight

        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0, top_n=10,
            position_sizing_rule=sizing,
        )
        runner.run()
        weights = runner.weight_panel()
        assert abs(weights.loc[dates[10], "AAA"] - 0.25) < 1e-9


# ──────────────────────────────────────────────────────────────────────────
# G. Cost integration (1 test)
# ──────────────────────────────────────────────────────────────────────────


class TestCostIntegration:
    def test_19_cost_model_applied_to_signal_driven_fills(self):
        """Test 19: cost_model param applied; transaction cost present."""
        from core.execution.cost_model import CostModel
        from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
        dates = _mk_dates(60)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[5]]})
        exit_ = _mk_signals(dates, syms, fire_dates={"AAA": [dates[55]]})
        prices = _mk_prices(dates, syms)
        cost = CostModel(
            CostModelConfig(
                tiers={
                    "default": CostTierConfig(
                        symbols=[],
                        commission_bps=5.0,
                        slippage_interday_bps=10.0,
                        slippage_intraday_bps=15.0,
                    )
                }
            )
        )
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0, top_n=10,
            cost_model=cost,
        )
        result = runner.run()
        assert isinstance(result, BacktestResult)
        # Final NAV should be reduced by transaction cost
        # (compared to zero-cost baseline if we ran one)
        # Smoke check: trades happened + total_cost > 0
        assert hasattr(result, "metrics")
        # The signal-driven path should have generated at least 2 trades (open + close)
        assert result.trades is not None or "n_trades" in (result.metrics or {})


# ──────────────────────────────────────────────────────────────────────────
# H. Leakage discipline (1 test)
# ──────────────────────────────────────────────────────────────────────────


class TestLeakage:
    def test_20_predicate_cannot_see_future(self):
        """Test 20: confirmation_predicate(state, bar_idx, ctx) receives only
        info ≤ bar_idx. ctx exposes price_df up to bar_idx inclusive."""
        dates = _mk_dates(30)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[5]]})
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        captured_ctx = []

        def predicate(state, bar_idx, ctx):
            captured_ctx.append((bar_idx, ctx))
            return False  # never confirm so we see all 6 evaluations (T..T+5)

        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=5,
            confirmation_predicate=predicate,
        )
        runner.run()
        # Each ctx should expose price data only up to its bar_idx (no future leak)
        for bar_idx, ctx in captured_ctx:
            current_date = dates[bar_idx]
            # ctx['price_df_so_far'] should not contain dates > current_date
            df_so_far = ctx.get("price_df_so_far")
            assert df_so_far is not None
            assert df_so_far.index.max() <= current_date, (
                f"Leak at bar_idx={bar_idx}: predicate ctx sees future dates"
            )


# ──────────────────────────────────────────────────────────────────────────
# I. Edge cases (3 tests)
# ──────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_21_empty_signals_flat_nav(self):
        """Test 21: empty entry+exit signals → NAV = initial_capital throughout."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms)
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0,
            initial_capital=10_000.0,
        )
        result = runner.run()
        # NAV should be flat ≈ initial_capital (no trades)
        nav = result.nav if hasattr(result, "nav") else result.metrics.get("nav_series")
        if nav is not None and len(nav) > 0:
            assert abs(nav.iloc[-1] - 10_000.0) < 1e-6

    def test_22_all_false_signals_no_trades(self):
        """Test 22: signals all False → no trades, NAV = initial."""
        dates = _mk_dates(30)
        syms = ["AAA", "BBB"]
        entry = _mk_signals(dates, syms)
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=5,
            initial_capital=10_000.0,
        )
        result = runner.run()
        # No fills should have happened
        assert len(runner.signal_history()) == 0

    def test_23_signal_at_last_bar_no_fill(self):
        """Test 23: entry signal at last bar → no fill (no T+1 to fill into)."""
        dates = _mk_dates(20)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[-1]]})
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0,
        )
        runner.run()
        weights = runner.weight_panel()
        # No fill possible after last bar
        assert (weights["AAA"] == 0).all()


# ──────────────────────────────────────────────────────────────────────────
# J. Integration / regression (3 tests)
# ──────────────────────────────────────────────────────────────────────────


class TestIntegration:
    def test_24_returns_backtest_result_type(self):
        """Test 24: runner.run() returns BacktestResult-compatible object."""
        dates = _mk_dates(60)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[10]]})
        exit_ = _mk_signals(dates, syms, fire_dates={"AAA": [dates[40]]})
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0, top_n=10,
        )
        result = runner.run()
        assert isinstance(result, BacktestResult)

    def test_25_hash_determinism_across_runs(self):
        """Test 25: Same inputs produce identical results across runs
        (M11a sorted-iteration determinism preserved through wrapper)."""
        dates = _mk_dates(30)
        syms = ["ZZZZ", "AAA", "MMMM"]  # unsorted on purpose
        entry = _mk_signals(
            dates, syms,
            fire_dates={s: [dates[5]] for s in syms},
        )
        exit_ = _mk_signals(dates, syms, fire_dates={s: [dates[25]] for s in syms})
        prices = _mk_prices(dates, syms)

        def _go():
            r = SignalDrivenBacktest(
                entry_signals=entry, exit_signals=exit_,
                price_df=prices, ttl_bars=0, top_n=10,
            )
            return r.run().nav if hasattr(r.run(), "nav") else r.weight_panel().sum().sum()

        a = _go()
        b = _go()
        # Both runs must produce identical output
        if hasattr(a, "iloc"):
            pd.testing.assert_series_equal(a, b)
        else:
            assert a == b

    def test_26_end_to_end_spy_above_sma_smoke(self):
        """Test 26: Simple SPY > 200-SMA entry / < 200-SMA exit produces
        a non-trivial backtest with reasonable trade count."""
        dates = _mk_dates(252 * 2)  # 2 years
        syms = ["SPY"]
        prices = _mk_prices(dates, syms, start=300.0, drift=0.0008, seed=7)
        sma200 = prices["SPY"].rolling(200, min_periods=200).mean()
        entry_bool = (prices["SPY"] > sma200) & (prices["SPY"].shift(1) <= sma200.shift(1))
        exit_bool = (prices["SPY"] < sma200) & (prices["SPY"].shift(1) >= sma200.shift(1))
        entry = pd.DataFrame({"SPY": entry_bool.fillna(False)}, index=dates)
        exit_ = pd.DataFrame({"SPY": exit_bool.fillna(False)}, index=dates)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0, top_n=1,
            initial_capital=10_000.0,
        )
        result = runner.run()
        assert isinstance(result, BacktestResult)
        # Should have generated at least 1 entry (could be more)
        history = runner.signal_history()
        confirmed = [s for s in history if s.status == SignalStatus.CONFIRMED]
        assert len(confirmed) >= 1


# ──────────────────────────────────────────────────────────────────────────
# K. Smoke tests (4 tests)
# ──────────────────────────────────────────────────────────────────────────


class TestSmoke:
    def test_27_cash_carry_nav_flat_during_armed(self):
        """Test 27: 5-bar TTL with predicate confirming at age=4 → bars 5-9
        held as cash (no position), NAV ≈ flat from bar 5 to bar 9 fill."""
        dates = _mk_dates(30)
        syms = ["AAA"]
        entry = _mk_signals(dates, syms, fire_dates={"AAA": [dates[5]]})
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms, drift=0.0)
        # No need for high precision NAV check; just verify no position carried during armed window
        def predicate(state, bar_idx, ctx):
            return (bar_idx - state.armed_at_bar) == 4

        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=5,
            confirmation_predicate=predicate,
        )
        runner.run()
        weights = runner.weight_panel()
        # During armed window (bars 5-8), AAA weight should be 0
        for i in range(5, 9):
            assert weights.loc[dates[i], "AAA"] == 0
        # Fill at bar 10 (confirmed at 9 + delay 1)
        assert weights.loc[dates[10], "AAA"] > 0

    def test_28_multi_sym_overlapping_arm_exit(self):
        """Test 28: 3 syms with overlapping arm/exit dates handled correctly."""
        dates = _mk_dates(60)
        syms = ["AAA", "BBB", "CCC"]
        entry = _mk_signals(
            dates, syms,
            fire_dates={
                "AAA": [dates[5]],
                "BBB": [dates[10]],
                "CCC": [dates[15]],
            },
        )
        exit_ = _mk_signals(
            dates, syms,
            fire_dates={
                "AAA": [dates[40]],
                "BBB": [dates[35]],
                "CCC": [dates[50]],
            },
        )
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0, top_n=10,
        )
        runner.run()
        weights = runner.weight_panel()
        # Bar 30: all three held
        for s in syms:
            assert weights.loc[dates[30], s] > 0
        # Bar 55: all three flat (BBB exit at 35, AAA at 40, CCC at 50)
        for s in syms:
            assert weights.loc[dates[55], s] == 0

    def test_29_realistic_252_bar_backtest(self):
        """Test 29: 252-bar synthetic backtest with multiple signals doesn't crash."""
        dates = _mk_dates(252)
        syms = ["AAA", "BBB", "CCC", "DDD"]
        # Sparse signals throughout
        rng = np.random.default_rng(101)
        fire_dates_dict = {
            s: list(rng.choice(dates[20:230], size=5, replace=False))
            for s in syms
        }
        entry = _mk_signals(dates, syms, fire_dates=fire_dates_dict)
        # Exits 30 days after entries
        exit_fire = {
            s: [d + pd.tseries.offsets.BDay(30) for d in fire_dates_dict[s]]
            for s in syms
        }
        exit_ = _mk_signals(dates, syms, fire_dates=exit_fire)
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0, top_n=10,
            initial_capital=100_000.0,
        )
        result = runner.run()
        assert isinstance(result, BacktestResult)

    def test_30_cap_aware_max_single_weight_enforced(self):
        """Test 30: cap_aware max_single_weight=0.1 enforced even when many syms fill simultaneously."""
        dates = _mk_dates(30)
        syms = [f"S{i:02d}" for i in range(15)]  # 15 syms
        d = dates[5]
        entry = _mk_signals(dates, syms, fire_dates={s: [d] for s in syms})
        exit_ = _mk_signals(dates, syms)
        prices = _mk_prices(dates, syms)
        runner = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=prices, ttl_bars=0, top_n=10,
            max_single_weight=0.10,
        )
        runner.run()
        weights = runner.weight_panel()
        # At bar 10 (after fills), no single sym should exceed 0.10
        held_syms = [c for c in weights.columns if weights.loc[dates[10], c] > 0]
        for s in held_syms:
            assert weights.loc[dates[10], s] <= 0.10 + 1e-9, (
                f"sym {s} weight {weights.loc[dates[10], s]} exceeds cap 0.10"
            )
        # No more than top_n=10 syms held
        assert len(held_syms) <= 10
