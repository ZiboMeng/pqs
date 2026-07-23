from __future__ import annotations

from pathlib import Path

import pytest

from core.data.pit_contract import (
    DirectionalComputeBlockedError,
    PitContractError,
    PitDataContract,
    guard_phase_a,
)

PROJECT = Path(__file__).resolve().parents[3]
CONTRACT = PROJECT / "config" / "pit_data_v1.yaml"


def test_frozen_phase_a_contract_loads_and_blocks_paid_and_directional_work():
    contract = PitDataContract.load(CONTRACT)
    assert contract.contract_id == "pqs-pit-data-v1"
    assert contract.directional_compute_enabled is False
    assert contract.paid_resource_creation_enabled is False
    contract.assert_operation_allowed("source_inventory")
    contract.assert_operation_allowed("feature_value_construction")
    with pytest.raises(DirectionalComputeBlockedError, match="forward_return"):
        contract.assert_operation_allowed("forward_return")


def test_unknown_operation_fails_closed():
    contract = PitDataContract.load(CONTRACT)
    with pytest.raises(DirectionalComputeBlockedError, match="not explicitly allowlisted"):
        contract.assert_operation_allowed("helpful_new_metric")


def test_phase_a_artifact_rejects_nested_directional_metrics():
    contract = PitDataContract.load(CONTRACT)
    contract.assert_artifact_non_directional(
        {"coverage": {"assets": 200}, "evidence_scope": contract.evidence_scope}
    )
    with pytest.raises(DirectionalComputeBlockedError, match="metrics.sharpe"):
        contract.assert_artifact_non_directional(
            {"coverage": {"assets": 200}, "metrics": {"sharpe": 1.2}}
        )


def test_guard_returns_contract_for_allowlisted_work():
    contract = guard_phase_a("readiness_evaluation", contract_path=CONTRACT)
    assert contract.schema_version == 1


def test_invalid_contract_cannot_turn_directional_compute_on(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
schema_version: 1
contract_id: bad
phase_a:
  evidence_scope: DATA_ENGINEERING_NO_DIRECTIONAL_RETURN
  directional_compute_enabled: true
  paid_resource_creation_enabled: false
  allowed_operations: [source_inventory]
  forbidden_operations: [forward_return]
  forbidden_artifact_keys: [return]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(PitContractError, match="must remain false"):
        PitDataContract.load(path)
