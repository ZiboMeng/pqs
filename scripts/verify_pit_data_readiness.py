#!/usr/bin/env python3
"""Independently verify V6 PIT readiness structure and bound artifact hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from core.data.pit_contract import PitDataContract  # noqa: E402
from core.data.pit_readiness import verify_readiness_artifact  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default="config/pit_data_v1.yaml")
    parser.add_argument(
        "--readiness", default="research/data_readiness/pit_v1/readiness.json"
    )
    args = parser.parse_args()
    contract = PitDataContract.load(args.contract)
    artifact = json.loads(Path(args.readiness).read_text(encoding="utf-8"))
    verified = verify_readiness_artifact(artifact, contract=contract)
    for artifact_id, binding in artifact.get("bound_artifacts", {}).items():
        path = Path(binding["path"])
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != binding["sha256"]:
            raise RuntimeError(f"bound artifact hash mismatch: {artifact_id}")
    print("integrity_pass=true")
    print(f"all_gates_pass={str(verified['all_gates_pass']).lower()}")
    print(f"phase_b_eligible={str(verified['phase_b_eligible']).lower()}")
    print(f"phase_b_status={verified['phase_b_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
