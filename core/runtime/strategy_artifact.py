"""Immutable, transitive strategy artifacts for approved PAPER runtimes."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import tempfile
from collections.abc import Mapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import Any

ARTIFACT_SCHEMA_VERSION = 1
REQUIRED_COMPONENT_ROLES = frozenset(
    {
        "strategy",
        "configuration",
        "feature_regime",
        "allocator",
        "risk",
        "cost_execution",
        "data_contract",
        "runtime",
        "dependency",
    }
)


class StrategyArtifactError(RuntimeError):
    """Raised when an artifact cannot be built or verified safely."""


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    """Serialize a manifest without NaN or platform-dependent whitespace."""
    try:
        rendered = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise StrategyArtifactError(f"artifact is not canonical-JSON safe: {exc}") from exc
    return rendered.encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_repo_file(repo_root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise StrategyArtifactError(f"artifact path must be repository-relative: {relative_path}")
    root = repo_root.resolve(strict=True)
    unresolved = repo_root / relative
    cursor = unresolved
    while cursor != repo_root and cursor != cursor.parent:
        if cursor.is_symlink():
            raise StrategyArtifactError(f"artifact component cannot be a symlink: {relative_path}")
        cursor = cursor.parent
    try:
        resolved = unresolved.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise StrategyArtifactError(
            f"artifact component is missing or escapes repository: {relative_path}"
        ) from exc
    if not resolved.is_file():
        raise StrategyArtifactError(f"artifact component is not a file: {relative_path}")
    return resolved


def _component_record(repo_root: Path, relative_path: str, role: str) -> dict[str, Any]:
    path = _safe_repo_file(repo_root, relative_path)
    content = path.read_bytes()
    return {
        "path": Path(relative_path).as_posix(),
        "role": role,
        "sha256": sha256_bytes(content),
        "size_bytes": len(content),
    }


def _records_hash(records: Sequence[Mapping[str, Any]]) -> str:
    identity = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in sorted(records, key=lambda value: str(value["path"]))
    ]
    return sha256_bytes(canonical_json({"files": identity}))


def current_environment(packages: Sequence[str]) -> dict[str, str]:
    """Return exact installed versions for the explicitly frozen packages."""
    versions: dict[str, str] = {}
    for package in sorted(set(packages)):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError as exc:
            raise StrategyArtifactError(f"required package is not installed: {package}") from exc
    return versions


def build_strategy_artifact(
    *,
    repo_root: str | Path,
    strategy_id: str,
    strategy_version: str,
    promotion_status: str,
    allowed_runtime_modes: Sequence[str],
    live_enabled: bool,
    component_paths: Mapping[str, Sequence[str]],
    strategy_parameters: Mapping[str, Any],
    universe: Sequence[str],
    schedule: Mapping[str, Any],
    data_schema_version: str,
    promotion_evidence_paths: Sequence[str],
    code_commit: str,
    created_at_utc: str,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    """Build a deterministic behavior manifest; this function does not write."""
    root = Path(repo_root)
    if not strategy_id.strip() or not strategy_version.strip():
        raise StrategyArtifactError("strategy id and version are required")
    modes = sorted({str(mode).upper() for mode in allowed_runtime_modes})
    if promotion_status == "PAPER_APPROVED" and (
        live_enabled or modes != ["PAPER"]
    ):
        raise StrategyArtifactError(
            "PAPER-approved artifact must allow PAPER only and keep LIVE disabled"
        )
    missing_roles = sorted(REQUIRED_COMPONENT_ROLES - set(component_paths))
    if missing_roles:
        raise StrategyArtifactError(f"artifact component roles missing: {missing_roles}")

    seen_paths: set[str] = set()
    components: list[dict[str, Any]] = []
    for role in sorted(component_paths):
        for relative_path in sorted(component_paths[role]):
            normalized = Path(relative_path).as_posix()
            if normalized in seen_paths:
                raise StrategyArtifactError(f"duplicate artifact component path: {normalized}")
            seen_paths.add(normalized)
            components.append(_component_record(root, normalized, role))

    evidence = [
        _component_record(root, Path(path).as_posix(), "promotion_evidence")
        for path in sorted(set(promotion_evidence_paths))
    ]
    if not evidence:
        raise StrategyArtifactError("at least one promotion evidence file is required")

    role_hashes = {
        role: _records_hash([item for item in components if item["role"] == role])
        for role in sorted(component_paths)
    }
    payload: dict[str, Any] = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "promotion_status": promotion_status,
        "allowed_runtime_modes": modes,
        "live_enabled": bool(live_enabled),
        "code_commit": code_commit,
        "python_version": platform.python_version(),
        "created_at_utc": created_at_utc,
        "strategy_parameters": dict(strategy_parameters),
        "universe": sorted(set(str(symbol).upper() for symbol in universe)),
        "schedule": dict(schedule),
        "data_schema_version": data_schema_version,
        "components": sorted(components, key=lambda item: (item["role"], item["path"])),
        "component_role_hashes": role_hashes,
        "feature_schema_hash": role_hashes["feature_regime"],
        "data_contract_hash": role_hashes["data_contract"],
        "risk_policy_hash": role_hashes["risk"],
        "cost_model_hash": role_hashes["cost_execution"],
        "dependency_lock_hash": role_hashes["dependency"],
        "promotion_evidence": evidence,
        "promotion_evidence_hash": _records_hash(evidence),
        "environment": dict(sorted(environment.items())),
    }
    payload["artifact_root_sha256"] = sha256_bytes(canonical_json(payload))
    return payload


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise StrategyArtifactError(f"duplicate JSON key in artifact: {key}")
        output[key] = value
    return output


def load_strategy_artifact(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategyArtifactError(f"cannot read strategy artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StrategyArtifactError("strategy artifact root must be a JSON object")
    return payload


def verify_strategy_artifact(
    artifact: Mapping[str, Any] | str | Path,
    *,
    repo_root: str | Path,
    expected_strategy_id: str | None = None,
    expected_strategy_version: str | None = None,
    expected_promotion_status: str | None = None,
    verify_environment: bool = True,
) -> dict[str, Any]:
    """Verify the root, every transitive component and runtime identity."""
    payload = (
        load_strategy_artifact(artifact)
        if isinstance(artifact, (str, Path))
        else dict(artifact)
    )
    if payload.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise StrategyArtifactError("unsupported strategy artifact schema")
    recorded_root = payload.get("artifact_root_sha256")
    unsigned = dict(payload)
    unsigned.pop("artifact_root_sha256", None)
    actual_root = sha256_bytes(canonical_json(unsigned))
    if recorded_root != actual_root:
        raise StrategyArtifactError("strategy artifact root hash mismatch")

    expectations = {
        "strategy_id": expected_strategy_id,
        "strategy_version": expected_strategy_version,
        "promotion_status": expected_promotion_status,
    }
    for field, expected in expectations.items():
        if expected is not None and payload.get(field) != expected:
            raise StrategyArtifactError(
                f"strategy artifact {field} mismatch: {payload.get(field)!r} != {expected!r}"
            )
    if payload.get("promotion_status") == "PAPER_APPROVED" and (
        payload.get("live_enabled") is not False
        or payload.get("allowed_runtime_modes") != ["PAPER"]
    ):
        raise StrategyArtifactError("approved PAPER artifact violates runtime-mode boundary")

    root = Path(repo_root)
    components = payload.get("components")
    evidence = payload.get("promotion_evidence")
    if not isinstance(components, list) or not isinstance(evidence, list):
        raise StrategyArtifactError("artifact component and evidence lists are required")
    observed_roles: set[str] = set()
    for record in [*components, *evidence]:
        if not isinstance(record, dict):
            raise StrategyArtifactError("artifact file record must be an object")
        path = _safe_repo_file(root, str(record.get("path", "")))
        actual_hash = sha256_bytes(path.read_bytes())
        if actual_hash != record.get("sha256") or path.stat().st_size != record.get(
            "size_bytes"
        ):
            raise StrategyArtifactError(f"strategy artifact component drift: {record['path']}")
        if record in components:
            observed_roles.add(str(record.get("role")))
    missing_roles = sorted(REQUIRED_COMPONENT_ROLES - observed_roles)
    if missing_roles:
        raise StrategyArtifactError(f"verified artifact roles missing: {missing_roles}")

    expected_role_hashes = {
        role: _records_hash([item for item in components if item.get("role") == role])
        for role in sorted(observed_roles)
    }
    if payload.get("component_role_hashes") != expected_role_hashes:
        raise StrategyArtifactError("strategy artifact role hash mismatch")
    if payload.get("promotion_evidence_hash") != _records_hash(evidence):
        raise StrategyArtifactError("strategy promotion evidence hash mismatch")

    if verify_environment:
        if payload.get("python_version") != platform.python_version():
            raise StrategyArtifactError(
                "strategy artifact Python version drift: "
                f"{platform.python_version()} != {payload.get('python_version')}"
            )
        frozen_environment = payload.get("environment")
        if not isinstance(frozen_environment, dict) or not frozen_environment:
            raise StrategyArtifactError("strategy artifact environment is missing")
        installed = current_environment(list(frozen_environment))
        if installed != frozen_environment:
            raise StrategyArtifactError(
                f"strategy artifact environment drift: {installed} != {frozen_environment}"
            )
    return payload


def write_strategy_artifact(path: str | Path, payload: Mapping[str, Any]) -> tuple[Path, bool]:
    """Atomically create an immutable artifact; conflicting rewrites fail."""
    target = Path(path)
    rendered = canonical_json(payload) + b"\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() == rendered:
            return target, True
        raise StrategyArtifactError(f"immutable strategy artifact conflict: {target}")

    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() == rendered:
                return target, True
            raise StrategyArtifactError(f"immutable strategy artifact conflict: {target}")
        target.chmod(0o444)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return target, False
    finally:
        temporary.unlink(missing_ok=True)
