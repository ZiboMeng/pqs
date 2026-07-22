from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from core.research.qualification_v3 import (
    QualificationV3Error,
    _annual_drawdown_comparison,
    recompute_qualification,
    validate_qualification_artifact,
)
from tests.unit.research._qualification_fixture import write_passing_qualification_v3

ROOT = Path(__file__).resolve().parents[3]
COMMIT = "a" * 40


def _fixture(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir(parents=True)
    shutil.copy(
        ROOT / "config/research_governance_v2.yaml",
        tmp_path / "config/research_governance.yaml",
    )
    return write_passing_qualification_v3(
        tmp_path, candidate_id="candidate-v3", code_commit=COMMIT
    )


def test_v3_requires_every_year_and_cost_scenario_to_beat_spy(tmp_path: Path) -> None:
    artifact = _fixture(tmp_path)
    result = validate_qualification_artifact(
        artifact,
        expected_candidate_id="candidate-v3",
        expected_code_commit=COMMIT,
        repo_root=tmp_path,
    )
    assert result.passed, result.failed_checks
    annual = result.recomputed["annual_drawdown_vs_spy"]
    assert annual["base"]["passed"] is True
    assert all(row["passed"] for row in annual["cost_stress"].values())
    assert result.recomputed["drawdown_policy"][
        "absolute_max_drawdown_gate_enabled"
    ] is False
    assert result.recomputed["overfit"]["cpcv"]["evidence_role"] == (
        "DEVELOPMENT_STABILITY_DIAGNOSTIC_NOT_OOS"
    )


def test_one_bad_calendar_year_fails_closed(tmp_path: Path) -> None:
    artifact = _fixture(tmp_path)
    document = json.loads(artifact.read_text())
    input_path = tmp_path / document["input_bundle"]["path"]
    bundle = json.loads(input_path.read_text())
    year = bundle["dates"][300][:4]
    index = next(i for i, value in enumerate(bundle["dates"]) if value.startswith(year))
    bundle["candidate_net_returns"][index] = -0.50
    for scenario in bundle["cost_stress_returns"].values():
        scenario[index] = -0.50
    computed = recompute_qualification(
        bundle,
        raw_independent_n=3,
        governance_path=tmp_path / "config/research_governance.yaml",
    )
    assert computed["gates"][
        "annual_max_drawdown_strictly_better_than_spy"
    ] is False
    assert computed["qualification_passed"] is False


def test_omitting_a_frozen_cost_scenario_fails_closed(tmp_path: Path) -> None:
    artifact = _fixture(tmp_path)
    document = json.loads(artifact.read_text())
    input_path = tmp_path / document["input_bundle"]["path"]
    bundle = json.loads(input_path.read_text())
    bundle["cost_stress_returns"].pop("triple_90bps")
    bundle["cost_stress_benchmark_returns"].pop("triple_90bps")
    with pytest.raises(QualificationV3Error, match="every frozen"):
        recompute_qualification(
            bundle,
            raw_independent_n=3,
            governance_path=tmp_path / "config/research_governance.yaml",
        )


def test_mutating_the_frozen_return_date_index_fails_closed(tmp_path: Path) -> None:
    artifact = _fixture(tmp_path)
    document = json.loads(artifact.read_text())
    input_path = tmp_path / document["input_bundle"]["path"]
    bundle = json.loads(input_path.read_text())
    dates = [date.fromisoformat(value) for value in bundle["dates"]]
    index = next(
        i
        for i in range(1, len(dates) - 1)
        if dates[i] + timedelta(days=1) < dates[i + 1]
    )
    dates[index] += timedelta(days=1)
    bundle["dates"] = [value.isoformat() for value in dates]
    with pytest.raises(QualificationV3Error, match="return-date index"):
        recompute_qualification(
            bundle,
            raw_independent_n=3,
            governance_path=tmp_path / "config/research_governance.yaml",
        )


def test_governance_or_evaluation_contract_drift_invalidates_v3(tmp_path: Path) -> None:
    artifact = _fixture(tmp_path)
    payload = json.loads(artifact.read_text())
    contract = tmp_path / payload["evaluation_contract"]["path"]
    contract.write_text("protocol_id: changed-after-freeze\n", encoding="utf-8")
    result = validate_qualification_artifact(
        artifact,
        expected_candidate_id="candidate-v3",
        repo_root=tmp_path,
    )
    assert not result.passed
    assert any("evaluation" in item or "unverifiable" in item for item in result.failed_checks)


def test_absolute_drawdown_over_25pct_can_pass_when_strictly_better_than_spy() -> None:
    dates = tuple(date(2024, 1, day) for day in range(2, 7))
    candidate = np.asarray([0.10, -0.30, 0.05, 0.05, 0.05])
    spy = np.asarray([0.10, -0.50, 0.05, 0.05, 0.05])
    result = _annual_drawdown_comparison(candidate, spy, dates)
    assert result["years"][0]["candidate_max_drawdown"] < -0.25
    assert result["passed"] is True


def test_equal_drawdown_does_not_count_as_strictly_better() -> None:
    dates = tuple(date(2024, 1, day) for day in range(2, 7))
    returns = np.asarray([0.01, -0.10, 0.02, 0.02, 0.02])
    result = _annual_drawdown_comparison(returns, returns.copy(), dates)
    assert result["passed"] is False
