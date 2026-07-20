#!/usr/bin/env python3
"""Read-only liveness check for the Phase 3 monitor supervisor heartbeat."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate heartbeat key: {key}")
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heartbeat", required=True)
    parser.add_argument("--maximum-age-seconds", type=int, default=180)
    args = parser.parse_args()
    report: dict[str, Any] = {
        "status": "failed",
        "checked_at_utc": datetime.now(UTC).isoformat(),
    }
    try:
        if args.maximum_age_seconds <= 0:
            raise ValueError("maximum age must be positive")
        path = Path(args.heartbeat)
        if path.is_symlink() or not path.is_file():
            raise ValueError("heartbeat must be a regular non-symlink file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            raw = os.read(descriptor, 65_537)
        finally:
            os.close(descriptor)
        if len(raw) > 65_536:
            raise ValueError("heartbeat exceeds size limit")
        payload = json.loads(raw, object_pairs_hook=_reject_duplicates)
        if not isinstance(payload, dict):
            raise ValueError("heartbeat must be an object")
        checked_at = datetime.fromisoformat(str(payload["checked_at_utc"]))
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("heartbeat timestamp must include an offset")
        age = (datetime.now(UTC) - checked_at.astimezone(UTC)).total_seconds()
        if age < -5 or age > args.maximum_age_seconds:
            raise ValueError(f"heartbeat age is outside the allowed window: {age:.3f}s")
        if payload.get("service") != "phase3-monitor-only-supervisor":
            raise ValueError("heartbeat service identity is invalid")
        if payload.get("healthy") is not True:
            raise ValueError("supervisor reported unhealthy")
        if payload.get("ready_for_live") is not False:
            raise ValueError("heartbeat violated the LIVE boundary")
        report = {
            "status": "ok",
            "checked_at_utc": datetime.now(UTC).isoformat(),
            "heartbeat_age_seconds": age,
            "monitor_only": bool(payload.get("monitor_only")),
            "ready_for_live": False,
        }
    except Exception as exc:  # noqa: BLE001
        report["error"] = str(exc)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
