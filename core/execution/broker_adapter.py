"""BrokerAdapter ABC + SimulatedBrokerAdapter (Round 11 Topic L,
2026-04-20).

Per CLAUDE.md §4.1 'Data Provider and Broker Adapter Separation'. This
module decouples strategy execution from broker-specific APIs. Current
production paper trading routes orders directly through
`ExecutionSimulator`; once a real broker (IBKR / Alpaca / etc.) is
integrated, `PaperTradingEngine` will swap in a real
`BrokerAdapter` implementation without touching strategy code.

Design principles (per CLAUDE.md):
- Strategy code MUST NEVER import broker APIs
- BrokerAdapter is a pure interface layer — all broker-specific
  concerns (auth, rate limits, error translation, session management)
  stay inside the adapter implementation
- `SimulatedBrokerAdapter` wraps `ExecutionSimulator` so the interface
  can be exercised without any network / external broker
- Real broker implementations live in `core/execution/brokers/<vendor>.py`
  and MUST inherit from `BrokerAdapter` directly (no mixin).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from core.execution.cost_model import CostModel
from core.execution.execution_simulator import (
    ExecutionSimulator, Fill, Order, OrderSide,
)


# ── Interface types ──────────────────────────────────────────────────────────

@dataclass
class OrderAck:
    """Broker's acknowledgement of a submitted order. Returned by
    `BrokerAdapter.submit_order` before any fills."""
    order_id:    str          # broker-assigned unique ID
    order:       Order
    submitted_at: datetime
    status:      str = "ACCEPTED"  # ACCEPTED / REJECTED / ...
    reject_reason: Optional[str] = None


@dataclass
class ReconcileResult:
    """Output of `BrokerAdapter.reconcile`. Compares our expected
    position/cash book against what the broker reports."""
    passed:         bool
    position_mismatches: Dict[str, float] = field(default_factory=dict)  # sym → diff
    cash_mismatch:  float = 0.0
    details:        str = ""


# ── ABC ──────────────────────────────────────────────────────────────────────

class BrokerAdapter(ABC):
    """Minimum interface per CLAUDE.md §4.1. Every real broker
    integration (IBKR / Alpaca / paper vendor) must inherit from this
    class and implement every abstract method."""

    @abstractmethod
    def submit_order(self, order: Order) -> OrderAck:
        """Submit an order. Returns an acknowledgement with broker
        order_id. Does NOT block for fill — caller polls `get_fills`."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True on success. If the order
        already filled or doesn't exist, returns False."""

    @abstractmethod
    def get_positions(self) -> Dict[str, float]:
        """Current positions as {symbol → shares}."""

    @abstractmethod
    def get_cash(self) -> float:
        """Current cash balance in USD."""

    @abstractmethod
    def get_open_orders(self) -> List[Order]:
        """Orders that have been submitted but not yet filled/cancelled."""

    @abstractmethod
    def get_fills(self, since: datetime) -> List[Fill]:
        """Fills booked at or after `since`."""

    @abstractmethod
    def reconcile(
        self,
        expected_positions: Dict[str, float],
        expected_cash:      float,
    ) -> ReconcileResult:
        """Compare our book against broker's. Caller passes the
        engine's expected state; adapter returns mismatches."""


# ── SimulatedBrokerAdapter ────────────────────────────────────────────────────

