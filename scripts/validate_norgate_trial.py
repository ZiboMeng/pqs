#!/usr/bin/env python3
"""Build Norgate trial preflight or run aggregate-only field validation."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from core.data.norgate_trial_validation import (  # noqa: E402
    NorgateTrialValidationConfig,
    PythonNorgateRuntime,
    build_norgate_preflight_artifact,
    validate_norgate_runtime,
)
from core.data.pit_contract import PitDataContract  # noqa: E402


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "runtime"), default="preflight")
    parser.add_argument("--contract", default="config/pit_data_v1.yaml")
    parser.add_argument(
        "--validation-config", default="config/norgate_trial_validation_v1.yaml"
    )
    parser.add_argument(
        "--output",
        default="research/data_readiness/pit_v1/norgate_trial_validation.json",
    )
    args = parser.parse_args()
    contract = PitDataContract.load(args.contract)
    config = NorgateTrialValidationConfig.load(args.validation_config)
    if args.mode == "runtime":
        artifact = validate_norgate_runtime(
            PythonNorgateRuntime.import_installed(),
            config=config,
            contract=contract,
        )
    else:
        artifact = build_norgate_preflight_artifact(
            config=config,
            contract=contract,
        )
    _atomic_json(artifact, Path(args.output))
    print(f"norgate_trial_validation={args.output}")
    print(f"runtime_status={artifact['runtime_status']}")
    print(f"formal_source_eligible={str(artifact['formal_source_eligible']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
