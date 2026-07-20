"""Durable local alerts with frozen policy, deduplication, and audit actions."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from core.runtime.strategy_artifact import canonical_json, sha256_bytes

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_REQUIRED_RULES = frozenset(
    {
        "missed_schedule",
        "data_stale",
        "data_missing",
        "data_out_of_order",
        "artifact_drift",
        "broker_snapshot_stale",
        "order_unknown",
        "order_duplicate",
        "reconciliation_failure",
        "nav_invalid",
        "risk_breach",
        "daily_loss",
        "drawdown",
        "database_failure",
        "registry_anomaly",
        "live_true",
    }
)


class AlertError(RuntimeError):
    """Alert policy, persistence, or action error."""


class AlertRequestConflictError(AlertError):
    """An operator request ID was reused with different content."""


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class AlertRule:
    rule_id: str
    severity: AlertSeverity


@dataclass(frozen=True, slots=True)
class AlertPolicy:
    policy_id: str
    rules: Mapping[str, AlertRule]
    maximum_summary_length: int
    maximum_details_bytes: int
    maximum_schedule_lag_seconds: int
    maximum_data_age_seconds: int
    maximum_broker_snapshot_age_seconds: int
    maximum_daily_loss_fraction: float
    maximum_drawdown_fraction: float
    policy_sha256: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> AlertPolicy:
        expected = {
            "policy_id",
            "maximum_summary_length",
            "maximum_details_bytes",
            "maximum_schedule_lag_seconds",
            "maximum_data_age_seconds",
            "maximum_broker_snapshot_age_seconds",
            "maximum_daily_loss_fraction",
            "maximum_drawdown_fraction",
            "rules",
        }
        if set(payload) != expected:
            raise ValueError("alert policy fields are not exact")
        policy_id = _safe_id(str(payload["policy_id"]), "policy id")
        rule_payload = payload["rules"]
        if not isinstance(rule_payload, dict) or set(rule_payload) != _REQUIRED_RULES:
            raise ValueError("alert policy must define the exact required rule set")
        rules: dict[str, AlertRule] = {}
        for rule_id, settings in rule_payload.items():
            _safe_id(str(rule_id), "rule id")
            if not isinstance(settings, dict) or set(settings) != {"severity"}:
                raise ValueError(f"alert rule {rule_id} fields are not exact")
            rules[str(rule_id)] = AlertRule(
                rule_id=str(rule_id), severity=AlertSeverity(str(settings["severity"]))
            )
        integer_fields = (
            "maximum_summary_length",
            "maximum_details_bytes",
            "maximum_schedule_lag_seconds",
            "maximum_data_age_seconds",
            "maximum_broker_snapshot_age_seconds",
        )
        integers: dict[str, int] = {}
        for field in integer_fields:
            value = payload[field]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field} must be a positive integer")
            integers[field] = value
        fractions: dict[str, float] = {}
        for field in ("maximum_daily_loss_fraction", "maximum_drawdown_fraction"):
            value = float(payload[field])
            if not math.isfinite(value) or not 0 < value < 1:
                raise ValueError(f"{field} must be finite and between zero and one")
            fractions[field] = value
        policy_document = {key: payload[key] for key in sorted(payload)}
        return cls(
            policy_id=policy_id,
            rules=rules,
            maximum_summary_length=integers["maximum_summary_length"],
            maximum_details_bytes=integers["maximum_details_bytes"],
            maximum_schedule_lag_seconds=integers["maximum_schedule_lag_seconds"],
            maximum_data_age_seconds=integers["maximum_data_age_seconds"],
            maximum_broker_snapshot_age_seconds=integers["maximum_broker_snapshot_age_seconds"],
            maximum_daily_loss_fraction=fractions["maximum_daily_loss_fraction"],
            maximum_drawdown_fraction=fractions["maximum_drawdown_fraction"],
            policy_sha256=sha256_bytes(canonical_json(policy_document)),
        )


@dataclass(frozen=True, slots=True)
class AlertRecord:
    alert_id: str
    rule_id: str
    dedup_key: str
    generation: int
    severity: AlertSeverity
    status: str
    summary: str
    details: dict[str, Any]
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    resolved_by: str | None
    resolved_at: datetime | None
    reused: bool = False


@runtime_checkable
class AlertNotificationAdapter(Protocol):
    """Optional best-effort external fan-out; local persistence happens first."""

    @property
    def adapter_name(self) -> str: ...

    def send(self, alert: AlertRecord) -> None: ...


def _safe_id(value: str, label: str) -> str:
    normalized = str(value).strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"unsafe {label}: {value!r}")
    return normalized


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("alert timestamp must be timezone-aware")
    return value.astimezone(UTC)


class DurableAlertStore:
    """SQLite local sink. Active alerts deduplicate until explicit resolution."""

    def __init__(self, database: str | Path, policy: AlertPolicy) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.policy = policy
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS alert_policy (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    policy_id TEXT NOT NULL,
                    policy_sha256 TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    frozen_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    dedup_key TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    first_seen_at_utc TEXT NOT NULL,
                    last_seen_at_utc TEXT NOT NULL,
                    occurrences INTEGER NOT NULL,
                    acknowledged_by TEXT,
                    acknowledged_at_utc TEXT,
                    resolved_by TEXT,
                    resolved_at_utc TEXT,
                    UNIQUE(rule_id, dedup_key, generation)
                );
                CREATE TABLE IF NOT EXISTS alert_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    request_id TEXT,
                    occurred_at_utc TEXT NOT NULL,
                    FOREIGN KEY(alert_id) REFERENCES alerts(alert_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_event_request
                    ON alert_events(request_id) WHERE request_id IS NOT NULL;
                """
            )
            policy_document = {
                "policy_id": policy.policy_id,
                "policy_sha256": policy.policy_sha256,
            }
            row = conn.execute("SELECT * FROM alert_policy WHERE id = 1").fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO alert_policy (
                        id, policy_id, policy_sha256, policy_json, frozen_at_utc
                    ) VALUES (1, ?, ?, ?, ?)
                    """,
                    (
                        policy.policy_id,
                        policy.policy_sha256,
                        canonical_json(policy_document).decode("utf-8"),
                        datetime.now(UTC).isoformat(),
                    ),
                )
            elif (
                row["policy_id"] != policy.policy_id or row["policy_sha256"] != policy.policy_sha256
            ):
                raise AlertError("alert policy drifted after its first durable use")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def emit(
        self,
        rule_id: str,
        dedup_key: str,
        summary: str,
        *,
        details: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> AlertRecord:
        rule = self.policy.rules.get(rule_id)
        if rule is None:
            raise ValueError(f"unknown alert rule: {rule_id}")
        key = _safe_id(dedup_key, "alert dedup key")
        clean_summary = summary.strip()
        if not clean_summary or len(clean_summary) > self.policy.maximum_summary_length:
            raise ValueError("alert summary is empty or too long")
        detail_payload = dict(details or {})
        encoded_details = canonical_json(detail_payload)
        if len(encoded_details) > self.policy.maximum_details_bytes:
            raise ValueError("alert details exceed the configured size limit")
        timestamp = _utc(now or datetime.now(UTC))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                """
                SELECT * FROM alerts
                WHERE rule_id = ? AND dedup_key = ? AND status != 'RESOLVED'
                ORDER BY generation DESC LIMIT 1
                """,
                (rule_id, key),
            ).fetchone()
            if active is not None:
                conn.execute(
                    """
                    UPDATE alerts SET last_seen_at_utc = ?, occurrences = occurrences + 1,
                        severity = ?, summary = ?, details_json = ?
                    WHERE alert_id = ?
                    """,
                    (
                        timestamp.isoformat(),
                        rule.severity.value,
                        clean_summary,
                        encoded_details.decode("utf-8"),
                        active["alert_id"],
                    ),
                )
                self._event(
                    conn,
                    str(active["alert_id"]),
                    "DEDUPLICATED",
                    "system:alert-engine",
                    "condition observed again",
                    None,
                    timestamp,
                )
                updated = conn.execute(
                    "SELECT * FROM alerts WHERE alert_id = ?", (active["alert_id"],)
                ).fetchone()
                assert updated is not None
                return self._record(updated, reused=True)
            generation_row = conn.execute(
                """
                SELECT COALESCE(MAX(generation), 0) AS generation
                FROM alerts WHERE rule_id = ? AND dedup_key = ?
                """,
                (rule_id, key),
            ).fetchone()
            generation = int(generation_row["generation"]) + 1
            alert_id = "al_" + sha256_bytes(
                canonical_json({"rule_id": rule_id, "dedup_key": key, "generation": generation})
            )
            conn.execute(
                """
                INSERT INTO alerts (
                    alert_id, rule_id, dedup_key, generation, severity, status,
                    summary, details_json, first_seen_at_utc, last_seen_at_utc,
                    occurrences
                ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, 1)
                """,
                (
                    alert_id,
                    rule_id,
                    key,
                    generation,
                    rule.severity.value,
                    clean_summary,
                    encoded_details.decode("utf-8"),
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                ),
            )
            self._event(
                conn,
                alert_id,
                "CREATED",
                "system:alert-engine",
                "rule condition observed",
                None,
                timestamp,
            )
            row = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
            assert row is not None
            return self._record(row)

    @staticmethod
    def _event(
        conn: sqlite3.Connection,
        alert_id: str,
        action: str,
        actor: str,
        reason: str,
        request_id: str | None,
        now: datetime,
    ) -> None:
        conn.execute(
            """
            INSERT INTO alert_events (
                alert_id, action, actor, reason, request_id, occurred_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (alert_id, action, actor, reason, request_id, now.isoformat()),
        )

    def _operator_action(
        self,
        alert_id: str,
        action: str,
        *,
        actor: str,
        reason: str,
        request_id: str,
        now: datetime | None,
    ) -> AlertRecord:
        actor_value = actor.strip()
        reason_value = reason.strip()
        request_value = _safe_id(request_id, "request id")
        if not actor_value or not reason_value:
            raise ValueError("actor and reason are required")
        timestamp = _utc(now or datetime.now(UTC))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM alert_events WHERE request_id = ?", (request_value,)
            ).fetchone()
            if existing is not None:
                expected = (alert_id, action, actor_value, reason_value)
                actual = (
                    existing["alert_id"],
                    existing["action"],
                    existing["actor"],
                    existing["reason"],
                )
                if actual != expected:
                    raise AlertRequestConflictError(
                        "request_id was reused with different alert action content"
                    )
                row = conn.execute(
                    "SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)
                ).fetchone()
                if row is None:
                    raise AlertError("audited alert no longer exists")
                return self._record(row, reused=True)
            row = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
            if row is None:
                raise AlertError(f"unknown alert: {alert_id}")
            if action == "ACKNOWLEDGED":
                if row["status"] == "RESOLVED":
                    raise AlertError("resolved alert cannot be acknowledged")
                conn.execute(
                    """
                    UPDATE alerts SET status = 'ACKNOWLEDGED', acknowledged_by = ?,
                        acknowledged_at_utc = ? WHERE alert_id = ?
                    """,
                    (actor_value, timestamp.isoformat(), alert_id),
                )
            elif action == "RESOLVED":
                if row["status"] == "RESOLVED":
                    raise AlertError("resolved alert requires reuse of its original request_id")
                conn.execute(
                    """
                    UPDATE alerts SET status = 'RESOLVED', resolved_by = ?,
                        resolved_at_utc = ? WHERE alert_id = ?
                    """,
                    (actor_value, timestamp.isoformat(), alert_id),
                )
            else:
                raise ValueError(f"unsupported alert action: {action}")
            self._event(
                conn,
                alert_id,
                action,
                actor_value,
                reason_value,
                request_value,
                timestamp,
            )
            updated = conn.execute(
                "SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)
            ).fetchone()
            assert updated is not None
            return self._record(updated)

    def acknowledge(
        self,
        alert_id: str,
        *,
        actor: str,
        reason: str,
        request_id: str,
        now: datetime | None = None,
    ) -> AlertRecord:
        return self._operator_action(
            alert_id,
            "ACKNOWLEDGED",
            actor=actor,
            reason=reason,
            request_id=request_id,
            now=now,
        )

    def resolve(
        self,
        alert_id: str,
        *,
        actor: str,
        reason: str,
        request_id: str,
        now: datetime | None = None,
    ) -> AlertRecord:
        return self._operator_action(
            alert_id,
            "RESOLVED",
            actor=actor,
            reason=reason,
            request_id=request_id,
            now=now,
        )

    @staticmethod
    def _record(row: sqlite3.Row, *, reused: bool = False) -> AlertRecord:
        return AlertRecord(
            alert_id=str(row["alert_id"]),
            rule_id=str(row["rule_id"]),
            dedup_key=str(row["dedup_key"]),
            generation=int(row["generation"]),
            severity=AlertSeverity(str(row["severity"])),
            status=str(row["status"]),
            summary=str(row["summary"]),
            details=json.loads(row["details_json"]),
            first_seen_at=datetime.fromisoformat(row["first_seen_at_utc"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at_utc"]),
            occurrences=int(row["occurrences"]),
            acknowledged_by=row["acknowledged_by"],
            acknowledged_at=(
                None
                if row["acknowledged_at_utc"] is None
                else datetime.fromisoformat(row["acknowledged_at_utc"])
            ),
            resolved_by=row["resolved_by"],
            resolved_at=(
                None
                if row["resolved_at_utc"] is None
                else datetime.fromisoformat(row["resolved_at_utc"])
            ),
            reused=reused,
        )

    def list_alerts(self, *, include_resolved: bool = False) -> list[AlertRecord]:
        query = "SELECT * FROM alerts"
        if not include_resolved:
            query += " WHERE status != 'RESOLVED'"
        query += " ORDER BY first_seen_at_utc, alert_id"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [self._record(row) for row in rows]

    def status(self) -> dict[str, Any]:
        active = self.list_alerts()
        return {
            "sink": "durable_local_sqlite",
            "policy_id": self.policy.policy_id,
            "policy_sha256": self.policy.policy_sha256,
            "active_count": len(active),
            "critical_count": sum(item.severity == AlertSeverity.CRITICAL for item in active),
            "active": [
                {
                    "alert_id": item.alert_id,
                    "rule_id": item.rule_id,
                    "severity": item.severity.value,
                    "status": item.status,
                    "summary": item.summary,
                    "occurrences": item.occurrences,
                    "last_seen_at_utc": item.last_seen_at.isoformat(),
                }
                for item in active
            ],
        }


class AlertEngine:
    """Evaluate a fixed operational signal mapping into durable incidents."""

    def __init__(self, store: DurableAlertStore) -> None:
        self.store = store

    def evaluate(self, signals: Mapping[str, Any], *, now: datetime) -> list[AlertRecord]:
        timestamp = _utc(now)
        observations: list[tuple[str, bool, str, dict[str, Any]]] = [
            (
                "missed_schedule",
                float(signals.get("scheduler_lag_seconds", 0.0))
                > self.store.policy.maximum_schedule_lag_seconds,
                "forward scheduler exceeded its maximum lag",
                {"lag_seconds": signals.get("scheduler_lag_seconds")},
            ),
            (
                "data_stale",
                float(signals.get("data_age_seconds", 0.0))
                > self.store.policy.maximum_data_age_seconds,
                "market data exceeded its maximum age",
                {"age_seconds": signals.get("data_age_seconds")},
            ),
            (
                "data_missing",
                int(signals.get("data_missing_count", 0)) > 0,
                "market data contains missing observations",
                {"count": signals.get("data_missing_count")},
            ),
            (
                "data_out_of_order",
                int(signals.get("data_out_of_order_count", 0)) > 0,
                "market data contains out-of-order observations",
                {"count": signals.get("data_out_of_order_count")},
            ),
            (
                "artifact_drift",
                signals.get("artifact_valid") is False,
                "strategy artifact verification failed",
                {},
            ),
            (
                "broker_snapshot_stale",
                float(signals.get("broker_snapshot_age_seconds", 0.0))
                > self.store.policy.maximum_broker_snapshot_age_seconds,
                "broker snapshot exceeded its maximum age",
                {"age_seconds": signals.get("broker_snapshot_age_seconds")},
            ),
            (
                "order_unknown",
                int(signals.get("unknown_order_count", 0)) > 0,
                "one or more orders have UNKNOWN outcome",
                {"count": signals.get("unknown_order_count")},
            ),
            (
                "order_duplicate",
                int(signals.get("duplicate_order_count", 0)) > 0,
                "duplicate order identity was observed",
                {"count": signals.get("duplicate_order_count")},
            ),
            (
                "reconciliation_failure",
                signals.get("reconciliation_passed") is False,
                "broker reconciliation failed",
                {},
            ),
            (
                "nav_invalid",
                signals.get("nav_valid") is False,
                "NAV/account values are invalid",
                {},
            ),
            (
                "risk_breach",
                int(signals.get("risk_breach_count", 0)) > 0,
                "one or more risk limits were breached",
                {"count": signals.get("risk_breach_count")},
            ),
            (
                "daily_loss",
                float(signals.get("daily_loss_fraction", 0.0))
                > self.store.policy.maximum_daily_loss_fraction,
                "daily loss exceeded its control limit",
                {"loss_fraction": signals.get("daily_loss_fraction")},
            ),
            (
                "drawdown",
                float(signals.get("drawdown_fraction", 0.0))
                > self.store.policy.maximum_drawdown_fraction,
                "drawdown exceeded its control limit",
                {"drawdown_fraction": signals.get("drawdown_fraction")},
            ),
            (
                "database_failure",
                signals.get("database_healthy") is False,
                "runtime database health check failed",
                {},
            ),
            (
                "registry_anomaly",
                signals.get("registry_valid") is False,
                "strategy or hypothesis registry validation failed",
                {},
            ),
            (
                "live_true",
                signals.get("live_enabled") is True,
                "LIVE was enabled inside a PAPER-only deployment",
                {},
            ),
        ]
        emitted: list[AlertRecord] = []
        for rule_id, triggered, summary, details in observations:
            if triggered:
                emitted.append(
                    self.store.emit(
                        rule_id,
                        "global",
                        summary,
                        details=details,
                        now=timestamp,
                    )
                )
        return emitted
