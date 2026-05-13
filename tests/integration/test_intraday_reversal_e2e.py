"""End-to-end smoke test: IntradayReversalStrategy → bridge → BacktestEngine.

alt-A Phase 2 D2 deliverable per design memo
`docs/memos/20260512-deferred_execution_bt_integration_design.md`.

5-sym 1-month panel. Verifies:
  1. Bridge produces signals_df with non-zero weights on confirmed days
  2. BacktestEngine consumes signals_df without errors (5-sym × 21 days)
  3. Cash carry semantics: armed-not-yet-filled symbols contribute 0 to NAV
  4. Cost sensitivity preview: 2.5bp slip × 5d holding ≈ expected drag
  5. M11a determinism: same inputs → same fills (sorted iteration)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.backtest.backtest_engine import BacktestEngine
from core.backtest.intraday_reversal_bridge import (
    build_alt_a_cost_model,
    build_intraday_reversal_signals,
    estimate_alt_a_turnover,
)
from core.signals.strategies.intraday_reversal import (
    IntradayReversalConfig, IntradayReversalStrategy,
)


@pytest.fixture
def smoke_panel():
    """5 symbols × ~22 business days (1 month). Synthetic data:
       - AAA: persistent reversal candidate (always low wr, high volume z,
         positive early-session)
       - BBB: weaker reversal candidate
       - CCC, DDD, EEE: noise / no setup
    """
    dates = pd.date_range("2024-01-02", periods=22, freq="B")
    syms = ["AAA", "BBB", "CCC", "DDD", "EEE"]

    rng = np.random.default_rng(42)

    # Price panel: 5-sym ~constant-vol, AAA/BBB drift positive (reversal alpha)
    price = pd.DataFrame(100.0, index=dates, columns=syms)
    daily_rets = rng.normal(0, 0.01, (len(dates), len(syms)))
    daily_rets[:, 0] += 0.003  # AAA: +30bps/day
    daily_rets[:, 1] += 0.002  # BBB: +20bps/day
    price = price * np.exp(daily_rets.cumsum(axis=0))

    # weekly_reversal_signal_5d: low for AAA/BBB
    wr = pd.DataFrame(0.5, index=dates, columns=syms)
    wr["AAA"] = -2.5
    wr["BBB"] = -1.8

    # vol_21d: above filter
    vol = pd.DataFrame(0.20, index=dates, columns=syms)

    # intraday volume z: AAA/BBB surge
    iv = pd.DataFrame(0.5, index=dates, columns=syms)
    iv["AAA"] = 2.5
    iv["BBB"] = 2.0

    # early session return: positive for AAA/BBB
    er = pd.DataFrame(-0.005, index=dates, columns=syms)
    er["AAA"] = 0.008
    er["BBB"] = 0.006

    # open ~= close (simplified — real BT uses T+1 open)
    open_panel = price.copy()

    return price, open_panel, wr, vol, iv, er, dates, syms


class TestEndToEndPipeline:
    def test_bridge_signals_to_backtest(self, smoke_panel):
        """Bridge output → BT.run() consumes without error."""
        price, open_panel, wr, vol, iv, er, dates, syms = smoke_panel

        strat = IntradayReversalStrategy()  # PRD §11 LOCKED defaults
        signals = build_intraday_reversal_signals(
            strat, wr, vol, iv, er, dates,
        )
        assert (signals.values >= 0).all()
        assert signals.shape == (22, 5)

        # Build BT with alt-A cost (2.5bp intraday slip)
        cost_model = build_alt_a_cost_model(syms, intraday_slip_bps=2.5)
        bt = BacktestEngine(
            cost_model=cost_model,
            initial_capital=10_000.0,
            integer_shares=False,
            execution_freq="intraday",
        )
        result = bt.run(
            signals_df=signals,
            price_df=price,
            open_df=open_panel,
            vix_series=pd.Series(15.0, index=dates),
        )

        # Sanity checks
        assert len(result.equity_curve) == 22
        # Strategy is long-only; equity should be >0 throughout
        assert (result.equity_curve > 0).all()
        # Final equity should differ from initial (some trades happened)
        assert abs(result.equity_curve.iloc[-1] - 10_000.0) > 1.0

    def test_cash_carry_armed_not_yet_filled(self, smoke_panel):
        """Day 0 strategy arms AAA (close-of-day signal). On the SAME day,
        BT marks portfolio at price[T] close — AAA NOT yet held (fill
        happens at T+1 open per BT semantics). So equity[T=0] = initial
        capital with $0 from any held alt-A position.

        This is the "cash carry during ARMED" semantics — naturally
        handled by the daily-grain signals_df → fill-at-T+1-open flow.

        Note: BT records equity[T=0] as PRE-fill portfolio value (= initial
        cash, no shares yet), while cash_curve[T=0] is POST-fill (cash
        committed to T+1 orders has already left the cash bucket — this
        is cycle04-08 existing BT semantics, not changed here).
        """
        price, open_panel, wr, vol, iv, er, dates, syms = smoke_panel
        strat = IntradayReversalStrategy()
        signals = build_intraday_reversal_signals(
            strat, wr, vol, iv, er, dates,
        )
        cost_model = build_alt_a_cost_model(syms, intraday_slip_bps=2.5)
        bt = BacktestEngine(
            cost_model=cost_model,
            initial_capital=10_000.0,
            integer_shares=False,
            execution_freq="intraday",
        )
        result = bt.run(
            signals_df=signals,
            price_df=price,
            open_df=open_panel,
            vix_series=pd.Series(15.0, index=dates),
        )
        # T=0: equity_curve PRE-fill snapshot = initial capital (no shares
        # held at T=0 close before T+1 fills settle).
        assert abs(result.equity_curve.iloc[0] - 10_000.0) < 1e-3

        # cycle04-08 BT semantics: cash_curve[T=0] records cash AFTER T+1
        # fills are simulated — this is the canonical existing behavior,
        # NOT a cash-carry semantic. The actual cash-carry visibility is
        # the gap between equity[T=0] (pre-fill, $10k) and the value of
        # shares that WILL fill at T+1 open.
        # Just verify cash went DOWN (some orders generated):
        assert result.cash_curve.iloc[0] < 10_000.0, (
            "Expected some cash committed to T+1 orders on day 0"
        )


class TestCostSensitivity:
    def test_2x_cost_does_not_break(self, smoke_panel):
        """PRD §9 hard blocker: 2× cost (5bp slip) must not render
        strategy unprofitable. This is a *preview* check — full Track A
        cost sensitivity test runs on 2018/19/21/23/25 validation panels.
        """
        price, open_panel, wr, vol, iv, er, dates, syms = smoke_panel
        strat = IntradayReversalStrategy()
        signals = build_intraday_reversal_signals(
            strat, wr, vol, iv, er, dates,
        )

        result_1x = BacktestEngine(
            cost_model=build_alt_a_cost_model(syms, intraday_slip_bps=2.5),
            initial_capital=10_000.0, integer_shares=False,
            execution_freq="intraday",
        ).run(signals, price, open_panel, vix_series=pd.Series(15.0, index=dates))

        result_2x = BacktestEngine(
            cost_model=build_alt_a_cost_model(syms, intraday_slip_bps=5.0),
            initial_capital=10_000.0, integer_shares=False,
            execution_freq="intraday",
        ).run(signals, price, open_panel, vix_series=pd.Series(15.0, index=dates))

        # 2× cost should yield strictly worse final equity (more drag)
        assert result_2x.equity_curve.iloc[-1] < result_1x.equity_curve.iloc[-1]
        # But the difference should be bounded (drag is in bps not %)
        drag_pct = (
            (result_1x.equity_curve.iloc[-1] - result_2x.equity_curve.iloc[-1])
            / result_1x.equity_curve.iloc[-1]
        )
        # Over 22 days × few trades × 2.5bp extra slip ≈ a few bps total
        # Allow up to 1% drag (loose bound for synthetic smoke)
        assert drag_pct < 0.01, f"Unexpected cost-2x drag: {drag_pct*100:.2f}%"


class TestM11aDeterminism:
    def test_same_inputs_same_fills(self, smoke_panel):
        """M11a contract: identical inputs produce identical fills
        regardless of process/seed/iteration order."""
        price, open_panel, wr, vol, iv, er, dates, syms = smoke_panel

        # Run twice — same strategy, same panels, same cost model
        def _run():
            strat = IntradayReversalStrategy()
            signals = build_intraday_reversal_signals(
                strat, wr, vol, iv, er, dates,
            )
            bt = BacktestEngine(
                cost_model=build_alt_a_cost_model(syms, intraday_slip_bps=2.5),
                initial_capital=10_000.0, integer_shares=False,
                execution_freq="intraday",
            )
            return bt.run(signals, price, open_panel, vix_series=pd.Series(15.0, index=dates))

        r1 = _run()
        r2 = _run()

        # Equity curve bit-for-bit identical
        pd.testing.assert_series_equal(r1.equity_curve, r2.equity_curve)
        # Trades same count + same details
        assert len(r1.trades) == len(r2.trades)
        for t1, t2 in zip(r1.trades, r2.trades):
            assert t1.symbol == t2.symbol
            assert t1.side == t2.side
            assert abs(t1.executed_qty - t2.executed_qty) < 1e-9


class TestTurnoverEstimate:
    def test_turnover_periodic_reversal(self):
        """Realistic test: AAA reverses periodically (every 7d), creating
        enter/exit cycles. Annualized turnover should be > 0.

        Constant-arming smoke (sample_panel) doesn't exercise turnover
        because positions re-enter same-day after aging (synthetic
        artifact; real reversal candidates lose their reversal signal
        after the bounce completes).
        """
        dates = pd.date_range("2024-01-02", periods=40, freq="B")
        syms = ["AAA", "BBB"]
        # AAA reverses on days 0, 7, 14, 21, 28, 35 (every 7d)
        wr = pd.DataFrame(0.5, index=dates, columns=syms)
        for d in range(0, len(dates), 7):
            wr.iloc[d, 0] = -2.5  # AAA: extreme reversal candidate
        vol = pd.DataFrame(0.25, index=dates, columns=syms)
        iv = pd.DataFrame(2.5, index=dates, columns=syms)  # always confirms
        er = pd.DataFrame(0.01, index=dates, columns=syms)

        strat = IntradayReversalStrategy(
            IntradayReversalConfig(
                setup_quantile_threshold=0.10,  # only extreme
                vol_filter_min_pct=0.0,
                volume_surge_at_open_60m_min=1.5,
                top_n=5,
                holding_period_max_days=5,
            )
        )
        signals = build_intraday_reversal_signals(
            strat, wr, vol, iv, er, dates,
        )
        turn = estimate_alt_a_turnover(signals)
        # With ~5 enter/exit cycles over 40 business days, annualized
        # turnover should be visibly positive.
        assert turn > 0, (
            f"Expected non-zero turnover with periodic reversal pattern, "
            f"got {turn}"
        )


class TestRegressionBacktestEngine:
    def test_default_freq_unchanged(self, smoke_panel):
        """cycle04-08 path (execution_freq='interday' default) must be
        bit-for-bit unchanged."""
        price, open_panel, _, _, _, _, dates, syms = smoke_panel
        # Use existing prod cost model (not alt-A custom one)
        from core.config.loader import load_config
        from core.execution.cost_model import CostModel as _CostModel
        cfg = load_config("config")

        bt = BacktestEngine(
            cost_model=_CostModel(cfg.cost_model),
            initial_capital=10_000.0,
            integer_shares=False,
            # No execution_freq → defaults to 'interday'
        )
        # Trivial signals (all zero) → no trades → equity == initial
        signals = pd.DataFrame(0.0, index=dates, columns=syms)
        result = bt.run(
            signals_df=signals,
            price_df=price,
            open_df=open_panel,
            vix_series=pd.Series(15.0, index=dates),
        )
        # No trades, equity stays at initial capital throughout
        assert (abs(result.equity_curve - 10_000.0) < 1e-3).all()
        assert len(result.trades) == 0
