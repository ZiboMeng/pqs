#!/usr/bin/env python3
"""
Disk guard: watch C: drive free space. When it falls below the threshold,
kill the Baidu Netdisk downloader from WSL via taskkill. Scanner keeps
running and frees space by deleting processed zips; download stays paused
until the operator restarts Baidu.

Designed for unattended overnight runs. Logs every poll to disk so the
operator can see history in the morning.

Run:
  nohup python dev/scripts/ops/disk_guard.py \
    --warn-gb 60 --kill-gb 30 --resume-gb 100 \
    > logs/disk_guard_<TS>.log 2>&1 &
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

TASKKILL = Path("/mnt/c/Windows/System32/taskkill.exe")
# Baidu process names (Windows). Observed running on the target machine:
#   BaiduNetdisk.exe         — main UI process
#   BaiduNetdiskUnite.exe    — download workers (multiple)
#   baidunetdiskhost.exe     — background host
# We kill ALL of them; Baidu will not auto-resume downloading until the
# operator launches the app manually.
BAIDU_PROCS = (
    "BaiduNetdisk.exe",
    "BaiduNetdiskUnite.exe",
    "baidunetdiskhost.exe",
    # fallback legacy names:
    "baidunetdisk.exe",
    "BaiduCloud.exe",
    "BaiduYunGuanjia.exe",
)


def _log(msg: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def free_gb(path: str = "/mnt/c") -> float:
    try:
        usage = shutil.disk_usage(path)
    except FileNotFoundError:
        return -1.0
    return usage.free / (1024 ** 3)


def kill_baidu(logger=_log) -> list[str]:
    """Try to kill all known Baidu processes via Windows taskkill.
    Returns list of process names where kill command succeeded."""
    if not TASKKILL.exists():
        logger(f"WARN: {TASKKILL} not found — cannot kill baidu")
        return []
    killed: list[str] = []
    for name in BAIDU_PROCS:
        try:
            r = subprocess.run(
                [str(TASKKILL), "/F", "/IM", name],
                capture_output=True, text=True, timeout=15,
            )
        except Exception as e:
            logger(f"  taskkill {name}: exception {e}")
            continue
        # taskkill exit 0 = killed, 128 = not found
        if r.returncode == 0:
            killed.append(name)
            logger(f"  killed {name}: {r.stdout.strip()}")
    return killed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mount", default="/mnt/c", help="disk mount to watch")
    ap.add_argument("--warn-gb", type=float, default=60.0,
                    help="log warning when free space drops below this")
    ap.add_argument("--kill-gb", type=float, default=30.0,
                    help="kill Baidu when free space drops below this")
    ap.add_argument("--resume-gb", type=float, default=100.0,
                    help="log that it is safe to resume when free space "
                         "exceeds this again (operator still starts Baidu "
                         "manually)")
    ap.add_argument("--poll-sec", type=int, default=60)
    args = ap.parse_args()

    _log(f"disk_guard start: mount={args.mount} "
         f"warn<{args.warn_gb}G kill<{args.kill_gb}G resume>{args.resume_gb}G")

    killed_state = False  # true after kill, until resume_gb reached
    while True:
        f = free_gb(args.mount)
        status = "OK"
        if f < 0:
            _log(f"  cannot stat {args.mount}"); time.sleep(args.poll_sec); continue
        if f < args.kill_gb:
            status = "CRITICAL"
            if not killed_state:
                _log(f"CRITICAL: free={f:.1f}G < {args.kill_gb}G — killing Baidu")
                killed = kill_baidu()
                _log(f"  kill result: {killed or 'nothing found / all already dead'}")
                killed_state = True
            else:
                _log(f"CRITICAL: free={f:.1f}G — already killed Baidu, waiting")
        elif f < args.warn_gb:
            status = "WARN"
            _log(f"WARN: free={f:.1f}G < {args.warn_gb}G")
        else:
            if killed_state and f >= args.resume_gb:
                _log(f"RECOVERED: free={f:.1f}G — safe for operator to resume Baidu")
                killed_state = False
            if status == "OK":
                _log(f"OK: free={f:.1f}G")
        time.sleep(args.poll_sec)


if __name__ == "__main__":
    main()
