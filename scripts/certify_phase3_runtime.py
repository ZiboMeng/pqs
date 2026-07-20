#!/usr/bin/env python3
"""Build or verify the Phase 3 local runtime/deployment certification."""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.runtime.strategy_artifact import canonical_json, sha256_bytes  # noqa: E402

OUTPUT = ROOT / "research/registries/runtime_certifications/phase3_forward_v1.json"
FROZEN_STRATEGY = ROOT / "research/registries/strategy_artifacts/dual_index_growth_v1/v1.json"
COMPONENTS = {
    "runtime": [
        "core/runtime/lease.py",
        "core/paper_trading/forward_runtime.py",
        "core/paper_trading/forward_state.py",
        "core/paper_trading/forward_tracking.py",
        "core/execution/broker_adapter.py",
        "core/execution/read_only_broker.py",
        "core/execution/target_weight_planner.py",
        "scripts/run_forward_paper.py",
    ],
    "sealed_evidence": [
        "core/research/sealed_evidence.py",
        "core/research/sealed_worker.py",
        "scripts/sealed_evidence.py",
        "config/sealed_evaluator.yaml",
        "research/registries/hypothesis_registry.json",
    ],
    "collection": [
        "core/data/collection.py",
        "scripts/collect_phase3_data.py",
        "config/data_collection.yaml",
    ],
    "operations": [
        "core/operations/alerts.py",
        "core/operations/control_plane.py",
        "scripts/phase3_control.py",
        "config/alerts.yaml",
    ],
    "deployment": [
        "Dockerfile",
        "deployment/compose.yaml",
        "deployment/kubernetes/phase3-paper.yaml",
        "deployment/requirements-runtime.lock",
        "deployment/terraform/main.tf",
        "deployment/terraform/outputs.tf",
        "deployment/terraform/variables.tf",
        "deployment/terraform/versions.tf",
        "monitoring/phase3-monitoring.yaml",
        "scripts/phase3_backup.py",
        "scripts/phase3_entrypoint.py",
        "scripts/phase3_liveness.py",
        "scripts/phase3_supervisor.py",
        "scripts/validate_phase3_deployment.py",
    ],
    "policy": [
        "config/forward_paper.yaml",
        "docs/PHASE3_PRD.md",
    ],
    "certifier": ["scripts/certify_phase3_runtime.py"],
}
ENVIRONMENT_PACKAGES = ("PyYAML", "numpy", "pandas", "pydantic", "scipy")


class RuntimeCertificationError(RuntimeError):
    pass


