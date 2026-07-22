"""Prospective qualification with annual SPY-relative drawdown governance.

V3 preserves the independently recomputable V2 statistical panel while
replacing its full-period drawdown-ratio gates with the user-authorized rule:
the candidate must have a strictly smaller after-cost MaxDD magnitude than SPY
in every aligned calendar year and every frozen cost-stress scenario.

Historical V2 artifacts remain immutable historical evidence.  They are not
silently upgraded by this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from core.research.governance import load_research_governance
from core.research.qualification_v2 import (
    QualificationV2Error,
    _finite_array,
    canonical_sha256,
    sha256_file,
)
from core.research.qualification_v2 import (
    recompute_qualification as recompute_v2,
)
from core.research.trial_ledger import AppendOnlyTrialLedger

QUALIFICATION_SCHEMA_VERSION = 3
INPUT_SCHEMA_VERSION = 2


class QualificationV3Error(RuntimeError):
    """Raised when prospective V3 evidence is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class QualificationV3Validation:
    candidate_id: str
    artifact_path: str
    artifact_sha256: str
    passed: bool
    failed_checks: tuple[str, ...]
    recomputed: Mapping[str, Any]


def _parse_dates(raw: Any, expected_length: int) -> tuple[date, ...]:
    if not isinstance(raw, list) or len(raw) != expected_length:
        raise QualificationV3Error("dates must align with candidate returns")
    try:
        parsed = tuple(date.fromisoformat(str(value)) for value in raw)
    except ValueError as exc:
        raise QualificationV3Error("dates must be ISO calendar dates") from exc
    if len(set(parsed)) != len(parsed) or any(
        current <= previous for previous, current in zip(parsed, parsed[1:])
    ):
        raise QualificationV3Error("dates must be unique and strictly increasing")
    return parsed


def _contract_scenario_names(raw: Any) -> tuple[str, ...]:
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(value, str) or not value.strip() for value in raw)
    ):
        raise QualificationV3Error(
            "evaluation contract must freeze cost_stress_scenarios"
        )
    names = tuple(raw)
    if len(names) != len(set(names)):
        raise QualificationV3Error(
            "evaluation contract cost_stress_scenarios contain duplicates"
        )
    return names


def _contract_calendar_years(raw: Any) -> tuple[int, ...]:
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(value, int) for value in raw)
    ):
        raise QualificationV3Error(
            "evaluation contract must freeze calendar_years"
        )
    years = tuple(raw)
    if years != tuple(sorted(set(years))):
        raise QualificationV3Error(
            "evaluation contract calendar_years must be sorted and unique"
        )
    return years


def _validate_evaluation_contract(
    bundle: Mapping[str, Any], parsed_dates: tuple[date, ...]
) -> Mapping[str, Any]:
    contract = bundle.get("evaluation_contract")
    if not isinstance(contract, dict):
        raise QualificationV3Error("evaluation_contract is required")
    if not isinstance(contract.get("path"), str) or not contract["path"].strip():
        raise QualificationV3Error("evaluation_contract.path is required")
    if not isinstance(contract.get("sha256"), str) or len(contract["sha256"]) != 64:
        raise QualificationV3Error("evaluation_contract.sha256 is invalid")
    try:
        start = date.fromisoformat(str(contract.get("evaluation_start")))
        end = date.fromisoformat(str(contract.get("evaluation_end")))
    except ValueError as exc:
        raise QualificationV3Error("evaluation contract dates must be ISO dates") from exc
    if start > parsed_dates[0] or end != parsed_dates[-1]:
        raise QualificationV3Error(
            "evaluation contract does not cover the exact return window"
        )
    _contract_scenario_names(contract.get("cost_stress_scenarios"))
    actual_years = tuple(sorted({value.year for value in parsed_dates}))
    if _contract_calendar_years(contract.get("calendar_years")) != actual_years:
        raise QualificationV3Error(
            "return dates do not cover the frozen evaluation calendar years"
        )
    if contract.get("return_dates_sha256") != canonical_sha256(
        [value.isoformat() for value in parsed_dates]
    ):
        raise QualificationV3Error("return-date index differs from evaluation contract")
    return contract


