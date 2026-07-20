#!/usr/bin/env python3
"""Gracefully stoppable Phase 3 monitor-only deployment process."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "scripts/phase3_control.py"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise RuntimeError("supervisor state path cannot traverse a symlink")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _invoke(
    state_dir: Path,
    command: str,
    *extra_arguments: str,
) -> tuple[int, dict[str, Any]]:
    completed = subprocess.run(
        [
            sys.executable,
            str(CONTROL),
            command,
            "--state-dir",
            str(state_dir),
            *extra_arguments,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={
            "PATH": os.environ.get("PATH", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PQS_DEPLOYMENT_VERSION": os.environ.get(
                "PQS_DEPLOYMENT_VERSION", "development-unversioned"
            ),
        },
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {
            "status": "FAIL",
            "error": "control command returned non-JSON output",
            "stderr": completed.stderr[-1000:],
        }
    if not isinstance(payload, dict):
        payload = {"status": "FAIL", "error": "control output was not an object"}
    return completed.returncode, payload


def _scheduler_lag(heartbeat: Path, expected_interval_seconds: int) -> float:
    if not heartbeat.exists():
        return 0.0
    if heartbeat.is_symlink() or not heartbeat.is_file():
        return float(expected_interval_seconds + 3600)
    try:
        payload = json.loads(heartbeat.read_text(encoding="utf-8"))
        previous = datetime.fromisoformat(str(payload["checked_at_utc"]))
        if previous.tzinfo is None or previous.utcoffset() is None:
            raise ValueError("heartbeat time is naive")
        elapsed = (datetime.now(UTC) - previous.astimezone(UTC)).total_seconds()
        return max(0.0, elapsed - expected_interval_seconds)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
        return float(expected_interval_seconds + 3600)


def run_cycle(
    state_dir: Path,
    heartbeat: Path,
    *,
    expected_interval_seconds: int,
) -> dict[str, Any]:
    scheduler_lag = _scheduler_lag(heartbeat, expected_interval_seconds)
    signals_path = state_dir / "supervisor_signals.json"
    _atomic_json(signals_path, {"scheduler_lag_seconds": scheduler_lag})
    alert_code, alert_result = _invoke(
        state_dir,
        "evaluate-alerts",
        "--signals",
        str(signals_path),
    )
    status_code, status_result = _invoke(state_dir, "status")
    readiness = status_result.get("readiness", {})
    payload = {
        "schema_version": 1,
        "service": "phase3-monitor-only-supervisor",
        "monitor_only": True,
        "market_events_processed": False,
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "process_id": os.getpid(),
        "alert_evaluation_exit_code": alert_code,
        "status_exit_code": status_code,
        "readiness_status": readiness.get("status", "UNKNOWN"),
        "ready_for_live": False,
        "active_alert_count": alert_result.get("status", {}).get("active_count"),
        "scheduler_lag_seconds": scheduler_lag,
        "healthy": alert_code == 0 and status_code == 0,
    }
    _atomic_json(heartbeat, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-dir",
        default=os.environ.get(
            "PQS_PHASE3_STATE_DIR", "data/paper_trading/phase3_forward/dual_index_growth_v1"
        ),
    )
    parser.add_argument("--heartbeat", default=None)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.interval_seconds <= 3600:
        raise SystemExit("interval-seconds must be between 1 and 3600")
    state_dir = Path(args.state_dir)
    if not state_dir.is_absolute():
        state_dir = ROOT / state_dir
    if state_dir.exists() and state_dir.is_symlink():
        raise SystemExit("state-dir cannot be a symlink")
    heartbeat = Path(args.heartbeat) if args.heartbeat else state_dir / "supervisor_heartbeat.json"
    if not heartbeat.is_absolute():
        heartbeat = ROOT / heartbeat

    stopped = threading.Event()

    def request_stop(signum: int, frame: Any) -> None:
        del signum, frame
        stopped.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    exit_code = 0
    while not stopped.is_set():
        try:
            result = run_cycle(
                state_dir,
                heartbeat,
                expected_interval_seconds=args.interval_seconds,
            )
            if not result["healthy"]:
                exit_code = 1
        except Exception as exc:  # noqa: BLE001
            exit_code = 1
            _atomic_json(
                heartbeat,
                {
                    "schema_version": 1,
                    "service": "phase3-monitor-only-supervisor",
                    "monitor_only": True,
                    "market_events_processed": False,
                    "checked_at_utc": datetime.now(UTC).isoformat(),
                    "process_id": os.getpid(),
                    "ready_for_live": False,
                    "healthy": False,
                    "error": str(exc)[:1000],
                },
            )
        if args.once:
            break
        stopped.wait(args.interval_seconds)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
