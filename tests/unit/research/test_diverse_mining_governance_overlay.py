from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np

from core.research.qualification_v2 import sha256_file
from core.research.qualification_v3 import _annual_drawdown_comparison

ROOT = Path(__file__).resolve().parents[3]
OVERLAY = ROOT / "research/results/governance/diverse_mining_v1_review_hold.json"


def test_legacy_review_hold_is_non_promoting_and_annual_failures_recompute() -> None:
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    source = ROOT / overlay["source_report"]["path"]
    assert sha256_file(source) == overlay["source_report"]["sha256"]
    assert overlay["status"] == "REVIEW_HOLD_EXPLORATORY_NOT_FORMAL"
    assert overlay["paper_eligible"] is False
    assert overlay["automatic_promotion_eligible"] is False
    assert overlay["current_governance"]["required_qualification_schema"] == 3

    for candidate in overlay["candidates"]:
        qualification_path = ROOT / candidate["qualification_path"]
        assert sha256_file(qualification_path) == candidate["qualification_sha256"]
        qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
        bundle_path = ROOT / qualification["input_bundle"]["path"]
        assert sha256_file(bundle_path) == qualification["input_bundle"]["sha256"]
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        comparison = _annual_drawdown_comparison(
            np.asarray(bundle["candidate_net_returns"], dtype=float),
            np.asarray(bundle["benchmark_total_returns"], dtype=float),
            tuple(date.fromisoformat(value) for value in bundle["dates"]),
        )
        recorded = candidate["current_annual_drawdown_base_assessment"]
        assert comparison["passed"] is False
        assert comparison["failed_years"] == recorded["failed_years"]
        assert [
            row["year"] for row in comparison["years"] if row["passed"]
        ] == recorded["passed_years"]
        assert recorded["cost_stress_scenarios_assessed"] is False
