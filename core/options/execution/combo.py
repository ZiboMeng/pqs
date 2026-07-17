"""Atomic multi-leg option order intent and partial-fill accounting models."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from core.options.data import OptionContract


class LegAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class NetPriceType(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class ComboStatus(StrEnum):
    CREATED = "CREATED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    LEGGED_RISK = "LEGGED_RISK"
    FILLED = "FILLED"


@dataclass(frozen=True, slots=True)
class ComboLeg:
    contract: OptionContract
    action: LegAction
    ratio: int = 1

    def __post_init__(self) -> None:
        if self.ratio <= 0:
            raise ValueError("leg ratio must be positive")


@dataclass(frozen=True, slots=True)
class ComboOrder:
    legs: tuple[ComboLeg, ...]
    quantity: int
    net_price_type: NetPriceType
    limit_price: float
    strategy_id: str
    decision_id: str
    idempotency_key: str
    order_id: str = field(default_factory=lambda: f"opt_{uuid.uuid4().hex}")
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if len(self.legs) not in {2, 4}:
            raise ValueError("defined-risk combo must contain exactly 2 or 4 legs")
        if self.quantity <= 0:
            raise ValueError("combo quantity must be positive")
        if not math.isfinite(self.limit_price) or self.limit_price < 0:
            raise ValueError("limit_price must be finite and non-negative")
        if not self.strategy_id.strip() or not self.decision_id.strip():
            raise ValueError("strategy_id and decision_id are required")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key is required")

        underlyings = {leg.contract.underlying for leg in self.legs}
        expiries = {leg.contract.expiry for leg in self.legs}
        multipliers = {leg.contract.multiplier for leg in self.legs}
        contract_ids = {leg.contract.contract_id for leg in self.legs}
        if len(underlyings) != 1 or len(expiries) != 1 or len(multipliers) != 1:
            raise ValueError("all combo legs must share underlying, expiry, and multiplier")
        if len(contract_ids) != len(self.legs):
            raise ValueError("duplicate contracts are forbidden in one combo")
        if {leg.action for leg in self.legs} != {LegAction.BUY, LegAction.SELL}:
            raise ValueError("defined-risk combo requires both long and short legs")


@dataclass(frozen=True, slots=True)
class LegFill:
    contract_id: str
    filled_contracts: int
    price: float
    filled_at: datetime

    def __post_init__(self) -> None:
        if self.filled_contracts < 0:
            raise ValueError("filled_contracts cannot be negative")
        if not math.isfinite(self.price) or self.price < 0:
            raise ValueError("fill price must be finite and non-negative")
        if self.filled_at.tzinfo is None:
            raise ValueError("filled_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ComboExecution:
    order: ComboOrder
    leg_fills: tuple[LegFill, ...]

    def __post_init__(self) -> None:
        expected = {leg.contract.contract_id: leg for leg in self.order.legs}
        seen: set[str] = set()
        for fill in self.leg_fills:
            if fill.contract_id not in expected:
                raise ValueError(f"fill for unknown leg {fill.contract_id}")
            if fill.contract_id in seen:
                raise ValueError("aggregate each contract into one LegFill")
            seen.add(fill.contract_id)
            max_fill = self.order.quantity * expected[fill.contract_id].ratio
            if fill.filled_contracts > max_fill:
                raise ValueError("leg fill exceeds ordered contracts")

    @property
    def status(self) -> ComboStatus:
        fills = {fill.contract_id: fill.filled_contracts for fill in self.leg_fills}
        expected = {
            leg.contract.contract_id: self.order.quantity * leg.ratio
            for leg in self.order.legs
        }
        quantities = [fills.get(contract_id, 0) for contract_id in expected]
        if all(quantity == 0 for quantity in quantities):
            return ComboStatus.CREATED
        if all(fills.get(contract_id, 0) == quantity for contract_id, quantity in expected.items()):
            return ComboStatus.FILLED
        if any(quantity == 0 for quantity in quantities):
            return ComboStatus.LEGGED_RISK
        return ComboStatus.PARTIALLY_FILLED

    @property
    def net_cash_delta(self) -> float:
        legs = {leg.contract.contract_id: leg for leg in self.order.legs}
        total = 0.0
        for fill in self.leg_fills:
            leg = legs[fill.contract_id]
            cash = fill.price * fill.filled_contracts * leg.contract.multiplier
            total += cash if leg.action is LegAction.SELL else -cash
        return total
