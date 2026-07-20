"""Durable state for the three-stage Forward PAPER lifecycle."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.execution.execution_simulator import Fill
from core.runtime.lease import LeaseToken, SQLiteLeaseManager
from core.runtime.strategy_artifact import canonical_json, sha256_bytes


class ForwardStateError(RuntimeError):
    """Raised on illegal, duplicate-conflicting, or corrupt forward state."""


@dataclass(frozen=True, slots=True)
class ForwardAccount:
    cash: float
    positions: dict[str, float]
    equity: float
    last_finalized_session: str | None


@dataclass(frozen=True, slots=True)
class StoredDecision:
    signal_session: str
    execution_session: str
    decision_id: str
    artifact_root_sha256: str
    state: str
    payload: dict[str, Any]


def content_hash(payload: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(payload))


class ForwardStateStore:
    def __init__(self, db_path: str | Path, *, initial_capital: float) -> None:
        if not math.isfinite(initial_capital) or initial_capital <= 0:
            raise ValueError("initial capital must be finite and positive")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS forward_account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    cash REAL NOT NULL,
                    positions_json TEXT NOT NULL,
                    equity REAL NOT NULL,
                    last_finalized_session TEXT,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forward_decisions (
                    signal_session TEXT PRIMARY KEY,
                    execution_session TEXT NOT NULL UNIQUE,
                    decision_id TEXT NOT NULL UNIQUE,
                    artifact_root_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forward_events (
                    event_id TEXT PRIMARY KEY,
                    phase TEXT NOT NULL,
                    session TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    processed_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forward_fills (
                    fill_id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    cash_delta REAL NOT NULL,
                    cost REAL NOT NULL,
                    fill_time_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forward_nav (
                    session TEXT PRIMARY KEY,
                    equity REAL NOT NULL,
                    cash REAL NOT NULL,
                    positions_json TEXT NOT NULL,
                    daily_pnl REAL NOT NULL,
                    reconciliation_json TEXT NOT NULL,
                    recorded_at_utc TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO forward_account (
                    id, cash, positions_json, equity,
                    last_finalized_session, updated_at_utc
                ) VALUES (1, ?, '{}', ?, NULL, ?)
                """,
                (initial_capital, initial_capital, datetime.now(UTC).isoformat()),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def account(self, *, connection: sqlite3.Connection | None = None) -> ForwardAccount:
        def _read(conn: sqlite3.Connection) -> ForwardAccount:
            row = conn.execute("SELECT * FROM forward_account WHERE id = 1").fetchone()
            if row is None:
                raise ForwardStateError("forward account is not initialized")
            positions = {
                str(symbol): float(quantity)
                for symbol, quantity in json.loads(row["positions_json"]).items()
            }
            account = ForwardAccount(
                cash=float(row["cash"]),
                positions=positions,
                equity=float(row["equity"]),
                last_finalized_session=row["last_finalized_session"],
            )
            self._validate_account(account)
            return account

        if connection is not None:
            return _read(connection)
        with self._connect() as conn:
            return _read(conn)

    @staticmethod
    def _validate_account(account: ForwardAccount) -> None:
        if not math.isfinite(account.cash) or account.cash < -0.01:
            raise ForwardStateError("forward account cash is invalid")
        if not math.isfinite(account.equity) or account.equity <= 0:
            raise ForwardStateError("forward account equity is invalid")
        if any(
            not math.isfinite(float(quantity)) or float(quantity) < 0
            for quantity in account.positions.values()
        ):
            raise ForwardStateError("forward account positions are not finite and long-only")

    def decision(self, signal_session: str) -> StoredDecision | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forward_decisions WHERE signal_session = ?",
                (signal_session,),
            ).fetchone()
        return None if row is None else self._decision_from_row(row)

    def decision_for_execution(self, execution_session: str) -> StoredDecision | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forward_decisions WHERE execution_session = ?",
                (execution_session,),
            ).fetchone()
        return None if row is None else self._decision_from_row(row)

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> StoredDecision:
        return StoredDecision(
            signal_session=str(row["signal_session"]),
            execution_session=str(row["execution_session"]),
            decision_id=str(row["decision_id"]),
            artifact_root_sha256=str(row["artifact_root_sha256"]),
            state=str(row["state"]),
            payload=json.loads(row["payload_json"]),
        )

    def event_result(self, event_id: str, event_sha256: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content_sha256, result_json FROM forward_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        if row["content_sha256"] != event_sha256:
            raise ForwardStateError(f"event id reused with different content: {event_id}")
        return json.loads(row["result_json"])

    def record_decision(
        self,
        *,
        event_id: str,
        event_sha256: str,
        signal_session: str,
        execution_session: str,
        decision_id: str,
        artifact_root_sha256: str,
        payload: dict[str, Any],
        result: dict[str, Any],
        token: LeaseToken,
        lease_manager: SQLiteLeaseManager,
        now: datetime,
    ) -> bool:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            lease_manager.assert_valid(token, now=now, connection=conn)
            existing_event = conn.execute(
                "SELECT * FROM forward_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if existing_event is not None:
                if existing_event["content_sha256"] != event_sha256:
                    raise ForwardStateError(
                        f"event id reused with different content: {event_id}"
                    )
                return True
            existing_decision = conn.execute(
                "SELECT decision_id FROM forward_decisions WHERE signal_session = ?",
                (signal_session,),
            ).fetchone()
            if existing_decision is not None:
                raise ForwardStateError(
                    f"signal session already has a different event: {signal_session}"
                )
            timestamp = now.astimezone(UTC).isoformat()
            conn.execute(
                """
                INSERT INTO forward_decisions (
                    signal_session, execution_session, decision_id,
                    artifact_root_sha256, state, payload_json,
                    created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, 'FROZEN', ?, ?, ?)
                """,
                (
                    signal_session,
                    execution_session,
                    decision_id,
                    artifact_root_sha256,
                    canonical_json(payload).decode("utf-8"),
                    timestamp,
                    timestamp,
                ),
            )
            self._insert_event(
                conn,
                event_id=event_id,
                phase="CLOSE_DECISION",
                session=signal_session,
                event_sha256=event_sha256,
                result=result,
                token=token,
                now=now,
            )
        return False

    def persist_execution(
        self,
        connection: sqlite3.Connection,
        *,
        event_id: str,
        event_sha256: str,
        decision: StoredDecision,
        cash: float,
        positions: dict[str, float],
        equity_at_open: float,
        fills: list[tuple[str, str, Fill]],
        result: dict[str, Any],
        token: LeaseToken,
        lease_manager: SQLiteLeaseManager,
        now: datetime,
    ) -> None:
        lease_manager.assert_valid(token, now=now, connection=connection)
        current = connection.execute(
            "SELECT state FROM forward_decisions WHERE decision_id = ?",
            (decision.decision_id,),
        ).fetchone()
        if current is None or current["state"] != "FROZEN":
            raise ForwardStateError("decision is not in FROZEN state")
        account = ForwardAccount(cash, positions, equity_at_open, None)
        self._validate_account(account)
        timestamp = now.astimezone(UTC).isoformat()
        connection.execute(
            """
            UPDATE forward_account
            SET cash = ?, positions_json = ?, equity = ?, updated_at_utc = ?
            WHERE id = 1
            """,
            (
                cash,
                json.dumps(positions, sort_keys=True),
                equity_at_open,
                timestamp,
            ),
        )
        for fill_id, order_id, fill in fills:
            fill_payload = {
                "signal_date": fill.signal_date.isoformat(),
                "fill_date": fill.fill_date.isoformat(),
                "notional_usd": fill.notional_usd,
            }
            connection.execute(
                """
                INSERT INTO forward_fills (
                    fill_id, decision_id, order_id, symbol, side,
                    quantity, price, cash_delta, cost, fill_time_utc,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill_id,
                    decision.decision_id,
                    order_id,
                    fill.symbol,
                    fill.side.value,
                    fill.executed_qty,
                    fill.executed_price,
                    fill.cash_delta,
                    fill.cost_breakdown.total_cost_usd,
                    timestamp,
                    canonical_json(fill_payload).decode("utf-8"),
                ),
            )
        connection.execute(
            """
            UPDATE forward_decisions
            SET state = 'EXECUTED', updated_at_utc = ? WHERE decision_id = ?
            """,
            (timestamp, decision.decision_id),
        )
        self._insert_event(
            connection,
            event_id=event_id,
            phase="OPEN_EXECUTION",
            session=decision.execution_session,
            event_sha256=event_sha256,
            result=result,
            token=token,
            now=now,
        )

    def finalize(
        self,
        *,
        event_id: str,
        event_sha256: str,
        decision: StoredDecision,
        equity: float,
        daily_pnl: float,
        reconciliation: dict[str, Any],
        result: dict[str, Any],
        token: LeaseToken,
        lease_manager: SQLiteLeaseManager,
        now: datetime,
    ) -> bool:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            lease_manager.assert_valid(token, now=now, connection=conn)
            existing_event = conn.execute(
                "SELECT * FROM forward_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            if existing_event is not None:
                if existing_event["content_sha256"] != event_sha256:
                    raise ForwardStateError(
                        f"event id reused with different content: {event_id}"
                    )
                return True
            current = conn.execute(
                "SELECT state FROM forward_decisions WHERE decision_id = ?",
                (decision.decision_id,),
            ).fetchone()
            if current is None or current["state"] != "EXECUTED":
                raise ForwardStateError("decision is not in EXECUTED state")
            account = self.account(connection=conn)
            if not math.isfinite(equity) or equity <= 0 or not math.isfinite(daily_pnl):
                raise ForwardStateError("finalized NAV values are invalid")
            timestamp = now.astimezone(UTC).isoformat()
            conn.execute(
                """
                UPDATE forward_account
                SET equity = ?, last_finalized_session = ?, updated_at_utc = ?
                WHERE id = 1
                """,
                (equity, decision.execution_session, timestamp),
            )
            conn.execute(
                """
                INSERT INTO forward_nav (
                    session, equity, cash, positions_json, daily_pnl,
                    reconciliation_json, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.execution_session,
                    equity,
                    account.cash,
                    json.dumps(account.positions, sort_keys=True),
                    daily_pnl,
                    canonical_json(reconciliation).decode("utf-8"),
                    timestamp,
                ),
            )
            conn.execute(
                """
                UPDATE forward_decisions
                SET state = 'FINALIZED', updated_at_utc = ? WHERE decision_id = ?
                """,
                (timestamp, decision.decision_id),
            )
            self._insert_event(
                conn,
                event_id=event_id,
                phase="EOD_FINALIZE",
                session=decision.execution_session,
                event_sha256=event_sha256,
                result=result,
                token=token,
                now=now,
            )
        return False

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        *,
        event_id: str,
        phase: str,
        session: str,
        event_sha256: str,
        result: dict[str, Any],
        token: LeaseToken,
        now: datetime,
    ) -> None:
        conn.execute(
            """
            INSERT INTO forward_events (
                event_id, phase, session, content_sha256, result_json,
                fencing_token, processed_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                phase,
                session,
                event_sha256,
                canonical_json(result).decode("utf-8"),
                token.fencing_token,
                now.astimezone(UTC).isoformat(),
            ),
        )

    def nav_history(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM forward_nav ORDER BY session").fetchall()
        return [dict(row) for row in rows]

    def status(self) -> dict[str, Any]:
        account = self.account()
        with self._connect() as conn:
            decision_counts = {
                row["state"]: int(row["count"])
                for row in conn.execute(
                    "SELECT state, COUNT(*) AS count FROM forward_decisions GROUP BY state"
                ).fetchall()
            }
            latest_event = conn.execute(
                "SELECT * FROM forward_events ORDER BY processed_at_utc DESC LIMIT 1"
            ).fetchone()
        return {
            "account": {
                "cash": account.cash,
                "positions": account.positions,
                "equity": account.equity,
                "last_finalized_session": account.last_finalized_session,
            },
            "decision_counts": decision_counts,
            "latest_event": None if latest_event is None else dict(latest_event),
        }
