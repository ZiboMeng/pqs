#!/usr/bin/env python
"""Workstream R0 — re-risk pack driver.

PRD: docs/prd/20260521-rerisk-and-ml-training-audit-prd.md §6.

Re-computes a trustworthy risk picture for the production baseline and
the active evidence candidates after the 2026-05-21 execution-kernel
fixes. Every row declares its backtest window and the temporal_split
partition it touches (PRD §6.5) and is reproducible from the
checked-in `scripts/run_backtest.py` path — no manual numbers (§6.4).

Round 1 (first ralph-loop round) wires the `baseline` candidate on the
train-only 2009-2017 window. Subsequent rounds add: stress slices, the
recent-window diagnostic, and the cycle06 / cycle08 / PEAD rows.

temporal_split discipline (PRD §6.5): the train-only window
(2009-2017) consumes no holdout. Validation-spanning windows, when
added later, are recorded with `partition: diagnostic` and never
reused as pre-promotion evidence.

Output: data/audit/rerisk_pack_20260521.json

Usage:
  python dev/scripts/audit/rerisk_pack.py --candidate baseline
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
PYTHON = sys.executable
PACK_PATH = PROJ / "data/audit/rerisk_pack_20260521.json"

# Per-row hard caps (PRD §6.3 + CLAUDE.md invariants).
MAXDD_HARD_CAP = 0.20      # 15-20% MaxDD invariant — full-period proxy
MAXDD_STRESS_CAP = 0.25    # 2008-style stress slice cap


def _num(text: str) -> float:
    """Parse a master_report cell like '+12.59%' / '-20.21%' / '0.67'."""
    t = text.strip().replace("%", "").replace("+", "").replace(",", "")
    return float(t)


def parse_master_report(path: Path) -> dict:
    """Extract the §1 strategy + benchmark metrics from a master_report.md."""
    txt = path.read_text()
    out: dict = {}
    row_re = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$", re.M)
    label_map = {
        "总收益": "total_return_pct", "CAGR": "cagr_pct",
        "Sharpe": "sharpe", "最大回撤": "max_dd_pct",
        "年化波动率": "ann_vol_pct", "交易笔数": "n_trades",
        "Beta": "beta", "IR": "ir",
    }
    for label, value in row_re.findall(txt):
        key = label_map.get(label.strip())
        if key is None:
            continue
        try:
            out[key] = _num(value)
        except ValueError:
            continue
    return out


def _verdict(row: dict) -> tuple[str, list[str]]:
    """PRD §6.3 verdict. Round-1 provisional: full-period MaxDD only;
    upgraded once stress-slice + per-validation-year rows land."""
    flags: list[str] = []
    max_dd = abs(row["metrics"].get("max_dd_pct", 0.0)) / 100.0
    if max_dd > MAXDD_STRESS_CAP:
        flags.append(f"full-period MaxDD {max_dd:.1%} > {MAXDD_STRESS_CAP:.0%} stress cap")
        verdict = "RED"
    elif max_dd > MAXDD_HARD_CAP:
        flags.append(f"full-period MaxDD {max_dd:.1%} > {MAXDD_HARD_CAP:.0%} hard cap")
        verdict = "YELLOW"
    else:
        verdict = "GREEN"
    flags.append("PROVISIONAL — stress-slice + per-validation-year MaxDD pending (round 2+)")
    return verdict, flags


def run_baseline(start: str, end: str, partition: str) -> dict:
    """Re-risk the production baseline (multi_factor conservative_default)
    over [start, end] via the checked-in run_backtest path."""
    with tempfile.TemporaryDirectory(prefix="rerisk_") as tmp:
        cmd = [
            PYTHON, str(PROJ / "scripts/run_backtest.py"),
            "--strategy", "multi_factor",
            "--start", start, "--end", end,
            "--no-walk-forward",
            "--output-dir", tmp,
        ]
        proc = subprocess.run(cmd, cwd=PROJ, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"run_backtest failed (exit {proc.returncode}):\n"
                f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
        reports = sorted(Path(tmp).glob("backtest/runs/*/master_report.md"))
        if not reports:
            raise RuntimeError("run_backtest produced no master_report.md")
        metrics = parse_master_report(reports[-1])
    return {
        "candidate_id": "production_baseline (multi_factor conservative_default)",
        "source": "config/production_strategy.yaml",
        "window": f"{start}..{end}",
        "partition": partition,
        "metrics": metrics,
        "reproduce_cmd": (
            f"python scripts/run_backtest.py --strategy multi_factor "
            f"--start {start} --end {end} --no-walk-forward"),
    }


def _load_pack() -> dict:
    if PACK_PATH.exists():
        return json.loads(PACK_PATH.read_text())
    return {
        "prd": "docs/prd/20260521-rerisk-and-ml-training-audit-prd.md",
        "workstream": "R0 — re-risk pack",
        "rows": [],
        "updated_utc": None,
    }


def _upsert_row(pack: dict, row: dict) -> None:
    """Replace any existing row with the same candidate_id + window."""
    key = (row["candidate_id"], row["window"])
    pack["rows"] = [r for r in pack["rows"]
                    if (r["candidate_id"], r["window"]) != key]
    pack["rows"].append(row)


def main() -> int:
    ap = argparse.ArgumentParser(description="R0 re-risk pack driver")
    ap.add_argument("--candidate", required=True,
                    choices=["baseline", "cycle06", "cycle08", "pead"])
    ap.add_argument("--start", default="2009-01-02")
    ap.add_argument("--end", default="2017-12-31")
    ap.add_argument("--partition", default="train_only",
                    help="temporal_split partition this window touches")
    args = ap.parse_args()

    if args.candidate != "baseline":
        print(f"[{args.candidate}] not wired yet — added in a later "
              f"ralph-loop round (R0 §6.1 candidates 2-4).")
        return 0

    print(f"=== R0 re-risk: baseline  window={args.start}..{args.end}  "
          f"partition={args.partition} ===")
    row = run_baseline(args.start, args.end, args.partition)
    row["verdict"], row["verdict_flags"] = _verdict(row)

    pack = _load_pack()
    _upsert_row(pack, row)
    pack["updated_utc"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    PACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    PACK_PATH.write_text(json.dumps(pack, indent=2, ensure_ascii=False))

    m = row["metrics"]
    print(f"  CAGR={m.get('cagr_pct')}%  Sharpe={m.get('sharpe')}  "
          f"MaxDD={m.get('max_dd_pct')}%  vol={m.get('ann_vol_pct')}%  "
          f"trades={m.get('n_trades')}")
    print(f"  verdict={row['verdict']}  flags={row['verdict_flags']}")
    print(f"  → {PACK_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
