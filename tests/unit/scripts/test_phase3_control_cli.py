from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_ROOT / "scripts/phase3_control.py"


def invoke(state_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--state-dir", str(state_dir)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_status_is_read_only_and_readiness_is_honestly_not_ready(tmp_path: Path) -> None:
    state_dir = tmp_path / "absent"
    status = invoke(state_dir, "status")
    report = json.loads(status.stdout)
    assert status.returncode == 0
    assert report["artifact"]["status"] == "ok"
    assert report["readiness"]["status"] == "NOT_READY"
    assert report["live_boundary"]["live_toggle_available"] is False
    assert not state_dir.exists()

    readiness = invoke(state_dir, "readiness")
    assert readiness.returncode == 1
    assert json.loads(readiness.stdout)["ready_for_live"] is False
    assert not state_dir.exists()


def test_pause_requires_exact_confirmation_and_reuses_request(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    missing_confirmation = invoke(
        state_dir,
        "pause",
        "--scope",
        "GLOBAL",
        "--request-id",
        "pause-1",
        "--actor",
        "oncall-a",
        "--reason",
        "incident",
    )
    assert missing_confirmation.returncode == 1
    assert not state_dir.exists()

    arguments = (
        "pause",
        "--scope",
        "GLOBAL",
        "--request-id",
        "pause-1",
        "--actor",
        "oncall-a",
        "--reason",
        "incident",
        "--confirm",
        "YES:pause-1",
    )
    first = invoke(state_dir, *arguments)
    second = invoke(state_dir, *arguments)
    assert first.returncode == 0
    assert json.loads(first.stdout)["paused"] is True
    assert json.loads(second.stdout)["reused"] is True

    blocked_resume = invoke(
        state_dir,
        "resume",
        "--scope",
        "GLOBAL",
        "--request-id",
        "resume-1",
        "--actor",
        "oncall-a",
        "--reason",
        "unsafe early resume",
        "--confirm",
        "YES:resume-1",
    )
    assert blocked_resume.returncode == 1
    assert "readiness gates" in json.loads(blocked_resume.stdout)["error"]


def test_alert_evaluation_and_ack_use_durable_local_sink(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    signals = tmp_path / "signals.json"
    signals.write_text(json.dumps({"live_enabled": True}), encoding="utf-8")
    evaluated = invoke(
        state_dir,
        "evaluate-alerts",
        "--signals",
        str(signals),
    )
    result = json.loads(evaluated.stdout)
    assert evaluated.returncode == 0
    assert result["status"]["sink"] == "durable_local_sqlite"
    alert = next(item for item in result["emitted"] if item["rule_id"] == "live_true")

    acknowledged = invoke(
        state_dir,
        "ack-alert",
        "--alert-id",
        alert["alert_id"],
        "--request-id",
        "ack-1",
        "--actor",
        "oncall-a",
        "--reason",
        "investigating",
        "--confirm",
        "YES:ack-1",
    )
    assert acknowledged.returncode == 0
    assert json.loads(acknowledged.stdout)["status"] == "ACKNOWLEDGED"
