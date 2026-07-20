from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_ROOT / "scripts/run_forward_paper.py"


def test_real_event_rejects_unbound_caller_supplied_source_hash(tmp_path: Path) -> None:
    state_dir = tmp_path / "must-not-be-created"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "run-once",
            "--phase",
            "close",
            "--session",
            "2026-07-20",
            "--event-id",
            "unbound-source",
            "--source-batch-sha256",
            "a" * 64,
            "--available-at",
            "2026-07-20T20:10:00+00:00",
            "--received-at",
            "2026-07-20T20:10:01+00:00",
            "--state-dir",
            str(state_dir),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert "trusted collection records are not yet bound" in payload["error"]
    assert not state_dir.exists()
