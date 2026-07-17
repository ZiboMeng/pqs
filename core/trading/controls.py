"""Durable global/strategy/symbol trading pause controls with audit events."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class ControlScope(StrEnum):
    GLOBAL = "GLOBAL"
    STRATEGY = "STRATEGY"
    SYMBOL = "SYMBOL"


@dataclass(frozen=True, slots=True)
class TradingControl:
    scope: ControlScope
    scope_key: str
    paused: bool
    reason: str
    updated_by: str
    updated_at: datetime
    version: int


class TradingControlStore:
    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trading_controls (
                    scope       TEXT NOT NULL,
                    scope_key   TEXT NOT NULL,
                    paused      INTEGER NOT NULL,
                    reason      TEXT NOT NULL,
                    updated_by  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    version     INTEGER NOT NULL,
                    PRIMARY KEY(scope, scope_key)
                );
                CREATE TABLE IF NOT EXISTS trading_control_events (
                    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope       TEXT NOT NULL,
                    scope_key   TEXT NOT NULL,
                    paused      INTEGER NOT NULL,
                    reason      TEXT NOT NULL,
                    updated_by  TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    version     INTEGER NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def set_paused(
        self,
        scope: ControlScope,
        scope_key: str,
        *,
        paused: bool,
        reason: str,
        updated_by: str,
    ) -> TradingControl:
        key = self._normalize_key(scope, scope_key)
        if not reason.strip():
            raise ValueError("reason is required for pause and resume")
        if not updated_by.strip():
            raise ValueError("updated_by is required for pause and resume")
        now = datetime.now(UTC)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT version FROM trading_controls WHERE scope=? AND scope_key=?",
                (scope.value, key),
            ).fetchone()
            version = 1 if row is None else int(row["version"]) + 1
            values = (
                int(paused),
                reason.strip(),
                updated_by.strip(),
                now.isoformat(),
                version,
                scope.value,
                key,
            )
            conn.execute(
                """
                INSERT INTO trading_controls (
                    paused, reason, updated_by, updated_at, version, scope, scope_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, scope_key) DO UPDATE SET
                    paused=excluded.paused,
                    reason=excluded.reason,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at,
                    version=excluded.version
                """,
                values,
            )
            conn.execute(
                """
                INSERT INTO trading_control_events (
                    scope, scope_key, paused, reason, updated_by, occurred_at, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope.value,
                    key,
                    int(paused),
                    reason.strip(),
                    updated_by.strip(),
                    now.isoformat(),
                    version,
                ),
            )
        return TradingControl(scope, key, paused, reason.strip(), updated_by.strip(), now, version)

    def is_paused(self, *, strategy_id: str, symbol: str) -> bool:
        checks = (
            (ControlScope.GLOBAL.value, "*"),
            (ControlScope.STRATEGY.value, strategy_id.strip()),
            (ControlScope.SYMBOL.value, symbol.strip().upper()),
        )
        with self._connect() as conn:
            for scope, key in checks:
                row = conn.execute(
                    "SELECT paused FROM trading_controls WHERE scope=? AND scope_key=?",
                    (scope, key),
                ).fetchone()
                if row is not None and bool(row["paused"]):
                    return True
        return False

    def events(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trading_control_events ORDER BY event_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_current(self) -> list[TradingControl]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trading_controls ORDER BY scope, scope_key"
            ).fetchall()
        return [
            TradingControl(
                scope=ControlScope(row["scope"]),
                scope_key=row["scope_key"],
                paused=bool(row["paused"]),
                reason=row["reason"],
                updated_by=row["updated_by"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
                version=int(row["version"]),
            )
            for row in rows
        ]

    @staticmethod
    def _normalize_key(scope: ControlScope, scope_key: str) -> str:
        if scope is ControlScope.GLOBAL:
            return "*"
        key = scope_key.strip().upper() if scope is ControlScope.SYMBOL else scope_key.strip()
        if not key:
            raise ValueError("scope_key is required")
        return key
