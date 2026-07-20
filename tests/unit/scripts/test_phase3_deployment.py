from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SUPERVISOR = PROJECT_ROOT / "scripts/phase3_supervisor.py"
LIVENESS = PROJECT_ROOT / "scripts/phase3_liveness.py"
ENTRYPOINT = PROJECT_ROOT / "scripts/phase3_entrypoint.py"
BACKUP = PROJECT_ROOT / "scripts/phase3_backup.py"
VALIDATOR = PROJECT_ROOT / "scripts/validate_phase3_deployment.py"


def _run(script: Path, *args: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_static_deployment_contract_passes_without_claiming_tools_or_cloud() -> None:
    completed = _run(VALIDATOR)
    result = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert result["status"] == "PASS"
    assert result["cloud_resources_created"] is False
    assert result["kubernetes"]["image_digest_is_placeholder"] is True
    assert result["terraform_contract"]["creates_no_cloud_resources"] is True


def test_monitor_supervisor_writes_healthy_heartbeat_and_liveness(tmp_path: Path) -> None:
    state = tmp_path / "state"
    heartbeat = state / "heartbeat.json"
    supervisor = _run(
        SUPERVISOR,
        "--state-dir",
        str(state),
        "--heartbeat",
        str(heartbeat),
        "--once",
    )
    assert supervisor.returncode == 0
    payload = json.loads(heartbeat.read_text(encoding="utf-8"))
    assert payload["healthy"] is True
    assert payload["monitor_only"] is True
    assert payload["market_events_processed"] is False
    assert payload["ready_for_live"] is False

    liveness = _run(
        LIVENESS,
        "--heartbeat",
        str(heartbeat),
        "--maximum-age-seconds",
        "60",
    )
    assert liveness.returncode == 0
    assert json.loads(liveness.stdout)["status"] == "ok"

    payload["checked_at_utc"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    heartbeat.write_text(json.dumps(payload), encoding="utf-8")
    restarted = _run(
        SUPERVISOR,
        "--state-dir",
        str(state),
        "--heartbeat",
        str(heartbeat),
        "--once",
    )
    assert restarted.returncode == 0
    alerts = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts/phase3_control.py"),
            "alerts",
            "--state-dir",
            str(state),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    alert_status = json.loads(alerts.stdout)
    assert any(item["rule_id"] == "missed_schedule" for item in alert_status["active"])


def test_liveness_rejects_stale_heartbeat(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(
        json.dumps(
            {
                "service": "phase3-monitor-only-supervisor",
                "checked_at_utc": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                "healthy": True,
                "ready_for_live": False,
                "monitor_only": True,
            }
        ),
        encoding="utf-8",
    )
    result = _run(
        LIVENESS,
        "--heartbeat",
        str(heartbeat),
        "--maximum-age-seconds",
        "60",
    )
    assert result.returncode == 1
    assert "outside the allowed window" in json.loads(result.stdout)["error"]


def test_supervisor_exits_on_sigterm_within_grace_period(tmp_path: Path) -> None:
    state = tmp_path / "state"
    process = subprocess.Popen(
        [
            sys.executable,
            str(SUPERVISOR),
            "--state-dir",
            str(state),
            "--interval-seconds",
            "60",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while not (state / "supervisor_heartbeat.json").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert (state / "supervisor_heartbeat.json").exists()
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=5) == 0


def test_container_entrypoint_executes_only_with_safe_volume_environment(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    data = tmp_path / "data"
    state.mkdir()
    data.mkdir()
    environment = {
        **os.environ,
        "PQS_PHASE3_STATE_DIR": str(state),
        "PQS_DATA_DIR": str(data),
    }
    safe = _run(
        ENTRYPOINT,
        sys.executable,
        "-c",
        "print('entrypoint-ok')",
        env=environment,
    )
    assert safe.returncode == 0
    assert safe.stdout.strip() == "entrypoint-ok"

    unsafe = _run(
        ENTRYPOINT,
        sys.executable,
        "-c",
        "print('must-not-run')",
        env={**environment, "PQS_LIVE_APPROVAL_TOKEN": "not-a-real-secret"},
    )
    assert unsafe.returncode != 0
    assert "forbidden LIVE/write" in unsafe.stderr
    assert "must-not-run" not in unsafe.stdout


def test_backup_verify_restore_preserves_sqlite_snapshot_without_overwrite(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    database = source / "state.db"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO events(value) VALUES ('before-backup')")
    (source / "heartbeat.json").write_text('{"status":"ok"}\n', encoding="utf-8")
    backup = tmp_path / "backup"

    created = _run(
        BACKUP,
        "backup",
        "--source",
        str(source),
        "--destination",
        str(backup),
    )
    created_result = json.loads(created.stdout)
    assert created.returncode == 0
    verification = _run(BACKUP, "verify", "--backup", str(backup))
    verified = json.loads(verification.stdout)
    assert verification.returncode == 0
    assert verified["status"] == "PASS"

    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO events(value) VALUES ('after-backup')")
    restored = tmp_path / "restored"
    wrong = _run(
        BACKUP,
        "restore",
        "--backup",
        str(backup),
        "--target",
        str(restored),
        "--confirm",
        "RESTORE:wrong",
    )
    assert wrong.returncode == 1
    assert not restored.exists()

    result = _run(
        BACKUP,
        "restore",
        "--backup",
        str(backup),
        "--target",
        str(restored),
        "--confirm",
        f"RESTORE:{created_result['manifest_sha256']}",
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["overwrote_existing_data"] is False
    with sqlite3.connect(restored / "state.db") as connection:
        values = [row[0] for row in connection.execute("SELECT value FROM events")]
    assert values == ["before-backup"]


def test_backup_rejects_symlink_source_content(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    (source / "linked").symlink_to(outside)
    result = _run(
        BACKUP,
        "backup",
        "--source",
        str(source),
        "--destination",
        str(tmp_path / "backup"),
    )
    assert result.returncode == 1
    assert "symlink" in json.loads(result.stdout)["error"]
