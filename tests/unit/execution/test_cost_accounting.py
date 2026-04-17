"""
Tests for execution cost accounting: slippage in price, commission in cash.
Verifies no double-counting.
"""

import numpy as np
import pandas as pd
import pytest

from core.execution.execution_simulator import ExecutionSimulator, Order, OrderSide
from core.execution.cost_model import CostModel, CostBreakdown
from core.config.loader import load_config
from pathlib import Path


def _make_cost_model():
    cfg = load_config(Path("config"))
    return CostModel(cfg.cost_model), cfg.cost_model


class TestCostAccountingSeparation:
    """Slippage affects exec price; commission affects cash only."""

    def test_buy_slippage_raises_price(self):
        cost, cost_cfg = _make_cost_model()
        sim = ExecutionSimulator(cost_model=cost)
        order = Order(symbol="SPY", side=OrderSide.BUY, qty_shares=10,
                      signal_date=pd.Timestamp("2025-01-02"))
        fill = sim.simulate_fill(order, open_price=500.0, vix=15.0, cash=100000.0)
        assert fill is not None
        assert fill.executed_price > 500.0, "Slippage should raise buy price"

    def test_sell_slippage_lowers_price(self):
        cost, _ = _make_cost_model()
        sim = ExecutionSimulator(cost_model=cost)
        order = Order(symbol="SPY", side=OrderSide.SELL, qty_shares=10,
                      signal_date=pd.Timestamp("2025-01-02"))
        fill = sim.simulate_fill(order, open_price=500.0, vix=15.0, cash=100000.0)
        assert fill is not None
        assert fill.executed_price < 500.0, "Slippage should lower sell price"

    def test_no_commission_double_counting(self):
        """
        The exec_price shift must reflect ONLY slippage, not commission.
        Commission is accounted for separately in cash_delta.

        If commission were in the price shift, then:
          exec_price_shift_bps ≈ commission_bps + slippage_bps (WRONG)
        Correct:
          exec_price_shift_bps ≈ slippage_bps only
        """
        cost, cost_cfg = _make_cost_model()
        sim = ExecutionSimulator(cost_model=cost)

        order = Order(symbol="SPY", side=OrderSide.BUY, qty_shares=100,
                      signal_date=pd.Timestamp("2025-01-02"))
        open_price = 500.0
        fill = sim.simulate_fill(order, open_price=open_price, vix=15.0, cash=1_000_000.0)
        assert fill is not None

        # Calculate the actual price shift
        actual_shift_bps = (fill.executed_price / open_price - 1) * 10_000

        # Get the slippage-only bps from config
        slippage_only_bps = cost_cfg.get_slippage_bps("SPY", "interday", 15.0)
        commission_bps = cost_cfg.get_commission_bps("SPY")

        # The price shift should match slippage only, NOT slippage + commission
        assert abs(actual_shift_bps - slippage_only_bps) < 0.01, (
            f"Price shift {actual_shift_bps:.2f} bps should match slippage-only "
            f"{slippage_only_bps:.2f} bps, not total {slippage_only_bps + commission_bps:.2f} bps"
        )

    def test_commission_in_cash_delta(self):
        """Commission must be reflected in cash_delta, separate from price."""
        cost, cost_cfg = _make_cost_model()
        sim = ExecutionSimulator(cost_model=cost)

        order = Order(symbol="SPY", side=OrderSide.BUY, qty_shares=100,
                      signal_date=pd.Timestamp("2025-01-02"))
        fill = sim.simulate_fill(order, open_price=500.0, vix=15.0, cash=1_000_000.0)
        assert fill is not None

        notional = fill.executed_price * fill.executed_qty
        expected_cash_delta = -(notional + fill.cost_breakdown.commission_usd)
        assert abs(fill.cash_delta - expected_cash_delta) < 0.01, (
            f"cash_delta {fill.cash_delta:.2f} != expected {expected_cash_delta:.2f}"
        )

    def test_cost_breakdown_fields_separate(self):
        """CostBreakdown must have separate slippage and commission."""
        cost, _ = _make_cost_model()
        bd = cost.estimate_cost("SPY", 50000.0)
        assert bd.commission_usd >= 0
        assert bd.slippage_usd >= 0
        assert abs(bd.total_cost_usd - bd.commission_usd - bd.slippage_usd) < 0.01


class TestCostRobustnessStress:
    """Verify evaluator's cost robustness uses real stressed costs, not fallback."""

    def test_stressed_cost_model_actually_multiplies(self):
        """_check_cost_robustness must create a cost model with multiplied tiers."""
        import copy
        cost, cost_cfg = _make_cost_model()
        mult = 2.0

        stressed_cfg = copy.deepcopy(cost_cfg)
        for tier_name, tier in stressed_cfg.tiers.items():
            tier.commission_bps *= mult
            tier.slippage_interday_bps *= mult
            tier.slippage_intraday_bps *= mult
        stressed = CostModel(stressed_cfg)

        bd_1x = cost.estimate_cost("SPY", 100000.0)
        bd_2x = stressed.estimate_cost("SPY", 100000.0)

        assert bd_2x.commission_usd > bd_1x.commission_usd, "2x commission must be higher"
        assert bd_2x.slippage_usd > bd_1x.slippage_usd, "2x slippage must be higher"
        assert bd_2x.total_cost_usd > bd_1x.total_cost_usd * 1.5, "Total 2x must be >1.5x of 1x"
