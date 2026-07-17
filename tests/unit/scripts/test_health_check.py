from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_ROOT / "scripts" / "health_check.py"


def run_health(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_health_check_reports_safe_runtime_defaults():
    result = run_health("--config-dir", "config")
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["status"] == "ok"
    assert report["checks"]["config"]["runtime_default"] == "PAPER"
    assert report["checks"]["config"]["live_enabled"] is False


def test_health_check_reads_sqlite_integrity_without_mutation(tmp_path):
    db = tmp_path / "state.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE state (id INTEGER PRIMARY KEY)")
    before = db.stat().st_mtime_ns
    result = run_health("--config-dir", "config", "--db-path", str(db))
    report = json.loads(result.stdout)
    assert result.returncode == 0
    assert report["checks"]["sqlite"]["quick_check"] == "ok"
    assert db.stat().st_mtime_ns == before
