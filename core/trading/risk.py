"""Independent pre-trade veto. No strategy may override this decision."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .order import OrderIntent, TradingSide


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_gross_exposure: float = 1.0
    max_single_position: float = 0.35
    max_positions: int = 10
    min_cash_fraction: float = 0.05
    max_daily_loss_fraction: float = 0.03
    max_daily_turnover_fraction: float = 1.0
    max_order_notional_fraction: float = 0.35
    max_reference_price_deviation: float = 0.05
    symbol_caps: dict[str, float] = field(default_factory=dict)
    blocked_symbols: frozenset[str] = frozenset()
    long_only: bool = True
    allow_margin: bool = False


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    equity: float
    cash: float
    positions: dict[str, float]
    prices: dict[str, float]
    daily_pnl: float = 0.0
    daily_turnover: float = 0.0
    estimated_order_cost: float = 0.0
    data_fresh: bool = False
    kill_switch_active: bool = False
    manual_pause: bool = False
    reconciliation_ok: bool = False


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    reason_codes: tuple[str, ...] = ()


class PreTradeRiskEngine:
    """Evaluate an order against a complete account snapshot, fail closed."""

    def __init__(self, limits: RiskLimits):
        self._limits = limits

    def evaluate(self, order: OrderIntent, snapshot: RiskSnapshot) -> RiskDecision:
        reasons: list[str] = []
        limits = self._limits

        if not snapshot.data_fresh:
            reasons.append("STALE_MARKET_DATA")
        if snapshot.kill_switch_active:
            reasons.append("KILL_SWITCH_ACTIVE")
        if snapshot.manual_pause:
            reasons.append("MANUAL_PAUSE_ACTIVE")
        if not snapshot.reconciliation_ok:
            reasons.append("RECONCILIATION_NOT_OK")
        if order.symbol in limits.blocked_symbols:
            reasons.append("SYMBOL_BLOCKED")
        if not math.isfinite(snapshot.equity) or snapshot.equity <= 0:
            reasons.append("INVALID_EQUITY")
            return RiskDecision(False, tuple(reasons))
        if not math.isfinite(snapshot.cash):
            reasons.append("INVALID_CASH")
            return RiskDecision(False, tuple(reasons))

        price = snapshot.prices.get(order.symbol)
        if price is None or not math.isfinite(price) or price <= 0:
            reasons.append("MISSING_REFERENCE_PRICE")
            return RiskDecision(False, tuple(reasons))

        current_qty = float(snapshot.positions.get(order.symbol, 0.0))
        signed_qty = order.quantity if order.side is TradingSide.BUY else -order.quantity
        projected_qty = current_qty + signed_qty
        if limits.long_only and projected_qty < -1e-9:
            reasons.append("SHORT_POSITION_FORBIDDEN")

        order_notional = order.quantity * price
        if order_notional > snapshot.equity * limits.max_order_notional_fraction:
            reasons.append("MAX_ORDER_NOTIONAL_BREACH")
        reference_deviation = abs(order.reference_price - price) / price
        if reference_deviation > limits.max_reference_price_deviation:
            reasons.append("REFERENCE_PRICE_DEVIATION")
        projected_cash = (
            snapshot.cash - order_notional - snapshot.estimated_order_cost
            if order.side is TradingSide.BUY
            else snapshot.cash + order_notional - snapshot.estimated_order_cost
        )
        min_cash = snapshot.equity * limits.min_cash_fraction
        if not limits.allow_margin and projected_cash < min_cash - 1e-9:
            reasons.append("MIN_CASH_BREACH")

        projected_values: dict[str, float] = {}
        for symbol, qty in snapshot.positions.items():
            symbol_price = snapshot.prices.get(symbol)
            if symbol_price is None or not math.isfinite(symbol_price) or symbol_price <= 0:
                reasons.append(f"MISSING_POSITION_PRICE:{symbol}")
                continue
            projected_values[symbol] = float(qty) * float(symbol_price)
        projected_values[order.symbol] = max(projected_qty, 0.0) * price
        projected_values = {s: v for s, v in projected_values.items() if v > 1e-9}

        symbol_cap = limits.symbol_caps.get(order.symbol, limits.max_single_position)
        if projected_values.get(order.symbol, 0.0) / snapshot.equity > symbol_cap + 1e-9:
            reasons.append("SYMBOL_CAP_BREACH")
        gross = sum(abs(v) for v in projected_values.values()) / snapshot.equity
        if gross > limits.max_gross_exposure + 1e-9:
            reasons.append("GROSS_EXPOSURE_BREACH")
        if len(projected_values) > limits.max_positions:
            reasons.append("MAX_POSITIONS_BREACH")
        if snapshot.daily_pnl <= -snapshot.equity * limits.max_daily_loss_fraction:
            reasons.append("DAILY_LOSS_LIMIT")
        if (
            snapshot.daily_turnover + order_notional
            > snapshot.equity * limits.max_daily_turnover_fraction
        ):
            reasons.append("DAILY_TURNOVER_LIMIT")

        return RiskDecision(not reasons, tuple(reasons))
