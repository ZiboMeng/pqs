#!/usr/bin/env python
"""Workstream R0 — PEAD re-risk row.

PRD docs/prd/20260521-rerisk-and-ml-training-audit-prd.md §6.1 (#4):
re-risk the PEAD evidence candidate `pead_sue_trial1_evidence_v1`
(= trial1_short_hold, SUE>=1.5 hold=21 top_n=10) after the 2026-05-21
execution-kernel fixes.

PEAD is on an independent evidence-only track; its sanctioned Track-A
acceptance is `dev/scripts/pead/run_pead_track_a_acceptance.py`, which
must be re-run first (this driver reads its fresh output). This driver
then folds the `trial1_short_hold` result into the R0 re-risk pack and
compares it to the frozen evidence (PEAD's frozen evidence itself
records Track-A 14/17, overall NOT passed — it is an evidence-only
candidate, never claimed a full Track-A PASS).

Usage:
  python dev/scripts/pead/run_pead_track_a_acceptance.py   # first
  python dev/scripts/audit/rerisk_pead.py                  # then
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "dev/scripts/audit"))

from rerisk_pack import _load_pack, _upsert_row, PACK_PATH  # noqa: E402

VERDICT = PROJ / "data/audit/pead_path1_track_a_verdict.json"
FROZEN_N_GATES_PASSED = 14  # PEAD frozen evidence (pre-fix verdict / PRD §2.4)


def _pead_verdict(maxdd: float, n_passed: int, n_total: int) -> tuple[str, list]:
    """PRD §6.3 verdict for the PEAD row. PEAD is evidence-only and its
    frozen evidence already records Track-A 14/17 (not a full PASS), so
    matching ~14/17 is consistency, not a contradiction. RED only on a
    drawdown-cap breach or a material Track-A regression vs frozen."""
    flags: list[str] = []
    dd = abs(maxdd)
    if dd > 0.25:
        return "RED", [f"full-period MaxDD {dd:.1%} > 25% stress cap"]
    if n_passed < FROZEN_N_GATES_PASSED:
        flags.append(f"Track-A gates regressed post-fix: {n_passed}/{n_total} "
                     f"vs frozen {FROZEN_N_GATES_PASSED}/17")
        return ("RED" if dd > 0.20 else "YELLOW"), flags
    flags.append(f"Track-A {n_passed}/{n_total} — consistent with frozen "
                 f"evidence (evidence-only candidate; never claimed a full "
                 f"Track-A PASS — fails are aggregate excess vs SPY/QQQ)")
    flags.append(f"full-period MaxDD {dd:.1%} well within risk caps")
    return ("GREEN" if dd <= 0.20 else "YELLOW"), flags


def main() -> int:
    if not VERDICT.exists():
        raise RuntimeError(
            f"{VERDICT} not found — run "
            f"dev/scripts/pead/run_pead_track_a_acceptance.py first.")
    payload = json.loads(VERDICT.read_text())
    cands = {c["label"]: c for c in payload.get("candidates", [])}
    c = cands.get("trial1_short_hold")
    if c is None:
        raise RuntimeError("trial1_short_hold not in PEAD verdict json")

    perf = c["performance"]
    ta = c["track_a"]
    maxdd = float(perf["full_period_max_dd"])
    verdict, flags = _pead_verdict(
        maxdd, int(ta["n_gates_passed"]), int(ta["n_gates_total"]))

    row = {
        "candidate_id": "pead_sue_trial1_evidence_v1 (trial1_short_hold)",
        "source": ("data/research_candidates/pead_sue_trial1_evidence_v1.yaml"
                   " + data/audit/pead_path1_track_a_verdict.json"),
        "window": ("PEAD Track-A acceptance (independent evidence-only "
                   "track; run_pead_track_a_acceptance.py)"),
        "partition": "track_a_pead",
        "metrics": {
            "sharpe": float(perf["sharpe"]),
            "cagr_pct": float(perf["cagr"]) * 100.0,
            "max_dd_pct": maxdd * 100.0,
            "n_trades": int(perf.get("n_trades", 0)),
            "cost_2x_remains_positive": bool(
                perf.get("cost_2x_remains_positive", False)),
        },
        "track_a_passed": bool(ta["overall_passed"]),
        "track_a_n_gates": f"{ta['n_gates_passed']}/{ta['n_gates_total']}",
        "track_a_failed_gates": [g["name"] for g in ta.get("gates", [])
                                 if not g.get("passed", True)],
        "verdict": verdict,
        "verdict_flags": flags,
        "reproduce_cmd": ("python dev/scripts/pead/run_pead_track_a_acceptance.py"
                          " && python dev/scripts/audit/rerisk_pead.py"),
    }
    pack = _load_pack()
    _upsert_row(pack, row)
    pack["updated_utc"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    PACK_PATH.write_text(json.dumps(pack, indent=2, ensure_ascii=False))

    m = row["metrics"]
    print(f"=== R0 re-risk: PEAD trial1_short_hold ===")
    print(f"  Sharpe={m['sharpe']:.3f}  CAGR={m['cagr_pct']:.2f}%  "
          f"MaxDD={m['max_dd_pct']:.2f}%  2x-cost+={m['cost_2x_remains_positive']}")
    print(f"  Track-A {row['track_a_n_gates']} passed={row['track_a_passed']}")
    print(f"  verdict={verdict}  flags={flags}")
    print(f"  → {PACK_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
