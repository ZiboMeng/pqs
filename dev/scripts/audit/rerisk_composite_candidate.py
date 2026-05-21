#!/usr/bin/env python
"""Workstream R0 — composite-candidate re-risk row (exact frozen-spec replay).

PRD docs/prd/20260521-rerisk-and-ml-training-audit-prd.md §6.1 + §2.2:
cycle06 / cycle08 must be re-risked against their EXACT frozen spec,
NOT a lineage top-1 lookup (the defect §2.2 flagged). This driver loads
a frozen candidate yaml's feature_set verbatim and reuses the
sanctioned cycle Track-A evaluation (`_eval_trial` on the selector
panel — for a research candidate the Track-A stage is the sanctioned
selector stage, so train+validation panel access is correct here,
unlike the production baseline).

Writes the candidate row into data/audit/rerisk_pack_20260521.json and
the full eval into data/audit/rerisk_<candidate>_eval.json.

Usage:
  python dev/scripts/audit/rerisk_composite_candidate.py --candidate cycle06
  python dev/scripts/audit/rerisk_composite_candidate.py --candidate cycle08
  (add --reuse-eval to reuse a cached eval json)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "dev/scripts/cycle06"))
sys.path.insert(0, str(PROJ / "dev/scripts/audit"))

import yaml  # noqa: E402

from cycle06_track_a_eval import _load_panel, _eval_trial  # noqa: E402
from rerisk_pack import _load_pack, _upsert_row, PACK_PATH  # noqa: E402

CANDIDATES = {
    "cycle06": "cycle06_31af04cf2ff9_evidence_v1",
    "cycle08": "cycle08_3f40e3f4ed1a_evidence_v1",
}


def _composite_verdict(per_year: dict, stress: dict, track_a_passed: bool,
                       failed_gates: list) -> tuple[str, list[str]]:
    """PRD §6.3 verdict for a composite-candidate row. RED if drawdown
    gates fail OR the result materially contradicts the frozen evidence
    (a Track-A PASS→FAIL flip is a material contradiction). Flags
    separate a true drawdown regression from an alpha-gate (vs-SPY)
    failure — non-blanket per `feedback_no_blanket_failure_verdict`."""
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
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--candidate", required=True, choices=list(CANDIDATES))
    ap.add_argument("--reuse-eval", action="store_true")
    args = ap.parse_args()

    cand_id = CANDIDATES[args.candidate]
    frozen = PROJ / f"data/research_candidates/{cand_id}.yaml"
    eval_cache = PROJ / f"data/audit/rerisk_{args.candidate}_eval.json"

    spec = yaml.safe_load(frozen.read_text())
    feats = [f["name"] for f in spec["feature_set"]]
    weights = [float(f["weight"]) for f in spec["feature_set"]]
    cadence = spec["construction"]["rebalance_cadence"]
    print(f"=== R0 re-risk: {args.candidate} (exact frozen spec) ===")
    print(f"  features={feats}  weights={weights}  cadence={cadence}")

    if args.reuse_eval and eval_cache.exists():
        print(f"  reusing cached eval: {eval_cache}")
        ev = json.loads(eval_cache.read_text())
    else:
        trial_row = {
            "features": ",".join(feats),
            "weights_csv": ",".join(str(w) for w in weights),
            "holding_freq": cadence,
        }
        panel, factors, mask, split_cfg = _load_panel()
        ev = _eval_trial(trial_row, panel, factors, mask, split_cfg)
        if ev.get("error"):
            raise RuntimeError(f"{args.candidate} eval error: {ev['error']}")
        eval_cache.write_text(json.dumps(ev, indent=2, default=str))

    # Frozen-evidence comparison (PRD §6.3: "no new catastrophic
    # regression vs frozen evidence").
    rs = spec.get("robustness_summary", {})
    per_year_maxdd = {int(y): float(m.get("max_dd", 0.0))
                      for y, m in ev["metrics_per_year"].items()}
    stress_maxdd = {k: float(v.get("max_dd", 0.0))
                    for k, v in ev["metrics_per_stress"].items()}
    verdict, verdict_flags = _composite_verdict(
        per_year_maxdd, stress_maxdd,
        ev["track_a_overall_passed"], ev["track_a_failed_gates"])

    row = {
        "candidate_id": cand_id,
        "source": (f"data/research_candidates/{cand_id}.yaml "
                   f"(exact frozen spec)"),
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
        "reproduce_cmd": (f"python dev/scripts/audit/rerisk_composite_candidate.py "
                          f"--candidate {args.candidate}"),
    }
    pack = _load_pack()
    _upsert_row(pack, row)
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
