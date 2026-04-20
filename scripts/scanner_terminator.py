#!/usr/bin/env python3
"""
Scanner terminator: wait for a single scanner to fully drain, then kill it.

Conditions for "drained":
  - year*.zip on disk = 0
  - state file has no in_progress
  - optional: --completion-date YYYYMMDD is in state as status=done
  - stable for --stable-polls consecutive polls

Uses /proc/<pid>/stat to detect zombie PIDs (unlike os.kill(pid,0) which
returns success for zombies — this bug caused earlier sequential driver to
think a dead scanner was alive).

Launch:
  nohup python scripts/scanner_terminator.py \\
    --pid <PID> --year 2025 \\
    --state-file data/trades_scanner_state_2025.json \\
    --completion-date 20251231 \\
    > logs/scanner_terminator_<TS>.log 2>&1 &
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

TRADES_ROOT = Path("/mnt/c/Users/Admin/Documents/projects/trades")


def log(msg: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} [term] {msg}", flush=True)


def pid_alive(pid: int) -> bool:
    """True if process exists AND not zombie. /proc/<pid>/stat field 3 is the
    state char: R/S/D/Z/T/…"""
    try:
        with open(f"/proc/{pid}/stat") as f:
            data = f.read()
    except FileNotFoundError:
        return False
    # field 3 is state; field 2 is comm wrapped in parens (may contain spaces)
    rparen = data.rfind(")")
    if rparen < 0:
        return False
    state = data[rparen + 2]  # char after ") "
    return state != "Z"


def count_year_zips(year: str) -> int:
    if not TRADES_ROOT.exists():
        return 0
    return sum(1 for _ in TRADES_ROOT.rglob(f"{year}*.zip"))


def read_state(path: Path) -> dict:
    if not path.exists():
        return {"processed": {}}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"processed": {}}


def has_in_progress(state: dict) -> bool:
    return any(rec.get("status") == "in_progress"
               for rec in state.get("processed", {}).values())


def has_done_for_date(state: dict, yyyymmdd: str) -> bool:
    iso = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
    return any(rec.get("status") == "done" and rec.get("date") == iso
               for rec in state.get("processed", {}).values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--year", type=str, required=True, help="4-digit year")
    ap.add_argument("--state-file", type=Path, required=True)
    ap.add_argument("--completion-date", type=str, default=None,
                    help="YYYYMMDD — state must have this date processed")
    ap.add_argument("--stable-polls", type=int, default=3)
    ap.add_argument("--poll-sec", type=int, default=60)
    args = ap.parse_args()

    log(f"terminator start: PID={args.pid} year={args.year} "
        f"state={args.state_file} completion={args.completion_date} "
        f"stable_target={args.stable_polls}")

    if not pid_alive(args.pid):
        log(f"PID {args.pid} already dead, nothing to do")
        return

    stable = 0
    while True:
        if not pid_alive(args.pid):
            log(f"PID {args.pid} exited on its own, terminator done")
            return
        zips = count_year_zips(args.year)
        state = read_state(args.state_file)
        ip = has_in_progress(state)
        comp_ok = True
        comp_msg = ""
        if args.completion_date:
            comp_ok = has_done_for_date(state, args.completion_date)
            comp_msg = f" completion({args.completion_date})={'OK' if comp_ok else 'PENDING'}"
        log(f"poll: zips={zips} in_progress={ip}{comp_msg} "
            f"stable={stable}/{args.stable_polls}")
        if zips == 0 and not ip and comp_ok:
            stable += 1
            if stable >= args.stable_polls:
                log(f"draining criteria met — SIGTERM PID {args.pid}")
                try:
                    os.kill(args.pid, signal.SIGTERM)
                except ProcessLookupError:
                    log("already gone"); return
                time.sleep(5)
                if pid_alive(args.pid):
                    log(f"SIGTERM did not exit — SIGKILL")
                    try:
                        os.kill(args.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    time.sleep(2)
                log("terminator done")
                return
        else:
            stable = 0
        time.sleep(args.poll_sec)


if __name__ == "__main__":
    main()
