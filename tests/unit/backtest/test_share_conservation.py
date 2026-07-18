"""Accounting invariants for gap-open rebalances and actual fill bars."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.backtest.backtest_engine import BacktestEngine
from core.config.loader import load_config
from core.execution.cost_model import CostModel
from core.execution.execution_simulator import OrderSide


def _cost_model() -> CostModel:
    return CostModel(load_config(Path("config")).cost_model)


@pytest.mark.parametrize("liquidation_open", [50.0, 200.0])
def test_liquidation_never_sells_more_than_held_after_gap(liquidation_open: float):
    dates = pd.DatetimeIndex(
        [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04")]
    )
    closes = pd.DataFrame({"SPY": [100.0, 100.0, liquidation_open]}, index=dates)
    opens = pd.DataFrame({"SPY": [100.0, 100.0, liquidation_open]}, index=dates)
    targets = pd.DataFrame({"SPY": [1.0, 0.0, 0.0]}, index=dates)

    result = BacktestEngine(
        _cost_model(),
        initial_capital=10_000.0,
        min_trade_usd=0.0,
        rebalance_threshold=0.0,
        integer_shares=False,
    ).run(targets, closes, opens)

    buys = [f for f in result.trades if f.side is OrderSide.BUY]
    sells = [f for f in result.trades if f.side is OrderSide.SELL]
    assert len(buys) == 1
    assert len(sells) == 1
    assert sells[0].executed_qty <= buys[0].executed_qty + 1e-9
    assert result.positions.iloc[-1].get("SPY", 0.0) == pytest.approx(0.0, abs=1e-9)

    # A 50% gap-down must approximately halve the account.  The historical
    # bug sold ~2x the holding and left NAV near 10k by creating cash.
    if liquidation_open == 50.0:
        assert 4_800.0 < float(result.equity_curve.iloc[-1]) < 5_100.0


def test_fill_date_is_the_actual_next_panel_bar_not_calendar_inference():
    # The panel intentionally omits Fri 2024-01-05.  The selected execution
    # price is Monday's open, so the ledger must also say Monday.
    dates = pd.DatetimeIndex(
        [pd.Timestamp("2024-01-04"), pd.Timestamp("2024-01-08")]
    )
    closes = pd.DataFrame({"SPY": [100.0, 101.0]}, index=dates)
    opens = pd.DataFrame({"SPY": [100.0, 101.0]}, index=dates)
    targets = pd.DataFrame({"SPY": [0.5, 0.5]}, index=dates)

    result = BacktestEngine(
        _cost_model(), min_trade_usd=0.0, rebalance_threshold=0.0
    ).run(targets, closes, opens)

    assert len(result.trades) == 1
    assert result.trades[0].signal_date == pd.Timestamp("2024-01-04")
    assert result.trades[0].fill_date == pd.Timestamp("2024-01-08")
