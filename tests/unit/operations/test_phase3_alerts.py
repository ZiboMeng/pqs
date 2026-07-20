from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from core.operations.alerts import (
    AlertEngine,
    AlertError,
    AlertPolicy,
    AlertRequestConflictError,
    DurableAlertStore,
)

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 7, 20, 18, 0, tzinfo=UTC)


def _policy() -> AlertPolicy:
    payload = yaml.safe_load((ROOT / "config/alerts.yaml").read_text(encoding="utf-8"))
    return AlertPolicy.from_mapping(payload["policy"])


def test_alert_policy_has_exact_required_rules_and_stable_hash() -> None:
    first = _policy()
    second = _policy()
    assert len(first.rules) == 16
    assert first.policy_sha256 == second.policy_sha256
    assert len(first.policy_sha256) == 64


def test_emit_deduplicates_until_resolved_then_opens_new_generation(tmp_path: Path) -> None:
    store = DurableAlertStore(tmp_path / "alerts.db", _policy())
    first = store.emit("artifact_drift", "global", "artifact failed", now=NOW)
    second = store.emit("artifact_drift", "global", "artifact still failed", now=NOW)

    assert second.alert_id == first.alert_id
    assert second.reused is True
    assert second.occurrences == 2
    resolved = store.resolve(
        first.alert_id,
        actor="oncall-a",
        reason="artifact restored",
        request_id="resolve-1",
        now=NOW,
    )
    assert resolved.status == "RESOLVED"
    reopened = store.emit("artifact_drift", "global", "artifact failed again", now=NOW)
    assert reopened.alert_id != first.alert_id
    assert reopened.generation == 2


def test_acknowledgement_is_idempotent_and_request_conflict_fails(tmp_path: Path) -> None:
    store = DurableAlertStore(tmp_path / "alerts.db", _policy())
    alert = store.emit("database_failure", "global", "database failed", now=NOW)
    first = store.acknowledge(
        alert.alert_id,
        actor="oncall-a",
        reason="investigating",
        request_id="ack-1",
        now=NOW,
    )
    second = store.acknowledge(
        alert.alert_id,
        actor="oncall-a",
        reason="investigating",
        request_id="ack-1",
        now=NOW,
    )
    assert first.status == "ACKNOWLEDGED"
    assert second.reused is True
    with pytest.raises(AlertRequestConflictError):
        store.resolve(
            alert.alert_id,
            actor="oncall-a",
            reason="investigating",
            request_id="ack-1",
            now=NOW,
        )


def test_concurrent_emit_produces_one_active_alert_with_all_occurrences(
    tmp_path: Path,
) -> None:
    store = DurableAlertStore(tmp_path / "alerts.db", _policy())

    def emit(_: int) -> None:
        store.emit("live_true", "global", "LIVE enabled", now=NOW)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(emit, range(16)))

    alerts = store.list_alerts()
    assert len(alerts) == 1
    assert alerts[0].occurrences == 16
    assert store.status()["critical_count"] == 1


def test_alert_policy_drift_after_first_use_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "alerts.db"
    policy = _policy()
    DurableAlertStore(database, policy)
    changed = yaml.safe_load((ROOT / "config/alerts.yaml").read_text(encoding="utf-8"))["policy"]
    changed["maximum_schedule_lag_seconds"] += 1

    with pytest.raises(AlertError, match="drifted"):
        DurableAlertStore(database, AlertPolicy.from_mapping(changed))


def test_engine_covers_every_required_failure_class(tmp_path: Path) -> None:
    store = DurableAlertStore(tmp_path / "alerts.db", _policy())
    signals = {
        "scheduler_lag_seconds": 901,
        "data_age_seconds": 1801,
        "data_missing_count": 1,
        "data_out_of_order_count": 1,
        "artifact_valid": False,
        "broker_snapshot_age_seconds": 121,
        "unknown_order_count": 1,
        "duplicate_order_count": 1,
        "reconciliation_passed": False,
        "nav_valid": False,
        "risk_breach_count": 1,
        "daily_loss_fraction": 0.031,
        "drawdown_fraction": 0.201,
        "database_healthy": False,
        "registry_valid": False,
        "live_enabled": True,
    }
    emitted = AlertEngine(store).evaluate(signals, now=NOW)
    assert {item.rule_id for item in emitted} == set(_policy().rules)
