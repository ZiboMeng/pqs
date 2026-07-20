from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from core.runtime.lease import (
    LeaseUnavailableError,
    SQLiteLeaseManager,
    StaleFencingTokenError,
)

NOW = datetime(2026, 7, 20, 20, 0, tzinfo=UTC)


def test_lease_is_single_owner_and_same_owner_renews_same_fence(tmp_path) -> None:
    manager = SQLiteLeaseManager(tmp_path / "state.db")
    first = manager.acquire("forward-paper", "worker-a", now=NOW, ttl=timedelta(minutes=5))
    renewed = manager.acquire(
        "forward-paper",
        "worker-a",
        now=NOW + timedelta(minutes=1),
        ttl=timedelta(minutes=5),
    )
    assert renewed.fencing_token == first.fencing_token == 1
    manager.assert_valid(renewed, now=NOW + timedelta(minutes=2))

    with pytest.raises(LeaseUnavailableError, match="worker-a"):
        manager.acquire(
            "forward-paper",
            "worker-b",
            now=NOW + timedelta(minutes=2),
            ttl=timedelta(minutes=5),
        )


def test_expired_owner_is_fenced_by_monotonic_token(tmp_path) -> None:
    manager = SQLiteLeaseManager(tmp_path / "state.db")
    old = manager.acquire("forward-paper", "worker-a", now=NOW, ttl=timedelta(minutes=1))
    new = manager.acquire(
        "forward-paper",
        "worker-b",
        now=NOW + timedelta(minutes=2),
        ttl=timedelta(minutes=5),
    )
    assert new.fencing_token == old.fencing_token + 1
    with pytest.raises(StaleFencingTokenError, match="expired|stale"):
        manager.assert_valid(old, now=NOW + timedelta(minutes=2))
    manager.assert_valid(new, now=NOW + timedelta(minutes=2))


def test_release_preserves_fencing_history(tmp_path) -> None:
    manager = SQLiteLeaseManager(tmp_path / "state.db")
    first = manager.acquire("forward-paper", "worker-a", now=NOW, ttl=timedelta(minutes=5))
    assert manager.release(first, now=NOW + timedelta(seconds=1))
    second = manager.acquire(
        "forward-paper",
        "worker-b",
        now=NOW + timedelta(seconds=2),
        ttl=timedelta(minutes=5),
    )
    assert second.fencing_token == 2
    assert not manager.release(first, now=NOW + timedelta(seconds=3))


def test_assert_valid_can_share_callers_write_transaction(tmp_path) -> None:
    db = tmp_path / "state.db"
    manager = SQLiteLeaseManager(db)
    token = manager.acquire("forward-paper", "worker-a", now=NOW, ttl=timedelta(minutes=5))
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        manager.assert_valid(token, now=NOW + timedelta(minutes=1), connection=conn)
