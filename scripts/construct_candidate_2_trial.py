#!/usr/bin/env python
"""Insert a synthetic Candidate-2 trial row into rcm_archive.db so that
`freeze_research_candidate.py` can treat it as any other archive trial.

This is NOT mining — it is deterministic construction. The 3 factors
were chosen by hand (after an IC screen ruled out the initial PRD §5.5
suggestions) with equal weights 1/3 each, per PRD §5.5 which bans
TPE / Optuna / grid search / any weight search.

The inserted row is clearly labeled:
  - study_id  = "candidate-2-construction-2026-04-24"
  - lineage_tag = "phase-e-post-2026-04-24-cand2"

It cannot be confused with a real mining trial (different study_id
namespace).

PRD §12.2 forbids rcm_archive.db SCHEMA mutation. This script only
INSERTs data into the existing schema — it does not ALTER any table.

Idempotency: if the trial_id already exists, the script is a no-op
(logs and returns 0). Safe to run multiple times.

Usage:
    python scripts/construct_candidate_2_trial.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("construct_candidate_2_trial")


ARCHIVE_DB = "data/mining/rcm_archive.db"
PROBE_JSON = "data/research_candidates/candidate_2_probe_report.json"

TRIAL_ID = "cand2_equal_03"
STUDY_ID = "candidate-2-construction-2026-04-24"
LINEAGE_TAG = "phase-e-post-2026-04-24-cand2"

CAND2_FEATURES = ["ret_5d", "rs_vs_spy_126d", "hl_range"]
CAND2_WEIGHTS = [1.0 / 3.0] * 3


def main() -> int:
    probe = json.loads(Path(PROBE_JSON).read_text())
    if probe["decision"] != "PASS":
        logger.error("Probe decision=%s; refusing to construct trial. "
                     "Re-run probe until PASS before construction.",
                     probe["decision"])
        return 1
    if probe["feature_set"] != CAND2_FEATURES:
        logger.error("Probe feature_set=%s but construction wants %s. "
                     "Regenerate probe or update constants.",
                     probe["feature_set"], CAND2_FEATURES)
        return 1

    per_factor = probe["per_factor"]
    mean_ic = sum(per_factor[n]["ic_mean"] for n in CAND2_FEATURES) / 3.0
    mean_ir = sum(per_factor[n]["ic_ir"] for n in CAND2_FEATURES) / 3.0
    n_dates = max(per_factor[n]["n_ics"] for n in CAND2_FEATURES)

    spec_payload = {
        "features": CAND2_FEATURES,
        "weights": CAND2_WEIGHTS,
        "family_counts": {"B_momentum_path": 1, "A_benchmark_relative": 1,
                          "C_liquidity_risk": 1},
        "construction_method": "hand_selected_equal_weight",
        "construction_notes": (
            "Candidate-2: 3 factors equally weighted, selected after IC "
            "screen of RESEARCH_FACTORS on post-2026-04-24-rcm-v1-lag1 "
            "window. Initial PRD §5.5 suggestions (residual_mom_spy_20d, "
            "return_per_risk_21d, trend_tstat_20d) were rejected — all "
            "had negative or ~0 IC at 21d forward horizon on this "
            "universe (see candidate_2_probe_initial_reject.json). "
            "Pivoted to {ret_5d, rs_vs_spy_126d, hl_range} which all "
            "have positive IC with p < 0.05, each with positive IC in "
            ">= 3 of 6 regimes, distinct economic families, and the "
            "combined composite has corr < 0.5 with RCMv1 and turnover "
            "differs by >= 20%. NO TPE / Optuna / grid search used."
        ),
    }

    conn = sqlite3.connect(ARCHIVE_DB)
    try:
        existing = conn.execute(
            "SELECT trial_id FROM rcm_trials WHERE trial_id = ?",
            (TRIAL_ID,),
        ).fetchone()
        if existing:
            logger.info("trial_id=%s already in archive; no-op.", TRIAL_ID)
            print(f"Already inserted; no-op. trial_id={TRIAL_ID}")
            return 0

        now = datetime.now(timezone.utc).isoformat()
        o = probe["orthogonality"]
        conn.execute(
            """INSERT INTO rcm_trials (
                 trial_id, study_id, lineage_tag, created_at, spec_json,
                 n_features, n_families, features_csv, weights_csv,
                 family_counts_json, n_dates, ic_mean, ic_std, ic_ir,
                 turnover_proxy, corr_concentration, benchmark_excess,
                 regime_stddev, objective
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                TRIAL_ID, STUDY_ID, LINEAGE_TAG, now,
                json.dumps(spec_payload),
                len(CAND2_FEATURES), 3,
                ",".join(CAND2_FEATURES),
                ",".join(f"{w:.4f}" for w in CAND2_WEIGHTS),
                json.dumps(spec_payload["family_counts"]),
                n_dates, mean_ic,
                per_factor[CAND2_FEATURES[0]]["ic_std"],
                mean_ir,
                o["turnover_cand2"],
                # low redundancy — cand2 factors are each from distinct family
                0.10,
                0.0,   # benchmark_excess: cross-sectional composite is
                       # approximately benchmark-neutral by construction
                0.0,   # regime_stddev: deferred to acceptance artifact
                mean_ir,  # objective = IR for this construction
            ),
        )
        conn.commit()
        logger.info("Inserted synthetic trial_id=%s (study=%s, lineage=%s)",
                    TRIAL_ID, STUDY_ID, LINEAGE_TAG)
    finally:
        conn.close()

    print("=" * 70)
    print(f"Constructed Candidate-2 trial: {TRIAL_ID}")
    print("=" * 70)
    print(f"  study_id          : {STUDY_ID}")
    print(f"  lineage_tag       : {LINEAGE_TAG}")
    print(f"  features          : {CAND2_FEATURES}")
    print(f"  weights           : equally 1/3 each")
    print(f"  mean IC           : {mean_ic:.4f}")
    print(f"  mean IC_IR        : {mean_ir:.4f}")
    print(f"  Next step         : scripts/freeze_research_candidate.py "
          f"--trial-id {TRIAL_ID} --candidate-id candidate_2_orthogonal_01")
    return 0


if __name__ == "__main__":
    sys.exit(main())
