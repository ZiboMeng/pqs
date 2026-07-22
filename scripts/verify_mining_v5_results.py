#!/usr/bin/env python3
"""Independently verify a completed Mining V5 report and every V4 artifact."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.research.qualification_v2 import sha256_file  # noqa: E402
from core.research.qualification_v4 import validate_qualification_artifact  # noqa: E402
from core.research.trial_ledger import AppendOnlyTrialLedger  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        default=(
            "research/results/mining_v5_balanced_20260722_v1/"
            "campaign_report.json"
        ),
    )
    args = parser.parse_args()
    report_path = Path(args.report)
    report_path = report_path if report_path.is_absolute() else ROOT / report_path
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("rounds_consumed") != 30:
        raise RuntimeError("campaign did not consume the preregistered 30 rounds")
    if len(report.get("round_results") or []) != 30:
        raise RuntimeError("campaign report does not contain all 30 rows")
    ledger_path = report_path.parent / "trial_ledger.jsonl"
    snapshot = AppendOnlyTrialLedger(ledger_path).snapshot()
    if snapshot != report.get("ledger"):
        raise RuntimeError("campaign ledger snapshot drifted")
    if snapshot["raw_independent_n"] != 30 or snapshot["incomplete_trial_ids"]:
        raise RuntimeError("campaign ledger is not complete raw-N=30")
    benchmark = report["canonical_benchmark"]
    benchmark_path = ROOT / benchmark["path"]
    if sha256_file(benchmark_path) != benchmark["sha256"]:
        raise RuntimeError("canonical benchmark binding drifted")

    integrity_valid = 0
    gate_passed = 0
    for row in report.get("qualifications") or []:
        artifact_path = ROOT / row["qualification_path"]
        if sha256_file(artifact_path) != row["qualification_sha256"]:
            raise RuntimeError(f"qualification hash drifted: {row['candidate_id']}")
        validation = validate_qualification_artifact(
            artifact_path,
            expected_candidate_id=row["candidate_id"],
            expected_code_commit=report["code_commit"],
            repo_root=ROOT,
        )
        non_gate_failures = [
            item for item in validation.failed_checks
            if item != "qualification_canonical_gates_failed"
        ]
        if non_gate_failures:
            raise RuntimeError(
                f"qualification integrity failed {row['candidate_id']}: "
                + ",".join(non_gate_failures)
            )
        integrity_valid += 1
        canonical_pass = validation.recomputed.get(
            "research_qualification_passed"
        ) is True
        if canonical_pass != bool(row["research_qualification_passed"]):
            raise RuntimeError(f"qualification summary drifted: {row['candidate_id']}")
        if canonical_pass:
            gate_passed += 1
        if validation.recomputed.get("capital_eligible") is not False:
            raise RuntimeError("V5 artifact acquired forbidden capital authority")
    if gate_passed != report.get("formal_candidate_count"):
        raise RuntimeError("formal candidate count differs from recomputation")
    if report.get("capital_eligible") is not False:
        raise RuntimeError("campaign acquired forbidden capital authority")
    print(f"report_sha256={sha256_file(report_path)}")
    print(f"ledger_raw_independent_n={snapshot['raw_independent_n']}")
    print(f"composite_raw_independent_n={report['composite_raw_independent_n']}")
    print(f"qualification_artifacts_integrity_valid={integrity_valid}")
    print(f"formal_candidate_count={gate_passed}")
    print("verification=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
