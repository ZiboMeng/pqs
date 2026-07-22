"""Signed-position accounting for the isolated short PAPER research lane."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping


class ShortPaperError(RuntimeError):
    """Fail-closed violation in short research accounting."""


@dataclass(frozen=True, slots=True)
class BorrowSnapshot:
    symbol: str
    observed_at_utc: str
    available_at_utc: str
    shortable: bool
    available_quantity: int
    annual_borrow_fee: float
    annual_short_proceeds_rebate: float = 0.0
    hard_to_borrow: bool = False
    recalled: bool = False
    source: str = "SYNTHETIC_ASSUMPTION"
    source_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("borrow symbol is required")
        if self.available_quantity < 0:
            raise ValueError("available_quantity must be non-negative")
        if self.annual_borrow_fee < 0 or self.annual_short_proceeds_rebate < 0:
            raise ValueError("borrow fee/rebate must be non-negative")
        observed = _utc(self.observed_at_utc)
        available = _utc(self.available_at_utc)
        if available < observed:
            raise ValueError("borrow availability cannot precede observation")
        if self.source == "BROKER_PIT" and len(self.source_sha256) != 64:
            raise ValueError("BROKER_PIT snapshot requires a source hash")

    @property
    def formal_evidence_eligible(self) -> bool:
        return self.source == "BROKER_PIT" and len(self.source_sha256) == 64


@dataclass(frozen=True, slots=True)
class ShortPaperOrder:
    order_id: str
    symbol: str
    action: Literal["SHORT_SELL", "BUY_TO_COVER"]
    quantity: int
    submitted_at_utc: str

    def __post_init__(self) -> None:
        if not self.order_id.strip() or not self.symbol.strip():
            raise ValueError("order id and symbol are required")
        if self.quantity <= 0:
            raise ValueError("order quantity must be positive")
        _utc(self.submitted_at_utc)


@dataclass(slots=True)
class _ShortPosition:
    quantity: int = 0  # Signed: a short is always negative.
    average_entry_price: float = 0.0
    accrued_borrow_fee: float = 0.0
    accrued_dividend_liability: float = 0.0


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


@dataclass(slots=True)
class ShortPaperAccount:
    initial_cash: float
    initial_margin_rate: float = 0.50
    maintenance_margin_rate: float = 0.30
    commission_bps: float = 0.0
    slippage_bps: float = 30.0
    cash: float = field(init=False)
    restricted_short_proceeds: float = field(default=0.0, init=False)
    positions: dict[str, _ShortPosition] = field(default_factory=dict, init=False)
    audit_events: list[dict[str, Any]] = field(default_factory=list, init=False)
    _processed_event_ids: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if not 0 < self.maintenance_margin_rate <= self.initial_margin_rate <= 1:
            raise ValueError("invalid initial/maintenance margin rates")
        if self.commission_bps < 0 or self.slippage_bps < 0:
            raise ValueError("cost bps must be non-negative")
        self.cash = float(self.initial_cash)

    def _once(self, event_id: str) -> bool:
        if not event_id.strip():
            raise ValueError("event_id is required")
        if event_id in self._processed_event_ids:
            return False
        self._processed_event_ids.add(event_id)
        return True

    def signed_quantity(self, symbol: str) -> int:
        position = self.positions.get(symbol)
        return position.quantity if position is not None else 0

    def equity(self, marks: Mapping[str, float]) -> float:
        signed_market_value = 0.0
        for symbol, position in self.positions.items():
            mark = float(marks.get(symbol, float("nan")))
            if not math.isfinite(mark) or mark <= 0:
                raise ShortPaperError(f"missing/invalid mark for {symbol}")
            signed_market_value += position.quantity * mark
        # Short-sale cash proceeds are present in cash, while the signed
        # liability is negative.  Restricted proceeds are a buying-power
        # restriction and must not be subtracted a second time from NAV.
        return float(self.cash + signed_market_value)

    def exposures(self, marks: Mapping[str, float]) -> dict[str, float]:
        equity = self.equity(marks)
        if equity <= 0:
            return {"equity": equity, "gross": float("inf"), "net": float("-inf")}
        values = {
            symbol: position.quantity * float(marks[symbol])
            for symbol, position in self.positions.items()
        }
        return {
            "equity": equity,
            "gross": sum(abs(value) for value in values.values()) / equity,
            "net": sum(values.values()) / equity,
            "short_market_value": sum(-value for value in values.values() if value < 0),
            "restricted_short_proceeds": self.restricted_short_proceeds,
        }

    def execute(
        self,
        order: ShortPaperOrder,
        *,
        open_price: float | None,
        borrow: BorrowSnapshot | None = None,
        rule201_triggered: bool = False,
        price_above_nbb: bool | None = None,
    ) -> bool:
        """Execute only at a supplied next-session open; never fake a close fill."""

        if order.order_id in self._processed_event_ids:
            return False
        if open_price is None or not math.isfinite(float(open_price)) or open_price <= 0:
            raise ShortPaperError("next-session open is missing; order rejected")
        price = float(open_price)
        position = self.positions.setdefault(order.symbol, _ShortPosition())
        if order.action == "SHORT_SELL":
            if borrow is None or borrow.symbol != order.symbol:
                raise ShortPaperError("locate snapshot missing or wrong symbol")
            if _utc(borrow.available_at_utc) > _utc(order.submitted_at_utc):
                raise ShortPaperError("borrow snapshot was not available at order time")
            if not borrow.shortable or borrow.recalled:
                raise ShortPaperError("security is not currently shortable")
            if borrow.available_quantity < order.quantity:
                raise ShortPaperError("locate quantity is insufficient")
            if rule201_triggered and price_above_nbb is not True:
                raise ShortPaperError("Rule 201 triggered without price-above-NBB evidence")
            fill = price * (1.0 - self.slippage_bps / 10_000.0)
            notional = order.quantity * fill
            commission = notional * self.commission_bps / 10_000.0
            prior_quantity = position.quantity
            prior_average_entry = position.average_entry_price
            new_short = -position.quantity + order.quantity
            position.average_entry_price = (
                (-position.quantity * position.average_entry_price + notional)
                / new_short
            )
            position.quantity -= order.quantity
            self.cash += notional - commission
            self.restricted_short_proceeds += notional
            if self.equity({order.symbol: fill, **{
                symbol: item.average_entry_price
                for symbol, item in self.positions.items()
                if symbol != order.symbol
            }}) < self.initial_margin_rate * self._gross_short_market_value({
                symbol: (fill if symbol == order.symbol else item.average_entry_price)
                for symbol, item in self.positions.items()
            }):
                # Roll back an entry that would violate initial margin.
                position.quantity = prior_quantity
                position.average_entry_price = prior_average_entry
                self.cash -= notional - commission
                self.restricted_short_proceeds -= notional
                raise ShortPaperError("initial margin requirement failed")
        else:
            outstanding = -position.quantity
            if order.quantity > outstanding:
                raise ShortPaperError("BUY_TO_COVER exceeds outstanding short")
            fill = price * (1.0 + self.slippage_bps / 10_000.0)
            notional = order.quantity * fill
            commission = notional * self.commission_bps / 10_000.0
            self.cash -= notional + commission
            released = min(
                self.restricted_short_proceeds,
                order.quantity * position.average_entry_price,
            )
            self.restricted_short_proceeds -= released
            position.quantity += order.quantity
            if position.quantity == 0:
                position.average_entry_price = 0.0
        self._once(order.order_id)
        self.audit_events.append({
            "event_id": order.order_id,
            "event_type": order.action,
            "symbol": order.symbol,
            "quantity": order.quantity,
            "open_price": price,
            "cash": self.cash,
            "restricted_short_proceeds": self.restricted_short_proceeds,
        })
        return True

    def _gross_short_market_value(self, marks: Mapping[str, float]) -> float:
        return float(sum(
            -position.quantity * float(marks[symbol])
            for symbol, position in self.positions.items()
            if position.quantity < 0
        ))

    def accrue_session(
        self,
        *,
        event_id: str,
        marks: Mapping[str, float],
        borrow_by_symbol: Mapping[str, BorrowSnapshot],
        cash_distributions: Mapping[str, float] | None = None,
        day_count: int = 360,
    ) -> bool:
        if event_id in self._processed_event_ids:
            return False
        cash_distributions = cash_distributions or {}
        total_borrow = 0.0
        total_rebate = 0.0
        total_dividend = 0.0
        charges: dict[str, tuple[float, float]] = {}
        for symbol, position in self.positions.items():
            if position.quantity >= 0:
                continue
            snapshot = borrow_by_symbol.get(symbol)
            if snapshot is None:
                raise ShortPaperError(f"borrow snapshot missing for open short {symbol}")
            mark = float(marks.get(symbol, float("nan")))
            if not math.isfinite(mark) or mark <= 0:
                raise ShortPaperError(f"mark missing for open short {symbol}")
            market_value = -position.quantity * mark
            fee = market_value * snapshot.annual_borrow_fee / day_count
            rebate = min(
                self.restricted_short_proceeds,
                market_value,
            ) * snapshot.annual_short_proceeds_rebate / day_count
            dividend = -position.quantity * float(cash_distributions.get(symbol, 0.0))
            if dividend < 0:
                raise ShortPaperError("cash distribution cannot be negative")
            charges[symbol] = (fee, dividend)
            total_borrow += fee
            total_rebate += rebate
            total_dividend += dividend
        for symbol, (fee, dividend) in charges.items():
            self.positions[symbol].accrued_borrow_fee += fee
            self.positions[symbol].accrued_dividend_liability += dividend
        self.cash += total_rebate - total_borrow - total_dividend
        self._once(event_id)
        self.audit_events.append({
            "event_id": event_id,
            "event_type": "SESSION_ACCRUAL",
            "borrow_fee": total_borrow,
            "short_proceeds_rebate": total_rebate,
            "short_dividend_liability": total_dividend,
        })
        return True

    def apply_split(self, *, event_id: str, symbol: str, ratio: float) -> bool:
        if event_id in self._processed_event_ids:
            return False
        if not math.isfinite(ratio) or ratio <= 0:
            raise ShortPaperError("split ratio must be positive")
        position = self.positions.get(symbol)
        if position is None or position.quantity == 0:
            self._once(event_id)
            return True
        adjusted = position.quantity * ratio
        if not float(adjusted).is_integer():
            raise ShortPaperError("fractional split requires broker cash-in-lieu evidence")
        position.quantity = int(adjusted)
        position.average_entry_price /= ratio
        self._once(event_id)
        self.audit_events.append({
            "event_id": event_id,
            "event_type": "SPLIT",
            "symbol": symbol,
            "ratio": ratio,
        })
        return True

    def maintenance_breach(self, marks: Mapping[str, float]) -> bool:
        gross_short = self._gross_short_market_value(marks)
        return self.equity(marks) < self.maintenance_margin_rate * gross_short

    def force_cover(
        self,
        *,
        event_id: str,
        symbol: str,
        open_price: float | None,
        reason: Literal["RECALL", "MARGIN", "BUY_IN", "KILL_SWITCH"],
        submitted_at_utc: str,
    ) -> bool:
        quantity = -self.signed_quantity(symbol)
        if quantity <= 0:
            return False
        return self.execute(
            ShortPaperOrder(
                order_id=event_id,
                symbol=symbol,
                action="BUY_TO_COVER",
                quantity=quantity,
                submitted_at_utc=submitted_at_utc,
            ),
            open_price=open_price,
        )

    def reconcile(self, broker_signed_quantities: Mapping[str, int]) -> None:
        local = {
            symbol: position.quantity
            for symbol, position in self.positions.items()
            if position.quantity != 0
        }
        broker = {
            symbol: int(quantity)
            for symbol, quantity in broker_signed_quantities.items()
            if int(quantity) != 0
        }
        if local != broker:
            raise ShortPaperError(
                f"signed broker reconciliation mismatch local={local} broker={broker}"
            )

    def evidence_status(self, snapshots: Mapping[str, BorrowSnapshot]) -> str:
        open_symbols = [
            symbol for symbol, position in self.positions.items()
            if position.quantity < 0
        ]
        if open_symbols and all(
            symbol in snapshots and snapshots[symbol].formal_evidence_eligible
            for symbol in open_symbols
        ):
            return "SHORT_PAPER_EVIDENCE_ELIGIBLE"
        return "RESEARCH_INCOMPLETE"

    def save_atomic(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "initial_cash": self.initial_cash,
            "initial_margin_rate": self.initial_margin_rate,
            "maintenance_margin_rate": self.maintenance_margin_rate,
            "commission_bps": self.commission_bps,
            "slippage_bps": self.slippage_bps,
            "cash": self.cash,
            "restricted_short_proceeds": self.restricted_short_proceeds,
            "positions": {
                symbol: asdict(position) for symbol, position in self.positions.items()
            },
            "processed_event_ids": sorted(self._processed_event_ids),
            "audit_events": self.audit_events,
        }
        descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
