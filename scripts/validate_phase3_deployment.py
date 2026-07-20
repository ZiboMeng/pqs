#!/usr/bin/env python3
"""Static fail-closed validation for Phase 3 deployment assets."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DeploymentValidationError(RuntimeError):
    pass


def _yaml(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise DeploymentValidationError(f"deployment asset is irregular: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeploymentValidationError(message)


def _validate_dockerfile() -> dict[str, Any]:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    requirements = {
        "pinned_python": "FROM python:3.13.12-slim" in text,
        "non_root_uid": "USER 10001:10001" in text,
        "artifact_verified_at_build": "freeze_phase3_strategy.py verify" in text,
        "runtime_lock": "deployment/requirements-runtime.lock" in text,
        "phase3_entrypoint": 'ENTRYPOINT ["python", "scripts/phase3_entrypoint.py"]' in text,
        "phase3_liveness": "phase3_liveness.py" in text,
        "copies_artifact": "COPY research/registries" in text,
        "copies_evidence": "COPY research/results/phase2" in text,
        "no_legacy_default": 'CMD ["python", "scripts/run_paper.py"' not in text,
    }
    _require(all(requirements.values()), f"Dockerfile contract failed: {requirements}")
    return requirements


def _validate_compose() -> dict[str, Any]:
    payload = _yaml(ROOT / "deployment/compose.yaml")
    _require(isinstance(payload, dict), "Compose document must be a mapping")
    services = payload.get("services", {})
    _require(set(services) == {"phase3-monitor"}, "Compose must define one singleton service")
    service = services["phase3-monitor"]
    requirements = {
        "non_root": service.get("user") == "10001:10001",
        "read_only_root": service.get("read_only") is True,
        "init": service.get("init") is True,
        "graceful_stop": service.get("stop_grace_period") == "30s",
        "drop_all_caps": service.get("cap_drop") == ["ALL"],
        "no_new_privileges": "no-new-privileges:true" in service.get("security_opt", []),
        "persistent_volumes": len(service.get("volumes", [])) == 4,
        "tmpfs": bool(service.get("tmpfs")),
        "healthcheck": "phase3_liveness.py" in json.dumps(service.get("healthcheck")),
        "no_privileged": service.get("privileged") is not True,
        "no_live_environment": not any(
            "LIVE" in str(key).upper() or "BROKER_WRITE" in str(key).upper()
            for key in service.get("environment", {})
        ),
    }
    _require(all(requirements.values()), f"Compose contract failed: {requirements}")
    return requirements


def _validate_kubernetes() -> dict[str, Any]:
    path = ROOT / "deployment/kubernetes/phase3-paper.yaml"
    documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    kinds = {document.get("kind") for document in documents if isinstance(document, dict)}
    _require(
        {
            "Namespace",
            "PersistentVolumeClaim",
            "StatefulSet",
            "PodDisruptionBudget",
            "NetworkPolicy",
        }
        <= kinds,
        "Kubernetes template is missing required resource kinds",
    )
    workload = next(document for document in documents if document.get("kind") == "StatefulSet")
    pod = workload["spec"]["template"]["spec"]
    container = pod["containers"][0]
    context = pod["securityContext"]
    container_context = container["securityContext"]
    image = str(container["image"])
    requirements = {
        "singleton": workload["spec"]["replicas"] == 1,
        "service_account_token_disabled": pod["automountServiceAccountToken"] is False,
        "non_root": context["runAsNonRoot"] is True and context["runAsUser"] == 10001,
        "seccomp": context["seccompProfile"]["type"] == "RuntimeDefault",
        "read_only_root": container_context["readOnlyRootFilesystem"] is True,
        "no_privilege_escalation": container_context["allowPrivilegeEscalation"] is False,
        "drop_all_caps": container_context["capabilities"]["drop"] == ["ALL"],
        "immutable_image_format": bool(re.search(r"@sha256:[0-9a-f]{64}$", image)),
        "liveness": "phase3_liveness.py" in json.dumps(container["livenessProbe"]),
        "readiness": "phase3_control.py" in json.dumps(container["readinessProbe"]),
        "graceful_stop": pod["terminationGracePeriodSeconds"] >= 30,
        "no_live_environment": not any(
            "LIVE" in item["name"].upper() or "BROKER_WRITE" in item["name"].upper()
            for item in container.get("env", [])
        ),
    }
    _require(all(requirements.values()), f"Kubernetes contract failed: {requirements}")
    return {**requirements, "image_digest_is_placeholder": set(image.rsplit(":", 1)[-1]) == {"0"}}


def _validate_terraform() -> dict[str, Any]:
    directory = ROOT / "deployment/terraform"
    files = {path.name: path.read_text(encoding="utf-8") for path in directory.glob("*.tf")}
    text = "\n".join(files.values())
    cloud_resources = re.findall(r'resource\s+"(?!terraform_data)([^"]+)"\s+"', text)
    requirements = {
        "version_constraint": 'required_version = ">= 1.5.0"' in text,
        "immutable_digest_validation": "@sha256:[0-9a-f]{64}$" in text,
        "singleton_validation": "var.replicas == 1" in text,
        "non_root_validation": "var.run_as_user == 10001" in text,
        "read_only_validation": "var.read_only_root_filesystem" in text,
        "encrypted_volume_validation": "var.persistent_volume_encrypted" in text,
        "live_false_validation": "!var.live_enabled" in text,
        "broker_write_false_validation": "!var.broker_write_enabled" in text,
        "creates_no_cloud_resources": not cloud_resources,
    }
    _require(all(requirements.values()), f"Terraform contract failed: {requirements}")
    return requirements


def _validate_runtime_lock() -> dict[str, Any]:
    lock = {}
    for line in (
        (ROOT / "deployment/requirements-runtime.lock").read_text(encoding="utf-8").splitlines()
    ):
        if not line or line.startswith("#"):
            continue
        name, version = line.split("==", 1)
        lock[name.lower()] = version
    artifact = json.loads(
        (
            ROOT
            / "research/registries/strategy_artifacts/dual_index_growth_v1/observation_v1.json"
        ).read_text(encoding="utf-8")
    )
    normalized = {
        "PyYAML": "pyyaml",
        "numpy": "numpy",
        "pandas": "pandas",
        "pydantic": "pydantic",
        "scipy": "scipy",
    }
    mismatches = {
        package: (artifact["environment"].get(package), lock.get(lock_name))
        for package, lock_name in normalized.items()
        if artifact["environment"].get(package) != lock.get(lock_name)
    }
    _require(not mismatches, f"runtime lock differs from artifact environment: {mismatches}")
    return {"frozen_environment_matches": True, "locked_direct_dependencies": len(lock)}


def main() -> int:
    try:
        result = {
            "schema_version": 1,
            "status": "PASS",
            "dockerfile": _validate_dockerfile(),
            "compose": _validate_compose(),
            "kubernetes": _validate_kubernetes(),
            "terraform_contract": _validate_terraform(),
            "runtime_lock": _validate_runtime_lock(),
            "tool_availability": {
                name: shutil.which(name) is not None
                for name in ("docker", "podman", "terraform", "tofu", "kubectl")
            },
            "cloud_resources_created": False,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
