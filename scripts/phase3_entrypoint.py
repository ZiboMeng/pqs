#!/usr/bin/env python3
"""Container entrypoint enforcing non-root PAPER-only startup."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise RuntimeError("Phase 3 container refuses to run as root")
    forward = yaml.safe_load((ROOT / "config/forward_paper.yaml").read_text(encoding="utf-8"))
    system = yaml.safe_load((ROOT / "config/system.yaml").read_text(encoding="utf-8"))
    if (
        forward.get("mode") != "PAPER"
        or forward.get("live_enabled") is not False
        or forward.get("broker_write_enabled") is not False
        or system.get("runtime", {}).get("live_enabled") is not False
    ):
        raise RuntimeError("container configuration violates the PAPER-only boundary")
    forbidden = [
        name
        for name in (
            "PQS_LIVE_APPROVAL_TOKEN",
            "PQS_BROKER_WRITE_TOKEN",
            "PQS_LIVE_BROKER_CREDENTIALS",
        )
        if os.environ.get(name)
    ]
    if forbidden:
        raise RuntimeError(f"forbidden LIVE/write environment variables are set: {forbidden}")
    for variable in ("PQS_PHASE3_STATE_DIR", "PQS_DATA_DIR"):
        value = os.environ.get(variable)
        if not value:
            raise RuntimeError(f"required writable-volume environment is absent: {variable}")
        path = Path(value)
        if path.is_symlink() or not path.is_dir() or not os.access(path, os.W_OK):
            raise RuntimeError(f"writable-volume path is unavailable: {variable}")
    command = sys.argv[1:] or [
        sys.executable,
        str(ROOT / "scripts/phase3_supervisor.py"),
    ]
    os.execvp(command[0], command)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
