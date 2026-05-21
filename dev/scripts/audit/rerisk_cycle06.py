#!/usr/bin/env python
"""Workstream R0 — cycle06 re-risk row (exact frozen-spec replay).

PRD docs/prd/20260521-rerisk-and-ml-training-audit-prd.md §6.1 (#2) +
§2.2: cycle06 must be re-risked against the EXACT frozen spec
`cycle06_31af04cf2ff9_evidence_v1`, NOT a lineage top-1 lookup (the
defect §2.2 flagged). This driver loads the frozen yaml's feature_set
verbatim and reuses the sanctioned cycle06 Track-A evaluation
(`_eval_trial` on the selector panel — for a research candidate the
Track-A stage is the sanctioned selector stage, so train+validation
panel access is correct here, unlike the production baseline).

Writes the cycle06 row into data/audit/rerisk_pack_20260521.json and
the full eval into data/audit/rerisk_cycle06_eval.json.

Usage: python dev/scripts/audit/rerisk_cycle06.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "dev/scripts/cycle06"))
sys.path.insert(0, str(PROJ / "dev/scripts/audit"))

import yaml  # noqa: E402

from cycle06_track_a_eval import _load_panel, _eval_trial  # noqa: E402
from rerisk_pack import _load_pack, _upsert_row, PACK_PATH  # noqa: E402

FROZEN = PROJ / "data/research_candidates/cycle06_31af04cf2ff9_evidence_v1.yaml"
EVAL_CACHE = PROJ / "data/audit/rerisk_cycle06_eval.json"


def _cycle06_verdict(per_year: dict, stress: dict, track_a_passed: bool,
                     failed_gates: list) -> tuple[str, list[str]]:
    """PRD §6.3 verdict for the cycle06 row. RED if drawdown gates fail
    OR the result materially contradicts the frozen evidence (a Track-A
    PASS→FAIL flip is a material contradiction). Flags separate a true
    drawdown regression from an alpha-gate (vs-SPY) failure — non-blanket
    per `feedback_no_blanket_failure_verdict`."""
    flags: list[str] = []
    worst_year = max((abs(v) for v in per_year.values()), default=0.0)
    worst_stress = max((abs(v) for v in stress.values()), default=0.0)
    dd_ok = worst_year <= 0.20 and worst_stress <= 0.25
    if dd_ok:
        flags.append(f"drawdown stable vs frozen evidence — per-year MaxDD "
                     f"≤20% (worst {worst_year:.1%}), stress ≤25% "
                     f"(worst {worst_stress:.1%})")
    else:
        flags.append(f"drawdown gate breach — worst per-year {worst_year:.1%}"
                     f" / stress {worst_stress:.1%}")
    if not track_a_passed:
        flags.append(f"Track-A re-risk FAIL ({', '.join(failed_gates)}) — "
                     f"contradicts frozen `track_a_acceptance: PASS`; this "
                     f"is an alpha-gate (vs-SPY) failure, NOT a drawdown "
                     f"regression")
        return "RED", flags
    return ("GREEN" if dd_ok else "YELLOW"), flags


def main() -> int:
    spec = yaml.safe_load(FROZEN.read_text())
    feats = [f["name"] for f in spec["feature_set"]]
    weights = [float(f["weight"]) for f in spec["feature_set"]]
    cadence = spec["construction"]["rebalance_cadence"]
    print(f"=== R0 re-risk: cycle06 (exact frozen spec) ===")
    print(f"  features={feats}  weights={weights}  cadence={cadence}")

    reuse = "--reuse-eval" in sys.argv and EVAL_CACHE.exists()
    if reuse:
        print(f"  reusing cached eval: {EVAL_CACHE}")
        ev = json.loads(EVAL_CACHE.read_text())
    else:
        trial_row = {
            "features": ",".join(feats),
            "weights_csv": ",".join(str(w) for w in weights),
            "holding_freq": cadence,
        }
        panel, factors, mask, split_cfg = _load_panel()
        ev = _eval_trial(trial_row, panel, factors, mask, split_cfg)
        if ev.get("error"):
            raise RuntimeError(f"cycle06 eval error: {ev['error']}")
        EVAL_CACHE.write_text(json.dumps(ev, indent=2, default=str))

    # Frozen-evidence comparison (PRD §6.3: "no new catastrophic
    # regression vs frozen evidence").
    rs = spec.get("robustness_summary", {})
    per_year_maxdd = {int(y): float(m.get("max_dd", 0.0))
                      for y, m in ev["metrics_per_year"].items()}
    stress_maxdd = {k: float(v.get("max_dd", 0.0))
                    for k, v in ev["metrics_per_stress"].items()}
    verdict, verdict_flags = _cycle06_verdict(
        per_year_maxdd, stress_maxdd,
        ev["track_a_overall_passed"], ev["track_a_failed_gates"])

    row = {
        "candidate_id": "cycle06_31af04cf2ff9_evidence_v1",
        "source": ("data/research_candidates/"
                   "cycle06_31af04cf2ff9_evidence_v1.yaml (exact frozen spec)"),
        "window": ("Track-A selector panel (train+validation) — sanctioned "
                   "for a research candidate's Track-A stage"),
        "partition": "track_a_selector",
        "metrics": dict(ev["metrics_full_period"]),
        "per_validation_year_maxdd": per_year_maxdd,
        "stress_slice_maxdd": stress_maxdd,
        "concentration": ev["concentration"],
        "n_observed_days": ev["n_observed_days"],
        "track_a_passed": ev["track_a_overall_passed"],
        "track_a_failed_gates": ev["track_a_failed_gates"],
        "verdict": verdict,
        "verdict_flags": verdict_flags,
        "frozen_evidence_compare": {
            "frozen_covid_flash_maxdd": rs.get("stress_covid_flash_maxdd"),
            "frozen_rate_hike_2022_maxdd": rs.get("stress_rate_hike_2022_maxdd"),
            "frozen_per_year_maxdd_max": rs.get("per_year_maxdd_max"),
            "frozen_track_a": spec.get("research_evidence", {}).get(
                "track_a_acceptance"),
        },
        "reproduce_cmd": "python dev/scripts/audit/rerisk_cycle06.py",
    }
    pack = _load_pack()
    _upsert_row(pack, row)
    from datetime import datetime, timezone
    pack["updated_utc"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    PACK_PATH.write_text(json.dumps(pack, indent=2, ensure_ascii=False))

    print(f"  verdict={verdict}  flags={verdict_flags}")
    print(f"  track_a_passed={row['track_a_passed']}  "
          f"failed_gates={row['track_a_failed_gates']}")
    print(f"  per-year MaxDD: {per_year_maxdd}")
    print(f"  stress MaxDD:   {stress_maxdd}")
    print(f"  → {PACK_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
