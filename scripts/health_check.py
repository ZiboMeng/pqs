#!/usr/bin/env python3
"""Machine-readable local/container health check; no network or order writes."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config.loader import load_config


def _sqlite_health(db_path: Path) -> dict:
    if not db_path.exists():
        return {"status": "not_initialized", "path": str(db_path)}
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            result = conn.execute("PRAGMA quick_check").fetchone()
        ok = result is not None and result[0] == "ok"
        return {
            "status": "ok" if ok else "corrupt",
            "path": str(db_path),
            "quick_check": None if result is None else result[0],
        }
    except sqlite3.Error as exc:
        return {"status": "error", "path": str(db_path), "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="PQS read-only health check")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args()

    report = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "status": "ok",
        "checks": {},
    }
    try:
        config = load_config(Path(args.config_dir))
        report["checks"]["config"] = {
            "status": "ok",
            "environment": config.system.env,
            "runtime_default": config.system.runtime.default_mode,
            "live_enabled": config.system.runtime.live_enabled,
        }
        if config.system.runtime.live_enabled:
            report["status"] = "degraded"
            report["checks"]["live_default"] = {
                "status": "warning",
                "reason": "repository safety default was overridden",
            }
    except Exception as exc:  # noqa: BLE001
        report["status"] = "failed"
        report["checks"]["config"] = {"status": "error", "error": str(exc)}

    if args.db_path:
        db_check = _sqlite_health(Path(args.db_path))
        report["checks"]["sqlite"] = db_check
        if db_check["status"] in {"corrupt", "error"}:
            report["status"] = "failed"

    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in {"ok", "degraded"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
