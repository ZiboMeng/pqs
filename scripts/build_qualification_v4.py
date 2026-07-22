#!/usr/bin/env python3
"""Build and independently validate an immutable Qualification V4 artifact."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.research.qualification_v4 import (  # noqa: E402
    build_qualification_artifact,
    validate_qualification_artifact,
)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


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
    parser.add_argument("--input-bundle", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-dirty-development", action="store_true")
    args = parser.parse_args()
    if not args.allow_dirty_development and _git(
        "status", "--porcelain", "--untracked-files=no"
    ):
        print("ERROR: tracked worktree must be clean", file=sys.stderr)
        return 2
    output = Path(args.output)
    output = output if output.is_absolute() else ROOT / output
    if output.exists():
        print(f"ERROR: qualification artifact already exists: {output}", file=sys.stderr)
        return 2
    commit = _git("rev-parse", "HEAD")
    artifact = build_qualification_artifact(
        input_bundle_path=args.input_bundle,
        ledger_path=args.ledger,
        repo_root=ROOT,
        code_commit=commit,
    )
    _atomic_json(output, artifact)
    validation = validate_qualification_artifact(
        output,
        expected_candidate_id=str(artifact["candidate_id"]),
        expected_code_commit=commit,
        repo_root=ROOT,
    )
    print(f"wrote {output}")
    print(f"qualification_passed={validation.passed}")
    if validation.failed_checks:
        print("failed_checks=" + ",".join(validation.failed_checks))
    return 0 if validation.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
