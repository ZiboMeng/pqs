"""Fail-closed absolute-risk contract for a sized PAPER account.

This module deliberately does not grade raw strategy quality.  Qualification
V4 owns the relative strategy gates; this module decides whether a frozen raw
candidate plus its account sizing/risk overlay has enough path evidence to run
in the risk-governed PAPER lane.  Missing evidence remains useful for shadow
observation but cannot acquire capital authority.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from core.research.governance import load_research_governance
from core.research.qualification_v2 import canonical_sha256


@dataclass(frozen=True, slots=True)
class AccountDeploymentRiskValidation:
    status: str
    absolute_risk_contract_passed: bool
    capital_eligible: bool
    failed_checks: tuple[str, ...]
    metrics: Mapping[str, Any]


def _max_drawdown(returns: np.ndarray) -> float:
    nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    peaks = np.maximum.accumulate(nav)
    return float(np.min(nav / peaks - 1.0))


def _path(value: Any) -> np.ndarray | None:
    try:
        values = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    if (
        values.ndim != 1
        or len(values) < 2
        or not np.isfinite(values).all()
        or bool((values <= -1.0).any())
    ):
        return None
    return values


def evaluate_account_deployment_risk(
    evidence: Mapping[str, Any] | None,
    *,
    governance_path: str | Path = "config/research_governance.yaml",
) -> AccountDeploymentRiskValidation:
    governance = load_research_governance(governance_path)
    if governance.schema_version != 3:
        raise ValueError("account deployment risk requires governance schema v3")
    policy = governance.automatic_promotion_evidence.account_deployment_risk
    failed: list[str] = []
    metrics: dict[str, Any] = {
        "required_path_scenarios": list(policy.required_path_scenarios),
        "stress_path_max_drawdown": policy.stress_path_max_drawdown,
        "gap_overshoot_not_guaranteed": True,
    }
    if not isinstance(evidence, Mapping):
        failed.append("account_risk_evidence_missing")
        evidence = {}
    if evidence.get("evidence_type") != "daily_path_returns":
        failed.append("account_risk_path_capable_evidence_required")
    if evidence.get("path_capable") is not True:
        failed.append("account_risk_path_capability_unproven")
    if evidence.get("terminal_weighted_shock_only") is True:
        failed.append("terminal_weighted_shock_cannot_pass_path_contract")

    target = evidence.get("operating_max_drawdown_target")
    try:
        target_value = float(target)
    except (TypeError, ValueError):
        target_value = float("nan")
    if not (
        math.isfinite(target_value)
        and policy.operating_max_drawdown_target_min
        <= target_value
        <= policy.operating_max_drawdown_target_max
    ):
        failed.append("account_risk_operating_target_outside_15_20pct")
    metrics["operating_max_drawdown_target"] = (
        target_value if math.isfinite(target_value) else None
    )

    runtime = evidence.get("runtime_thresholds")
    expected_runtime = {
        "alert": policy.runtime_alert_drawdown,
        "derisk": policy.runtime_derisk_drawdown,
        "halt": policy.runtime_halt_drawdown,
    }
    if not isinstance(runtime, Mapping) or any(
        runtime.get(name) != value for name, value in expected_runtime.items()
    ):
        failed.append("account_risk_runtime_thresholds_mismatch")
    metrics["runtime_thresholds"] = expected_runtime

    for name in (
        "next_session_execution_passed",
        "future_mutation_passed",
        "deterministic_replay_passed",
        "paper_replay_passed",
    ):
        if evidence.get(name) is not True:
            failed.append(f"account_risk_{name}")

    paths = evidence.get("stress_path_returns")
    source_hashes = evidence.get("path_source_sha256")
    if not isinstance(paths, Mapping):
        paths = {}
        failed.append("account_risk_stress_paths_missing")
    if set(paths) != set(policy.required_path_scenarios):
        failed.append("account_risk_stress_scenario_set_mismatch")
    if not isinstance(source_hashes, Mapping) or set(source_hashes) != set(
        policy.required_path_scenarios
    ):
        source_hashes = {}
        failed.append("account_risk_path_source_hashes_missing")

    scenario_metrics: dict[str, Any] = {}
    for scenario in policy.required_path_scenarios:
        values = _path(paths.get(scenario))
        source_hash = source_hashes.get(scenario)
        if values is None:
            failed.append(f"account_risk_invalid_path:{scenario}")
            scenario_metrics[scenario] = {"max_drawdown": None, "passed": False}
            continue
        expected_path_hash = canonical_sha256(values.tolist())
        if (
            not isinstance(source_hash, str)
            or len(source_hash) != 64
            or any(char not in "0123456789abcdef" for char in source_hash)
            or source_hash != expected_path_hash
        ):
            failed.append(f"account_risk_invalid_source_hash:{scenario}")
        drawdown = _max_drawdown(values)
        passed = abs(drawdown) <= policy.stress_path_max_drawdown
        if not passed:
            failed.append(f"account_risk_stress_maxdd:{scenario}")
        scenario_metrics[scenario] = {
            "periods": len(values),
            "max_drawdown": drawdown,
            "passed": passed,
            "source_sha256": source_hash,
            "recomputed_path_sha256": expected_path_hash,
        }
    metrics["stress_paths"] = scenario_metrics

    passed = not failed
    return AccountDeploymentRiskValidation(
        status=(
            policy.applies_to_status
            if passed
            else policy.incomplete_evidence_status
        ),
        absolute_risk_contract_passed=passed,
        capital_eligible=policy.capital_eligible_in_this_phase,
        failed_checks=tuple(dict.fromkeys(failed)),
        metrics=metrics,
    )


__all__ = [
    "AccountDeploymentRiskValidation",
    "evaluate_account_deployment_risk",
]
