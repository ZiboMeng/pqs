from __future__ import annotations

import pandas as pd
import pytest

from core.backtest.backtest_engine import BacktestEngine
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.cost_model import CostModel
from core.execution.execution_simulator import OrderSide
from core.execution.target_weight_planner import (
    TargetWeightOrderPlanner,
    TargetWeightPlannerConfig,
)


def _cost() -> CostModel:
    return CostModel(
        CostModelConfig(
            tiers={
                "default": CostTierConfig(
                    symbols=[],
                    commission_bps=0,
                    slippage_interday_bps=0,
                    slippage_intraday_bps=0,
                )
            }
        )
    )


def test_planner_matches_certified_backtest_order_kernel() -> None:
    prior = {"BIL": 100.0, "QQQ": 400.0, "SPY": 500.0}
    opened = {"BIL": 100.1, "QQQ": 404.0, "SPY": 495.0}
    positions = {"BIL": 200.0, "SPY": 50.0}
    cash = 55_000.0
    target = {"BIL": 0.20, "QQQ": 0.30, "SPY": 0.35}
    signal_date = pd.Timestamp("2026-07-17")
    planner = TargetWeightOrderPlanner(
        TargetWeightPlannerConfig(
            minimum_trade_usd=100.0,
            rebalance_threshold=0.02,
            integer_shares=True,
        )
    )
    actual = planner.plan(
        target_weights=target,
        positions=positions,
        cash=cash,
        prior_close=prior,
        execution_open=opened,
        signal_date=signal_date,
    )

    execution_equity = cash + sum(positions[s] * opened[s] for s in positions)
    current_weights = {
        symbol: quantity * opened[symbol] / execution_equity
        for symbol, quantity in positions.items()
    }
    expected = BacktestEngine(
        _cost(),
        integer_shares=True,
        min_trade_usd=100.0,
        rebalance_threshold=0.02,
    )._generate_orders(
        cur_weights=current_weights,
        tgt_weights=target,
        portfolio_val=execution_equity,
        price_row=pd.Series(prior),
        open_row=pd.Series(opened),
        signal_date=signal_date,
        current_positions=positions,
        cash=cash,
    )
    assert [
        (order.symbol, order.side, order.qty_shares) for order in actual
    ] == [
        (order.symbol, order.side, order.qty_shares) for order in expected
    ]


def test_planner_closes_gap_down_position_by_actual_shares() -> None:
    orders = TargetWeightOrderPlanner().plan(
        target_weights={"SPY": 0.0},
        positions={"SPY": 10.0},
        cash=1_000.0,
        prior_close={"SPY": 500.0},
        execution_open={"SPY": 400.0},
        signal_date=pd.Timestamp("2026-07-17"),
    )
    assert len(orders) == 1
    assert orders[0].side is OrderSide.SELL
    assert orders[0].qty_shares == 10.0


@pytest.mark.parametrize(
    ("target", "positions", "opened", "match"),
    [
        ({"SPY": float("nan")}, {}, {"SPY": 100.0}, "target weight"),
        ({"SPY": 0.5}, {}, {"SPY": float("nan")}, "execution open"),
        ({"SPY": 0.0}, {"SPY": -1.0}, {"SPY": 100.0}, "positions"),
    ],
)
def test_planner_fails_closed_on_invalid_inputs(target, positions, opened, match) -> None:
    with pytest.raises(ValueError, match=match):
        TargetWeightOrderPlanner().plan(
            target_weights=target,
            positions=positions,
            cash=100_000.0,
            prior_close={"SPY": 100.0},
            execution_open=opened,
            signal_date=pd.Timestamp("2026-07-17"),
        )