def _safe_repo_file(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeCertificationError(f"unsafe certification path: {relative}")
    candidate = ROOT / path
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeCertificationError(f"certification path traverses a symlink: {relative}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise RuntimeCertificationError(f"certification path escapes repository: {relative}")
    if resolved.is_symlink() or not resolved.is_file():
        raise RuntimeCertificationError(f"certification component is irregular: {relative}")
    return resolved


def _record(relative: str, role: str) -> dict[str, Any]:
    path = _safe_repo_file(relative)
    raw = path.read_bytes()
    return {
        "path": relative,
        "role": role,
        "size_bytes": len(raw),
        "sha256": sha256_bytes(raw),
    }


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _environment() -> dict[str, str]:
    return {package: metadata.version(package) for package in sorted(ENVIRONMENT_PACKAGES)}


def build_payload(
    *,
    validation_evidence_path: str,
    code_commit: str,
    created_at_utc: str,
) -> dict[str, Any]:
    evidence_path = _safe_repo_file(validation_evidence_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict) or evidence.get("status") != "PASS":
        raise RuntimeCertificationError("final validation evidence must be a PASS object")
    strategy = json.loads(FROZEN_STRATEGY.read_text(encoding="utf-8"))
    components = [
        _record(path, role) for role, paths in sorted(COMPONENTS.items()) for path in sorted(paths)
    ]
    role_hashes = {
        role: sha256_bytes(
            canonical_json({"files": [record for record in components if record["role"] == role]})
        )
        for role in sorted(COMPONENTS)
    }
    payload: dict[str, Any] = {
        "certification_schema_version": 1,
        "certification_id": "phase3_forward_runtime_v1",
        "status": "CODE_CERTIFIED_LOCAL_ONLY",
        "mode": "PAPER",
        "live_enabled": False,
        "broker_write_enabled": False,
        "cloud_resources_created": False,
        "code_commit": code_commit,
        "created_at_utc": created_at_utc,
        "python_version": platform.python_version(),
        "environment": _environment(),
        "approved_strategy_artifact": {
            "path": str(FROZEN_STRATEGY.relative_to(ROOT)),
            "artifact_root_sha256": strategy["artifact_root_sha256"],
            "file_sha256": sha256_bytes(FROZEN_STRATEGY.read_bytes()),
        },
        "components": components,
        "component_role_hashes": role_hashes,
        "validation_evidence": {
            "path": validation_evidence_path,
            "sha256": sha256_bytes(evidence_path.read_bytes()),
            "full_test_summary": evidence.get("full_test_summary"),
            "ci_equivalent_status": evidence.get("ci_equivalent_status"),
        },
        "external_state": {
            "real_forward_sessions": 0,
            "real_sealed_batches": 0,
            "real_sealed_submissions": 0,
            "real_collection_batches": 0,
            "container_built": False,
            "cloud_deployed": False,
            "second_strategy_promoted": False,
        },
    }
    payload["certification_root_sha256"] = sha256_bytes(canonical_json(payload))
    return payload


def verify_payload(payload: Mapping[str, Any], *, verify_environment: bool = True) -> None:
    root_hash = payload.get("certification_root_sha256")
    unsigned = dict(payload)
    unsigned.pop("certification_root_sha256", None)
    if root_hash != sha256_bytes(canonical_json(unsigned)):
        raise RuntimeCertificationError("runtime certification root hash mismatch")
    if (
        payload.get("status") != "CODE_CERTIFIED_LOCAL_ONLY"
        or payload.get("mode") != "PAPER"
        or payload.get("live_enabled") is not False
        or payload.get("broker_write_enabled") is not False
        or payload.get("cloud_resources_created") is not False
    ):
        raise RuntimeCertificationError("runtime certification safety boundary is invalid")
    records = payload.get("components")
    if not isinstance(records, list):
        raise RuntimeCertificationError("runtime certification components are absent")
    observed_roles: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeCertificationError("runtime certification record is invalid")
        path = _safe_repo_file(str(record.get("path", "")))
        raw = path.read_bytes()
        if len(raw) != record.get("size_bytes") or sha256_bytes(raw) != record.get("sha256"):
            raise RuntimeCertificationError(f"runtime component drift: {record['path']}")
        observed_roles.add(str(record.get("role")))
    if observed_roles != set(COMPONENTS):
        raise RuntimeCertificationError("runtime certification roles are incomplete")
    expected_role_hashes = {
        role: sha256_bytes(
            canonical_json({"files": [record for record in records if record["role"] == role]})
        )
        for role in sorted(observed_roles)
    }
    if payload.get("component_role_hashes") != expected_role_hashes:
        raise RuntimeCertificationError("runtime certification role hashes differ")
    evidence = payload.get("validation_evidence")
    if not isinstance(evidence, dict):
        raise RuntimeCertificationError("validation evidence is absent")
    evidence_path = _safe_repo_file(str(evidence.get("path", "")))
    if sha256_bytes(evidence_path.read_bytes()) != evidence.get("sha256"):
        raise RuntimeCertificationError("final validation evidence drifted")
    strategy = payload.get("approved_strategy_artifact")
    if not isinstance(strategy, dict):
        raise RuntimeCertificationError("approved strategy reference is absent")
    frozen = json.loads(FROZEN_STRATEGY.read_text(encoding="utf-8"))
    if strategy.get("artifact_root_sha256") != frozen.get("artifact_root_sha256") or strategy.get(
        "file_sha256"
    ) != sha256_bytes(FROZEN_STRATEGY.read_bytes()):
        raise RuntimeCertificationError("approved strategy artifact reference drifted")
    if verify_environment and (
        payload.get("python_version") != platform.python_version()
        or payload.get("environment") != _environment()
    ):
        raise RuntimeCertificationError("runtime certification environment drifted")


def _atomic_create(path: Path, payload: Mapping[str, Any]) -> bool:
    rendered = canonical_json(dict(payload)) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise RuntimeCertificationError("certification output path cannot be a symlink")
    if path.exists():
        if path.read_bytes() == rendered:
            return True
        raise RuntimeCertificationError("immutable runtime certification conflicts")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o444)
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return False
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("--output", default=str(OUTPUT.relative_to(ROOT)))
    parser.add_argument(
        "--validation-evidence",
        default="research/results/phase3/final_validation.json",
    )
    parser.add_argument("--skip-environment", action="store_true")
    args = parser.parse_args()
    try:
        output = Path(args.output)
        if output.is_absolute() or ".." in output.parts:
            raise RuntimeCertificationError("certification output must remain in the repository")
        target = ROOT / output
        if args.mode == "build":
            payload = build_payload(
                validation_evidence_path=args.validation_evidence,
                code_commit=_git_commit(),
                created_at_utc=datetime.now(UTC).isoformat(),
            )
            reused = _atomic_create(target, payload)
        else:
            payload = json.loads(target.read_text(encoding="utf-8"))
            reused = True
        verify_payload(payload, verify_environment=not args.skip_environment)
        result = {
            "status": "PASS",
            "artifact": str(target.relative_to(ROOT)),
            "certification_root_sha256": payload["certification_root_sha256"],
            "reused": reused,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
