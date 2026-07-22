#!/usr/bin/env python3
"""Build the immutable Mining V5 canonical SPY total-return artifact."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.research.canonical_benchmark import (  # noqa: E402
    build_canonical_spy_payload,
)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-parquet", required=True)
    parser.add_argument("--start", default="2015-01-02")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument(
        "--output",
        default="research/protocols/mining_v5/canonical_spy_total_return.json",
    )
    args = parser.parse_args()
    output = Path(args.output)
    output = output if output.is_absolute() else ROOT / output
    if output.exists():
        print(f"ERROR: canonical benchmark is immutable: {output}", file=sys.stderr)
        return 2
    payload = build_canonical_spy_payload(
        args.source_parquet,
        evaluation_start=date.fromisoformat(args.start),
        evaluation_end=date.fromisoformat(args.end),
    )
    _atomic_json(output, payload)
    print(f"wrote {output}")
    print(f"sessions={payload['metrics']['sessions']}")
    print(f"cagr={payload['metrics']['cagr']:.8f}")
    print(f"max_drawdown={payload['metrics']['max_drawdown']:.8f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
