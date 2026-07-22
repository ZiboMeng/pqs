"""Qualification V4: Balanced Drawdown plus separated account-risk status.

V4 is prospective only.  It binds governance schema v3, evaluation-contract
schema v2, one canonical costless SPY total-return path, the append-only trial
universe, and raw 30/60/90bps candidate paths.  Historical V2/V3 artifacts are
never migrated or re-signed.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from core.research.account_deployment_risk import evaluate_account_deployment_risk
from core.research.composite_trial_universe import (
    CompositeTrialUniverseError,
    composite_trial_snapshot,
    validate_trial_matrix_ids,
)
from core.research.evaluation_contract_v2 import (
    EvaluationContractV2,
    EvaluationContractV2Error,
    load_evaluation_contract_v2,
)
from core.research.governance import load_research_governance
from core.research.qualification_v2 import (
    QualificationV2Error,
    _annualized_return,
    _finite_array,
    canonical_sha256,
    sha256_file,
)
from core.research.qualification_v2 import (
    recompute_qualification as recompute_v2,
)
from core.research.trial_ledger import AppendOnlyTrialLedger

QUALIFICATION_SCHEMA_VERSION = 4
INPUT_SCHEMA_VERSION = 3


class QualificationV4Error(RuntimeError):
    """Raised when prospective V4 evidence is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class QualificationV4Validation:
    candidate_id: str
    artifact_path: str
    artifact_sha256: str
    passed: bool
    failed_checks: tuple[str, ...]
    recomputed: Mapping[str, Any]


def _parse_dates(raw: Any, expected_length: int) -> tuple[date, ...]:
    if not isinstance(raw, list) or len(raw) != expected_length:
        raise QualificationV4Error("dates must align with candidate returns")
    try:
        parsed = tuple(date.fromisoformat(str(value)) for value in raw)
    except ValueError as exc:
        raise QualificationV4Error("dates must be ISO calendar dates") from exc
    if len(set(parsed)) != len(parsed) or any(
        current <= previous for previous, current in zip(parsed, parsed[1:])
    ):
        raise QualificationV4Error("dates must be unique and strictly increasing")
    return parsed


def _max_drawdown(returns: np.ndarray) -> float:
    nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    peaks = np.maximum.accumulate(nav)
    return float(np.min(nav / peaks - 1.0))


def _month_end_indices(dates: tuple[date, ...]) -> tuple[int, ...]:
    return tuple(
        index
        for index, value in enumerate(dates)
        if index == len(dates) - 1
        or (dates[index + 1].year, dates[index + 1].month)
        != (value.year, value.month)
    )


def _month_windows(
    dates: tuple[date, ...], months: int = 36
) -> tuple[tuple[int, int, date], ...]:
    ends = _month_end_indices(dates)
    if len(ends) < months:
        return ()
    windows: list[tuple[int, int, date]] = []
    for position in range(months - 1, len(ends)):
        start = 0 if position == months - 1 else ends[position - months] + 1
        end = ends[position] + 1
        windows.append((start, end, dates[ends[position]]))
    return tuple(windows)


def _rolling_comparison(
    candidate: np.ndarray,
    benchmark: np.ndarray,
    dates: tuple[date, ...],
    *,
    tolerance: float,
) -> dict[str, Any]:
    windows = _month_windows(dates, 36)
    rows: list[dict[str, Any]] = []
    for start, end, window_end in windows:
        candidate_mdd = _max_drawdown(candidate[start:end])
        benchmark_mdd = _max_drawdown(benchmark[start:end])
        candidate_return = float(np.prod(1.0 + candidate[start:end]) - 1.0)
        benchmark_return = float(np.prod(1.0 + benchmark[start:end]) - 1.0)
        rows.append({
            "window_end": window_end.isoformat(),
            "start_index": start,
            "end_index_exclusive": end,
            "candidate_max_drawdown": candidate_mdd,
            "spy_max_drawdown": benchmark_mdd,
            "drawdown_won": abs(candidate_mdd) < abs(benchmark_mdd) - tolerance,
            "candidate_return": candidate_return,
            "spy_return": benchmark_return,
            "excess_positive": candidate_return > benchmark_return,
        })
    drawdown_fraction = (
        float(np.mean([row["drawdown_won"] for row in rows])) if rows else None
    )
    excess_fraction = (
        float(np.mean([row["excess_positive"] for row in rows])) if rows else None
    )
    return {
        "window_months": 36,
        "sample_at_month_end": True,
        "windows": rows,
        "window_count": len(rows),
        "conservative_non_overlapping_effective_count": (
            len(_month_end_indices(dates)) // 36
        ),
        "drawdown_win_fraction": drawdown_fraction,
        "excess_positive_fraction": excess_fraction,
    }


