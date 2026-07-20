"""Read-only Phase 3 status/readiness plus audited SQLite reconciliation."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from core.runtime.strategy_artifact import canonical_json, sha256_bytes, verify_strategy_artifact
from core.trading.controls import ControlScope, TradingControlStore

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_TERMINAL_ORDER_STATES = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}
_PRE_BROKER_ORDER_STATES = {"CREATED", "VALIDATED"}


class ControlPlaneError(RuntimeError):
    """Control-plane snapshot, audit, or reconciliation failure."""


class OperatorRequestConflictError(ControlPlaneError):
    """An operator request ID was reused for different content."""


@dataclass(frozen=True, slots=True)
class OperatorControlResult:
    scope: ControlScope
    scope_key: str
    paused: bool
    reason: str
    updated_by: str
    updated_at: datetime
    version: int
    request_id: str
    reused: bool = False


class OperatorControlStore:
    """Add atomic request-id semantics without changing frozen risk code."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        TradingControlStore(self.database)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operator_control_requests (
                    request_id TEXT PRIMARY KEY,
                    request_sha256 TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    occurred_at_utc TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _key(scope: ControlScope, scope_key: str) -> str:
        if scope is ControlScope.GLOBAL:
            return "*"
        key = scope_key.strip().upper() if scope is ControlScope.SYMBOL else scope_key.strip()
        if not key:
            raise ValueError("scope_key is required")
        return key

    def set_paused(
        self,
        scope: ControlScope,
        scope_key: str,
        *,
        paused: bool,
        reason: str,
        updated_by: str,
        request_id: str,
    ) -> OperatorControlResult:
        key = self._key(scope, scope_key)
        reason_value = reason.strip()
        actor_value = updated_by.strip()
        request_value = _safe_id(request_id, "request id")
        if not reason_value or not actor_value:
            raise ValueError("reason and updated_by are required")
        request_payload = {
            "action": "PAUSE" if paused else "RESUME",
            "scope": scope.value,
            "scope_key": key,
            "reason": reason_value,
            "updated_by": actor_value,
            "request_id": request_value,
        }
        request_hash = sha256_bytes(canonical_json(request_payload))
        with sqlite3.connect(self.database, timeout=30.0) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM operator_control_requests WHERE request_id = ?",
                (request_value,),
            ).fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_hash:
                    raise OperatorRequestConflictError(
                        "request_id was reused with different control content"
                    )
                payload = json.loads(existing["result_json"])
                return OperatorControlResult(
                    scope=ControlScope(payload["scope"]),
                    scope_key=str(payload["scope_key"]),
                    paused=bool(payload["paused"]),
                    reason=str(payload["reason"]),
                    updated_by=str(payload["updated_by"]),
                    updated_at=datetime.fromisoformat(payload["updated_at"]),
                    version=int(payload["version"]),
                    request_id=request_value,
                    reused=True,
                )
            row = connection.execute(
                "SELECT version FROM trading_controls WHERE scope=? AND scope_key=?",
                (scope.value, key),
            ).fetchone()
            version = 1 if row is None else int(row["version"]) + 1
            now = datetime.now(UTC)
            connection.execute(
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
                (
                    int(paused),
                    reason_value,
                    actor_value,
                    now.isoformat(),
                    version,
                    scope.value,
                    key,
                ),
            )
            connection.execute(
                """
                INSERT INTO trading_control_events (
                    scope, scope_key, paused, reason, updated_by, occurred_at, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope.value,
                    key,
                    int(paused),
                    reason_value,
                    actor_value,
                    now.isoformat(),
                    version,
                ),
            )
            result_payload = {
                "scope": scope.value,
                "scope_key": key,
                "paused": paused,
                "reason": reason_value,
                "updated_by": actor_value,
                "updated_at": now.isoformat(),
                "version": version,
                "request_id": request_value,
            }
            connection.execute(
                """
                INSERT INTO operator_control_requests (
                    request_id, request_sha256, result_json, occurred_at_utc
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    request_value,
                    request_hash,
                    canonical_json(result_payload).decode("utf-8"),
                    now.isoformat(),
                ),
            )
        return OperatorControlResult(
            scope=scope,
            scope_key=key,
            paused=paused,
            reason=reason_value,
            updated_by=actor_value,
            updated_at=now,
            version=version,
            request_id=request_value,
        )