class SimulatedBrokerAdapter(BrokerAdapter):
    """Wraps the existing `ExecutionSimulator` behind the
    `BrokerAdapter` interface. No external broker; useful for:
      - Interface verification (Round 11 Topic L)
      - End-to-end paper trading path regression tests
      - Bootstrapping: strategy code can target BrokerAdapter from
        day one; swap in a real adapter later without changes.

    Fill simulation requires a price lookup function since this adapter
    doesn't talk to a real market. Pass `price_provider(symbol) -> float`
    at construction time (or inject per-order via `set_next_fill_price`
    for deterministic tests).
    """

    def __init__(
        self,
        cost_model:      CostModel,
        initial_cash:    float = 100_000.0,
        initial_positions: Optional[Dict[str, float]] = None,
    ):
        self._sim = ExecutionSimulator(
            cost_model, freq="interday", allow_partial=True,
        )
        self._cash: float = initial_cash
        self._positions: Dict[str, float] = dict(initial_positions or {})

        self._open_orders: Dict[str, Order] = {}  # order_id → Order
        self._fills: List[Fill] = []              # chronological
        self._fill_timestamps: List[datetime] = []  # parallel to _fills
        # Optional deterministic price override for next fill (per-symbol)
        self._next_fill_prices: Dict[str, float] = {}
        # Default price if nothing injected — caller's responsibility
        self._default_price: Optional[float] = None

    # ── Knobs for tests ──────────────────────────────────────────────────────

    def set_next_fill_price(self, symbol: str, price: float) -> None:
        """Pin the fill price for the NEXT submit_order on `symbol`.
        Simplifies deterministic tests. Consumed on use."""
        self._next_fill_prices[symbol] = float(price)

    def set_default_fill_price(self, price: float) -> None:
        """Fallback price when no per-symbol override is set."""
        self._default_price = float(price)

    # ── Required ABC methods ─────────────────────────────────────────────────

    def submit_order(self, order: Order) -> OrderAck:
        # Look up (or default) fill price
        sym = order.symbol
        if sym in self._next_fill_prices:
            price = self._next_fill_prices.pop(sym)
        elif self._default_price is not None:
            price = self._default_price
        else:
            return OrderAck(
                order_id="", order=order,
                submitted_at=datetime.now(),
                status="REJECTED",
                reject_reason="no fill price configured "
                              "(use set_next_fill_price or set_default_fill_price)",
            )

        order_id = uuid.uuid4().hex[:12]
        self._open_orders[order_id] = order

        # Simulate fill immediately using ExecutionSimulator
        fill = self._sim.simulate_fill(order, price, vix=15.0, cash=self._cash)
        if fill is None:
            # Insufficient cash / qty → REJECTED
            self._open_orders.pop(order_id, None)
            return OrderAck(
                order_id=order_id, order=order,
                submitted_at=datetime.now(),
                status="REJECTED",
                reject_reason="execution simulator declined (cash / qty)",
            )

        # Book the fill
        prev = self._positions.get(sym, 0.0)
        if fill.side == OrderSide.BUY:
            self._positions[sym] = prev + fill.executed_qty
        else:
            self._positions[sym] = max(prev - fill.executed_qty, 0.0)
        self._cash += fill.cash_delta
        self._positions = {s: q for s, q in self._positions.items() if q > 1e-6}

        self._fills.append(fill)
        self._fill_timestamps.append(datetime.now())
        # Order completes (simulated, no partial fills here)
        self._open_orders.pop(order_id, None)

        return OrderAck(
            order_id=order_id, order=order,
            submitted_at=datetime.now(), status="ACCEPTED",
        )

    def cancel_order(self, order_id: str) -> bool:
        # Simulated adapter fills immediately, so there's nothing to cancel
        # unless the order is still pending (shouldn't happen here).
        return self._open_orders.pop(order_id, None) is not None

    def get_positions(self) -> Dict[str, float]:
        return dict(self._positions)

    def get_cash(self) -> float:
        return float(self._cash)

    def get_open_orders(self) -> List[Order]:
        return list(self._open_orders.values())

    def get_fills(self, since: datetime) -> List[Fill]:
        return [
            f for f, ts in zip(self._fills, self._fill_timestamps)
            if ts >= since
        ]

    def reconcile(
        self,
        expected_positions: Dict[str, float],
        expected_cash:      float,
    ) -> ReconcileResult:
        pos_diff: Dict[str, float] = {}
        all_syms = set(expected_positions) | set(self._positions)
        for sym in all_syms:
            exp = float(expected_positions.get(sym, 0.0))
            act = float(self._positions.get(sym, 0.0))
            if abs(exp - act) > 1e-6:
                pos_diff[sym] = act - exp
        cash_diff = self._cash - float(expected_cash)
        passed = (len(pos_diff) == 0) and (abs(cash_diff) < 0.01)
        details = (
            f"{len(pos_diff)} position mismatch(es); "
            f"cash diff ${cash_diff:+.4f}"
        )
        return ReconcileResult(
            passed=passed,
            position_mismatches=pos_diff,
            cash_mismatch=cash_diff,
            details=details,
        )
