"""Transactional SQLite order ledger with durable idempotency and events."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .order import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    OrderIntent,
    OrderState,
    TradingSide,
)


class InvalidOrderTransitionError(RuntimeError):
    pass


class IdempotencyConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StoredOrder:
    intent: OrderIntent
    state: OrderState
    broker_order_id: str | None
    filled_quantity: float
    updated_at: datetime


class OrderStore:
    """Single-writer-safe order ledger; every state change is atomic."""

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @property
    def db_path(self) -> Path:
        return self._db_path

    @contextmanager
    def transaction(self):
        """Yield one write transaction reusable by PAPER account persistence."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id          TEXT PRIMARY KEY,
                    idempotency_key   TEXT NOT NULL UNIQUE,
                    signal_id         TEXT NOT NULL,
                    strategy_id       TEXT NOT NULL,
                    decision_id       TEXT NOT NULL,
                    symbol            TEXT NOT NULL,
                    side              TEXT NOT NULL,
                    quantity          REAL NOT NULL,
                    reference_price   REAL NOT NULL,
                    comment           TEXT NOT NULL,
                    state             TEXT NOT NULL,
                    broker_order_id   TEXT,
                    filled_quantity   REAL NOT NULL DEFAULT 0,
                    created_at        TEXT NOT NULL,
                    updated_at        TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS order_events (
                    event_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id          TEXT NOT NULL,
                    from_state        TEXT,
                    to_state          TEXT NOT NULL,
                    reason            TEXT NOT NULL,
                    metadata_json     TEXT NOT NULL,
                    occurred_at       TEXT NOT NULL,
                    FOREIGN KEY(order_id) REFERENCES orders(order_id)
                );
                CREATE INDEX IF NOT EXISTS idx_order_events_order
                    ON order_events(order_id, event_id);
                """
            )

    def create_or_get(self, intent: OrderIntent) -> tuple[StoredOrder, bool]:
        """Insert once by idempotency key; return ``(order, created)``."""
        now = intent.created_at.astimezone(UTC).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM orders WHERE idempotency_key = ?",
                (intent.idempotency_key,),
            ).fetchone()
            if existing is not None:
                stored = self._from_row(existing)
                self._assert_same_intent(stored.intent, intent)
                return stored, False

            conn.execute(
                """
                INSERT INTO orders (
                    order_id, idempotency_key, signal_id, strategy_id,
                    decision_id, symbol, side, quantity, reference_price,
                    comment, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.order_id,
                    intent.idempotency_key,
                    intent.signal_id,
                    intent.strategy_id,
                    intent.decision_id,
                    intent.symbol,
                    intent.side.value,
                    intent.quantity,
                    intent.reference_price,
                    intent.comment,
                    OrderState.CREATED.value,
                    now,
                    now,
                ),
            )
            self._insert_event(
                conn,
                intent.order_id,
                None,
                OrderState.CREATED,
                reason="intent_registered",
            )
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id = ?", (intent.order_id,)
            ).fetchone()
            assert row is not None
            return self._from_row(row), True

    def get(
        self,
        order_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> StoredOrder | None:
        if connection is not None:
            row = connection.execute(
                "SELECT * FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            return None if row is None else self._from_row(row)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return None if row is None else self._from_row(row)

    def list_nonterminal(self) -> list[StoredOrder]:
        terminal_values = tuple(state.value for state in TERMINAL_STATES)
        placeholders = ",".join("?" for _ in terminal_values)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM orders WHERE state NOT IN ({placeholders}) "  # noqa: S608
                "ORDER BY created_at, order_id",
                terminal_values,
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_all(self) -> list[StoredOrder]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM orders ORDER BY created_at, order_id").fetchall()
        return [self._from_row(row) for row in rows]

    def transition(
        self,
        order_id: str,
        to_state: OrderState,
        *,
        reason: str,
        broker_order_id: str | None = None,
        filled_quantity: float | None = None,
        metadata: dict[str, Any] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> StoredOrder:
        if connection is not None:
            return self._transition_on_connection(
                connection,
                order_id,
                to_state,
                reason=reason,
                broker_order_id=broker_order_id,
                filled_quantity=filled_quantity,
                metadata=metadata,
            )
        with self.transaction() as conn:
            return self._transition_on_connection(
                conn,
                order_id,
                to_state,
                reason=reason,
                broker_order_id=broker_order_id,
                filled_quantity=filled_quantity,
                metadata=metadata,
            )

    def _transition_on_connection(
        self,
        conn: sqlite3.Connection,
        order_id: str,
        to_state: OrderState,
        *,
        reason: str,
        broker_order_id: str | None = None,
        filled_quantity: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StoredOrder:
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown order_id {order_id}")
        current = self._from_row(row)
        if to_state not in ALLOWED_TRANSITIONS.get(current.state, frozenset()):
            raise InvalidOrderTransitionError(
                f"{current.state.value} -> {to_state.value} is not allowed"
            )

        next_filled = current.filled_quantity if filled_quantity is None else float(filled_quantity)
        if next_filled < current.filled_quantity or next_filled > current.intent.quantity:
            raise InvalidOrderTransitionError(
                "filled quantity must be monotonic and <= order quantity"
            )
        if to_state is OrderState.PARTIALLY_FILLED and not (
            0 < next_filled < current.intent.quantity
        ):
            raise InvalidOrderTransitionError("PARTIALLY_FILLED requires 0 < filled < quantity")
        if to_state is OrderState.FILLED and next_filled != current.intent.quantity:
            raise InvalidOrderTransitionError("FILLED requires filled quantity == order quantity")

        now = datetime.now(UTC).isoformat()
        next_broker_id = broker_order_id or current.broker_order_id
        conn.execute(
            """
                UPDATE orders
                SET state = ?, broker_order_id = ?, filled_quantity = ?, updated_at = ?
                WHERE order_id = ?
                """,
            (to_state.value, next_broker_id, next_filled, now, order_id),
        )
        self._insert_event(
            conn,
            order_id,
            current.state,
            to_state,
            reason=reason,
            metadata=metadata,
        )
        updated = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        assert updated is not None
        return self._from_row(updated)

    def events(self, order_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT from_state, to_state, reason, metadata_json, occurred_at
                FROM order_events WHERE order_id = ? ORDER BY event_id
                """,
                (order_id,),
            ).fetchall()
        return [
            {
                "from_state": row["from_state"],
                "to_state": row["to_state"],
                "reason": row["reason"],
                "metadata": json.loads(row["metadata_json"]),
                "occurred_at": row["occurred_at"],
            }
            for row in rows
        ]

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        order_id: str,
        from_state: OrderState | None,
        to_state: OrderState,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO order_events (
                order_id, from_state, to_state, reason, metadata_json, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                None if from_state is None else from_state.value,
                to_state.value,
                reason,
                json.dumps(metadata or {}, sort_keys=True),
                datetime.now(UTC).isoformat(),
            ),
        )

    @staticmethod
    def _assert_same_intent(existing: OrderIntent, incoming: OrderIntent) -> None:
        material_existing = (
            existing.symbol,
            existing.side,
            existing.quantity,
            existing.reference_price,
            existing.signal_id,
            existing.strategy_id,
            existing.decision_id,
        )
        material_incoming = (
            incoming.symbol,
            incoming.side,
            incoming.quantity,
            incoming.reference_price,
            incoming.signal_id,
            incoming.strategy_id,
            incoming.decision_id,
        )
        if material_existing != material_incoming:
            raise IdempotencyConflictError(
                "idempotency key was already used for a different order intent"
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StoredOrder:
        created_at = datetime.fromisoformat(row["created_at"])
        intent = OrderIntent(
            order_id=row["order_id"],
            idempotency_key=row["idempotency_key"],
            signal_id=row["signal_id"],
            strategy_id=row["strategy_id"],
            decision_id=row["decision_id"],
            symbol=row["symbol"],
            side=TradingSide(row["side"]),
            quantity=float(row["quantity"]),
            reference_price=float(row["reference_price"]),
            comment=row["comment"],
            created_at=created_at,
        )
        return StoredOrder(
            intent=intent,
            state=OrderState(row["state"]),
            broker_order_id=row["broker_order_id"],
            filled_quantity=float(row["filled_quantity"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
