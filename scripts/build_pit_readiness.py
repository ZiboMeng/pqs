#!/usr/bin/env python3
"""Build the current fail-closed V6 PIT G1-G12 readiness artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from core.data.pit_contract import PitDataContract  # noqa: E402
from core.data.pit_readiness import GateEvidence, evaluate_pit_readiness  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _blocked(gate_id: str, reason: str, *evidence: str) -> GateEvidence:
    return GateEvidence(
        gate_id=gate_id,
        passed=False,
        status="BLOCKED",
        evidence=tuple(evidence),
        details={"reason": reason},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default="config/pit_data_v1.yaml")
    parser.add_argument(
        "--inventory",
        default="research/data_readiness/pit_v1/source_inventory.json",
    )
    parser.add_argument(
        "--prospective",
        default="research/data_readiness/pit_v1/prospective_latest.json",
    )
    parser.add_argument(
        "--norgate-validation",
        default="research/data_readiness/pit_v1/norgate_trial_validation.json",
    )
    parser.add_argument(
        "--output", default="research/data_readiness/pit_v1/readiness.json"
    )
    args = parser.parse_args()
    contract = PitDataContract.load(args.contract)
    inventory_path = Path(args.inventory)
    prospective_path = Path(args.prospective)
    norgate_validation_path = Path(args.norgate_validation)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    prospective = json.loads(prospective_path.read_text(encoding="utf-8"))
    norgate_validation = json.loads(
        norgate_validation_path.read_text(encoding="utf-8")
    )
    contract.assert_artifact_non_directional(inventory)
    contract.assert_artifact_non_directional(prospective)
    contract.assert_artifact_non_directional(norgate_validation)

    source_status = inventory["historical_source_assessment"]["status"]
    gates = {
        "G1": _blocked(
            "G1",
            "Norgate documents an unchanging assetid, but the trial is not connected and dated ticker/name alias intervals are not documented",
            str(inventory_path),
            str(norgate_validation_path),
        ),
        "G2": _blocked(
            "G2",
            "formal historical universe has not been reconstructed; the free trial is limited to two years and cannot establish 2012-2024 coverage",
            str(inventory_path),
            str(norgate_validation_path),
        ),
        "G3": _blocked(
            "G3",
            "Norgate's public Python interface does not document source-bound delisting reason, consideration or disposition amount",
            str(inventory_path),
            str(norgate_validation_path),
        ),
        "G4": _blocked(
            "G4",
            "formal action/delisting parity is absent; local split coverage is missing and Norgate documents a binary capital-event indicator rather than a complete event ledger",
            str(inventory_path),
            str(norgate_validation_path),
        ),
        "G5": _blocked(
            "G5",
            "no filing-level accession/context/unit formal fact panel",
            "core/data/pit_fundamentals.py",
        ),
        "G6": _blocked(
            "G6",
            "acceptance-to-next-session code exists but no complete formal fact/document panel has been certified",
            "core/data/pit_fundamentals.py",
        ),
        "G7": _blocked(
            "G7",
            "unit prefix/amendment tests pass but full-source vintage replay is not available",
            "tests/unit/data/test_pit_fundamentals.py",
        ),
        "G8": _blocked(
            "G8",
            "existing immutable body corpus is 8-K; V6 requires historical-set 10-K/10-Q bodies and parser coverage",
            str(inventory_path),
        ),
        "G9": _blocked(
            "G9",
            "no formal 2012-2024 rebalance-level eligible-asset coverage panel",
            "core/data/pit_security_master.py",
        ),
        "G10": _blocked(
            "G10",
            "no formal rule-feature coverage panel",
            "config/pit_data_v1.yaml",
        ),
        "G11": _blocked(
            "G11",
            "unit temporal tests exist but full identity/action/fact/document source suite has not passed",
            "tests/unit/data/test_pit_security_master.py",
            "tests/unit/data/test_pit_fundamentals.py",
        ),
        "G12": _blocked(
            "G12",
            "prospective snapshot is hash-bound, but Norgate trial/runtime has no verified immutable historical edition or replay contract",
            str(prospective_path),
            str(norgate_validation_path),
        ),
    }
    bound = {
        "contract": {"path": args.contract, "sha256": _sha256(Path(args.contract))},
        "source_inventory": {
            "path": str(inventory_path),
            "sha256": _sha256(inventory_path),
        },
        "prospective_snapshot": {
            "path": str(prospective_path),
            "sha256": _sha256(prospective_path),
        },
        "norgate_trial_validation": {
            "path": str(norgate_validation_path),
            "sha256": _sha256(norgate_validation_path),
        },
    }
    artifact = evaluate_pit_readiness(
        gates,
        contract=contract,
        bound_artifacts=bound,
        binding_raw_independent_n=60,
    )
    artifact["historical_source_status"] = source_status
    contract.assert_artifact_non_directional(artifact)
    _atomic_json(artifact, Path(args.output))
    print(f"pit_readiness={args.output}")
    print(f"phase_b_status={artifact['phase_b_status']}")
    print(f"blocked_gates={sum(not gate['passed'] for gate in artifact['gates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
