from __future__ import annotations

from pathlib import Path

from core.research.account_deployment_risk import evaluate_account_deployment_risk
from core.research.qualification_v2 import canonical_sha256

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "config/research_governance.yaml"


def _evidence() -> dict:
    paths = {
        "gfc_2008": [0.01, -0.10, -0.08, 0.03, 0.04],
        "covid_2020": [0.01, -0.12, -0.05, 0.08],
        "rate_hike_2022": [0.01, -0.05, -0.04, 0.02],
    }
    return {
        "evidence_type": "daily_path_returns",
        "path_capable": True,
        "terminal_weighted_shock_only": False,
        "operating_max_drawdown_target": 0.18,
        "runtime_thresholds": {"alert": 0.15, "derisk": 0.20, "halt": 0.25},
        "next_session_execution_passed": True,
        "future_mutation_passed": True,
        "deterministic_replay_passed": True,
        "paper_replay_passed": True,
        "stress_path_returns": paths,
        "path_source_sha256": {
            name: canonical_sha256(values) for name, values in paths.items()
        },
    }


def test_complete_path_evidence_enters_risk_governed_paper_without_capital() -> None:
    result = evaluate_account_deployment_risk(_evidence(), governance_path=POLICY)
    assert result.absolute_risk_contract_passed is True
    assert result.status == "RISK_GOVERNED_PAPER_ELIGIBLE"
    assert result.capital_eligible is False


def test_missing_evidence_fails_closed_to_shadow() -> None:
    result = evaluate_account_deployment_risk(None, governance_path=POLICY)
    assert result.absolute_risk_contract_passed is False
    assert result.status == "SHADOW_PAPER_OBSERVATION"
    assert "account_risk_evidence_missing" in result.failed_checks


def test_terminal_shock_cannot_masquerade_as_path_maxdd() -> None:
    evidence = _evidence()
    evidence["terminal_weighted_shock_only"] = True
    result = evaluate_account_deployment_risk(evidence, governance_path=POLICY)
    assert result.status == "SHADOW_PAPER_OBSERVATION"
    assert "terminal_weighted_shock_cannot_pass_path_contract" in result.failed_checks


def test_one_stress_path_over_25pct_blocks_risk_governed_paper() -> None:
    evidence = _evidence()
    evidence["stress_path_returns"]["gfc_2008"] = [0.02, -0.30, 0.01]
    result = evaluate_account_deployment_risk(evidence, governance_path=POLICY)
    assert result.status == "SHADOW_PAPER_OBSERVATION"
    assert "account_risk_stress_maxdd:gfc_2008" in result.failed_checks


def test_operating_target_must_be_inside_15_20pct() -> None:
    evidence = _evidence()
    evidence["operating_max_drawdown_target"] = 0.25
    result = evaluate_account_deployment_risk(evidence, governance_path=POLICY)
    assert "account_risk_operating_target_outside_15_20pct" in result.failed_checks
