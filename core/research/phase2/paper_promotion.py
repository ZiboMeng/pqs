"""Fail-closed transition from research qualification to PAPER approval."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from core.research.phase2.promotion import CandidateEvidence, PromotionPolicy

STRATEGY_ID = "dual_index_growth_v1"
FAMILY = "dual_index_growth"
OPERATIONAL_CONTROL_NAMES = (
    "missing_data_fail_closed",
    "stale_data_fail_closed",
    "risk_veto_test",
    "restart_idempotency_test",
    "paper_replay",
    "live_disabled",
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"invalid schema: {path}")
    return payload


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"invalid schema: {path}")
    return payload


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_paper_only(config_paths: tuple[Path, ...]) -> None:
    for path in config_paths:
        config = _load_yaml(path)
        if config.get("mode") != "PAPER" or config.get("live_enabled") is not False:
            raise RuntimeError(f"PAPER promotion requires LIVE-disabled PAPER config: {path}")


def _find_strategy(registry: Mapping[str, Any]) -> dict[str, Any]:
    strategies = registry.get("strategies")
    if not isinstance(strategies, list):
        raise ValueError("strategy registry strategies must be a list")
    matches = [item for item in strategies if item.get("strategy_id") == STRATEGY_ID]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {STRATEGY_ID} registry record")
    return matches[0]


def promote(
    *,
    policy_path: Path,
    validation_path: Path,
    holdout_path: Path,
    operational_path: Path,
    strategy_registry_path: Path,
    promotion_registry_path: Path,
    config_paths: tuple[Path, ...],
    code_commit: str,
) -> dict[str, Any]:
    """Evaluate every frozen gate and persist an auditable approval decision."""
    validation = _load_json(validation_path)
    holdout = _load_json(holdout_path)
    operational = _load_json(operational_path)
    strategy_registry = _load_json(strategy_registry_path)
    promotion_registry = _load_json(promotion_registry_path)
    _require_paper_only(config_paths)
    policy = PromotionPolicy.load(policy_path)

    expected_validation = policy.payload["data_protocol"]["validation"]
    expected_holdout = policy.payload["data_protocol"]["final_holdout"]
    evidence_boundaries = (
        (validation, expected_validation, "validation"),
        (holdout, expected_holdout, "final holdout"),
    )
    for payload, expected, label in evidence_boundaries:
        actual_start = str(payload.get("evaluation_start", ""))[:10]
        actual_end = str(payload.get("evaluation_end", ""))[:10]
        if actual_start != expected["start"] or actual_end != expected["end"]:
            raise RuntimeError(f"{label} evidence interval does not match frozen policy")

    strategy = _find_strategy(strategy_registry)
    if strategy.get("status") not in {"RESEARCH_QUALIFIED", "PAPER_APPROVED"}:
        raise RuntimeError(f"strategy is not research-qualified: {strategy.get('status')}")
    if strategy.get("live_enabled") is not False:
        raise RuntimeError("strategy registry must keep LIVE disabled")

    validation_item = validation.get("families", {}).get(FAMILY)
    holdout_item = holdout.get("families", {}).get(FAMILY)
    if not isinstance(validation_item, dict) or not isinstance(holdout_item, dict):
        raise RuntimeError("candidate evidence is missing")
    if validation_item.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError("validation candidate identity mismatch")
    if holdout_item.get("strategy_id") != STRATEGY_ID:
        raise RuntimeError("holdout candidate identity mismatch")
    if validation_item.get("research_gate_pass") is not True:
        raise RuntimeError("validation research gates did not pass")
    if holdout_item.get("holdout_gate_pass") is not True:
        raise RuntimeError("sealed holdout gates did not pass")
    if holdout_item.get("logic_frozen_after_access") is not True:
        raise RuntimeError("holdout logic-freeze attestation is missing")
    if operational.get("strategy_id") != STRATEGY_ID or operational.get("status") != "PASS":
        raise RuntimeError("PAPER operational acceptance did not pass")
    checks = operational.get("checks")
    if (
        not isinstance(checks, dict)
        or not checks
        or not all(value is True for value in checks.values())
    ):
        raise RuntimeError("PAPER operational checks are incomplete or failed")
    operational_controls = operational.get("operational_controls")
    if not isinstance(operational_controls, dict):
        raise RuntimeError("PAPER operational controls are missing")
    missing_controls = [
        name for name in OPERATIONAL_CONTROL_NAMES if operational_controls.get(name) is not True
    ]
    if missing_controls:
        raise RuntimeError(f"PAPER operational controls failed: {missing_controls}")

    controls = dict(validation_item.get("controls", {}))
    controls.update(operational_controls)
    evidence = CandidateEvidence(
        strategy_id=STRATEGY_ID,
        strategy_type=strategy["strategy_type"],
        metrics=holdout_item["metrics"],
        benchmark_metrics=holdout_item["benchmark_metrics"],
        robustness=holdout_item["validation_robustness"],
        controls=controls,
    )
    decision = policy.evaluate(evidence, include_operational=True)
    if not decision.eligible:
        raise RuntimeError(f"promotion gates failed: {decision.failed_gates}")

    root = policy_path.resolve().parents[1]
    source_paths = {
        "validation": validation_path,
        "final_holdout": holdout_path,
        "operational": operational_path,
    }
    evidence_paths = {name: _display_path(path, root) for name, path in source_paths.items()}
    evidence_hashes = {name: _sha256(path) for name, path in source_paths.items()}
    promotion_record = {
        "strategy_id": STRATEGY_ID,
        "decision": "PAPER_APPROVED",
        "policy_id": policy.payload["policy_id"],
        "evaluated_at_utc": _utc_now(),
        "code_commit": code_commit,
        "operational_evidence_code_commit": operational.get("code_commit"),
        "evidence": evidence_paths,
        "evidence_sha256": evidence_hashes,
        "failed_gates": [],
        "gates": [asdict(gate) for gate in decision.gates],
        "live_enabled": False,
    }

    promotions = promotion_registry.get("promotions")
    if not isinstance(promotions, list):
        raise ValueError("promotion registry promotions must be a list")
    existing = [item for item in promotions if item.get("strategy_id") == STRATEGY_ID]
    if existing:
        prior = existing[0]
        if (
            len(existing) != 1
            or prior.get("decision") != "PAPER_APPROVED"
            or prior.get("evidence_sha256") != evidence_hashes
        ):
            raise RuntimeError("conflicting existing promotion record")
        promotion_record = prior
    else:
        promotions.append(promotion_record)
        _atomic_json(promotion_registry_path, promotion_registry)

    strategy["status"] = "PAPER_APPROVED"
    strategy["live_enabled"] = False
    strategy["promotion_evidence"]["operational"] = str(operational_path)
    strategy["promotion_decision"] = {
        "decision": "PAPER_APPROVED",
        "policy_id": policy.payload["policy_id"],
        "promotion_registry": str(promotion_registry_path),
    }
    _atomic_json(strategy_registry_path, strategy_registry)
    return promotion_record


def current_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