def _annual_drawdown_comparison(
    candidate: np.ndarray,
    benchmark: np.ndarray,
    dates: tuple[date, ...],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    years = sorted({item.year for item in dates})
    year_values = np.asarray([item.year for item in dates], dtype=int)
    for year in years:
        mask = year_values == year
        candidate_mdd = _max_drawdown(candidate[mask])
        benchmark_mdd = _max_drawdown(benchmark[mask])
        passed = abs(candidate_mdd) < abs(benchmark_mdd)
        rows.append({
            "year": year,
            "sessions": int(mask.sum()),
            "candidate_max_drawdown": candidate_mdd,
            "spy_max_drawdown": benchmark_mdd,
            "candidate_abs_drawdown_improvement": (
                abs(benchmark_mdd) - abs(candidate_mdd)
            ),
            "passed": bool(passed),
        })
    return {
        "comparison": "abs(candidate_max_drawdown) < abs(SPY_max_drawdown)",
        "strict": True,
        "years": rows,
        "failed_years": [row["year"] for row in rows if not row["passed"]],
        "passed": bool(rows) and all(row["passed"] for row in rows),
    }


def _max_drawdown(returns: np.ndarray) -> float:
    """Calendar-window MaxDD including the opening NAV of 1.0."""

    nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    peaks = np.maximum.accumulate(nav)
    return float(np.min(nav / peaks - 1.0))


def recompute_qualification(
    bundle: Mapping[str, Any],
    *,
    raw_independent_n: int,
    governance_path: str | Path,
) -> dict[str, Any]:
    """Recompute V3 from raw returns, ledger raw-N, and bound policy."""

    if bundle.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise QualificationV3Error("unsupported qualification V3 input schema")
    candidate = _finite_array(bundle.get("candidate_net_returns"), "candidate_net_returns")
    benchmark = _finite_array(
        bundle.get("benchmark_total_returns"), "benchmark_total_returns"
    )
    if len(candidate) != len(benchmark):
        raise QualificationV3Error("candidate and benchmark returns must align")
    parsed_dates = _parse_dates(bundle.get("dates"), len(candidate))
    evaluation_contract = _validate_evaluation_contract(bundle, parsed_dates)

    stress_candidate = bundle.get("cost_stress_returns")
    stress_benchmark = bundle.get("cost_stress_benchmark_returns")
    if not isinstance(stress_candidate, dict) or not stress_candidate:
        raise QualificationV3Error("cost_stress_returns is required")
    if not isinstance(stress_benchmark, dict):
        raise QualificationV3Error("cost_stress_benchmark_returns is required")
    if set(stress_candidate) != set(stress_benchmark):
        raise QualificationV3Error("candidate and SPY cost-stress scenarios differ")
    frozen_scenarios = _contract_scenario_names(
        evaluation_contract.get("cost_stress_scenarios")
    )
    if set(stress_candidate) != set(frozen_scenarios):
        raise QualificationV3Error(
            "cost-stress returns do not cover every frozen evaluation scenario"
        )

    # V2 remains the statistical computation source.  Its legacy drawdown
    # gates are removed below; no V2 artifact or digest is modified.
    v2_bundle = dict(bundle)
    v2_bundle["schema_version"] = 1
    computed = recompute_v2(
        v2_bundle,
        raw_independent_n=raw_independent_n,
        governance_path=governance_path,
    )
    governance = load_research_governance(governance_path)
    if governance.schema_version != 2:
        raise QualificationV3Error(
            "Qualification V3 requires historical governance schema v2"
        )
    policy = governance.automatic_promotion_evidence
    drawdown_policy = policy.annual_drawdown_comparison
    if (
        drawdown_policy.absolute_max_drawdown_gate_enabled
        or drawdown_policy.stress_slice_absolute_drawdown_gate_enabled
    ):
        raise QualificationV3Error("V3 forbids hidden absolute drawdown gates")

    annual_base = _annual_drawdown_comparison(candidate, benchmark, parsed_dates)
    stress_results: dict[str, Any] = {}
    for name in sorted(stress_candidate):
        candidate_values = _finite_array(
            stress_candidate[name], f"cost_stress_returns[{name}]"
        )
        benchmark_values = _finite_array(
            stress_benchmark[name], f"cost_stress_benchmark_returns[{name}]"
        )
        if len(candidate_values) != len(candidate) or len(benchmark_values) != len(candidate):
            raise QualificationV3Error(f"cost-stress scenario {name} is misaligned")
        stress_results[str(name)] = _annual_drawdown_comparison(
            candidate_values, benchmark_values, parsed_dates
        )

    gates = {
        name: passed
        for name, passed in computed["gates"].items()
        if name not in {
            "base_drawdown_vs_spy",
            "worst_cost_stress_drawdown_vs_spy",
            "cpcv_return_distribution",
        }
    }
    gates["annual_max_drawdown_strictly_better_than_spy"] = annual_base["passed"]
    gates["annual_cost_stress_max_drawdown_strictly_better_than_spy"] = all(
        item["passed"] for item in stress_results.values()
    )
    gates["development_return_distribution_stability"] = computed["overfit"][
        "cpcv"
    ]["passed"] is True and computed["overfit"]["cpcv"]["n_splits"] >= (
        policy.minimum_cpcv_folds
    )

    dsr = computed["overfit"]["deflated_sharpe"]
    dsr["probability_statement"] = (
        "PSR_STATISTIC_FOR_SR_EXCEEDING_MULTIPLE_TESTING_ADJUSTED_SR0"
    )
    dsr["not_probability_true_sharpe_above_zero"] = True
    computed["overfit"]["cpcv"].update({
        "evidence_role": "DEVELOPMENT_STABILITY_DIAGNOSTIC_NOT_OOS",
        "training_legs_used": False,
        "model_refit_per_split": False,
    })
    computed["qualification_schema_version"] = QUALIFICATION_SCHEMA_VERSION
    computed["drawdown_policy"] = {
        "benchmark": drawdown_policy.benchmark,
        "comparison_basis": drawdown_policy.comparison_basis,
        "require_every_year_strictly_better": True,
        "require_all_cost_stress_scenarios": True,
        "frozen_cost_stress_scenarios": list(frozen_scenarios),
        "absolute_max_drawdown_gate_enabled": False,
        "stress_slice_absolute_drawdown_gate_enabled": False,
    }
    computed["annual_drawdown_vs_spy"] = {
        "base": annual_base,
        "cost_stress": stress_results,
        "full_period_candidate_max_drawdown_diagnostic": _max_drawdown(candidate),
        "full_period_spy_max_drawdown_diagnostic": _max_drawdown(benchmark),
    }
    computed["gates"] = gates
    computed["qualification_passed"] = all(gates.values())
    return computed


def _resolve_bound_file(root: Path, reference: Mapping[str, Any], label: str) -> Path:
    try:
        path = (root / str(reference["path"])).resolve()
        path.relative_to(root)
    except (KeyError, ValueError) as exc:
        raise QualificationV3Error(f"{label} must be inside repo") from exc
    if not path.is_file() or sha256_file(path) != reference.get("sha256"):
        raise QualificationV3Error(f"{label} hash mismatch")
    return path


def _verify_contract_document(path: Path, reference: Mapping[str, Any]) -> None:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise QualificationV3Error("evaluation contract is unreadable") from exc
    if not isinstance(payload, dict):
        raise QualificationV3Error("evaluation contract must be a mapping")
    for key in ("evaluation_start", "evaluation_end"):
        if str(payload.get(key)) != str(reference.get(key)):
            raise QualificationV3Error(
                f"evaluation contract document disagrees on {key}"
            )
    document_scenarios = _contract_scenario_names(
        payload.get("cost_stress_scenarios")
    )
    reference_scenarios = _contract_scenario_names(
        reference.get("cost_stress_scenarios")
    )
    if document_scenarios != reference_scenarios:
        raise QualificationV3Error(
            "evaluation contract document disagrees on cost_stress_scenarios"
        )
    document_years = _contract_calendar_years(payload.get("calendar_years"))
    reference_years = _contract_calendar_years(reference.get("calendar_years"))
    if document_years != reference_years:
        raise QualificationV3Error(
            "evaluation contract document disagrees on calendar_years"
        )
    if payload.get("return_dates_sha256") != reference.get("return_dates_sha256"):
        raise QualificationV3Error(
            "evaluation contract document disagrees on return_dates_sha256"
        )


def build_qualification_artifact(
    *,
    input_bundle_path: str | Path,
    ledger_path: str | Path,
    repo_root: str | Path,
    code_commit: str,
    governance_path: str | Path = "config/research_governance.yaml",
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    input_path = Path(input_bundle_path).resolve()
    ledger = Path(ledger_path).resolve()
    try:
        input_relative = input_path.relative_to(root)
        ledger_relative = ledger.relative_to(root)
    except ValueError as exc:
        raise QualificationV3Error("qualification inputs must be inside repo") from exc
    bundle = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict):
        raise QualificationV3Error("qualification input must be a mapping")
    contract_reference = bundle.get("evaluation_contract") or {}
    contract_path = _resolve_bound_file(root, contract_reference, "evaluation contract")
    _verify_contract_document(contract_path, contract_reference)
    governance = Path(governance_path)
    governance = governance if governance.is_absolute() else root / governance
    governance = governance.resolve()
    governance.relative_to(root)
    snapshot = AppendOnlyTrialLedger(ledger).snapshot()
    if snapshot["incomplete_trial_ids"]:
        raise QualificationV3Error("trial ledger contains incomplete trials")
    computed = recompute_qualification(
        bundle,
        raw_independent_n=int(snapshot["raw_independent_n"]),
        governance_path=governance,
    )
    return {
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "candidate_id": bundle.get("candidate_id"),
        "code_commit": code_commit,
        "observed_through": bundle.get("observed_through"),
        "evidence_scope": "DEVELOPMENT_ONLY",
        "automatic_promotion_eligible": False,
        "input_bundle": {"path": str(input_relative), "sha256": sha256_file(input_path)},
        "evaluation_contract": dict(bundle["evaluation_contract"]),
        "governance": {
            "path": str(governance.relative_to(root)),
            "sha256": sha256_file(governance),
        },
        "trial_ledger": {"path": str(ledger_relative), **snapshot},
        "computed": computed,
        "computed_sha256": canonical_sha256(computed),
    }


def validate_qualification_artifact(
    artifact_path: str | Path,
    *,
    expected_candidate_id: str,
    repo_root: str | Path,
    expected_code_commit: str | None = None,
    governance_path: str | Path | None = None,
) -> QualificationV3Validation:
    root = Path(repo_root).resolve()
    path = Path(artifact_path)
    path = path if path.is_absolute() else root / path
    failed: list[str] = []
    recomputed: Mapping[str, Any] = {}
    artifact_sha = sha256_file(path) if path.is_file() else ""
    try:
        relative = str(path.resolve().relative_to(root))
    except ValueError:
        relative = str(path)
        failed.append("qualification_artifact_outside_repo")
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(artifact, dict):
            raise QualificationV3Error("artifact is not a mapping")
        if artifact.get("schema_version") != QUALIFICATION_SCHEMA_VERSION:
            failed.append("qualification_schema_not_v3")
        if artifact.get("candidate_id") != expected_candidate_id:
            failed.append("qualification_candidate_mismatch")
        if expected_code_commit is not None and artifact.get("code_commit") != expected_code_commit:
            failed.append("qualification_commit_mismatch")
        input_ref = artifact.get("input_bundle") or {}
        ledger_ref = artifact.get("trial_ledger") or {}
        governance_ref = artifact.get("governance") or {}
        input_path = _resolve_bound_file(root, input_ref, "qualification input")
        ledger_path = (root / str(ledger_ref.get("path", ""))).resolve()
        ledger_path.relative_to(root)
        bound_governance_path = _resolve_bound_file(root, governance_ref, "governance")
        if governance_path is not None:
            requested_governance = Path(governance_path)
            requested_governance = (
                requested_governance
                if requested_governance.is_absolute()
                else root / requested_governance
            ).resolve()
            if requested_governance != bound_governance_path:
                failed.append("qualification_governance_path_mismatch")
        bundle = json.loads(input_path.read_text(encoding="utf-8"))
        contract = _resolve_bound_file(
            root, bundle.get("evaluation_contract") or {}, "evaluation contract"
        )
        _verify_contract_document(contract, bundle.get("evaluation_contract") or {})
        if sha256_file(contract) != (artifact.get("evaluation_contract") or {}).get("sha256"):
            failed.append("qualification_evaluation_contract_mismatch")
        snapshot = AppendOnlyTrialLedger(ledger_path).snapshot()
        for key in (
            "ledger_sha256",
            "head_event_hash",
            "event_count",
            "raw_independent_n",
            "independent_content_hashes_sha256",
        ):
            if snapshot.get(key) != ledger_ref.get(key):
                failed.append(f"qualification_ledger_snapshot_mismatch:{key}")
        if snapshot["incomplete_trial_ids"]:
            failed.append("qualification_ledger_incomplete")
        recomputed = recompute_qualification(
            bundle,
            raw_independent_n=int(snapshot["raw_independent_n"]),
            governance_path=bound_governance_path,
        )
        if canonical_sha256(recomputed) != artifact.get("computed_sha256"):
            failed.append("qualification_recomputed_digest_mismatch")
        if canonical_sha256(artifact.get("computed")) != artifact.get("computed_sha256"):
            failed.append("qualification_reported_metrics_tampered")
        if recomputed.get("qualification_passed") is not True:
            failed.append("qualification_canonical_gates_failed")
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        QualificationV2Error,
        QualificationV3Error,
    ) as exc:
        failed.append(f"qualification_unverifiable:{type(exc).__name__}")
    return QualificationV3Validation(
        candidate_id=expected_candidate_id,
        artifact_path=relative,
        artifact_sha256=artifact_sha,
        passed=not failed,
        failed_checks=tuple(dict.fromkeys(failed)),
        recomputed=recomputed,
    )


__all__ = [
    "QualificationV3Error",
    "QualificationV3Validation",
    "build_qualification_artifact",
    "recompute_qualification",
    "validate_qualification_artifact",
]
