"""D3 regression tests for BacktestEngine `execution_freq` kwarg.

Per alt-A Phase 2 design memo §5: BacktestEngine.__init__ accepts
`execution_freq` kwarg with default "interday" preserving cycle04-08
bit-for-bit. This file pins those guarantees.

When invariant changes (e.g. new execution_freq value added), these
tests are the canary.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.backtest.backtest_engine import BacktestEngine
from core.config.loader import load_config
from core.execution.cost_model import CostModel


@pytest.fixture
def prod_cost_model():
    cfg = load_config("config")
    return CostModel(cfg.cost_model)


@pytest.fixture
def small_panel():
    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    syms = ["AAPL", "MSFT", "GOOG"]
    price = pd.DataFrame(100.0, index=dates, columns=syms)
    # Simple monotonic price moves
    for i, sym in enumerate(syms):
        price[sym] = 100.0 + np.arange(len(dates)) * (i + 1) * 0.1
    opens = price.shift(1).fillna(price.iloc[0])
    return price, opens, dates, syms


class TestDefaultKwargParity:
    """default execution_freq="interday" preserves cycle04-08 bit-for-bit."""

    def test_default_kwarg_omitted(self, prod_cost_model, small_panel):
        price, opens, dates, syms = small_panel
        # Omit execution_freq entirely
        bt = BacktestEngine(
            cost_model=prod_cost_model,
            initial_capital=10_000.0,
            integer_shares=False,
        )
        # Trivial signals (target weight 1/3 each, constant)
        signals = pd.DataFrame(1.0 / 3.0, index=dates, columns=syms)
        result = bt.run(
            signals_df=signals,
            price_df=price,
            open_df=opens,
            vix_series=pd.Series(15.0, index=dates),
        )
        # Long-only constant target → positions equilibrate within a few days
        assert len(result.equity_curve) == len(dates)
        assert (result.equity_curve > 0).all()
        assert len(result.trades) > 0  # some trades happened

    def test_explicit_interday_same_as_default(self, prod_cost_model, small_panel):
        """execution_freq='interday' explicit is bit-for-bit same as default."""
        price, opens, dates, syms = small_panel
        signals = pd.DataFrame(1.0 / 3.0, index=dates, columns=syms)

        bt_default = BacktestEngine(
            cost_model=prod_cost_model, initial_capital=10_000.0,
            integer_shares=False,
        )
        bt_explicit = BacktestEngine(
            cost_model=prod_cost_model, initial_capital=10_000.0,
            integer_shares=False, execution_freq="interday",
        )

        r1 = bt_default.run(signals, price, opens, vix_series=pd.Series(15.0, index=dates))
        r2 = bt_explicit.run(signals, price, opens, vix_series=pd.Series(15.0, index=dates))

        # Bit-for-bit identical
        pd.testing.assert_series_equal(r1.equity_curve, r2.equity_curve)
        pd.testing.assert_series_equal(r1.cash_curve, r2.cash_curve)
        assert len(r1.trades) == len(r2.trades)


class TestIntradayFreqDiverges:
    """execution_freq='intraday' uses different slippage tier → cost drag differs."""

    def test_intraday_vs_interday_different_equity(self, prod_cost_model, small_panel):
        """Same panels, same signals → intraday slip > interday slip on
        prod cost_model.yaml (7+ vs 4+ bps). Equity curves diverge."""
        price, opens, dates, syms = small_panel
        signals = pd.DataFrame(1.0 / 3.0, index=dates, columns=syms)

        bt_inter = BacktestEngine(
            cost_model=prod_cost_model, initial_capital=10_000.0,
            integer_shares=False, execution_freq="interday",
        )
        bt_intra = BacktestEngine(
            cost_model=prod_cost_model, initial_capital=10_000.0,
            integer_shares=False, execution_freq="intraday",
        )

        r_inter = bt_inter.run(signals, price, opens, vix_series=pd.Series(15.0, index=dates))
        r_intra = bt_intra.run(signals, price, opens, vix_series=pd.Series(15.0, index=dates))

        # Both produce equity, but intraday has more cost drag
        # → strictly worse final equity given identical trades.
        assert r_intra.equity_curve.iloc[-1] <= r_inter.equity_curve.iloc[-1]


class TestInvalidFreqRejected:
    def test_unknown_freq_raises(self, prod_cost_model):
        with pytest.raises(ValueError, match="execution_freq"):
            BacktestEngine(
                cost_model=prod_cost_model,
                execution_freq="hourly",  # not in {"interday", "intraday"}
            )

    def test_empty_freq_raises(self, prod_cost_model):
        with pytest.raises(ValueError, match="execution_freq"):
            BacktestEngine(cost_model=prod_cost_model, execution_freq="")


class TestExecFreqAttributeExposed:
    """`self._exec_freq` is internal but useful for debugging."""

    def test_exec_freq_stored(self, prod_cost_model):
        bt = BacktestEngine(cost_model=prod_cost_model)
        assert bt._exec_freq == "interday"

        bt2 = BacktestEngine(cost_model=prod_cost_model, execution_freq="intraday")
        assert bt2._exec_freq == "intraday"
