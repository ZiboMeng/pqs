from __future__ import annotations

from pathlib import Path

import pytest

from core.data.pit_contract import DirectionalComputeBlockedError, PitDataContract
from core.data.pit_readiness import (
    GateEvidence,
    PitReadinessError,
    evaluate_pit_readiness,
    verify_readiness_artifact,
)

PROJECT = Path(__file__).resolve().parents[3]
CONTRACT = PitDataContract.load(PROJECT / "config" / "pit_data_v1.yaml")


def _gates(passed: bool):
    return {
        gate_id: GateEvidence(
            gate_id=gate_id,
            passed=passed,
            status="PASS" if passed else "BLOCKED",
            evidence=("fixture",),
            details={"count": 1},
        )
        for gate_id in CONTRACT.raw["readiness"]["required_gate_ids"]
    }


def test_blocked_gate_keeps_phase_b_closed():
    artifact = evaluate_pit_readiness(
        _gates(False),
        contract=CONTRACT,
        bound_artifacts={},
        binding_raw_independent_n=60,
    )
    assert artifact["all_gates_pass"] is False
    assert artifact["phase_b_eligible"] is False
    assert artifact["phase_b_status"] == "BLOCKED"
    assert verify_readiness_artifact(artifact, contract=CONTRACT)[
        "integrity_pass"
    ]


def test_all_gates_alone_cannot_unlock_without_approved_historical_source():
    artifact = evaluate_pit_readiness(
        _gates(True), contract=CONTRACT, bound_artifacts={}
    )
    assert artifact["all_gates_pass"] is True
    assert artifact["formal_historical_source_unlocked"] is False
    assert artifact["phase_b_eligible"] is False


def test_gate_set_and_binding_n_fail_closed():
    gates = _gates(False)
    gates.pop("G12")
    with pytest.raises(PitReadinessError, match="missing"):
        evaluate_pit_readiness(gates, contract=CONTRACT, bound_artifacts={})
    with pytest.raises(PitReadinessError, match="cannot be reduced"):
        evaluate_pit_readiness(
            _gates(False),
            contract=CONTRACT,
            bound_artifacts={},
            binding_raw_independent_n=59,
        )


def test_directional_metric_cannot_enter_readiness_details():
    gates = _gates(False)
    gates["G1"] = GateEvidence(
        gate_id="G1",
        passed=False,
        status="BLOCKED",
        evidence=("fixture",),
        details={"sharpe": 1.0},
    )
    with pytest.raises(DirectionalComputeBlockedError, match="sharpe"):
        evaluate_pit_readiness(gates, contract=CONTRACT, bound_artifacts={})
