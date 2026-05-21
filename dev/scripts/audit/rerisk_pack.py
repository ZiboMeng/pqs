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

import pandas as pd

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


REGIME_NAMES = {"BULL", "RISK_ON", "NEUTRAL", "CAUTIOUS", "RISK_OFF"}


def parse_regime_breakdown(txt: str) -> list[dict]:
    """Parse the §2 Regime 分层表现 table from a master_report.md."""
    m = re.search(r"## 2\. Regime.*?(?=\n## )", txt, re.S)
    if not m:
        return []
    rows: list[dict] = []
    for line in m.group(0).splitlines():
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) != 7 or cells[0] not in REGIME_NAMES:
            continue
        try:
            rows.append({
                "regime": cells[0],
                "days": int(_num(cells[1])),
                "cagr_pct": _num(cells[2]),
                "sharpe": _num(cells[3]),
                "max_dd_pct": _num(cells[4]),
                "vs_spy_pct": _num(cells[5]),
                "vs_qqq_pct": _num(cells[6]),
            })
        except ValueError:
            continue
    return rows


def parse_master_report(txt: str) -> dict:
    """Extract the §1 strategy + benchmark metrics from a master_report.md."""
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


def _maxdd(equity: pd.Series) -> float:
    """Max drawdown of an equity series (negative fraction)."""
    if equity.empty:
        return 0.0
    return float((equity / equity.cummax() - 1.0).min())


def _verdict(row: dict) -> tuple[str, list[str]]:
    """PRD §6.3 verdict.

    - `train_only`: provisional full-period MaxDD vs the 20%/25% caps.
    - `diagnostic`: validation-spanning sanity window (§6.5) —
      informational, NOT a candidate pass/fail gate.
    - `stress_slice:*`: designated stress-slice MaxDD vs the 25% cap
      (PRD Black Swan Quantification). Per Option A (user 2026-05-21)
      the slice is computed on a warmup+slice backtest whose warmup
      spans a validation year — informational stress-check, recorded
      with that caveat."""
    flags: list[str] = []
    m = row["metrics"]
    max_dd = abs(m.get("max_dd_pct", m.get("slice_max_dd_pct", 0.0))) / 100.0
    partition = row.get("partition", "")

    if partition.startswith("stress_slice:"):
        verdict = "RED" if max_dd > MAXDD_STRESS_CAP else "GREEN"
        cmp = ">" if max_dd > MAXDD_STRESS_CAP else "<="
        flags.append(f"stress-slice MaxDD {max_dd:.1%} {cmp} "
                     f"{MAXDD_STRESS_CAP:.0%} Black-Swan cap")
        flags.append("STRESS-SLICE (Option A) — warmup+slice backtest, "
                     "warmup spans a validation year; informational "
                     "MaxDD-sanity, NOT a candidate pass/fail gate")
        return verdict, flags

    if max_dd > MAXDD_STRESS_CAP:
        flags.append(f"full-period MaxDD {max_dd:.1%} > {MAXDD_STRESS_CAP:.0%} stress cap")
        verdict = "RED"
    elif max_dd > MAXDD_HARD_CAP:
        flags.append(f"full-period MaxDD {max_dd:.1%} > {MAXDD_HARD_CAP:.0%} hard cap")
        verdict = "YELLOW"
    else:
        verdict = "GREEN"
    if partition == "diagnostic":
        flags.append("DIAGNOSTIC WINDOW (validation-spanning, §6.5) — "
                     "informational regime-fragility evidence, NOT a "
                     "candidate pass/fail gate")
    else:
        flags.append("PROVISIONAL — per-validation-year MaxDD pending "
                     "(later round)")
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
        report_txt = reports[-1].read_text()
        metrics = parse_master_report(report_txt)
        regime = parse_regime_breakdown(report_txt)
    return {
        "candidate_id": "production_baseline (multi_factor conservative_default)",
        "source": "config/production_strategy.yaml",
        "window": f"{start}..{end}",
        "partition": partition,
        "metrics": metrics,
        "regime_breakdown": regime,
        "reproduce_cmd": (
            f"python scripts/run_backtest.py --strategy multi_factor "
            f"--start {start} --end {end} --no-walk-forward"),
    }


