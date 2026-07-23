#!/usr/bin/env python3
"""Write the compact V6 PIT source inventory without directional metrics."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from core.data.pit_contract import PitDataContract  # noqa: E402
from core.data.pit_source_inventory import build_source_inventory  # noqa: E402


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
    parser.add_argument("--source-project-root", default=".")
    parser.add_argument("--contract", default="config/pit_data_v1.yaml")
    parser.add_argument(
        "--output",
        default="research/data_readiness/pit_v1/source_inventory.json",
    )
    args = parser.parse_args()
    contract = PitDataContract.load(args.contract)
    inventory = build_source_inventory(
        args.source_project_root,
        contract=contract,
    )
    output = Path(args.output)
    _atomic_json(inventory, output)
    print(f"source_inventory={output}")
    print(f"historical_status={inventory['historical_source_assessment']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
