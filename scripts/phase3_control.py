#!/usr/bin/env python3
"""Phase 3 read-only status/readiness and explicitly confirmed operator actions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.operations.alerts import AlertEngine, AlertPolicy, DurableAlertStore  # noqa: E402
from core.operations.control_plane import (  # noqa: E402
    ControlPlanePaths,
    OperatorControlStore,
    Phase3StatusReader,
    ReconcileAuditStore,
    resume_blockers,
)
from core.trading.controls import ControlScope  # noqa: E402


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _yaml(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"configuration must be a regular non-symlink file: {path}")
    payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    if not isinstance(payload, dict):
        raise ValueError(f"configuration must be a mapping: {path}")
    return payload


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _deployment_version() -> str:
    configured = os.environ.get("PQS_DEPLOYMENT_VERSION")
    if configured:
        return configured[:128]
    head = ROOT / ".git/HEAD"
    try:
        value = head.read_text(encoding="utf-8").strip()
        if value.startswith("ref: "):
            reference = ROOT / ".git" / value[5:]
            return reference.read_text(encoding="utf-8").strip()[:64]
        return value[:64]
    except OSError:
        return "development-unversioned"


def _components(state_dir_override: str | None):
    forward = _yaml(ROOT / "config/forward_paper.yaml")
    sealed = _yaml(ROOT / "config/sealed_evaluator.yaml")
    collection = _yaml(ROOT / "config/data_collection.yaml")
    alerts = _yaml(ROOT / "config/alerts.yaml")
    system = _yaml(ROOT / "config/system.yaml")
    portfolio = _yaml(ROOT / "config/portfolio.paper.yaml")
    if (
        forward.get("mode") != "PAPER"
        or sealed.get("mode") != "PAPER"
        or collection.get("mode") != "COLLECT_ONLY"
        or alerts.get("mode") != "PAPER"
    ):
        raise ValueError("Phase 3 mode configuration is inconsistent")
    policy = AlertPolicy.from_mapping(alerts["policy"])
    state_root = _path(state_dir_override or str(forward["state"]["directory"]))
    state_database = state_root / str(forward["state"]["database"])
    broker_database = state_root / str(forward["state"]["broker_database"])
    configured_alert_database = _path(str(alerts["store"]["database"]))
    alerts_database = (
        state_root / configured_alert_database.name
        if state_dir_override
        else configured_alert_database
    )
    paths = ControlPlanePaths(
        repo_root=ROOT,
        state_database=state_database,
        broker_database=broker_database,
        alerts_database=alerts_database,
        collection_root=_path(str(collection["store"]["directory"])),
        sealed_batches_root=_path(str(sealed["store"]["directory"])),
        sealed_governance_database=_path(str(sealed["governance"]["database"])),
        strategy_artifact=_path(str(forward["strategy"]["artifact"])),
        strategy_registry=ROOT / "research/registry/strategy_registry.json",
        hypothesis_registry=_path(str(sealed["governance"]["hypothesis_registry"])),
    )
    live_flags = {
        "system": bool(system["runtime"]["live_enabled"]),
        "forward": bool(forward["live_enabled"]),
        "forward_broker_write": bool(forward["broker_write_enabled"]),
        "forward_external_broker_write": bool(forward["broker"]["external_write_enabled"]),
        "sealed": bool(sealed["live_enabled"]),
        "collection": bool(collection["live_enabled"]),
        "alerts": bool(alerts["live_enabled"]),
    }
    risk_budget = {
        "aggregate_limits": portfolio["aggregate_limits"],
        "tracking_controls": forward["tracking"]["controls"],
    }
    reader = Phase3StatusReader(
        paths,
        strategy_id=str(forward["strategy"]["strategy_id"]),
        strategy_version="v1",
        deployment_version=_deployment_version(),
        live_flags=live_flags,
        risk_budget=risk_budget,
        alert_policy_sha256=policy.policy_sha256,
    )
    return reader, paths, policy


def _confirm(args: argparse.Namespace) -> None:
    if not args.request_id or not args.actor or not args.reason:
        raise ValueError("write action requires --request-id, --actor, and --reason")
    expected = f"YES:{args.request_id}"
    if args.confirm != expected:
        raise ValueError(f"write action requires --confirm {expected}")


def _derived_signals(snapshot: dict[str, Any]) -> dict[str, Any]:
    runtime = snapshot["runtime"]
    account = runtime.get("account")
    pnl = runtime.get("pnl_drawdown") or {}
    equity = None if account is None else account.get("equity")
    daily_pnl = pnl.get("daily_pnl", 0.0)
    orders = runtime["positions_orders"]["orders_by_state"]
    reconciliation = runtime.get("latest_reconciliation")
    return {
        "scheduler_lag_seconds": 0.0,
        "data_age_seconds": 0.0,
        "data_missing_count": 0,
        "data_out_of_order_count": 0,
        "artifact_valid": snapshot["artifact"]["status"] == "ok",
        "broker_snapshot_age_seconds": 0.0,
        "unknown_order_count": int(orders.get("UNKNOWN", 0)),
        "duplicate_order_count": 0,
        "reconciliation_passed": (None if reconciliation is None else reconciliation.get("passed")),
        "nav_valid": (
            account is None
            or (isinstance(equity, (int, float)) and not isinstance(equity, bool) and equity > 0)
        ),
        "risk_breach_count": 0,
        "daily_loss_fraction": (
            0.0
            if not isinstance(equity, (int, float)) or equity <= 0
            else max(0.0, -float(daily_pnl) / float(equity))
        ),
        "drawdown_fraction": float(pnl.get("drawdown_fraction", 0.0)),
        "database_healthy": (runtime["database"]["status"] in {"ok", "not_initialized"}),
        "registry_valid": snapshot["registries"]["status"] == "ok",
        "live_enabled": bool(snapshot["live_boundary"]["unexpected_true"]),
    }


def _alert_payload(record: Any) -> dict[str, Any]:
    result = asdict(record)
    result["severity"] = record.severity.value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "status",
            "readiness",
            "pause",
            "resume",
            "reconcile",
            "evaluate-alerts",
            "alerts",
            "ack-alert",
            "resolve-alert",
        ),
    )
    parser.add_argument("--state-dir")
    parser.add_argument("--scope", choices=tuple(scope.value for scope in ControlScope))
    parser.add_argument("--key", default="")
    parser.add_argument("--request-id")
    parser.add_argument("--actor")
    parser.add_argument("--reason")
    parser.add_argument("--confirm")
    parser.add_argument("--alert-id")
    parser.add_argument("--signals")
    args = parser.parse_args()
    try:
        reader, paths, policy = _components(args.state_dir)
        if args.command in {"status", "readiness"}:
            snapshot = reader.read()
            result = snapshot if args.command == "status" else snapshot["readiness"]
            exit_code = 0 if args.command == "status" or result["status"] == "READY" else 1
        elif args.command in {"pause", "resume"}:
            _confirm(args)
            if args.scope is None:
                raise ValueError("pause/resume requires --scope")
            scope = ControlScope(args.scope)
            if scope is not ControlScope.GLOBAL and not args.key.strip():
                raise ValueError("strategy/symbol pause requires --key")
            if args.command == "resume":
                blockers = resume_blockers(reader.read())
                if blockers:
                    raise ValueError(f"resume is blocked by readiness gates: {blockers}")
            control = OperatorControlStore(paths.state_database).set_paused(
                scope,
                args.key,
                paused=args.command == "pause",
                reason=args.reason,
                updated_by=args.actor,
                request_id=args.request_id,
            )
            result = asdict(control)
            result["scope"] = control.scope.value
            exit_code = 0
        elif args.command == "reconcile":
            _confirm(args)
            result = ReconcileAuditStore(paths.state_database).execute(
                request_id=args.request_id,
                actor=args.actor,
                reason=args.reason,
                state_database=paths.state_database,
                broker_database=paths.broker_database,
            )
            exit_code = 0 if result["passed"] else 1
        else:
            alert_store = DurableAlertStore(paths.alerts_database, policy)
            if args.command == "alerts":
                result = alert_store.status()
            elif args.command == "evaluate-alerts":
                snapshot = reader.read()
                signals = _derived_signals(snapshot)
                if args.signals:
                    path = Path(args.signals)
                    if path.is_symlink() or not path.is_file():
                        raise ValueError("signals must be a regular non-symlink JSON file")
                    overrides = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(overrides, dict):
                        raise ValueError("signals override must be a JSON object")
                    unknown = set(overrides) - set(signals)
                    if unknown:
                        raise ValueError(f"unknown operational signals: {sorted(unknown)}")
                    signals.update(overrides)
                emitted = AlertEngine(alert_store).evaluate(signals, now=datetime.now(UTC))
                result = {
                    "emitted": [_alert_payload(record) for record in emitted],
                    "status": alert_store.status(),
                }
            else:
                _confirm(args)
                if not args.alert_id:
                    raise ValueError("alert action requires --alert-id")
                method = (
                    alert_store.acknowledge if args.command == "ack-alert" else alert_store.resolve
                )
                record = method(
                    args.alert_id,
                    actor=args.actor,
                    reason=args.reason,
                    request_id=args.request_id,
                )
                result = _alert_payload(record)
            exit_code = 0
        print(json.dumps(result, default=str, indent=2, sort_keys=True))
        return exit_code
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