# Designated stress slices (config/temporal_split.yaml). `warmup` is
# ~280 trading days before the slice start (>= the 189d momentum
# lookback) so the strategy is fully positioned entering the slice.
STRESS_SLICES = {
    "covid_flash":    {"slice": ("2020-02-15", "2020-04-30"), "warmup": "2019-01-02"},
    "rate_hike_2022": {"slice": ("2022-08-15", "2022-10-15"), "warmup": "2021-07-01"},
}


def run_baseline_stress(name: str) -> dict:
    """Re-risk the baseline on a designated stress slice (Option A,
    user 2026-05-21): run a warmup+slice backtest, then compute MaxDD
    restricted to the slice dates from the dumped equity_curve.csv."""
    cfg = STRESS_SLICES[name]
    (s_start, s_end), warmup = cfg["slice"], cfg["warmup"]
    with tempfile.TemporaryDirectory(prefix="rerisk_") as tmp:
        cmd = [
            PYTHON, str(PROJ / "scripts/run_backtest.py"),
            "--strategy", "multi_factor",
            "--start", warmup, "--end", s_end,
            "--no-walk-forward", "--output-dir", tmp,
        ]
        proc = subprocess.run(cmd, cwd=PROJ, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"run_backtest failed (exit {proc.returncode}):\n"
                f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
        eqs = sorted(Path(tmp).glob("backtest/runs/*/equity_curve.csv"))
        if not eqs:
            raise RuntimeError("run_backtest produced no equity_curve.csv")
        eq = pd.read_csv(eqs[-1], index_col=0, parse_dates=True).iloc[:, 0]
    sl = eq.loc[s_start:s_end]
    slice_dd = _maxdd(sl)
    return {
        "candidate_id": "production_baseline (multi_factor conservative_default)",
        "source": "config/production_strategy.yaml",
        "window": f"stress slice {s_start}..{s_end} (backtest warmup from {warmup})",
        "partition": f"stress_slice:{name} (warmup {warmup}..{s_start} spans validation)",
        "metrics": {
            "slice_max_dd_pct": slice_dd * 100.0,
            "slice_n_days": int(len(sl)),
        },
        "reproduce_cmd": "python dev/scripts/audit/rerisk_pack.py --candidate baseline-stress",
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
                    choices=["baseline", "baseline-stress",
                             "cycle06", "cycle08", "pead"])
    ap.add_argument("--start", default="2009-01-02")
    ap.add_argument("--end", default="2017-12-31")
    ap.add_argument("--partition", default="train_only",
                    help="temporal_split partition this window touches")
    args = ap.parse_args()

    if args.candidate in ("cycle06", "cycle08", "pead"):
        print(f"[{args.candidate}] not handled by this driver — cycle06 "
              f"uses rerisk_cycle06.py; cycle08/pead added in later rounds.")
        return 0

    rows: list[dict] = []
    if args.candidate == "baseline":
        print(f"=== R0 re-risk: baseline  window={args.start}..{args.end}  "
              f"partition={args.partition} ===")
        rows.append(run_baseline(args.start, args.end, args.partition))
    else:  # baseline-stress
        for name in STRESS_SLICES:
            print(f"=== R0 re-risk: baseline stress slice '{name}' ===")
            rows.append(run_baseline_stress(name))

    pack = _load_pack()
    for row in rows:
        row["verdict"], row["verdict_flags"] = _verdict(row)
        _upsert_row(pack, row)
        m = row["metrics"]
        if "slice_max_dd_pct" in m:
            print(f"  slice MaxDD={m['slice_max_dd_pct']:.2f}%  "
                  f"n_days={m['slice_n_days']}  verdict={row['verdict']}")
        else:
            print(f"  CAGR={m.get('cagr_pct')}%  MaxDD={m.get('max_dd_pct')}%"
                  f"  vol={m.get('ann_vol_pct')}%  verdict={row['verdict']}")
        for f in row["verdict_flags"]:
            print(f"    - {f}")
    pack["updated_utc"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    PACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    PACK_PATH.write_text(json.dumps(pack, indent=2, ensure_ascii=False))
    print(f"  → {PACK_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
