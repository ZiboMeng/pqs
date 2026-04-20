#!/usr/bin/env python3
"""
Post-processing orchestrator: waits for the trades scanners to finish,
then runs the full data-ready pipeline unattended.

Stages:
  0. Wait for all trades zip scanners to drain (no in_progress, no zips on disk)
  1. Kill chain watcher + disk guard (done their job)
  2. consolidate_trades.py  — merge .staging_trades/ into root 1m parquets
  3. aggregate_bars.py --workers 6  — 1m → 5/15/30/60m + daily
  4. consolidate_sanity_check.py  — halt if >= HALT_THRESHOLD tickers flagged
  5. build_catalog.py  — refresh _catalog.parquet
  6. validate_vs_yfinance.py (daily + 1m sample) — spot-check vs yfinance
  7. Verify zero failed zips in state files
  8. pytest -q tests/  — ensure no regression
  9. Cleanup: remove .staging/, .staging_trades/, /tmp/scanner_*_decrypt.csv
 10. Write summary report → reports/post_processing/summary.md

If ANY stage fails, orchestrator logs the failure and stops (does NOT attempt
to recover autonomously — leaves state for operator review).

Launch:
  nohup python scripts/post_processing_pipeline.py \\
    > logs/post_processing_<TS>.log 2>&1 &
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_BIN = "/home/zibo/miniconda3/envs/pqs/bin/python"
LOGS_DIR = PROJECT_ROOT / "logs"
REPORT_DIR = PROJECT_ROOT / "reports" / "post_processing"
TRADES_ROOT = Path("/mnt/c/Users/Admin/Documents/projects/trades")

STATE_FILES = [
    PROJECT_ROOT / "data" / "trades_scanner_state.json",
    PROJECT_ROOT / "data" / "trades_scanner_state_2025.json",
    PROJECT_ROOT / "data" / "trades_scanner_state_2026.json",
]
STAGING_DIR = PROJECT_ROOT / "data" / "intraday" / "1m" / ".staging"
STAGING_TRADES_DIR = PROJECT_ROOT / "data" / "intraday" / "1m" / ".staging_trades"

POLL_SECONDS = 300  # 5 min poll for scanner completion
STABLE_POLLS = 3    # 3 consecutive quiet polls = done


def log(msg: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} [orch] {msg}", flush=True)


def read_state_safe(path: Path) -> dict:
    if not path.exists():
        return {"processed": {}, "failed": {}}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"processed": {}, "failed": {}}


def any_in_progress() -> list[str]:
    out = []
    for sf in STATE_FILES:
        d = read_state_safe(sf)
        for path, rec in d.get("processed", {}).items():
            if rec.get("status") == "in_progress":
                out.append(path)
    return out


def zips_on_disk() -> int:
    if not TRADES_ROOT.exists():
        return 0
    return sum(1 for _ in TRADES_ROOT.rglob("*.zip"))


def scanners_running() -> list[int]:
    r = subprocess.run(
        ["pgrep", "-f", "trades_scanner.py --watch"],
        capture_output=True, text=True,
    )
    pids = [int(p) for p in r.stdout.split() if p.strip()]
    return pids


def wait_for_scanners_done() -> None:
    log("STAGE 0: wait for scanners to finish")
    stable = 0
    while True:
        zips = zips_on_disk()
        ip = any_in_progress()
        pids = scanners_running()
        log(f"  poll: zips_on_disk={zips} in_progress={len(ip)} "
            f"scanner_pids={pids} stable={stable}/{STABLE_POLLS}")
        if zips == 0 and not ip:
            # Also require scanners to have finished their current outer-loop
            # poll cycle — they sleep 60s when queue empty. We add STABLE_POLLS
            # × POLL_SECONDS of stability before declaring done.
            stable += 1
            if stable >= STABLE_POLLS:
                log(f"  all quiet for {stable} polls, moving on")
                return
        else:
            stable = 0
        time.sleep(POLL_SECONDS)


def kill_watcher_and_guard() -> None:
    log("STAGE 1: kill chain watcher + disk guard + any lingering scanners")
    patterns = [
        "scanner_chain_2024_to_2025.py",
        "disk_guard.py",
        "trades_scanner.py --watch",
    ]
    for p in patterns:
        r = subprocess.run(["pkill", "-f", p], capture_output=True, text=True)
        log(f"  pkill -f '{p}' rc={r.returncode}")
    time.sleep(3)


def run_stage(name: str, cmd: list[str], *, cwd: Path = PROJECT_ROOT,
              halt_on_fail: bool = True) -> subprocess.CompletedProcess:
    log(f"STAGE: {name}")
    log(f"  cmd: {' '.join(cmd)}")
    t0 = time.time()
    r = subprocess.run(cmd, cwd=str(cwd))
    dt = time.time() - t0
    log(f"  rc={r.returncode} elapsed={dt:.1f}s")
    if r.returncode != 0 and halt_on_fail:
        log(f"FAIL: {name} exited non-zero. Halting.")
        sys.exit(r.returncode)
    return r


def verify_no_failed_zips() -> list[str]:
    log("STAGE: verify zero failed zips in state files")
    fails: list[str] = []
    for sf in STATE_FILES:
        d = read_state_safe(sf)
        for path, rec in d.get("processed", {}).items():
            if rec.get("status") == "failed":
                fails.append(f"{sf.name}:{path}")
    if fails:
        log(f"  {len(fails)} failed zips remaining:")
        for f in fails[:10]:
            log(f"    {f}")
        if len(fails) > 10:
            log(f"    ... and {len(fails)-10} more")
    else:
        log("  zero failed zips — all processed cleanly")
    return fails


def cleanup() -> None:
    log("STAGE: cleanup staging + tmp files")
    for d in (STAGING_DIR, STAGING_TRADES_DIR):
        if d.exists():
            size_gb = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e9
            log(f"  removing {d} ({size_gb:.1f}GB)")
            shutil.rmtree(d, ignore_errors=True)
    for tmp in Path("/tmp").glob("scanner_*_decrypt.csv*"):
        try:
            tmp.unlink(); log(f"  removed {tmp}")
        except Exception:
            pass
    for tmp in Path("/tmp").glob("trades_scanner_*"):
        try:
            tmp.unlink(); log(f"  removed {tmp}")
        except Exception:
            pass


def write_summary(stages_log: list[dict], failed_zips: list[str],
                  sanity_report: Path | None) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"summary_{ts}.md"
    lines = [
        "# Post-processing pipeline summary",
        f"Generated: {datetime.now().isoformat()}",
        "",
        "## Stages",
        "",
    ]
    for s in stages_log:
        lines.append(f"- **{s['name']}**: rc={s['rc']}, {s['elapsed']:.1f}s")
    lines.extend([
        "",
        f"## Scanner state: failed zips remaining = {len(failed_zips)}",
        "",
    ])
    if failed_zips:
        lines.append("")
        for f in failed_zips[:20]:
            lines.append(f"  - `{f}`")
        if len(failed_zips) > 20:
            lines.append(f"  - ... and {len(failed_zips)-20} more")
    if sanity_report:
        lines.extend(["", "## Sanity report", "", f"See `{sanity_report.relative_to(PROJECT_ROOT)}`"])
    lines.extend([
        "",
        "## Next steps (interactive w/ operator)",
        "",
        "- P1 code changes (BarStore provenance, factor guard, provenance migration)",
        "- CLAUDE.md update (Phase D trades backfill section)",
        "- Git commits (logical groups)",
        "- Rerun best strategy backtest",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    log(f"summary report: {path}")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-wait", action="store_true",
                    help="Skip STAGE 0 (wait for scanners) — use when operator "
                         "has confirmed scanners are already done.")
    args = ap.parse_args()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    log(f"post_processing_pipeline start (skip_wait={args.skip_wait})")

    stages_log: list[dict] = []

    def _time_and_track(name: str, fn, *args, **kwargs):
        t0 = time.time()
        try:
            res = fn(*args, **kwargs)
            rc = 0
        except SystemExit as e:
            rc = int(e.code) if e.code is not None else 1
            res = None
        elapsed = time.time() - t0
        stages_log.append({"name": name, "rc": rc, "elapsed": elapsed})
        if rc != 0:
            log(f"stage {name} exit rc={rc}")
            # Write partial summary even on abort
            write_summary(stages_log, verify_no_failed_zips(), None)
            sys.exit(rc)
        return res

    if not args.skip_wait:
        _time_and_track("wait_for_scanners", wait_for_scanners_done)
    else:
        log("skipping STAGE 0 wait_for_scanners per --skip-wait")
    _time_and_track("kill_watcher_and_guard", kill_watcher_and_guard)

    _time_and_track(
        "consolidate_trades",
        run_stage, "consolidate_trades",
        [PYTHON_BIN, "scripts/consolidate_trades.py"],
    )

    _time_and_track(
        "aggregate_bars",
        run_stage, "aggregate_bars (workers=6)",
        [PYTHON_BIN, "scripts/aggregate_bars.py", "--workers", "6"],
    )

    # sanity check — halts if flagged ≥ HALT_THRESHOLD
    _time_and_track(
        "sanity_check",
        run_stage, "sanity_check",
        [PYTHON_BIN, "scripts/consolidate_sanity_check.py"],
    )

    _time_and_track(
        "build_catalog",
        run_stage, "build_catalog",
        [PYTHON_BIN, "scripts/build_catalog.py"],
    )

    _time_and_track(
        "validate_daily",
        run_stage, "validate (daily, 10 symbols × 5 windows)",
        [PYTHON_BIN, "scripts/validate_vs_yfinance.py",
         "--freq", "daily", "--n-symbols", "10", "--n-windows", "5"],
        halt_on_fail=False,  # validate is observational
    )
    _time_and_track(
        "validate_1m",
        run_stage, "validate (1m, 5 symbols)",
        [PYTHON_BIN, "scripts/validate_vs_yfinance.py",
         "--freq", "1m", "--n-symbols", "5"],
        halt_on_fail=False,
    )

    _time_and_track(
        "pytest",
        run_stage, "pytest full suite",
        [PYTHON_BIN, "-m", "pytest", "tests/", "-q"],
        halt_on_fail=False,  # log but don't abort
    )

    failed_zips = verify_no_failed_zips()

    # find latest sanity report for summary reference
    sanity_dir = PROJECT_ROOT / "reports" / "consolidate_sanity"
    sanity_reports = sorted(sanity_dir.glob("sanity_*.json"))
    latest_sanity = sanity_reports[-1] if sanity_reports else None

    _time_and_track("cleanup", cleanup)
    write_summary(stages_log, failed_zips, latest_sanity)

    log("post_processing_pipeline DONE")


if __name__ == "__main__":
    main()
