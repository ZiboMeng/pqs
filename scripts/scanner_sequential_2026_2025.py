#!/usr/bin/env python3
"""
Sequential scanner driver for the 2026-first-then-2025 plan.

Rationale:
  - 2026 zips are large (3-4 GB) — finish them first while 2025 downloads
    continue in the background.
  - 2025 has a known completion date (20251231 last trading day). We only
    terminate the 2025 scanner after that date appears in the state file as
    status=done, guarding against 'user still downloading, scanner prematurely
    stopped' failure mode.

Sequence:
  Stage 1: wait for 2026 scanner to drain (zips=0 + no in_progress + stable)
  Stage 2: kill 2026 scanner; launch 2025 scanner
  Stage 3: wait for 2025 drain AND 20251231 done in state
  Stage 4: kill 2025 scanner; exit (orchestrator picks up after this)

Launch:
  nohup python scripts/scanner_sequential_2026_2025.py \\
    --a-pid <current 2026 scanner PID> \\
    > logs/scanner_sequential_<TS>.log 2>&1 &
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_BIN = "/home/zibo/miniconda3/envs/pqs/bin/python"
SCANNER_PATH = PROJECT_ROOT / "scripts" / "trades_scanner.py"
LOGS_DIR = PROJECT_ROOT / "logs"
TRADES_ROOT = Path("/mnt/c/Users/Admin/Documents/projects/trades")

STATE_2026 = PROJECT_ROOT / "data" / "trades_scanner_state_2026.json"
STATE_2025 = PROJECT_ROOT / "data" / "trades_scanner_state_2025.json"
DECRYPT_TMP = "/tmp/scanner_a_decrypt.csv"

POLL_SECONDS = 60
STABLE_TARGET = 3  # consecutive empty polls to trigger drain-complete


def log(msg: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} [seq] {msg}", flush=True)


def count_year_zips(year: str) -> int:
    if not TRADES_ROOT.exists():
        return 0
    return sum(1 for _ in TRADES_ROOT.rglob(f"{year}*.zip"))


def read_state(path: Path) -> dict:
    if not path.exists():
        return {"processed": {}, "failed": {}}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"processed": {}, "failed": {}}


def state_has_in_progress(path: Path) -> bool:
    d = read_state(path)
    return any(rec.get("status") == "in_progress"
               for rec in d.get("processed", {}).values())


def state_has_done_for_date(path: Path, date: str) -> bool:
    """True if any processed zip has date=YYYY-MM-DD and status=done."""
    d = read_state(path)
    iso_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    for rec in d.get("processed", {}).values():
        if rec.get("status") == "done" and rec.get("date") == iso_date:
            return True
    return False


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def kill_scanner(pid: int, timeout_s: int = 120) -> None:
    if not pid_alive(pid):
        log(f"  PID {pid} already gone")
        return
    log(f"  SIGTERM {pid}")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not pid_alive(pid):
            log(f"  PID {pid} exited")
            return
        time.sleep(2)
    log(f"  SIGKILL {pid}")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    time.sleep(2)


def launch_scanner(year: str, state_file: Path) -> int:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"scanner_a_{year}_seq_{ts}.out"
    cmd = [
        PYTHON_BIN, str(SCANNER_PATH), "--watch",
        "--year-include", year,
        "--state-file", str(state_file),
        "--decrypt-tmp", DECRYPT_TMP,
    ]
    log(f"  launching {year} scanner: {' '.join(cmd)}")
    p = subprocess.Popen(
        cmd, stdout=open(log_path, "w"), stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log(f"  launched, PID={p.pid}, log={log_path}")
    return p.pid


def wait_drain(year: str, state_file: Path, pid: int,
               completion_date: str | None = None) -> None:
    """Poll every POLL_SECONDS until year zips = 0 AND no in_progress AND
    (optional) completion_date done, stable for STABLE_TARGET polls."""
    stable = 0
    while True:
        if not pid_alive(pid):
            log(f"  scanner PID {pid} exited unexpectedly — abort wait")
            return
        n = count_year_zips(year)
        ip = state_has_in_progress(state_file)
        comp_ok = True
        comp_msg = ""
        if completion_date:
            comp_ok = state_has_done_for_date(state_file, completion_date)
            comp_msg = f" completion({completion_date})={'OK' if comp_ok else 'PENDING'}"
        log(f"  wait {year}: zips={n} in_progress={ip}{comp_msg} "
            f"stable={stable}/{STABLE_TARGET}")
        if n == 0 and not ip and comp_ok:
            stable += 1
            if stable >= STABLE_TARGET:
                log(f"  {year} drained — completion criteria met")
                return
        else:
            stable = 0
        time.sleep(POLL_SECONDS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a-pid", type=int, required=True,
                    help="PID of the currently running 2026 scanner")
    ap.add_argument("--completion-date-2025", type=str, default="20251231",
                    help="YYYYMMDD of last expected 2025 trading day "
                         "(default 20251231)")
    args = ap.parse_args()

    log(f"sequential driver start: initial A PID={args.a_pid}")

    # Stage 1: wait for 2026 drain
    log("STAGE 1: wait for 2026 scanner to drain")
    wait_drain("2026", STATE_2026, args.a_pid)

    # Stage 2: kill 2026, launch 2025
    log("STAGE 2: kill 2026 scanner, launch 2025 scanner")
    kill_scanner(args.a_pid)
    a_2025_pid = launch_scanner("2025", STATE_2025)

    # Stage 3: wait for 2025 drain + completion_date done
    log(f"STAGE 3: wait for 2025 drain AND {args.completion_date_2025} "
        "processed")
    wait_drain("2025", STATE_2025, a_2025_pid,
               completion_date=args.completion_date_2025)

    # Stage 4: kill 2025, exit
    log("STAGE 4: kill 2025 scanner, exit (orchestrator takes over)")
    kill_scanner(a_2025_pid)
    log("sequential driver done")


if __name__ == "__main__":
    main()
