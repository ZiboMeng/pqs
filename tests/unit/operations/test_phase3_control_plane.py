from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from core.operations.control_plane import (
    OperatorControlStore,
    OperatorRequestConflictError,
    ReconcileAuditStore,
    readiness_from_snapshot,
    reconcile_sqlite_state,
)
from core.trading.controls import ControlScope, TradingControlStore


def _databases(root: Path, *, broker_cash: float = 100_000.0) -> tuple[Path, Path]:
    state = root / "forward.db"
    broker = root / "broker.db"
    with sqlite3.connect(state) as connection:
        connection.executescript(
            """
            CREATE TABLE forward_account (
                id INTEGER PRIMARY KEY, cash REAL, positions_json TEXT,
                equity REAL, last_finalized_session TEXT, updated_at_utc TEXT
            );
            CREATE TABLE orders (
                order_id TEXT PRIMARY KEY, broker_order_id TEXT, state TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO forward_account VALUES (1, 100000, '{}', 100000, NULL, 'now')"
        )
    with sqlite3.connect(broker) as connection:
        connection.executescript(
            """
            CREATE TABLE simulated_broker_state (
                id INTEGER PRIMARY KEY, cash REAL, positions_json TEXT, updated_at TEXT
            );
            CREATE TABLE simulated_broker_orders (
                broker_order_id TEXT PRIMARY KEY, status TEXT
            );
            """
        )
        connection.execute(
            "INSERT INTO simulated_broker_state VALUES (1, ?, '{}', 'now')",
            (broker_cash,),
        )
    return state, broker


def test_control_request_id_is_idempotent_and_conflict_protected(tmp_path: Path) -> None:
    database = tmp_path / "control.db"
    store = OperatorControlStore(database)
    first = store.set_paused(
        ControlScope.GLOBAL,
        "*",
        paused=True,
        reason="incident",
        updated_by="oncall-a",
        request_id="pause-1",
    )
    second = store.set_paused(
        ControlScope.GLOBAL,
        "*",
        paused=True,
        reason="incident",
        updated_by="oncall-a",
        request_id="pause-1",
    )
    assert first.version == second.version == 1
    assert second.reused is True
    assert len(TradingControlStore(database).events()) == 1
    with pytest.raises(OperatorRequestConflictError):
        store.set_paused(
            ControlScope.GLOBAL,
            "*",
            paused=False,
            reason="incident",
            updated_by="oncall-a",
            request_id="pause-1",
        )


def test_read_only_sqlite_reconciliation_passes_for_matching_accounts(tmp_path: Path) -> None:
    state, broker = _databases(tmp_path)
    result = reconcile_sqlite_state(state, broker)
    assert result["passed"] is True
    assert result["broker_writes_performed"] is False


def test_audited_reconcile_is_idempotent_and_mismatch_auto_pauses(tmp_path: Path) -> None:
    state, broker = _databases(tmp_path, broker_cash=99_000.0)
    audit = ReconcileAuditStore(state)
    first = audit.execute(
        request_id="reconcile-1",
        actor="oncall-a",
        reason="investigate cash",
        state_database=state,
        broker_database=broker,
    )
    second = audit.execute(
        request_id="reconcile-1",
        actor="oncall-a",
        reason="investigate cash",
        state_database=state,
        broker_database=broker,
    )
    assert first["passed"] is False
    assert second["reused"] is True
    assert TradingControlStore(state).is_paused(strategy_id="x", symbol="Y") is True
    with pytest.raises(OperatorRequestConflictError):
        audit.execute(
            request_id="reconcile-1",
            actor="oncall-b",
            reason="different",
            state_database=state,
            broker_database=broker,
        )


def test_readiness_fails_live_pause_and_missing_operational_state() -> None:
    snapshot = {
        "mode": "FORWARD_PAPER",
        "live_boundary": {"unexpected_true": ["system"]},
        "artifact": {"status": "ok"},
        "registries": {"status": "ok"},
        "runtime": {
            "database": {"status": "not_initialized"},
            "account": None,
            "controls": [{"scope": "GLOBAL", "paused": 1}],
            "latest_reconciliation": None,
        },
        "broker": {"database": {"status": "not_initialized"}},
        "alerts": {"database": {"status": "not_initialized"}, "critical_count": 0},
        "sealed_evidence": {"governance": {"status": "ok"}},
        "data_collection": {"status": "present"},
    }
    readiness = readiness_from_snapshot(snapshot)
    assert readiness["status"] == "NOT_READY"
    assert readiness["ready_for_live"] is False
    assert "live_disabled_everywhere" in readiness["failed_gates"]
    assert "global_not_paused" in readiness["failed_gates"]
    assert "trusted_source_batch_bound" in readiness["failed_gates"]


def test_reconcile_result_is_json_serializable(tmp_path: Path) -> None:
    state, broker = _databases(tmp_path)
    json.dumps(reconcile_sqlite_state(state, broker))
