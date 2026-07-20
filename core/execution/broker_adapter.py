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

import hashlib
import json
import math
import sqlite3
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from core.execution.cost_model import CostModel
from core.execution.execution_simulator import (
    ExecutionSimulator,
    Fill,
    Order,
    OrderSide,
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


@dataclass(frozen=True, slots=True)
class BrokerAccountSnapshot:
    """One internally consistent, broker-authoritative account observation."""

    snapshot_id: str
    source: str
    observed_at: datetime
    cash: float
    positions: Dict[str, float]
    open_order_ids: frozenset[str]
    fill_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip() or not self.source.strip():
            raise ValueError("broker snapshot identity and source are required")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("broker snapshot time must be timezone-aware")
        if not math.isfinite(float(self.cash)) or self.cash < -0.01:
            raise ValueError("broker snapshot cash must be finite and non-negative")
        invalid_positions = {
            symbol: quantity
            for symbol, quantity in self.positions.items()
            if not str(symbol).strip()
            or not math.isfinite(float(quantity))
            or float(quantity) < 0
        }
        if invalid_positions:
            raise ValueError(
                "broker snapshot positions must be finite and long-only: "
                f"{invalid_positions}"
            )
        if any(not str(value).strip() for value in self.open_order_ids | self.fill_ids):
            raise ValueError("broker snapshot order and fill identities must be non-empty")


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

    def get_open_order_ids(self) -> frozenset[str]:
        """Return stable identities for broker-authoritative open orders.

        Adapters must attach either ``broker_order_id`` or
        ``canonical_order_id`` to each returned order. Refusing an order with
        no stable identity is safer than silently omitting it from account
        reconciliation.
        """
        identities: set[str] = set()
        for order in self.get_open_orders():
            identity = getattr(order, "broker_order_id", None) or getattr(
                order, "canonical_order_id", None
            )
            if not identity:
                raise RuntimeError("broker open order has no stable identity")
            identities.add(str(identity))
        return frozenset(identities)

    def get_account_snapshot(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> BrokerAccountSnapshot:
        """Return one coherent snapshot with source time and stable identities.

        Phase 3 callers intentionally do not synthesize freshness from the
        individual legacy getters.  Adapters that cannot provide a coherent
        snapshot must fail closed by leaving this default in place.
        """

        del observed_at
        raise NotImplementedError("broker adapter does not expose authoritative snapshots")


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
        state_db_path: Optional[str | Path] = None,
    ):
        self._sim = ExecutionSimulator(
            cost_model, freq="interday", allow_partial=True,
        )
        self._cash: float = initial_cash
        self._positions: Dict[str, float] = dict(initial_positions or {})
        self._validate_account_state()

        self._open_orders: Dict[str, Order] = {}  # order_id → Order
        self._fills: List[Fill] = []              # chronological
        self._fill_timestamps: List[datetime] = []  # parallel to _fills
        self._mirrored_fill_ids: Dict[str, str] = {}
        # Optional deterministic price override for next fill (per-symbol)
        self._next_fill_prices: Dict[str, float] = {}
        # Default price if nothing injected — caller's responsibility
        self._default_price: Optional[float] = None
        self._state_db_path = Path(state_db_path) if state_db_path is not None else None
        if self._state_db_path is not None:
            self._initialize_state_db()
            self._load_persisted_state()

    # ── Knobs for tests ──────────────────────────────────────────────────────

    def set_next_fill_price(self, symbol: str, price: float) -> None:
        """Pin the fill price for the NEXT submit_order on `symbol`.
        Simplifies deterministic tests. Consumed on use."""
        self._next_fill_prices[symbol] = self._validated_price(price)

    def set_default_fill_price(self, price: float) -> None:
        """Fallback price when no per-symbol override is set."""
        self._default_price = self._validated_price(price)

    def mirror_fill(self, fill: Fill) -> OrderAck:
        """Book an already-simulated PAPER fill exactly once.

        ``PaperTradingEngine`` is the execution authority for the local PAPER
        path.  Re-simulating its completed fill would apply slippage and
        commission twice, so the simulated broker mirrors the authoritative
        quantity, cash delta and price verbatim.  The stable fill key also
        makes a duplicate broker callback idempotent.
        """
        canonical_id = getattr(fill.order, "canonical_order_id", None)
        execution_id = getattr(fill, "broker_fill_id", None) or getattr(
            fill, "execution_id", None
        )
        execution_signature = execution_id or (
            f"{fill.fill_date.isoformat()}:{fill.executed_qty:.12g}:"
            f"{fill.executed_price:.12g}:{fill.cash_delta:.12g}"
        )
        fill_key = (
            f"{canonical_id}:{execution_signature}"
            if canonical_id
            else f"{fill.symbol}:{fill.side.value}:{fill.signal_date.isoformat()}:"
            f"{execution_signature}"
        )
        existing_id = self._mirrored_fill_ids.get(fill_key)
        if existing_id is not None:
            return OrderAck(
                order_id=existing_id,
                order=fill.order,
                submitted_at=datetime.now(),
                status="ACCEPTED",
            )

        if not all(
            math.isfinite(float(value))
            for value in (fill.executed_qty, fill.executed_price, fill.cash_delta)
        ) or fill.executed_qty <= 0 or fill.executed_price <= 0:
            return OrderAck(
                order_id="",
                order=fill.order,
                submitted_at=datetime.now(),
                status="REJECTED",
                reject_reason="fill contains invalid numeric values",
            )

        order_id = uuid.uuid4().hex[:12]
        old_cash = self._cash
        old_positions = dict(self._positions)
        previous = self._positions.get(fill.symbol, 0.0)
        if fill.side == OrderSide.SELL and fill.executed_qty > previous + 1e-6:
            return OrderAck(
                order_id=order_id,
                order=fill.order,
                submitted_at=datetime.now(),
                status="REJECTED",
                reject_reason="sell fill exceeds long position",
            )
        if fill.side == OrderSide.BUY and self._cash + fill.cash_delta < -0.01:
            return OrderAck(
                order_id=order_id,
                order=fill.order,
                submitted_at=datetime.now(),
                status="REJECTED",
                reject_reason="buy fill would create negative cash",
            )
        if fill.side == OrderSide.BUY:
            self._positions[fill.symbol] = previous + fill.executed_qty
        else:
            self._positions[fill.symbol] = max(previous - fill.executed_qty, 0.0)
        self._cash += fill.cash_delta
        self._positions = {
            symbol: quantity
            for symbol, quantity in self._positions.items()
            if quantity > 1e-6
        }
        try:
            self._persist_state(
                fill_key=fill_key,
                broker_order_id=order_id,
                fill=fill,
            )
        except Exception:
            self._cash = old_cash
            self._positions = old_positions
            raise
        self._fills.append(fill)
        self._fill_timestamps.append(datetime.now(UTC))
        self._mirrored_fill_ids[fill_key] = order_id
        return OrderAck(
            order_id=order_id,
            order=fill.order,
            submitted_at=datetime.now(),
            status="ACCEPTED",
        )

    # ── Required ABC methods ─────────────────────────────────────────────────

    def submit_order(self, order: Order) -> OrderAck:
        # Look up (or default) fill price
        sym = order.symbol
        order_id = uuid.uuid4().hex[:12]
        if sym in self._next_fill_prices:
            price = self._next_fill_prices.pop(sym)
        elif self._default_price is not None:
            price = self._default_price
        else:
            self._persist_order(
                order_id,
                order,
                status="REJECTED",
                reason="no fill price configured",
            )
            return OrderAck(
                order_id=order_id, order=order,
                submitted_at=datetime.now(),
                status="REJECTED",
                reject_reason="no fill price configured "
                              "(use set_next_fill_price or set_default_fill_price)",
            )

        if order.side == OrderSide.SELL and order.qty_shares > self._positions.get(sym, 0.0) + 1e-6:
            self._persist_order(order_id, order, status="REJECTED", reason="oversell")
            return OrderAck(
                order_id=order_id,
                order=order,
                submitted_at=datetime.now(),
                status="REJECTED",
                reject_reason="sell order exceeds long position",
            )
        self._open_orders[order_id] = order
        self._persist_order(order_id, order, status="SUBMITTED")

        # Simulate fill immediately using ExecutionSimulator
        fill = self._sim.simulate_fill(order, price, vix=15.0, cash=self._cash)
        if fill is None:
            # Insufficient cash / qty → REJECTED
            self._open_orders.pop(order_id, None)
            self._persist_order(
                order_id,
                order,
                status="REJECTED",
                reason="execution simulator declined",
            )
            return OrderAck(
                order_id=order_id, order=order,
                submitted_at=datetime.now(),
                status="REJECTED",
                reject_reason="execution simulator declined (cash / qty)",
            )

        # Book the fill
        old_cash = self._cash
        old_positions = dict(self._positions)
        prev = self._positions.get(sym, 0.0)
        if fill.side == OrderSide.BUY:
            self._positions[sym] = prev + fill.executed_qty
        else:
            self._positions[sym] = max(prev - fill.executed_qty, 0.0)
        self._cash += fill.cash_delta
        self._positions = {s: q for s, q in self._positions.items() if q > 1e-6}

        try:
            self._persist_state(
                fill_key=f"submit:{order_id}",
                broker_order_id=order_id,
                fill=fill,
            )
        except Exception:
            self._cash = old_cash
            self._positions = old_positions
            self._open_orders.pop(order_id, None)
            raise
        self._fills.append(fill)
        self._fill_timestamps.append(datetime.now(UTC))
        self._mirrored_fill_ids[f"submit:{order_id}"] = order_id
        # Order completes (simulated, no partial fills here)
        self._open_orders.pop(order_id, None)

        return OrderAck(
            order_id=order_id, order=order,
            submitted_at=datetime.now(), status="ACCEPTED",
        )

    def cancel_order(self, order_id: str) -> bool:
        # Simulated adapter fills immediately, so there's nothing to cancel
        # unless the order is still pending (shouldn't happen here).
        order = self._open_orders.pop(order_id, None)
        if order is None:
            return False
        self._persist_order(order_id, order, status="CANCELLED")
        return True

    def get_positions(self) -> Dict[str, float]:
        return dict(self._positions)

    def get_cash(self) -> float:
        return float(self._cash)

    def get_open_orders(self) -> List[Order]:
        return list(self._open_orders.values())

    def get_fills(self, since: datetime) -> List[Fill]:
        since_utc = self._as_utc(since)
        return [
            f for f, ts in zip(self._fills, self._fill_timestamps)
            if self._as_utc(ts) >= since_utc
        ]

    def get_account_snapshot(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> BrokerAccountSnapshot:
        timestamp = datetime.now(UTC) if observed_at is None else self._as_utc(observed_at)
        payload = {
            "cash": float(self._cash),
            "positions": dict(sorted(self._positions.items())),
            "open_order_ids": sorted(self.get_open_order_ids()),
            "fill_ids": sorted(self._mirrored_fill_ids),
            "observed_at": timestamp.isoformat(),
        }
        snapshot_id = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        source = (
            f"simulated-sqlite:{self._state_db_path.resolve()}"
            if self._state_db_path is not None
            else "simulated-memory"
        )
        return BrokerAccountSnapshot(
            snapshot_id=snapshot_id,
            source=source,
            observed_at=timestamp,
            cash=float(self._cash),
            positions=dict(self._positions),
            open_order_ids=self.get_open_order_ids(),
            fill_ids=frozenset(self._mirrored_fill_ids),
        )

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

    def _initialize_state_db(self) -> None:
        assert self._state_db_path is not None
        self._state_db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._state_db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS simulated_broker_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    cash REAL NOT NULL,
                    positions_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS simulated_broker_fill_keys (
                    fill_key TEXT PRIMARY KEY,
                    broker_order_id TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS simulated_broker_fills (
                    fill_key TEXT PRIMARY KEY,
                    broker_order_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS simulated_broker_orders (
                    broker_order_id TEXT PRIMARY KEY,
                    canonical_order_id TEXT,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reject_reason TEXT,
                    submitted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO simulated_broker_state (
                    id, cash, positions_json, updated_at
                ) VALUES (1, ?, ?, ?)
                """,
                (
                    self._cash,
                    json.dumps(self._positions, sort_keys=True),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def _load_persisted_state(self) -> None:
        assert self._state_db_path is not None
        with sqlite3.connect(self._state_db_path) as conn:
            row = conn.execute(
                "SELECT cash, positions_json FROM simulated_broker_state WHERE id = 1"
            ).fetchone()
            keys = conn.execute(
                "SELECT fill_key, broker_order_id FROM simulated_broker_fill_keys"
            ).fetchall()
            fills = conn.execute(
                """
                SELECT fill_key, broker_order_id, payload_json, recorded_at
                FROM simulated_broker_fills ORDER BY recorded_at, fill_key
                """
            ).fetchall()
            open_orders = conn.execute(
                """
                SELECT broker_order_id, payload_json FROM simulated_broker_orders
                WHERE status = 'SUBMITTED' ORDER BY submitted_at, broker_order_id
                """
            ).fetchall()
        if row is not None:
            self._cash = float(row[0])
            self._positions = {
                str(symbol): float(quantity)
                for symbol, quantity in json.loads(row[1]).items()
            }
            self._validate_account_state()
        self._mirrored_fill_ids = {str(key): str(order_id) for key, order_id in keys}
        self._open_orders = {}
        for broker_order_id, payload_json in open_orders:
            order = self._deserialize_order(json.loads(payload_json))
            setattr(order, "broker_order_id", str(broker_order_id))
            self._open_orders[str(broker_order_id)] = order
        self._fills = []
        self._fill_timestamps = []
        for fill_key, broker_order_id, payload_json, recorded_at in fills:
            fill = self._deserialize_fill(json.loads(payload_json))
            setattr(fill, "broker_fill_id", str(fill_key))
            setattr(fill.order, "broker_order_id", str(broker_order_id))
            self._fills.append(fill)
            self._fill_timestamps.append(datetime.fromisoformat(str(recorded_at)))

    @staticmethod
    def _validated_price(price: float) -> float:
        value = float(price)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("fill price must be finite and positive")
        return value

    def _validate_account_state(self) -> None:
        if not math.isfinite(float(self._cash)) or self._cash < -0.01:
            raise ValueError("broker cash must be finite and non-negative")
        invalid = {
            str(symbol): quantity
            for symbol, quantity in self._positions.items()
            if not math.isfinite(float(quantity)) or float(quantity) < 0
        }
        if invalid:
            raise ValueError(f"broker positions must be finite and long-only: {invalid}")

    def _persist_state(
        self,
        *,
        fill_key: str | None = None,
        broker_order_id: str | None = None,
        fill: Fill | None = None,
    ) -> None:
        if self._state_db_path is None:
            return
        with sqlite3.connect(self._state_db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if fill_key is not None:
                if broker_order_id is None or fill is None:
                    raise ValueError("broker_order_id and fill are required with fill_key")
                recorded_at = datetime.now(UTC).isoformat()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO simulated_broker_fill_keys (
                        fill_key, broker_order_id, recorded_at
                    ) VALUES (?, ?, ?)
                    """,
                    (fill_key, broker_order_id, recorded_at),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO simulated_broker_fills (
                        fill_key, broker_order_id, payload_json, recorded_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        fill_key,
                        broker_order_id,
                        json.dumps(
                            self._serialize_fill(fill),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        recorded_at,
                    ),
                )
                order_payload = self._serialize_order(fill.order)
                conn.execute(
                    """
                    INSERT INTO simulated_broker_orders (
                        broker_order_id, canonical_order_id, payload_json,
                        status, reject_reason, submitted_at, updated_at
                    ) VALUES (?, ?, ?, 'FILLED', NULL, ?, ?)
                    ON CONFLICT(broker_order_id) DO UPDATE SET
                        payload_json=excluded.payload_json,
                        status='FILLED', reject_reason=NULL,
                        updated_at=excluded.updated_at
                    """,
                    (
                        broker_order_id,
                        order_payload.get("canonical_order_id"),
                        json.dumps(order_payload, sort_keys=True, separators=(",", ":")),
                        recorded_at,
                        recorded_at,
                    ),
                )
            conn.execute(
                """
                UPDATE simulated_broker_state
                SET cash = ?, positions_json = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    self._cash,
                    json.dumps(self._positions, sort_keys=True),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def _persist_order(
        self,
        broker_order_id: str,
        order: Order,
        *,
        status: str,
        reason: str | None = None,
    ) -> None:
        if self._state_db_path is None:
            return
        if status not in {"SUBMITTED", "FILLED", "REJECTED", "CANCELLED", "UNKNOWN"}:
            raise ValueError(f"unsupported simulated broker order status: {status}")
        now = datetime.now(UTC).isoformat()
        payload = self._serialize_order(order)
        with sqlite3.connect(self._state_db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO simulated_broker_orders (
                    broker_order_id, canonical_order_id, payload_json,
                    status, reject_reason, submitted_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(broker_order_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    status=excluded.status,
                    reject_reason=excluded.reject_reason,
                    updated_at=excluded.updated_at
                """,
                (
                    broker_order_id,
                    payload.get("canonical_order_id"),
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    status,
                    reason,
                    now,
                    now,
                ),
            )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _serialize_fill(fill: Fill) -> dict:
        canonical_order_id = getattr(fill.order, "canonical_order_id", None)
        return {
            "symbol": fill.symbol,
            "side": fill.side.value,
            "ordered_quantity": float(fill.order.qty_shares),
            "executed_quantity": float(fill.executed_qty),
            "executed_price": float(fill.executed_price),
            "signal_date": fill.signal_date.isoformat(),
            "fill_date": fill.fill_date.isoformat(),
            "cash_delta": float(fill.cash_delta),
            "canonical_order_id": canonical_order_id,
            "cost": {
                "notional_usd": float(fill.cost_breakdown.notional_usd),
                "commission_usd": float(fill.cost_breakdown.commission_usd),
                "slippage_usd": float(fill.cost_breakdown.slippage_usd),
                "total_cost_usd": float(fill.cost_breakdown.total_cost_usd),
                "total_bps": float(fill.cost_breakdown.total_bps),
            },
        }

    @staticmethod
    def _serialize_order(order: Order) -> dict:
        return {
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": float(order.qty_shares),
            "signal_date": order.signal_date.isoformat(),
            "comment": order.comment,
            "canonical_order_id": getattr(order, "canonical_order_id", None),
        }

    @staticmethod
    def _deserialize_order(payload: dict) -> Order:
        order = Order(
            symbol=str(payload["symbol"]),
            side=OrderSide(str(payload["side"])),
            qty_shares=float(payload["quantity"]),
            signal_date=pd.Timestamp(payload["signal_date"]),
            comment=str(payload.get("comment", "")),
        )
        if payload.get("canonical_order_id"):
            setattr(order, "canonical_order_id", str(payload["canonical_order_id"]))
        return order

    @staticmethod
    def _deserialize_fill(payload: dict) -> Fill:
        from core.execution.cost_model import CostBreakdown

        order = Order(
            symbol=str(payload["symbol"]),
            side=OrderSide(str(payload["side"])),
            qty_shares=float(payload["ordered_quantity"]),
            signal_date=pd.Timestamp(payload["signal_date"]),
        )
        if payload.get("canonical_order_id"):
            setattr(order, "canonical_order_id", str(payload["canonical_order_id"]))
        cost = payload["cost"]
        return Fill(
            order=order,
            executed_price=float(payload["executed_price"]),
            executed_qty=float(payload["executed_quantity"]),
            cost_breakdown=CostBreakdown(
                symbol=str(payload["symbol"]),
                notional_usd=float(cost["notional_usd"]),
                commission_usd=float(cost["commission_usd"]),
                slippage_usd=float(cost["slippage_usd"]),
                total_cost_usd=float(cost["total_cost_usd"]),
                total_bps=float(cost["total_bps"]),
            ),
            fill_date=pd.Timestamp(payload["fill_date"]),
            cash_delta=float(payload["cash_delta"]),
        )
