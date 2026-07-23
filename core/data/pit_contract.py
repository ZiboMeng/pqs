"""V6 PIT data contract and Phase-A no-directional-compute guard.

Phase A is allowed to inspect raw values, coverage, missingness, identity and
temporal invariance.  It is deliberately not allowed to compute labels,
candidate returns, benchmark comparisons, IC, Sharpe or drawdown.  New Phase-A
entry points call this module before doing work and before writing artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

DEFAULT_CONTRACT_PATH = Path("config/pit_data_v1.yaml")


class PitContractError(ValueError):
    """The PIT contract is absent or internally inconsistent."""


class DirectionalComputeBlockedError(RuntimeError):
    """A Phase-A caller attempted a directionally informative operation."""


@dataclass(frozen=True, slots=True)
class PitDataContract:
    schema_version: int
    contract_id: str
    evidence_scope: str
    directional_compute_enabled: bool
    paid_resource_creation_enabled: bool
    allowed_operations: frozenset[str]
    forbidden_operations: frozenset[str]
    forbidden_artifact_keys: frozenset[str]
    raw: Mapping[str, Any]

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONTRACT_PATH) -> "PitDataContract":
        contract_path = Path(path)
        if not contract_path.exists():
            raise PitContractError(f"PIT contract does not exist: {contract_path}")
        payload = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise PitContractError("PIT contract root must be a mapping")
        phase_a = payload.get("phase_a")
        if not isinstance(phase_a, Mapping):
            raise PitContractError("PIT contract requires phase_a mapping")
        contract = cls(
            schema_version=int(payload.get("schema_version", 0)),
            contract_id=str(payload.get("contract_id", "")),
            evidence_scope=str(phase_a.get("evidence_scope", "")),
            directional_compute_enabled=bool(
                phase_a.get("directional_compute_enabled", True)
            ),
            paid_resource_creation_enabled=bool(
                phase_a.get("paid_resource_creation_enabled", True)
            ),
            allowed_operations=frozenset(
                str(value) for value in phase_a.get("allowed_operations", [])
            ),
            forbidden_operations=frozenset(
                str(value) for value in phase_a.get("forbidden_operations", [])
            ),
            forbidden_artifact_keys=frozenset(
                str(value).lower()
                for value in phase_a.get("forbidden_artifact_keys", [])
            ),
            raw=payload,
        )
        contract.validate()
        return contract

    def validate(self) -> None:
        if self.schema_version != 1:
            raise PitContractError("only PIT data contract schema_version=1 is supported")
        if not self.contract_id:
            raise PitContractError("contract_id is required")
        if self.evidence_scope != "DATA_ENGINEERING_NO_DIRECTIONAL_RETURN":
            raise PitContractError("Phase A must use no-directional-return evidence scope")
        if self.directional_compute_enabled:
            raise PitContractError("Phase A directional_compute_enabled must remain false")
        if self.paid_resource_creation_enabled:
            raise PitContractError("Phase A cannot create paid resources")
        overlap = self.allowed_operations & self.forbidden_operations
        if overlap:
            raise PitContractError(
                f"operations cannot be both allowed and forbidden: {sorted(overlap)}"
            )
        if not self.allowed_operations or not self.forbidden_operations:
            raise PitContractError("allowed and forbidden operation sets cannot be empty")

    def assert_operation_allowed(self, operation: str) -> None:
        normalized = str(operation).strip().lower()
        if normalized in self.forbidden_operations:
            raise DirectionalComputeBlockedError(
                f"Phase A forbids directional operation {normalized!r}"
            )
        if normalized not in self.allowed_operations:
            raise DirectionalComputeBlockedError(
                f"Phase A operation {normalized!r} is not explicitly allowlisted"
            )

    def assert_artifact_non_directional(self, artifact: Mapping[str, Any]) -> None:
        hits: list[str] = []

        def visit(value: Any, prefix: str) -> None:
            if isinstance(value, Mapping):
                for raw_key, nested in value.items():
                    key = str(raw_key).strip().lower()
                    path = f"{prefix}.{key}" if prefix else key
                    if key in self.forbidden_artifact_keys:
                        hits.append(path)
                    visit(nested, path)
            elif isinstance(value, list):
                for index, nested in enumerate(value):
                    visit(nested, f"{prefix}[{index}]")

        visit(artifact, "")
        if hits:
            raise DirectionalComputeBlockedError(
                "Phase A artifact contains forbidden directional keys: "
                + ", ".join(sorted(hits))
            )


def guard_phase_a(
    operation: str,
    *,
    artifact: Mapping[str, Any] | None = None,
    contract_path: str | Path = DEFAULT_CONTRACT_PATH,
) -> PitDataContract:
    """Load the frozen contract and enforce one Phase-A operation."""

    contract = PitDataContract.load(contract_path)
    contract.assert_operation_allowed(operation)
    if artifact is not None:
        contract.assert_artifact_non_directional(artifact)
    return contract


__all__ = [
    "DEFAULT_CONTRACT_PATH",
    "DirectionalComputeBlockedError",
    "PitContractError",
    "PitDataContract",
    "guard_phase_a",
]