def _benchmark_episodes(
    benchmark: np.ndarray,
    dates: tuple[date, ...],
    *,
    trigger: float,
    tolerance: float,
) -> tuple[tuple[int, int, dict[str, Any]], ...]:
    nav = np.concatenate(([1.0], np.cumprod(1.0 + benchmark)))
    peak_index = 0
    peak_value = 1.0
    active: tuple[int, float] | None = None
    episodes: list[tuple[int, int, dict[str, Any]]] = []
    for nav_index in range(1, len(nav)):
        value = float(nav[nav_index])
        if active is None and value > peak_value:
            peak_index = nav_index
            peak_value = value
        if active is None and value / peak_value - 1.0 <= -trigger:
            active = (peak_index, peak_value)
        if active is not None:
            start_index, recovery_level = active
            if value >= recovery_level - tolerance:
                return_start = start_index
                return_end = nav_index
                episodes.append((
                    return_start,
                    return_end,
                    {
                        "start": dates[max(0, return_start - 1)].isoformat(),
                        "trigger": trigger,
                        "end": dates[return_end - 1].isoformat(),
                        "ended_by": "recovery",
                    },
                ))
                active = None
                peak_index = nav_index
                peak_value = value
    if active is not None:
        start_index, _ = active
        episodes.append((
            start_index,
            len(benchmark),
            {
                "start": dates[max(0, start_index - 1)].isoformat(),
                "trigger": trigger,
                "end": dates[-1].isoformat(),
                "ended_by": "evaluation_end",
            },
        ))
    return tuple(episodes)


