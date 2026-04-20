#!/usr/bin/env python3
"""
Generic scanner chain watcher: when the supplied scanner finishes all zips
for `--watching-year`, kill it and relaunch as a `--next-year` scanner with
the same decrypt_tmp slot.

Avoids running multiple heavy scanners concurrently (OOM risk) while being
hands-off — operator does not need to be present at the moment one year
wraps up.

Behavior:
  1. Poll every 60s
  2. When <watching-year>*.zip count == 0 AND no in_progress in state file
     AND condition stable for `--stable-polls` consecutive polls:
       a. SIGTERM current scanner by PID
       b. Wait for it to exit
       c. Launch new scanner with --year-include <next-year> + own state file
       d. Exit watcher

Run:
  nohup python scripts/scanner_chain_2024_to_2025.py \\
        --a-pid <PID> \\
        --watching-year 2025 --next-year 2026 \\
        --next-state-file data/trades_scanner_state_2026.json \\
        > logs/scanner_chain_<TS>.log 2>&1 &
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRADES_ROOT = Path("/mnt/c/Users/Admin/Documents/projects/trades")
PYTHON_BIN = "/home/zibo/miniconda3/envs/pqs/bin/python"
SCANNER_PATH = PROJECT_ROOT / "scripts" / "trades_scanner.py"
LOGS_DIR = PROJECT_ROOT / "logs"
POLL_SECONDS = 60


def _log(msg: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def count_year_zips(year: str) -> int:
    """Count zips matching <year>*.zip under TRADES_ROOT, recursively."""
    if not TRADES_ROOT.exists():
        return 0
    return sum(1 for _ in TRADES_ROOT.rglob(f"{year}*.zip"))


def state_in_progress(state_file: Path) -> bool:
    if not state_file.exists():
        return False
    try:
        d = json.loads(state_file.read_text())
    except Exception:
        return True  # be cautious
    return any(rec.get("status") == "in_progress"
               for rec in d.get("processed", {}).values())


def kill_pid(pid: int, timeout_s: int = 600) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _log(f"PID {pid} already gone")
        return True
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            os.kill(pid, 0)  # check existence
        except ProcessLookupError:
            return True
        time.sleep(2)
    _log(f"WARN: PID {pid} did not exit within {timeout_s}s; sending SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    time.sleep(3)
    return True


def launch_next_scanner(decrypt_tmp: str, next_year: str,
                         next_state_file: Path) -> int:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"scanner_a_{next_year}_{ts}.out"
    cmd = [
        PYTHON_BIN, str(SCANNER_PATH), "--watch",
        "--year-include", next_year,
        "--state-file", str(next_state_file),
        "--decrypt-tmp", decrypt_tmp,
    ]
    _log(f"launching: {' '.join(cmd)} > {log_path}")
    p = subprocess.Popen(
        cmd,
        stdout=open(log_path, "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _log(f"launched {next_year} scanner, PID {p.pid}, log {log_path}")
    return p.pid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a-pid", type=int, required=True,
                    help="PID of the currently running scanner")
    ap.add_argument("--state-file", type=Path,
                    default=PROJECT_ROOT / "data" / "trades_scanner_state.json",
                    help="current scanner's state file (to detect in_progress)")
    ap.add_argument("--decrypt-tmp", type=str, default="/tmp/scanner_a_decrypt.csv",
                    help="decrypt_tmp slot to reuse for the relaunched scanner")
    ap.add_argument("--watching-year", type=str, default="2024",
                    help="year prefix to wait for completion of")
    ap.add_argument("--next-year", type=str, default="2025",
                    help="year prefix to launch after completion")
    ap.add_argument("--next-state-file", type=Path,
                    default=PROJECT_ROOT / "data" / "trades_scanner_state_2025.json",
                    help="state file for the next-year scanner")
    ap.add_argument("--stable-polls", type=int, default=3,
                    help="require zips==0 for this many consecutive polls "
                         "before triggering swap (guards against user still "
                         "downloading more zips)")
    args = ap.parse_args()

    _log(f"watcher start: PID={args.a_pid}, state={args.state_file}, "
         f"watching {args.watching_year}*.zip, next_year={args.next_year}, "
         f"stable_polls={args.stable_polls}")

    # Sanity: PID exists
    try:
        os.kill(args.a_pid, 0)
    except ProcessLookupError:
        _log(f"ERROR: A PID {args.a_pid} not running. exit.")
        sys.exit(1)

    stable_count = 0
    while True:
        n = count_year_zips(args.watching_year)
        in_progress = state_in_progress(args.state_file)
        try:
            os.kill(args.a_pid, 0)
            a_alive = True
        except ProcessLookupError:
            a_alive = False
        _log(f"poll: {args.watching_year}*.zip on disk={n}, "
             f"in_progress={in_progress}, alive={a_alive}, "
             f"stable={stable_count}/{args.stable_polls}")

        if not a_alive:
            _log(f"current scanner already exited. launching {args.next_year} scanner.")
            launch_next_scanner(args.decrypt_tmp, args.next_year,
                                 args.next_state_file)
            break

        if n == 0 and not in_progress:
            stable_count += 1
            if stable_count >= args.stable_polls:
                _log(f"all {args.watching_year} zips processed, stable for "
                     f"{stable_count} polls. swapping to {args.next_year}.")
                kill_pid(args.a_pid)
                time.sleep(2)
                launch_next_scanner(args.decrypt_tmp, args.next_year,
                                     args.next_state_file)
                break
        else:
            stable_count = 0  # reset on any activity

        time.sleep(POLL_SECONDS)

    _log("watcher done.")


if __name__ == "__main__":
    main()
