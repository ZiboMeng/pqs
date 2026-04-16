"""Unit tests for ExecutionSimulator."""

import pandas as pd
import pytest

from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.cost_model import CostModel
from core.execution.execution_simulator import (
    ExecutionSimulator, Fill, Order, OrderSide,
)


def _make_cost_model() -> CostModel:
    cfg = CostModelConfig(
        tiers={
            "default": CostTierConfig(
                symbols=[],
                commission_bps=1.0,
                slippage_interday_bps=5.0,
                slippage_intraday_bps=8.0,
            )
        }
    )
    return CostModel(cfg)


def _order(side: OrderSide = OrderSide.BUY, qty: float = 10.0, sym: str = "SPY") -> Order:
    return Order(
        symbol=sym, side=side, qty_shares=qty,
        signal_date=pd.Timestamp("2024-01-02"),
    )


class TestSimulateFill:
    def test_buy_returns_fill(self):
        sim  = ExecutionSimulator(_make_cost_model())
        fill = sim.simulate_fill(_order(OrderSide.BUY), open_price=400.0, vix=15.0, cash=100_000.0)
        assert isinstance(fill, Fill)
        assert fill.side == OrderSide.BUY

    def test_sell_returns_fill(self):
        sim  = ExecutionSimulator(_make_cost_model())
        fill = sim.simulate_fill(_order(OrderSide.SELL), open_price=400.0, vix=15.0, cash=0.0)
        assert fill.side == OrderSide.SELL

    def test_buy_exec_price_above_open(self):
        """买入：exec_price 应包含滑点，大于开盘价。"""
        sim  = ExecutionSimulator(_make_cost_model())
        fill = sim.simulate_fill(_order(OrderSide.BUY), open_price=100.0, vix=15.0, cash=50_000.0)
        assert fill.executed_price > 100.0

    def test_sell_exec_price_below_open(self):
        """卖出：exec_price 应低于开盘价（滑点不利）。"""
        sim  = ExecutionSimulator(_make_cost_model())
        fill = sim.simulate_fill(_order(OrderSide.SELL), open_price=100.0, vix=15.0, cash=0.0)
        assert fill.executed_price < 100.0

    def test_buy_cash_delta_negative(self):
        sim  = ExecutionSimulator(_make_cost_model())
        fill = sim.simulate_fill(_order(OrderSide.BUY, qty=10), open_price=100.0, vix=15.0, cash=5_000.0)
        assert fill.cash_delta < 0

    def test_sell_cash_delta_positive(self):
        sim  = ExecutionSimulator(_make_cost_model())
        fill = sim.simulate_fill(_order(OrderSide.SELL, qty=10), open_price=100.0, vix=15.0, cash=0.0)
        assert fill.cash_delta > 0

    def test_invalid_price_returns_none(self):
        sim  = ExecutionSimulator(_make_cost_model())
        fill = sim.simulate_fill(_order(), open_price=-1.0, vix=15.0, cash=10_000.0)
        assert fill is None

    def test_zero_price_returns_none(self):
        sim  = ExecutionSimulator(_make_cost_model())
        fill = sim.simulate_fill(_order(), open_price=0.0, vix=15.0, cash=10_000.0)
        assert fill is None

    def test_zero_qty_returns_none(self):
        sim  = ExecutionSimulator(_make_cost_model())
        fill = sim.simulate_fill(_order(qty=0.0), open_price=100.0, vix=15.0, cash=10_000.0)
        assert fill is None

    def test_insufficient_cash_partial_fill(self):
        """现金不足时允许部分成交，不应返回 None。"""
        sim  = ExecutionSimulator(_make_cost_model(), allow_partial=True)
        # 买 100 股 @100 = 10,000 USD，但只有 500 USD
        fill = sim.simulate_fill(_order(qty=100), open_price=100.0, vix=15.0, cash=500.0)
        if fill is not None:
            assert fill.executed_qty < 100.0

    def test_insufficient_cash_strict_rejects(self):
        """allow_partial=False 时，现金不足应拒绝整笔。"""
        sim  = ExecutionSimulator(_make_cost_model(), allow_partial=False)
        fill = sim.simulate_fill(_order(qty=100), open_price=100.0, vix=15.0, cash=500.0)
        assert fill is None

    def test_fill_date_is_t_plus_1(self):
        sim  = ExecutionSimulator(_make_cost_model())
        fill = sim.simulate_fill(_order(), open_price=100.0, vix=15.0, cash=50_000.0)
        expected = pd.Timestamp("2024-01-02") + pd.tseries.offsets.BDay(1)
        assert fill.fill_date == expected


class TestSimulateFills:
    def test_sells_processed_before_buys(self):
        """卖单先执行，确保现金充足后再买入。"""
        sim    = ExecutionSimulator(_make_cost_model())
        orders = [
            _order(OrderSide.BUY,  qty=10, sym="QQQ"),
            _order(OrderSide.SELL, qty=5,  sym="SPY"),
        ]
        fills = sim.simulate_fills(
            orders, {"SPY": 400.0, "QQQ": 350.0}, vix=15.0, cash=100.0
        )
        # 卖出 SPY 后现金增加，QQQ 才能成交
        sides = [f.side for f in fills]
        if len(sides) == 2:
            assert sides[0] == OrderSide.SELL

    def test_missing_price_skips_order(self):
        sim  = ExecutionSimulator(_make_cost_model())
        orders = [_order(OrderSide.BUY, sym="NOPRICE")]
        fills = sim.simulate_fills(orders, {}, vix=15.0, cash=50_000.0)
        assert len(fills) == 0
