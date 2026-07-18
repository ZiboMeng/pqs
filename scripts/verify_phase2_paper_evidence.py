#!/usr/bin/env python3
"""Fail closed unless all phase-two PAPER operational evidence agrees."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PAPER_ROOT = ROOT / "research/results/phase2/paper"


def _load(name: str) -> dict[str, Any]:
    return json.loads((PAPER_ROOT / name).read_text(encoding="utf-8"))


def verify() -> dict[str, Any]:
    clean = _load("dual_index_growth_clean_2023.json")
    restart = _load("dual_index_growth_restart_2023.json")
    idempotent = _load("dual_index_growth_idempotent_2023.json")
    faults = _load("fault_injection.json")
    scenario_pass = {
        name: bool(item["passed"])
        for name, item in faults["scenarios"].items()
    }
    checks = {
        "paper_replay_250_sessions": clean["sessions"] == 250,
        "restart_nav_identical": clean["nav_sha256"] == restart["nav_sha256"],
        "restart_equity_identical": clean["latest_equity"] == restart["latest_equity"],
        "restart_cash_identical": clean["cash"] == restart["cash"],
        "restart_positions_identical": clean["positions"] == restart["positions"],
        "restart_orders_identical": (
            clean["orders"] == restart["orders"]
            and clean["order_states"] == restart["order_states"]
        ),
        "idempotent_nav_identical": clean["nav_sha256"] == idempotent["nav_sha256"],
        "idempotent_all_sessions_reused": (
            idempotent["reports_reused"] == idempotent["sessions"] == 250
        ),
        "idempotent_no_new_orders": clean["orders"] == idempotent["orders"],
        "broker_reconciled": all(
            item["broker_reconciled"] for item in (clean, restart, idempotent)
        ),
        "no_global_pause": not any(
            item["global_pause"] for item in (clean, restart, idempotent)
        ),
        "no_unresolved_orders": all(
            item["order_states"][state] == 0
            for item in (clean, restart, idempotent)
            for state in ("CREATED", "VALIDATED", "SUBMITTED", "ACKNOWLEDGED", "UNKNOWN")
        ),
        "live_disabled": all(
            item["live_enabled"] is False for item in (clean, restart, idempotent)
        ),
        "fault_suite_passed": faults["test_result"]["status"] == "PASS",
        "all_fault_scenarios_passed": all(scenario_pass.values()),
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise RuntimeError(f"PAPER operational evidence failed: {failed}")
    return {
        "schema_version": 1,
        "strategy_id": "dual_index_growth_v1",
        "code_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "status": "PASS",
        "checks": checks,
        "fault_scenarios": scenario_pass,
        "paper_replay": {
            "start": "2023-01-03",
            "end": "2023-12-29",
            "sessions": clean["sessions"],
            "nav_sha256": clean["nav_sha256"],
            "latest_equity": clean["latest_equity"],
            "orders": clean["orders"],
            "filled_orders": clean["order_states"]["FILLED"],
            "risk_rejected_orders": clean["order_states"]["REJECTED"],
        },
        "operational_controls": {
            "missing_data_fail_closed": True,
            "stale_data_fail_closed": True,
            "risk_veto_test": True,
            "restart_idempotency_test": True,
            "paper_replay": True,
            "live_disabled": True,
        },
        "evidence": {
            "clean": "research/results/phase2/paper/dual_index_growth_clean_2023.json",
            "restart": "research/results/phase2/paper/dual_index_growth_restart_2023.json",
            "idempotent": "research/results/phase2/paper/dual_index_growth_idempotent_2023.json",
            "fault_injection": "research/results/phase2/paper/fault_injection.json",
        },
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=PAPER_ROOT / "operational_acceptance.json",
        type=Path,
    )
    args = parser.parse_args()
    result = verify()
    _write(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
