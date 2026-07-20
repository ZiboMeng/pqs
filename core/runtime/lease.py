"""SQLite scheduler lease with monotonically increasing fencing tokens."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


class LeaseUnavailableError(RuntimeError):
    """Raised when another non-expired owner holds the scheduler lease."""


class StaleFencingTokenError(RuntimeError):
    """Raised before a stale or expired writer can commit state."""


@dataclass(frozen=True, slots=True)
class LeaseToken:
    lease_name: str
    owner_id: str
    fencing_token: int
    expires_at: datetime


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("lease timestamps must be timezone-aware")
    return value.astimezone(UTC)


class SQLiteLeaseManager:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduler_leases (
                    lease_name TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    expires_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduler_lease_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lease_name TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    occurred_at_utc TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def acquire(
        self,
        lease_name: str,
        owner_id: str,
        *,
        now: datetime,
        ttl: timedelta,
    ) -> LeaseToken:
        if not lease_name.strip() or not owner_id.strip():
            raise ValueError("lease name and owner id are required")
        if ttl <= timedelta(0):
            raise ValueError("lease ttl must be positive")
        current_time = _utc(now)
        expires = current_time + ttl
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM scheduler_leases WHERE lease_name = ?",
                (lease_name,),
            ).fetchone()
            if row is None:
                fencing_token = 1
                conn.execute(
                    """
                    INSERT INTO scheduler_leases (
                        lease_name, owner_id, fencing_token,
                        expires_at_utc, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        lease_name,
                        owner_id,
                        fencing_token,
                        expires.isoformat(),
                        current_time.isoformat(),
                    ),
                )
            else:
                recorded_expiry = datetime.fromisoformat(row["expires_at_utc"])
                if recorded_expiry > current_time and row["owner_id"] != owner_id:
                    raise LeaseUnavailableError(
                        f"lease {lease_name} is held by {row['owner_id']} until "
                        f"{recorded_expiry.isoformat()}"
                    )
                if recorded_expiry > current_time and row["owner_id"] == owner_id:
                    fencing_token = int(row["fencing_token"])
                else:
                    fencing_token = int(row["fencing_token"]) + 1
                conn.execute(
                    """
                    UPDATE scheduler_leases
                    SET owner_id = ?, fencing_token = ?, expires_at_utc = ?,
                        updated_at_utc = ?
                    WHERE lease_name = ?
                    """,
                    (
                        owner_id,
                        fencing_token,
                        expires.isoformat(),
                        current_time.isoformat(),
                        lease_name,
                    ),
                )
        return LeaseToken(lease_name, owner_id, fencing_token, expires)

    def assert_valid(
        self,
        token: LeaseToken,
        *,
        now: datetime,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        current_time = _utc(now)
        if token.expires_at <= current_time:
            raise StaleFencingTokenError("provided lease token is expired")

        def _validate(conn: sqlite3.Connection) -> None:
            row = conn.execute(
                "SELECT * FROM scheduler_leases WHERE lease_name = ?",
                (token.lease_name,),
            ).fetchone()
            if row is None:
                raise StaleFencingTokenError("scheduler lease no longer exists")
            recorded_expiry = datetime.fromisoformat(row["expires_at_utc"])
            if (
                row["owner_id"] != token.owner_id
                or int(row["fencing_token"]) != token.fencing_token
                or recorded_expiry <= current_time
            ):
                raise StaleFencingTokenError(
                    "scheduler lease owner, fencing token, or expiry is stale"
                )

        if connection is not None:
            _validate(connection)
            return
        with self._connect() as conn:
            _validate(conn)

    def release(self, token: LeaseToken, *, now: datetime) -> bool:
        current_time = _utc(now)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE scheduler_leases
                SET expires_at_utc = ?, updated_at_utc = ?
                WHERE lease_name = ? AND owner_id = ? AND fencing_token = ?
                """,
                (
                    current_time.isoformat(),
                    current_time.isoformat(),
                    token.lease_name,
                    token.owner_id,
                    token.fencing_token,
                ),
            )
            changed = cursor.rowcount == 1
            if changed:
                conn.execute(
                    """
                    INSERT INTO scheduler_lease_events (
                        lease_name, owner_id, fencing_token, action, occurred_at_utc
                    ) VALUES (?, ?, ?, 'RELEASED', ?)
                    """,
                    (
                        token.lease_name,
                        token.owner_id,
                        token.fencing_token,
                        current_time.isoformat(),
                    ),
                )
            return changed
