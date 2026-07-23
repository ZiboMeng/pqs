"""Machine-readable G1-G12 readiness evaluation for V6 PIT data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from core.data.pit_contract import PitDataContract


class PitReadinessError(ValueError):
    """Readiness evidence is incomplete or violates the frozen contract."""


@dataclass(frozen=True, slots=True)
class GateEvidence:
    gate_id: str
    passed: bool
    status: str
    evidence: tuple[str, ...]
    details: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.gate_id:
            raise PitReadinessError("gate_id is required")
        expected = "PASS" if self.passed else "BLOCKED"
        if self.status != expected:
            raise PitReadinessError(
                f"{self.gate_id}: status must be {expected} for passed={self.passed}"
            )


def evaluate_pit_readiness(
    gates: Mapping[str, GateEvidence],
    *,
    contract: PitDataContract,
    bound_artifacts: Mapping[str, Mapping[str, Any]],
    binding_raw_independent_n: int = 60,
) -> dict[str, Any]:
    contract.assert_operation_allowed("readiness_evaluation")
    required = tuple(contract.raw["readiness"]["required_gate_ids"])
    if set(gates) != set(required):
        missing = sorted(set(required) - set(gates))
        extra = sorted(set(gates) - set(required))
        raise PitReadinessError(
            f"readiness gates differ from contract; missing={missing}, extra={extra}"
        )
    if binding_raw_independent_n < int(
        contract.raw["phase_b"]["minimum_binding_raw_independent_n"]
    ):
        raise PitReadinessError("binding raw independent N cannot be reduced")
    gate_rows = [asdict(gates[gate_id]) for gate_id in required]
    all_pass = all(row["passed"] for row in gate_rows)
    historical = contract.raw["historical_sources"]
    formal_source_unlocked = bool(historical.get("formal_lane_unlocked")) and bool(
        historical.get("approved_source_ids")
    )
    phase_b_eligible = all_pass and formal_source_unlocked
    artifact = {
        "schema_version": 1,
        "readiness_id": "pqs-pit-readiness-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_id": contract.contract_id,
        "evidence_scope": contract.evidence_scope,
        "gates": gate_rows,
        "all_gates_pass": all_pass,
        "formal_historical_source_unlocked": formal_source_unlocked,
        "phase_b_eligible": phase_b_eligible,
        "phase_b_status": "ELIGIBLE" if phase_b_eligible else "BLOCKED",
        "binding_raw_independent_n": binding_raw_independent_n,
        "bound_artifacts": dict(bound_artifacts),
        "directional_compute_performed": False,
    }
    contract.assert_artifact_non_directional(artifact)
    return artifact


def verify_readiness_artifact(
    artifact: Mapping[str, Any], *, contract: PitDataContract
) -> dict[str, Any]:
    contract.assert_artifact_non_directional(artifact)
    required = tuple(contract.raw["readiness"]["required_gate_ids"])
    rows = artifact.get("gates")
    if not isinstance(rows, list):
        raise PitReadinessError("readiness gates must be a list")
    by_id = {str(row.get("gate_id")): row for row in rows}
    if set(by_id) != set(required) or len(rows) != len(required):
        raise PitReadinessError("readiness artifact gate IDs are incomplete/duplicated")
    recomputed_all = all(
        bool(by_id[gate_id].get("passed"))
        and by_id[gate_id].get("status") == "PASS"
        for gate_id in required
    )
    if bool(artifact.get("all_gates_pass")) != recomputed_all:
        raise PitReadinessError("all_gates_pass does not match gate evidence")
    formal_source = bool(artifact.get("formal_historical_source_unlocked"))
    recomputed_eligible = recomputed_all and formal_source
    if bool(artifact.get("phase_b_eligible")) != recomputed_eligible:
        raise PitReadinessError("phase_b_eligible does not match gate/source evidence")
    expected_status = "ELIGIBLE" if recomputed_eligible else "BLOCKED"
    if artifact.get("phase_b_status") != expected_status:
        raise PitReadinessError("phase_b_status is inconsistent")
    minimum_n = int(contract.raw["phase_b"]["minimum_binding_raw_independent_n"])
    if int(artifact.get("binding_raw_independent_n", -1)) < minimum_n:
        raise PitReadinessError("artifact improperly reduced binding raw N")
    return {
        "integrity_pass": True,
        "all_gates_pass": recomputed_all,
        "phase_b_eligible": recomputed_eligible,
        "phase_b_status": expected_status,
    }


__all__ = [
    "GateEvidence",
    "PitReadinessError",
    "evaluate_pit_readiness",
    "verify_readiness_artifact",
]
