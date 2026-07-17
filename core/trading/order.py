"""Canonical order intent and lifecycle for all execution adapters."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class TradingSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderState(StrEnum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


TERMINAL_STATES = frozenset(
    {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.EXPIRED}
)

ALLOWED_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.CREATED: frozenset({OrderState.VALIDATED, OrderState.REJECTED}),
    OrderState.VALIDATED: frozenset(
        {OrderState.SUBMITTED, OrderState.REJECTED, OrderState.EXPIRED}
    ),
    OrderState.SUBMITTED: frozenset(
        {OrderState.ACKNOWLEDGED, OrderState.REJECTED, OrderState.UNKNOWN}
    ),
    OrderState.ACKNOWLEDGED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_PENDING,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.EXPIRED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.PARTIALLY_FILLED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_PENDING,
            OrderState.CANCELLED,
            OrderState.EXPIRED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.CANCEL_PENDING: frozenset(
        {OrderState.CANCELLED, OrderState.FILLED, OrderState.UNKNOWN}
    ),
    OrderState.UNKNOWN: frozenset(
        {
            OrderState.ACKNOWLEDGED,
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_PENDING,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.EXPIRED,
        }
    ),
}


def new_order_id() -> str:
    return f"ord_{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    symbol: str
    side: TradingSide
    quantity: float
    reference_price: float
    signal_id: str
    strategy_id: str
    decision_id: str
    idempotency_key: str
    order_id: str = field(default_factory=new_order_id)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    comment: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        if not self.symbol:
            raise ValueError("symbol is required")
        if not math.isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("quantity must be finite and positive")
        if not math.isfinite(self.reference_price) or self.reference_price <= 0:
            raise ValueError("reference_price must be finite and positive")
        for name in ("signal_id", "strategy_id", "decision_id", "idempotency_key"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} is required")
