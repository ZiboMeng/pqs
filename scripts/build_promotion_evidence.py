#!/usr/bin/env python3
"""Build a candidate-bound automatic-promotion evidence artifact.

This command does not promote anything. It verifies a clean code commit, runs
the fixed lookahead/timing regression suite, binds supplied overfit metrics and
a paper/backtest replay artifact, and writes one immutable JSON evidence file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.research.promotion.evidence import (  # noqa: E402
    REQUIRED_BOUND_SOURCES,
    sha256_file,
)


LOOKAHEAD_TESTS = (
    "tests/unit/backtest/test_backtest_engine.py",
    "tests/unit/research/test_temporal_split_leak_detection.py",
    "tests/unit/research/test_w7b_overfit_diagnostics_wiring.py",
    "tests/unit/research/test_w7cd_cpcv_acceptance_wiring.py",
)


def _load_mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"evidence input must be a mapping: {path}")
    return payload


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
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
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--qualification-json", required=True)
    parser.add_argument(
        "--alignment-json",
        default=None,
        help=(
            "Candidate-specific paper/backtest replay result. Omit only to "
            "build pre-holdout qualification evidence; that artifact cannot "
            "authorize automatic promotion."
        ),
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    dirty = _git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        print("ERROR: tracked worktree must be clean before evidence certification", file=sys.stderr)
        return 2
    commit = _git("rev-parse", "HEAD")
    qualification_path = Path(args.qualification_json).resolve()
    alignment_path = Path(args.alignment_json).resolve() if args.alignment_json else None
    try:
        qualification_relative = qualification_path.relative_to(ROOT)
        alignment_relative = alignment_path.relative_to(ROOT) if alignment_path else None
    except ValueError:
        print("ERROR: evidence inputs must be files inside the repository", file=sys.stderr)
        return 2
    qualification = _load_mapping(qualification_path)
    alignment = _load_mapping(alignment_path) if alignment_path else None
    if qualification.get("candidate_id") != args.candidate_id:
        print("ERROR: qualification candidate_id mismatch", file=sys.stderr)
        return 2
    if qualification.get("code_commit") != commit:
        print("ERROR: qualification code_commit mismatch", file=sys.stderr)
        return 2

    command = [sys.executable, "-m", "pytest", "-q", *LOOKAHEAD_TESTS]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    source_hashes = {
        path: sha256_file(ROOT / path) for path in REQUIRED_BOUND_SOURCES
    }
    payload = {
        "schema_version": 1,
        "candidate_id": args.candidate_id,
        "code_commit": commit,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "benchmark": {
            "symbol": "SPY",
            "comparison_basis": "total_return_after_strategy_costs",
            "strategy_costs_included": True,
        },
        "lookahead": {
            "passed": completed.returncode == 0,
            "test_exit_code": completed.returncode,
            "tests": list(LOOKAHEAD_TESTS),
            "test_command": command,
            "test_output_sha256": hashlib.sha256(
                completed.stdout.encode("utf-8")
            ).hexdigest(),
            "source_hashes": source_hashes,
        },
        "overfit": {
            **qualification.get("overfit", {}),
            "artifact_path": str(qualification_relative),
            "artifact_sha256": sha256_file(qualification_path),
        },
    }
    if alignment_path is not None and alignment is not None:
        payload["paper_backtest_alignment"] = {
            "passed": alignment.get("passed") is True,
            "max_equity_drift_bps": alignment.get("max_equity_drift_bps"),
            "artifact_path": str(alignment_relative),
            "artifact_sha256": sha256_file(alignment_path),
        }
    output = Path(args.output)
    output = output if output.is_absolute() else ROOT / output
    if output.exists():
        print(f"ERROR: promotion evidence is immutable and already exists: {output}", file=sys.stderr)
        return 2
    _atomic_json(output, payload)
    print(f"wrote {output}")
    print(
        "evidence_scope="
        + ("automatic_promotion" if alignment_path else "qualification_only")
    )
    print(f"lookahead_tests={'PASS' if completed.returncode == 0 else 'FAIL'}")
    return 0 if completed.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
