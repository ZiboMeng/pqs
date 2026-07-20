from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_ROOT / "scripts" / "trading_control.py"


def invoke(db: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--db-path", str(db)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_operator_can_pause_inspect_and_resume_global_control(tmp_path):
    db = tmp_path / "controls.db"
    paused = invoke(
        db,
        "pause",
        "--scope",
        "GLOBAL",
        "--reason",
        "incident",
        "--operator",
        "oncall-a",
        "--request-id",
        "pause-1",
        "--confirm",
        "YES:pause-1",
    )
    assert paused.returncode == 0
    assert json.loads(paused.stdout)["paused"] is True

    status = invoke(db, "status")
    assert json.loads(status.stdout)[0]["scope"] == "GLOBAL"

    resumed = invoke(
        db,
        "resume",
        "--scope",
        "GLOBAL",
        "--reason",
        "reconciled",
        "--operator",
        "oncall-b",
        "--request-id",
        "resume-1",
        "--confirm",
        "YES:resume-1",
    )
    assert resumed.returncode == 0
    assert json.loads(resumed.stdout)["paused"] is False


def test_pause_rejects_missing_operator_identity(tmp_path):
    result = invoke(
        tmp_path / "controls.db",
        "pause",
        "--scope",
        "GLOBAL",
        "--reason",
        "incident",
    )
    assert result.returncode != 0
    assert "--operator" in result.stderr