def _episode_comparison(
    candidate: np.ndarray,
    benchmark: np.ndarray,
    dates: tuple[date, ...],
    *,
    trigger: float,
    tolerance: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for start, end, metadata in _benchmark_episodes(
        benchmark, dates, trigger=trigger, tolerance=tolerance
    ):
        candidate_mdd = _max_drawdown(candidate[start:end])
        benchmark_mdd = _max_drawdown(benchmark[start:end])
        passed = abs(candidate_mdd) < abs(benchmark_mdd) - tolerance
        rows.append({
            **metadata,
            "start_index": start,
            "end_index_exclusive": end,
            "candidate_max_drawdown": candidate_mdd,
            "spy_max_drawdown": benchmark_mdd,
            "passed": passed,
        })
    return {
        "benchmark_defined": True,
        "material_trigger": trigger,
        "episodes": rows,
        "episode_count": len(rows),
        "passed": bool(rows) and all(row["passed"] for row in rows),
    }


def _monthly_returns(
    returns: np.ndarray, dates: tuple[date, ...]
) -> tuple[tuple[str, float], ...]:
    output: list[tuple[str, float]] = []
    start = 0
    while start < len(dates):
        key = (dates[start].year, dates[start].month)
        end = start + 1
        while end < len(dates) and (dates[end].year, dates[end].month) == key:
            end += 1
        output.append((
            f"{key[0]:04d}-{key[1]:02d}",
            float(np.prod(1.0 + returns[start:end]) - 1.0),
        ))
        start = end
    return tuple(output)


def _downside_capture(
    candidate: np.ndarray,
    benchmark: np.ndarray,
    dates: tuple[date, ...],
    *,
    strict_max: float,
    tolerance: float,
) -> dict[str, Any]:
    candidate_monthly = dict(_monthly_returns(candidate, dates))
    benchmark_monthly = _monthly_returns(benchmark, dates)
    selected = [
        (key, candidate_monthly[key], value)
        for key, value in benchmark_monthly
        if value < 0.0
    ]
    if not selected:
        return {
            "negative_spy_months": 0,
            "downside_capture": None,
            "passed": False,
        }
    periods = len(selected)
    candidate_down = float(
        np.prod([1.0 + row[1] for row in selected]) ** (12.0 / periods) - 1.0
    )
    benchmark_down = float(
        np.prod([1.0 + row[2] for row in selected]) ** (12.0 / periods) - 1.0
    )
    capture = (
        candidate_down / benchmark_down
        if abs(benchmark_down) > tolerance
        else float("inf")
    )
    return {
        "negative_spy_months": periods,
        "candidate_annualized_down_month_return": candidate_down,
        "spy_annualized_down_month_return": benchmark_down,
        "downside_capture": capture,
        "passed": math.isfinite(capture) and capture < strict_max - tolerance,
    }


def _annual_material_harm(
    candidate: np.ndarray,
    benchmark: np.ndarray,
    dates: tuple[date, ...],
    *,
    max_extra_pp: float,
    tolerance: float,
) -> dict[str, Any]:
    years = sorted({value.year for value in dates})
    date_years = np.asarray([value.year for value in dates], dtype=int)
    rows: list[dict[str, Any]] = []
    for year in years:
        mask = date_years == year
        candidate_mdd = _max_drawdown(candidate[mask])
        benchmark_mdd = _max_drawdown(benchmark[mask])
        extra_pp = (abs(candidate_mdd) - abs(benchmark_mdd)) * 100.0
        rows.append({
            "year": year,
            "sessions": int(mask.sum()),
            "candidate_max_drawdown": candidate_mdd,
            "spy_max_drawdown": benchmark_mdd,
            "extra_drawdown_pp": extra_pp,
            "strictly_better_than_spy": (
                abs(candidate_mdd) < abs(benchmark_mdd) - tolerance
            ),
            "passed": extra_pp <= max_extra_pp + tolerance * 100.0,
        })
    return {
        "max_extra_drawdown_pp": max_extra_pp,
        "years": rows,
        "annual_win_fraction_diagnostic": float(np.mean([
            row["strictly_better_than_spy"] for row in rows
        ])),
        "passed": bool(rows) and all(row["passed"] for row in rows),
    }


def _resolve_bound_file(root: Path, reference: Mapping[str, Any], label: str) -> Path:
    try:
        path = (root / str(reference["path"])).resolve()
        path.relative_to(root)
    except (KeyError, ValueError) as exc:
        raise QualificationV4Error(f"{label} must be inside repo") from exc
    if not path.is_file() or sha256_file(path) != reference.get("sha256"):
        raise QualificationV4Error(f"{label} hash mismatch")
    return path


def _validate_contract_and_inputs(
    bundle: Mapping[str, Any],
    parsed_dates: tuple[date, ...],
    benchmark: np.ndarray,
    *,
    repo_root: Path,
    governance_path: Path,
) -> tuple[EvaluationContractV2, Path]:
    reference = bundle.get("evaluation_contract")
    if not isinstance(reference, Mapping):
        raise QualificationV4Error("evaluation_contract is required")
    contract_path = _resolve_bound_file(repo_root, reference, "evaluation contract")
    try:
        contract = load_evaluation_contract_v2(
            contract_path, governance_path=governance_path
        )
    except EvaluationContractV2Error as exc:
        raise QualificationV4Error(str(exc)) from exc
    if parsed_dates[0] != contract.evaluation_start or parsed_dates[-1] != (
        contract.evaluation_end
    ):
        raise QualificationV4Error("return dates differ from evaluation contract")
    date_values = [value.isoformat() for value in parsed_dates]
    if canonical_sha256(date_values) != contract.return_dates_sha256:
        raise QualificationV4Error("return-date index hash differs from contract")
    month_end_values = [
        parsed_dates[index].isoformat() for index in _month_end_indices(parsed_dates)
    ]
    if canonical_sha256(month_end_values) != contract.month_end_dates_sha256:
        raise QualificationV4Error("month-end date index hash differs from contract")
    if tuple(sorted({value.year for value in parsed_dates})) != contract.calendar_years:
        raise QualificationV4Error("calendar years differ from evaluation contract")
    if len(parsed_dates) < contract.minimum_history_sessions:
        raise QualificationV4Error("insufficient history for Qualification V4")
    for year in contract.calendar_years:
        year_dates = [value for value in parsed_dates if value.year == year]
        if year_dates[0].month != 1 or year_dates[-1].month != 12:
            raise QualificationV4Error("V4 calendar years must be complete")
    if canonical_sha256(benchmark.tolist()) != contract.benchmark.returns_sha256:
        raise QualificationV4Error("benchmark returns hash differs from contract")
    benchmark_source = _resolve_bound_file(
        repo_root,
        {
            "path": contract.benchmark.source_path,
            "sha256": contract.benchmark.source_sha256,
        },
        "canonical benchmark source",
    )
    return contract, benchmark_source


def recompute_qualification(
    bundle: Mapping[str, Any],
    *,
    raw_independent_n: int,
    governance_path: str | Path,
    repo_root: str | Path,
) -> dict[str, Any]:
    if bundle.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise QualificationV4Error("unsupported qualification V4 input schema")
    root = Path(repo_root).resolve()
    governance_file = Path(governance_path)
    governance_file = (
        governance_file if governance_file.is_absolute() else root / governance_file
    ).resolve()
    governance = load_research_governance(governance_file)
    if governance.schema_version != 3:
        raise QualificationV4Error("Qualification V4 requires governance schema v3")
    candidate_base = _finite_array(
        bundle.get("candidate_net_returns"), "candidate_net_returns"
    )
    benchmark = _finite_array(
        bundle.get("benchmark_total_returns"), "benchmark_total_returns"
    )
    if len(candidate_base) != len(benchmark):
        raise QualificationV4Error("candidate and benchmark returns must align")
    parsed_dates = _parse_dates(bundle.get("dates"), len(candidate_base))
    contract, benchmark_source = _validate_contract_and_inputs(
        bundle,
        parsed_dates,
        benchmark,
        repo_root=root,
        governance_path=governance_file,
    )
    scenario_names = tuple(item.name for item in contract.cost_scenarios)
    raw_scenarios = bundle.get("cost_stress_returns")
    if not isinstance(raw_scenarios, Mapping) or tuple(raw_scenarios) != scenario_names:
        raise QualificationV4Error("candidate cost scenarios differ from contract")
    scenarios: dict[str, np.ndarray] = {}
    for name in scenario_names:
        values = _finite_array(raw_scenarios.get(name), f"cost_stress_returns[{name}]")
        if len(values) != len(candidate_base):
            raise QualificationV4Error(f"cost scenario {name} is misaligned")
        scenarios[name] = values
    if not np.array_equal(scenarios["base_30bps"], candidate_base):
        raise QualificationV4Error("candidate_net_returns must equal base_30bps")

    v2_bundle = dict(bundle)
    v2_bundle["schema_version"] = 1
    v2_bundle["cost_stress_returns"] = {
        name: values.tolist() for name, values in scenarios.items()
    }
    computed_v2 = recompute_v2(
        v2_bundle,
        raw_independent_n=raw_independent_n,
        governance_path=governance_file,
    )
    tolerance = contract.float_comparison_tolerance
    benchmark_cagr = _annualized_return(benchmark)
    scenario_metrics: dict[str, Any] = {}
    for name, values in scenarios.items():
        rolling = _rolling_comparison(
            values, benchmark, parsed_dates, tolerance=tolerance
        )
        full_candidate_mdd = _max_drawdown(values)
        full_spy_mdd = _max_drawdown(benchmark)
        d1 = abs(full_candidate_mdd) < abs(full_spy_mdd) - tolerance
        d2 = (
            rolling["drawdown_win_fraction"] is not None
            and rolling["drawdown_win_fraction"]
            >= contract.drawdown_gates.min_rolling_win_fraction
        )
        episodes = _episode_comparison(
            values,
            benchmark,
            parsed_dates,
            trigger=contract.drawdown_gates.material_episode_trigger,
            tolerance=tolerance,
        )
        downside = _downside_capture(
            values,
            benchmark,
            parsed_dates,
            strict_max=contract.drawdown_gates.monthly_downside_capture_strict_max,
            tolerance=tolerance,
        )
        annual = _annual_material_harm(
            values,
            benchmark,
            parsed_dates,
            max_extra_pp=contract.drawdown_gates.annual_material_harm_max_pp,
            tolerance=tolerance,
        )
        scenario_metrics[name] = {
            "cagr": _annualized_return(values),
            "cagr_excess_vs_spy": _annualized_return(values) - benchmark_cagr,
            "full_period": {
                "candidate_max_drawdown": full_candidate_mdd,
                "spy_max_drawdown": full_spy_mdd,
                "passed": d1,
            },
            "rolling_36m": rolling,
            "material_episodes": episodes,
            "downside_capture": downside,
            "annual_material_harm": annual,
            "drawdown_gates": {
                "D1_full_period": d1,
                "D2_rolling_36m": d2,
                "D3_material_episodes": episodes["passed"],
                "D4_downside_capture": downside["passed"],
                "D5_annual_material_harm": annual["passed"],
            },
        }

    base = scenario_metrics["base_30bps"]
    double = scenario_metrics["double_60bps"]
    base_return_gate = base["cagr"] > benchmark_cagr + tolerance
    double_return_gate = double["cagr"] >= benchmark_cagr - tolerance
    base_rolling_return_gate = (
        base["rolling_36m"]["excess_positive_fraction"] is not None
        and base["rolling_36m"]["excess_positive_fraction"] >= 0.60
    )
    double_rolling_return_gate = (
        double["rolling_36m"]["excess_positive_fraction"] is not None
        and double["rolling_36m"]["excess_positive_fraction"] >= 0.60
    )
    all_drawdown_gates = all(
        all(metrics["drawdown_gates"].values())
        for metrics in scenario_metrics.values()
    )
    legacy_gates = computed_v2["gates"]
    gates = {
        "base_30bps_cagr_strictly_greater_than_spy": base_return_gate,
        "double_60bps_cagr_not_less_than_spy": double_return_gate,
        "base_30bps_rolling_36m_excess_fraction": base_rolling_return_gate,
        "double_60bps_rolling_36m_excess_fraction": double_rolling_return_gate,
        "balanced_drawdown_all_scenarios": all_drawdown_gates,
        "deflated_sharpe_probability": legacy_gates[
            "deflated_sharpe_probability"
        ],
        "probability_backtest_overfitting": legacy_gates[
            "probability_backtest_overfitting"
        ],
        "minimum_backtest_length": legacy_gates["minimum_backtest_length"],
        "development_return_distribution_stability": legacy_gates[
            "cpcv_return_distribution"
        ],
        "candidate_specific_timing": legacy_gates["candidate_specific_timing"],
    }
    account = evaluate_account_deployment_risk(
        bundle.get("account_deployment_evidence"),
        governance_path=governance_file,
    )
    dsr = computed_v2["overfit"]["deflated_sharpe"]
    dsr["probability_statement"] = (
        "PSR_STATISTIC_FOR_SR_EXCEEDING_MULTIPLE_TESTING_ADJUSTED_SR0"
    )
    dsr["not_probability_true_sharpe_above_zero"] = True
    computed_v2["overfit"]["cpcv"].update({
        "evidence_role": "DEVELOPMENT_STABILITY_DIAGNOSTIC_NOT_OOS",
        "training_legs_used": False,
        "model_refit_per_split": False,
    })
    research_passed = all(gates.values())
    return {
        "candidate_id": bundle.get("candidate_id"),
        "qualification_schema_version": QUALIFICATION_SCHEMA_VERSION,
        "evidence_scope": "DEVELOPMENT_ONLY",
        "raw_independent_n": raw_independent_n,
        "benchmark": {
            "symbol": "SPY",
            "return_basis": contract.benchmark.return_basis,
            "cost_policy": contract.benchmark.cost_policy,
            "source_path": str(benchmark_source.relative_to(root)),
            "source_sha256": contract.benchmark.source_sha256,
            "returns_sha256": contract.benchmark.returns_sha256,
            "cagr": benchmark_cagr,
            "max_drawdown": _max_drawdown(benchmark),
        },
        "candidate": computed_v2["candidate"],
        "active": computed_v2["active"],
        "overfit": computed_v2["overfit"],
        "balanced_drawdown": {
            "annual_all_years_strict_dominance": False,
            "raw_strategy_absolute_cap_enabled": False,
            "scenario_metrics": scenario_metrics,
        },
        "triple_90bps_cagr_excess_diagnostic": scenario_metrics[
            "triple_90bps"
        ]["cagr_excess_vs_spy"],
        "gates": gates,
        "research_qualification_passed": research_passed,
        "qualification_passed": research_passed,
        "formal_research_status": (
            "FORMAL_V5_RESEARCH_CANDIDATE" if research_passed else "REVIEW_HOLD"
        ),
        "account_deployment": {
            "status": account.status,
            "absolute_risk_contract_passed": (
                account.absolute_risk_contract_passed
            ),
            "capital_eligible": account.capital_eligible,
            "failed_checks": list(account.failed_checks),
            "metrics": account.metrics,
        },
        "paper_status": account.status if research_passed else "REVIEW_HOLD",
        "automatic_promotion_eligible": False,
        "capital_eligible": False,
    }


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
        raise QualificationV4Error("qualification inputs must be inside repo") from exc
    try:
        bundle = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationV4Error("qualification input is unreadable") from exc
    if not isinstance(bundle, dict):
        raise QualificationV4Error("qualification input must be a mapping")
    governance = Path(governance_path)
    governance = governance if governance.is_absolute() else root / governance
    governance = governance.resolve()
    governance.relative_to(root)
    contract_path = _resolve_bound_file(
        root, bundle.get("evaluation_contract") or {}, "evaluation contract"
    )
    snapshot = AppendOnlyTrialLedger(ledger).snapshot()
    if snapshot["incomplete_trial_ids"]:
        raise QualificationV4Error("trial ledger contains incomplete trials")
    historical_refs = bundle.get("historical_trial_ledgers") or []
    if not isinstance(historical_refs, list):
        raise QualificationV4Error("historical_trial_ledgers must be a list")
    composite = composite_trial_snapshot(
        repo_root=root,
        current_ledger_path=ledger,
        historical_ledger_refs=historical_refs,
    )
    if composite["incomplete_trial_ids"]:
        raise QualificationV4Error("composite trial universe is incomplete")
    trial_ids = bundle.get("trial_ids")
    if not isinstance(trial_ids, list):
        raise QualificationV4Error("trial_ids must be a list")
    validate_trial_matrix_ids(
        repo_root=root,
        current_ledger_path=ledger,
        historical_ledger_refs=historical_refs,
        trial_ids=[str(value) for value in trial_ids],
    )
    computed = recompute_qualification(
        bundle,
        raw_independent_n=int(composite["raw_independent_n"]),
        governance_path=governance,
        repo_root=root,
    )
    return {
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "candidate_id": bundle.get("candidate_id"),
        "code_commit": code_commit,
        "observed_through": bundle.get("observed_through"),
        "evidence_scope": "DEVELOPMENT_ONLY",
        "automatic_promotion_eligible": False,
        "capital_eligible": False,
        "input_bundle": {
            "path": str(input_relative),
            "sha256": sha256_file(input_path),
        },
        "evaluation_contract": {
            "path": str(contract_path.relative_to(root)),
            "sha256": sha256_file(contract_path),
        },
        "governance": {
            "path": str(governance.relative_to(root)),
            "sha256": sha256_file(governance),
        },
        "trial_ledger": {"path": str(ledger_relative), **snapshot},
        "composite_trial_universe": composite,
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
) -> QualificationV4Validation:
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
            raise QualificationV4Error("artifact is not a mapping")
        if artifact.get("schema_version") != QUALIFICATION_SCHEMA_VERSION:
            failed.append("qualification_schema_not_v4")
        if artifact.get("candidate_id") != expected_candidate_id:
            failed.append("qualification_candidate_mismatch")
        if expected_code_commit is not None and artifact.get("code_commit") != (
            expected_code_commit
        ):
            failed.append("qualification_commit_mismatch")
        input_path = _resolve_bound_file(
            root, artifact.get("input_bundle") or {}, "qualification input"
        )
        ledger_ref = artifact.get("trial_ledger") or {}
        ledger_path = (root / str(ledger_ref.get("path", ""))).resolve()
        ledger_path.relative_to(root)
        bound_governance = _resolve_bound_file(
            root, artifact.get("governance") or {}, "governance"
        )
        if governance_path is not None:
            requested = Path(governance_path)
            requested = requested if requested.is_absolute() else root / requested
            if requested.resolve() != bound_governance:
                failed.append("qualification_governance_path_mismatch")
        bundle = json.loads(input_path.read_text(encoding="utf-8"))
        contract_path = _resolve_bound_file(
            root, bundle.get("evaluation_contract") or {}, "evaluation contract"
        )
        if sha256_file(contract_path) != (
            artifact.get("evaluation_contract") or {}
        ).get("sha256"):
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
        historical_refs = bundle.get("historical_trial_ledgers") or []
        if not isinstance(historical_refs, list):
            raise QualificationV4Error("historical_trial_ledgers must be a list")
        composite = composite_trial_snapshot(
            repo_root=root,
            current_ledger_path=ledger_path,
            historical_ledger_refs=historical_refs,
        )
        if composite != artifact.get("composite_trial_universe"):
            failed.append("qualification_composite_trial_universe_mismatch")
        if composite["incomplete_trial_ids"]:
            failed.append("qualification_composite_trial_universe_incomplete")
        trial_ids = bundle.get("trial_ids")
        if not isinstance(trial_ids, list):
            raise QualificationV4Error("trial_ids must be a list")
        validate_trial_matrix_ids(
            repo_root=root,
            current_ledger_path=ledger_path,
            historical_ledger_refs=historical_refs,
            trial_ids=[str(value) for value in trial_ids],
        )
        recomputed = recompute_qualification(
            bundle,
            raw_independent_n=int(composite["raw_independent_n"]),
            governance_path=bound_governance,
            repo_root=root,
        )
        if canonical_sha256(recomputed) != artifact.get("computed_sha256"):
            failed.append("qualification_recomputed_digest_mismatch")
        if canonical_sha256(artifact.get("computed")) != artifact.get(
            "computed_sha256"
        ):
            failed.append("qualification_reported_metrics_tampered")
        if recomputed.get("research_qualification_passed") is not True:
            failed.append("qualification_canonical_gates_failed")
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        QualificationV2Error,
        QualificationV4Error,
        CompositeTrialUniverseError,
    ) as exc:
        failed.append(f"qualification_unverifiable:{type(exc).__name__}")
    return QualificationV4Validation(
        candidate_id=expected_candidate_id,
        artifact_path=relative,
        artifact_sha256=artifact_sha,
        passed=not failed,
        failed_checks=tuple(dict.fromkeys(failed)),
        recomputed=recomputed,
    )


__all__ = [
    "QualificationV4Error",
    "QualificationV4Validation",
    "_annual_material_harm",
    "_benchmark_episodes",
    "_downside_capture",
    "_episode_comparison",
    "_max_drawdown",
    "_month_end_indices",
    "_rolling_comparison",
    "build_qualification_artifact",
    "recompute_qualification",
    "validate_qualification_artifact",
]