def _safe_id(value: str, label: str) -> str:
    normalized = str(value).strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"unsafe {label}: {value!r}")
    return normalized


def _ro_connect(path: Path) -> sqlite3.Connection:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    os.close(descriptor)
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _database_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "not_initialized", "path": str(path)}
    if path.is_symlink() or not path.is_file():
        return {"status": "error", "path": str(path), "reason": "irregular database path"}
    try:
        with _ro_connect(path) as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
        result = None if row is None else str(row[0])
        return {
            "status": "ok" if result == "ok" else "corrupt",
            "path": str(path),
            "quick_check": result,
        }
    except (OSError, sqlite3.Error) as exc:
        return {"status": "error", "path": str(path), "reason": str(exc)}


@dataclass(frozen=True, slots=True)
class ControlPlanePaths:
    repo_root: Path
    state_database: Path
    broker_database: Path
    alerts_database: Path
    collection_root: Path
    sealed_batches_root: Path
    sealed_governance_database: Path
    strategy_artifact: Path
    strategy_registry: Path
    hypothesis_registry: Path


def _collection_summary(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {
            "status": "not_initialized",
            "mode": "COLLECT_ONLY",
            "strategy_consumption_enabled": False,
        }
    counts: dict[str, dict[str, int]] = {}
    invalid_paths: list[str] = []
    for feed in ("daily", "intraday", "options"):
        counts[feed] = {}
        for status in ("trusted", "quarantined"):
            path = root / status / feed
            if path.is_symlink() or not path.is_dir():
                invalid_paths.append(str(path))
                counts[feed][status] = 0
                continue
            records = list(path.iterdir())
            if any(item.is_symlink() or not item.is_file() for item in records):
                invalid_paths.append(str(path))
            counts[feed][status] = len(records)
    return {
        "status": "error" if invalid_paths else "present",
        "mode": "COLLECT_ONLY",
        "strategy_consumption_enabled": False,
        "counts": counts,
        "invalid_paths": invalid_paths,
        "note": "read-only status counts records; the ingestion process verifies the locked hash chain",
    }


def _sealed_summary(batch_root: Path, governance_database: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "raw_rows_exposed": False,
        "batches": None,
        "governance": _database_status(governance_database),
    }
    journal = batch_root / "journal"
    if not batch_root.exists():
        result["status"] = "not_initialized"
    elif batch_root.is_symlink() or journal.is_symlink() or not journal.is_dir():
        result["status"] = "error"
    else:
        result["status"] = "present"
        result["batches"] = len(list(journal.iterdir()))
    if result["governance"]["status"] == "ok":
        try:
            with _ro_connect(governance_database) as connection:
                tables = _tables(connection)
                for table, label in (
                    ("sealed_hypotheses", "hypotheses"),
                    ("sealed_submissions", "submissions"),
                    ("sealed_attempts", "attempts"),
                ):
                    if table in tables:
                        result[label] = int(
                            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        )
        except (OSError, sqlite3.Error) as exc:
            result["status"] = "error"
            result["reason"] = str(exc)
    return result


def _load_json_regular(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ControlPlaneError(f"registry path is irregular: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


class Phase3StatusReader:
    """Open operational state read-only; do not create DBs, locks, or controls."""

    def __init__(
        self,
        paths: ControlPlanePaths,
        *,
        strategy_id: str,
        strategy_version: str,
        deployment_version: str,
        live_flags: Mapping[str, bool],
        risk_budget: Mapping[str, Any],
        alert_policy_sha256: str,
    ) -> None:
        self.paths = paths
        self.strategy_id = strategy_id
        self.strategy_version = strategy_version
        self.deployment_version = deployment_version.strip() or "unknown"
        self.live_flags = dict(live_flags)
        self.risk_budget = dict(risk_budget)
        self.alert_policy_sha256 = alert_policy_sha256

    def _artifact(self) -> dict[str, Any]:
        try:
            verified = verify_strategy_artifact(
                self.paths.strategy_artifact,
                repo_root=self.paths.repo_root,
                expected_strategy_id=self.strategy_id,
                expected_strategy_version=self.strategy_version,
                expected_promotion_status="PAPER_APPROVED",
                verify_environment=True,
            )
            return {
                "status": "ok",
                "artifact_root_sha256": verified["artifact_root_sha256"],
                "promotion_status": verified["promotion_status"],
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "reason": str(exc)}

    def _registries(self) -> dict[str, Any]:
        try:
            strategy = _load_json_regular(self.paths.strategy_registry)
            hypothesis = _load_json_regular(self.paths.hypothesis_registry)
            strategies = strategy.get("strategies", [])
            matches = [
                item
                for item in strategies
                if isinstance(item, dict) and item.get("strategy_id") == self.strategy_id
            ]
            valid = (
                len(matches) == 1
                and matches[0].get("status") == "PAPER_APPROVED"
                and matches[0].get("live_enabled") is False
                and isinstance(hypothesis, dict)
            )
            return {
                "status": "ok" if valid else "error",
                "strategy_matches": len(matches),
                "strategy_status": None if not matches else matches[0].get("status"),
                "strategy_live_enabled": (None if not matches else matches[0].get("live_enabled")),
                "hypothesis_count": len(hypothesis.get("registrations", [])),
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "reason": str(exc)}

    def _runtime(self) -> dict[str, Any]:
        database_status = _database_status(self.paths.state_database)
        result: dict[str, Any] = {
            "database": database_status,
            "account": None,
            "latest_decision": None,
            "positions_orders": {"orders_by_state": {}, "open_orders": []},
            "latest_event_cursor": None,
            "latest_reconciliation": None,
            "pnl_drawdown": None,
            "controls": [],
            "scheduler_lease": None,
            "tracking_observations": 0,
        }
        if database_status["status"] != "ok":
            return result
        try:
            with _ro_connect(self.paths.state_database) as connection:
                tables = _tables(connection)
                if "forward_account" in tables:
                    account = connection.execute(
                        "SELECT * FROM forward_account WHERE id = 1"
                    ).fetchone()
                    if account is not None:
                        result["account"] = {
                            "cash": float(account["cash"]),
                            "positions": json.loads(account["positions_json"]),
                            "equity": float(account["equity"]),
                            "last_finalized_session": account["last_finalized_session"],
                        }
                if "forward_decisions" in tables:
                    decision = connection.execute(
                        """
                        SELECT * FROM forward_decisions
                        ORDER BY created_at_utc DESC, decision_id DESC LIMIT 1
                        """
                    ).fetchone()
                    if decision is not None:
                        payload = json.loads(decision["payload_json"])
                        result["latest_decision"] = {
                            "decision_id": decision["decision_id"],
                            "signal_session": decision["signal_session"],
                            "execution_session": decision["execution_session"],
                            "state": decision["state"],
                            "regime": payload.get("regime"),
                            "regime_confidence": payload.get("regime_confidence"),
                            "approved_target": payload.get("approved_target"),
                            "kill_switch_state": payload.get("kill_switch_state"),
                        }
                if "orders" in tables:
                    order_counts = {
                        str(row["state"]): int(row["count"])
                        for row in connection.execute(
                            "SELECT state, COUNT(*) AS count FROM orders GROUP BY state"
                        ).fetchall()
                    }
                    open_orders = [
                        dict(row)
                        for row in connection.execute(
                            """
                            SELECT order_id, broker_order_id, symbol, side, quantity,
                                   filled_quantity, state, updated_at
                            FROM orders
                            WHERE state NOT IN ('FILLED','CANCELLED','REJECTED','EXPIRED')
                            ORDER BY created_at, order_id
                            """
                        ).fetchall()
                    ]
                    result["positions_orders"] = {
                        "orders_by_state": order_counts,
                        "open_orders": open_orders,
                    }
                if "forward_events" in tables:
                    event = connection.execute(
                        """
                        SELECT event_id, phase, session, fencing_token, processed_at_utc
                        FROM forward_events ORDER BY processed_at_utc DESC, event_id DESC LIMIT 1
                        """
                    ).fetchone()
                    result["latest_event_cursor"] = None if event is None else dict(event)
                if "forward_nav" in tables:
                    nav_rows = connection.execute(
                        "SELECT * FROM forward_nav ORDER BY session"
                    ).fetchall()
                    if nav_rows:
                        equities = [float(row["equity"]) for row in nav_rows]
                        latest = nav_rows[-1]
                        peak = max(equities)
                        result["pnl_drawdown"] = {
                            "daily_pnl": float(latest["daily_pnl"]),
                            "drawdown_fraction": (
                                0.0 if peak <= 0 else max(0.0, (peak - equities[-1]) / peak)
                            ),
                            "session": latest["session"],
                        }
                        result["latest_reconciliation"] = json.loads(latest["reconciliation_json"])
                if "trading_controls" in tables:
                    result["controls"] = [
                        dict(row)
                        for row in connection.execute(
                            "SELECT * FROM trading_controls ORDER BY scope, scope_key"
                        ).fetchall()
                    ]
                if "scheduler_leases" in tables:
                    lease = connection.execute(
                        "SELECT * FROM scheduler_leases ORDER BY lease_name LIMIT 1"
                    ).fetchone()
                    result["scheduler_lease"] = None if lease is None else dict(lease)
                if "forward_tracking_observations" in tables:
                    result["tracking_observations"] = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM forward_tracking_observations"
                        ).fetchone()[0]
                    )
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            result["database"] = {
                **database_status,
                "status": "error",
                "reason": str(exc),
            }
        return result

    def _alerts(self) -> dict[str, Any]:
        status = _database_status(self.paths.alerts_database)
        result: dict[str, Any] = {
            "database": status,
            "policy_sha256": self.alert_policy_sha256,
            "active_count": 0,
            "critical_count": 0,
            "active": [],
        }
        if status["status"] != "ok":
            return result
        try:
            with _ro_connect(self.paths.alerts_database) as connection:
                alert_tables = _tables(connection)
                if "alerts" not in alert_tables or "alert_policy" not in alert_tables:
                    raise ControlPlaneError("alerts table is absent")
                frozen_policy = connection.execute(
                    "SELECT policy_sha256 FROM alert_policy WHERE id = 1"
                ).fetchone()
                if (
                    frozen_policy is None
                    or frozen_policy["policy_sha256"] != self.alert_policy_sha256
                ):
                    raise ControlPlaneError("durable alert policy hash is inconsistent")
                rows = connection.execute(
                    """
                    SELECT alert_id, rule_id, severity, status, summary, occurrences,
                           last_seen_at_utc FROM alerts
                    WHERE status != 'RESOLVED' ORDER BY first_seen_at_utc, alert_id
                    """
                ).fetchall()
            result["active"] = [dict(row) for row in rows]
            result["active_count"] = len(rows)
            result["critical_count"] = sum(row["severity"] == "CRITICAL" for row in rows)
        except (OSError, sqlite3.Error, ControlPlaneError) as exc:
            result["database"] = {**status, "status": "error", "reason": str(exc)}
        return result

    def read(self) -> dict[str, Any]:
        runtime = self._runtime()
        artifact = self._artifact()
        registries = self._registries()
        broker = _database_status(self.paths.broker_database)
        alerts = self._alerts()
        live_true = sorted(key for key, enabled in self.live_flags.items() if enabled)
        lease = runtime.get("scheduler_lease")
        scheduler_status = "IDLE"
        if lease is not None:
            try:
                scheduler_status = (
                    "LEASE_ACTIVE"
                    if datetime.fromisoformat(lease["expires_at_utc"]) > datetime.now(UTC)
                    else "LEASE_EXPIRED"
                )
            except (KeyError, TypeError, ValueError):
                scheduler_status = "ERROR"
        snapshot = {
            "schema_version": 1,
            "checked_at_utc": datetime.now(UTC).isoformat(),
            "mode": "FORWARD_PAPER",
            "live_enabled": bool(live_true),
            "live_boundary": {
                "configured_flags": self.live_flags,
                "unexpected_true": live_true,
                "live_toggle_available": False,
            },
            "service": {
                "status": (
                    "STATE_AVAILABLE"
                    if runtime["database"]["status"] == "ok"
                    else "NOT_INITIALIZED"
                ),
                "deployment_version": self.deployment_version,
                "runtime_database_initialized": (runtime["database"]["status"] == "ok"),
            },
            "artifact": artifact,
            "registries": registries,
            "runtime": runtime,
            "scheduler": {
                "status": scheduler_status,
                "lease": lease,
                "latest_event_cursor": runtime.get("latest_event_cursor"),
            },
            "broker": {
                "adapter": "simulated",
                "external_write_enabled": False,
                "database": broker,
            },
            "risk_budget": self.risk_budget,
            "data_collection": _collection_summary(self.paths.collection_root),
            "sealed_evidence": _sealed_summary(
                self.paths.sealed_batches_root,
                self.paths.sealed_governance_database,
            ),
            "alerts": alerts,
        }
        snapshot["readiness"] = readiness_from_snapshot(snapshot)
        return snapshot


def resume_blockers(snapshot: Mapping[str, Any]) -> list[str]:
    """Return readiness blockers that must remain after ignoring the pause itself."""

    readiness = readiness_from_snapshot(snapshot)
    return [blocker for blocker in readiness["failed_gates"] if blocker != "global_not_paused"]


def readiness_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    runtime = snapshot["runtime"]
    controls = runtime.get("controls", [])
    global_paused = any(
        item.get("scope") == "GLOBAL" and bool(item.get("paused")) for item in controls
    )
    reconciliation = runtime.get("latest_reconciliation")
    reconciliation_ok = reconciliation is None or reconciliation.get("passed") is True
    gates = {
        "paper_mode": snapshot.get("mode") == "FORWARD_PAPER",
        "live_disabled_everywhere": not snapshot["live_boundary"]["unexpected_true"],
        "artifact_verified": snapshot["artifact"]["status"] == "ok",
        "registries_valid": snapshot["registries"]["status"] == "ok",
        "runtime_database_healthy": runtime["database"]["status"] == "ok",
        "runtime_account_initialized": runtime.get("account") is not None,
        "broker_database_healthy": snapshot["broker"]["database"]["status"] == "ok",
        "durable_alert_sink_healthy": snapshot["alerts"]["database"]["status"] == "ok",
        "sealed_governance_healthy": (snapshot["sealed_evidence"]["governance"]["status"] == "ok"),
        "collection_boundary_not_corrupt": (snapshot["data_collection"]["status"] != "error"),
        "global_not_paused": not global_paused,
        "reconciliation_clean_or_not_yet_observed": reconciliation_ok,
        "no_active_critical_alert": snapshot["alerts"]["critical_count"] == 0,
    }
    failed = sorted(key for key, passed in gates.items() if not passed)
    return {
        "status": "READY" if not failed else "NOT_READY",
        "gates": gates,
        "failed_gates": failed,
        "ready_for_live": False,
    }


def reconcile_sqlite_state(
    state_database: str | Path,
    broker_database: str | Path,
) -> dict[str, Any]:
    """Compare persisted PAPER ledger and simulated broker without submitting orders."""

    state_path = Path(state_database)
    broker_path = Path(broker_database)
    if _database_status(state_path)["status"] != "ok":
        raise ControlPlaneError("forward state database is unavailable")
    if _database_status(broker_path)["status"] != "ok":
        raise ControlPlaneError("broker database is unavailable")
    with _ro_connect(state_path) as state, _ro_connect(broker_path) as broker:
        account = state.execute("SELECT * FROM forward_account WHERE id = 1").fetchone()
        actual = broker.execute("SELECT * FROM simulated_broker_state WHERE id = 1").fetchone()
        if account is None or actual is None:
            raise ControlPlaneError("forward or broker account is not initialized")
        expected_cash = float(account["cash"])
        actual_cash = float(actual["cash"])
        expected_positions = {
            str(key): float(value) for key, value in json.loads(account["positions_json"]).items()
        }
        actual_positions = {
            str(key): float(value) for key, value in json.loads(actual["positions_json"]).items()
        }
        expected_orders = {
            str(row["broker_order_id"] or row["order_id"])
            for row in state.execute(
                """
                SELECT order_id, broker_order_id, state FROM orders
                WHERE state NOT IN ('FILLED','CANCELLED','REJECTED','EXPIRED',
                                    'CREATED','VALIDATED')
                """
            ).fetchall()
        }
        actual_orders = {
            str(row["broker_order_id"])
            for row in broker.execute(
                """
                SELECT broker_order_id FROM simulated_broker_orders
                WHERE status = 'SUBMITTED'
                """
            ).fetchall()
        }
    numeric = [expected_cash, actual_cash, *expected_positions.values(), *actual_positions.values()]
    if any(not math.isfinite(value) for value in numeric):
        raise ControlPlaneError("reconciliation encountered non-finite account values")
    if any(value < 0 for value in (*expected_positions.values(), *actual_positions.values())):
        raise ControlPlaneError("reconciliation encountered a negative position")
    cash_difference = actual_cash - expected_cash
    position_differences = {
        symbol: actual_positions.get(symbol, 0.0) - expected_positions.get(symbol, 0.0)
        for symbol in sorted(set(expected_positions) | set(actual_positions))
        if abs(actual_positions.get(symbol, 0.0) - expected_positions.get(symbol, 0.0)) > 1e-6
    }
    missing = sorted(expected_orders - actual_orders)
    unexpected = sorted(actual_orders - expected_orders)
    passed = (
        abs(cash_difference) <= 0.01 and not position_differences and not missing and not unexpected
    )
    return {
        "passed": passed,
        "cash_difference": cash_difference,
        "position_differences": position_differences,
        "missing_open_orders": missing,
        "unexpected_open_orders": unexpected,
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "broker_source": "simulated-sqlite-read-only",
        "broker_writes_performed": False,
    }


class ReconcileAuditStore:
    """Idempotent operator audit around read-only reconciliation requests."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS operator_reconcile_events (
                    request_id TEXT PRIMARY KEY,
                    request_sha256 TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT
                )
                """
            )

    def execute(
        self,
        *,
        request_id: str,
        actor: str,
        reason: str,
        state_database: str | Path,
        broker_database: str | Path,
    ) -> dict[str, Any]:
        request_value = _safe_id(request_id, "request id")
        actor_value = actor.strip()
        reason_value = reason.strip()
        if not actor_value or not reason_value:
            raise ValueError("actor and reason are required")
        request_payload = {
            "action": "RECONCILE",
            "request_id": request_value,
            "actor": actor_value,
            "reason": reason_value,
        }
        request_hash = sha256_bytes(canonical_json(request_payload))
        now = datetime.now(UTC)
        with sqlite3.connect(self.database, timeout=30.0) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM operator_reconcile_events WHERE request_id = ?",
                (request_value,),
            ).fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_hash:
                    raise OperatorRequestConflictError(
                        "request_id was reused with different reconcile content"
                    )
                if existing["status"] == "COMPLETE":
                    result = json.loads(existing["result_json"])
                    return {**result, "reused": True}
                raise ControlPlaneError("reconcile request is already pending")
            connection.execute(
                """
                INSERT INTO operator_reconcile_events (
                    request_id, request_sha256, actor, reason, status, created_at_utc
                ) VALUES (?, ?, ?, ?, 'PENDING', ?)
                """,
                (request_value, request_hash, actor_value, reason_value, now.isoformat()),
            )
        try:
            result = reconcile_sqlite_state(state_database, broker_database)
            if not result["passed"]:
                OperatorControlStore(state_database).set_paused(
                    ControlScope.GLOBAL,
                    "*",
                    paused=True,
                    reason=f"operator reconciliation failed: request={request_value}",
                    updated_by=actor_value,
                    request_id=f"{request_value}:autopause",
                )
            with sqlite3.connect(self.database, timeout=30.0) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    UPDATE operator_reconcile_events SET status = 'COMPLETE',
                        result_json = ?, completed_at_utc = ? WHERE request_id = ?
                    """,
                    (
                        canonical_json(result).decode("utf-8"),
                        datetime.now(UTC).isoformat(),
                        request_value,
                    ),
                )
            return {**result, "reused": False}
        except Exception:
            with sqlite3.connect(self.database, timeout=30.0) as connection:
                connection.execute(
                    """
                    UPDATE operator_reconcile_events SET status = 'FAILED',
                        completed_at_utc = ? WHERE request_id = ?
                    """,
                    (datetime.now(UTC).isoformat(), request_value),
                )
            raise
