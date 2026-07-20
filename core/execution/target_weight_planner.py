"""Deterministic target-weight to order conversion for forward execution."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from core.execution.execution_simulator import Order, OrderSide


@dataclass(frozen=True, slots=True)
class TargetWeightPlannerConfig:
    minimum_trade_usd: float = 100.0
    rebalance_threshold: float = 0.02
    integer_shares: bool = True

    def __post_init__(self) -> None:
        if not math.isfinite(self.minimum_trade_usd) or self.minimum_trade_usd < 0:
            raise ValueError("minimum_trade_usd must be finite and non-negative")
        if not math.isfinite(self.rebalance_threshold) or not (
            0 <= self.rebalance_threshold <= 1
        ):
            raise ValueError("rebalance_threshold must be between zero and one")


class TargetWeightOrderPlanner:
    """Plan long-only rebalance orders using execution-time account value."""

    def __init__(self, config: TargetWeightPlannerConfig | None = None) -> None:
        self.config = config or TargetWeightPlannerConfig()

    def plan(
        self,
        *,
        target_weights: Mapping[str, float],
        positions: Mapping[str, float],
        cash: float,
        prior_close: Mapping[str, float],
        execution_open: Mapping[str, float],
        signal_date: pd.Timestamp,
    ) -> list[Order]:
        if not math.isfinite(cash) or cash < -0.01:
            raise ValueError("cash must be finite and non-negative")
        clean_positions: dict[str, float] = {}
        for symbol, quantity in positions.items():
            value = float(quantity)
            if not math.isfinite(value) or value < 0:
                raise ValueError("positions must be finite and long-only")
            if value > 0:
                clean_positions[str(symbol)] = value

        execution_equity = max(float(cash), 0.0)
        execution_marks: dict[str, float] = {}
        for symbol, quantity in clean_positions.items():
            open_price = float(execution_open.get(symbol, float("nan")))
            prior_price = float(prior_close.get(symbol, float("nan")))
            mark = open_price if math.isfinite(open_price) and open_price > 0 else prior_price
            if not math.isfinite(mark) or mark <= 0:
                raise ValueError(f"held position has no valid execution mark: {symbol}")
            execution_marks[symbol] = mark
            execution_equity += quantity * mark
        if not math.isfinite(execution_equity) or execution_equity <= 0:
            raise ValueError("execution equity must be finite and positive")

        current_weights = {
            symbol: quantity * execution_marks[symbol] / execution_equity
            for symbol, quantity in clean_positions.items()
        }
        orders: list[Order] = []
        for symbol in sorted(set(current_weights) | set(target_weights)):
            current_weight = float(current_weights.get(symbol, 0.0))
            target_weight = float(target_weights.get(symbol, 0.0))
            if not math.isfinite(target_weight) or not 0 <= target_weight <= 1:
                raise ValueError(f"invalid target weight for {symbol}: {target_weight}")
            delta_weight = target_weight - current_weight
            if (
                abs(delta_weight) < self.config.rebalance_threshold
                and target_weight > 0
            ):
                continue
            execution_price = float(execution_open.get(symbol, float("nan")))
            if not math.isfinite(execution_price) or execution_price <= 0:
                raise ValueError(f"missing or invalid execution open for {symbol}")
            current_quantity = clean_positions.get(symbol, 0.0)
            target_quantity = target_weight * execution_equity / execution_price
            delta_quantity = target_quantity - current_quantity
            side = OrderSide.BUY if delta_quantity > 0 else OrderSide.SELL
            quantity = abs(delta_quantity)
            if side is OrderSide.SELL:
                quantity = min(quantity, current_quantity)
            if self.config.integer_shares:
                quantity = float(int(quantity))
            if quantity < 1e-6 or quantity * execution_price < self.config.minimum_trade_usd:
                continue
            orders.append(
                Order(
                    symbol=symbol,
                    side=side,
                    qty_shares=quantity,
                    signal_date=pd.Timestamp(signal_date),
                )
            )
        return orders
