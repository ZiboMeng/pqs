"""Canonical, independently recomputable candidate qualification evidence.

Version 2 deliberately treats reported metrics as a cache, never as an
authority.  A verifier reloads the immutable return bundle and append-only
trial ledger, recomputes every statistic, and compares a canonical digest.
This prevents a hand-written DSR/PBO boolean from authorizing promotion.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from core.research.cpcv import cpcv_n_paths, cpcv_n_splits, cpcv_splits
from core.research.governance import load_research_governance
from core.research.overfit_metrics import (
    check_min_backtest_length,
    deflated_sharpe_ratio,
    effective_n_trials_onc,
    probability_backtest_overfitting,
)
from core.research.trial_ledger import AppendOnlyTrialLedger

QUALIFICATION_SCHEMA_VERSION = 2
INPUT_SCHEMA_VERSION = 1
TRADING_DAYS = 252.0


class QualificationV2Error(RuntimeError):
    """Raised when qualification evidence is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class QualificationV2Validation:
    candidate_id: str
    artifact_path: str
    artifact_sha256: str
    passed: bool
    failed_checks: tuple[str, ...]
    recomputed: Mapping[str, Any]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _finite_array(value: Any, name: str, *, ndim: int = 1) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim != ndim or array.size == 0:
        raise QualificationV2Error(f"{name} must be a non-empty {ndim}D array")
    if not np.isfinite(array).all():
        raise QualificationV2Error(f"{name} contains NaN/inf")
    if bool((array <= -1.0).any()):
        raise QualificationV2Error(f"{name} contains a return <= -100%")
    return array


def _annualized_return(returns: np.ndarray) -> float:
    return float(np.prod(1.0 + returns) ** (TRADING_DAYS / len(returns)) - 1.0)


def _annualized_sharpe(returns: np.ndarray) -> float:
    standard = float(np.std(returns, ddof=1))
    if len(returns) < 2 or standard <= 0:
        return float("nan")
    return float(np.mean(returns) / standard * math.sqrt(TRADING_DAYS))


def _max_drawdown(returns: np.ndarray) -> float:
    nav = np.cumprod(1.0 + returns)
    peaks = np.maximum.accumulate(nav)
    return float(np.min(nav / peaks - 1.0))


def _newey_west_mean_ci(values: np.ndarray, lag: int = 5) -> dict[str, float]:
    n = len(values)
    mean = float(np.mean(values))
    centered = values - mean
    gamma0 = float(np.dot(centered, centered) / n)
    variance = gamma0
    used_lag = min(max(0, lag), n - 1)
    for step in range(1, used_lag + 1):
        covariance = float(np.dot(centered[step:], centered[:-step]) / n)
        variance += 2.0 * (1.0 - step / (used_lag + 1.0)) * covariance
    standard_error = math.sqrt(max(variance, 0.0) / n)
    return {
        "daily_mean": mean,
        "annualized_mean": mean * TRADING_DAYS,
        "newey_west_lag": used_lag,
        "annualized_ci95_low": (mean - 1.959963984540054 * standard_error) * TRADING_DAYS,
        "annualized_ci95_high": (mean + 1.959963984540054 * standard_error) * TRADING_DAYS,
    }


def _beta_alpha(candidate: np.ndarray, benchmark: np.ndarray) -> dict[str, float]:
    variance = float(np.var(benchmark, ddof=1))
    beta = (
        float(np.cov(candidate, benchmark, ddof=1)[0, 1] / variance)
        if variance > 0 else float("nan")
    )
    alpha_daily = float(np.mean(candidate) - beta * np.mean(benchmark))
    residual = candidate - (alpha_daily + beta * benchmark)
    residual_se = float(np.std(residual, ddof=1) / math.sqrt(len(residual)))
    return {
        "beta": beta,
        "annualized_alpha": alpha_daily * TRADING_DAYS,
        "annualized_alpha_ci95_low": (
            alpha_daily - 1.959963984540054 * residual_se
        ) * TRADING_DAYS,
        "annualized_alpha_ci95_high": (
            alpha_daily + 1.959963984540054 * residual_se
        ) * TRADING_DAYS,
    }


def _rolling_excess_fraction(
    candidate: np.ndarray,
    benchmark: np.ndarray,
    window: int,
) -> float | None:
    if len(candidate) <= window:
        return None
    candidate_nav = np.cumprod(1.0 + candidate)
    benchmark_nav = np.cumprod(1.0 + benchmark)
    candidate_window = candidate_nav[window:] / candidate_nav[:-window] - 1.0
    benchmark_window = benchmark_nav[window:] / benchmark_nav[:-window] - 1.0
    return float(np.mean(candidate_window > benchmark_window))


def _cpcv_return_distribution(
    active_returns: np.ndarray,
    *,
    n_groups: int,
    k_test: int,
    horizon: int,
    embargo_frac: float,
) -> dict[str, Any]:
    fold_means: list[float] = []
    fold_sharpes: list[float | None] = []
    for _, test in cpcv_splits(
        len(active_returns), n_groups, k_test, horizon, embargo_frac
    ):
        values = active_returns[test]
        fold_means.append(float(np.mean(values) * TRADING_DAYS))
        sharpe = _annualized_sharpe(values)
        fold_sharpes.append(sharpe if math.isfinite(sharpe) else None)
    positive_fraction = float(np.mean(np.asarray(fold_means) > 0.0))
    return {
        "n_groups": n_groups,
        "k_test": k_test,
        "n_splits": cpcv_n_splits(n_groups, k_test),
        "n_paths": cpcv_n_paths(n_groups, k_test),
        "horizon": horizon,
        "embargo_frac": embargo_frac,
        "annualized_active_mean_by_split": fold_means,
        "active_sharpe_by_split": fold_sharpes,
        "positive_active_split_fraction": positive_fraction,
        "median_annualized_active_mean": float(np.median(fold_means)),
        "passed": positive_fraction >= 0.60 and float(np.median(fold_means)) > 0.0,
    }


def _validate_input_bundle(bundle: Mapping[str, Any]) -> tuple[np.ndarray, ...]:
    if bundle.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise QualificationV2Error("unsupported qualification input schema")
    candidate = _finite_array(bundle.get("candidate_net_returns"), "candidate_net_returns")
    benchmark = _finite_array(
        bundle.get("benchmark_total_returns"), "benchmark_total_returns"
    )
    matrix = _finite_array(bundle.get("trial_period_returns"), "trial_period_returns", ndim=2)
    dates = bundle.get("dates")
    trial_ids = bundle.get("trial_ids")
    if not isinstance(dates, list) or len(dates) != len(candidate):
        raise QualificationV2Error("dates must align with candidate returns")
    if len(benchmark) != len(candidate) or matrix.shape[0] != len(candidate):
        raise QualificationV2Error("all return inputs must have the same period count")
    if not isinstance(trial_ids, list) or len(trial_ids) != matrix.shape[1]:
        raise QualificationV2Error("trial_ids must align with trial matrix columns")
    if len(set(trial_ids)) != len(trial_ids):
        raise QualificationV2Error("trial_ids contain duplicates")
    if len(candidate) < 252:
        raise QualificationV2Error("qualification requires at least 252 daily periods")
    return candidate, benchmark, matrix


def recompute_qualification(
    bundle: Mapping[str, Any],
    *,
    raw_independent_n: int,
    governance_path: str | Path,
) -> dict[str, Any]:
    """Recompute all binding metrics from raw arrays and the ledger raw N."""

    candidate, benchmark, trial_matrix = _validate_input_bundle(bundle)
    if raw_independent_n < 2:
        raise QualificationV2Error("ledger raw independent N must be at least 2")
    governance = load_research_governance(governance_path)
    policy = governance.automatic_promotion_evidence
    active = candidate - benchmark
    candidate_cagr = _annualized_return(candidate)
    benchmark_cagr = _annualized_return(benchmark)
    candidate_mdd = _max_drawdown(candidate)
    benchmark_mdd = _max_drawdown(benchmark)
    mdd_ratio = (
        abs(candidate_mdd) / abs(benchmark_mdd)
        if abs(benchmark_mdd) > 0 else float("inf")
    )
    sharpe = _annualized_sharpe(candidate)
    trial_sharpes = np.asarray(
        [_annualized_sharpe(trial_matrix[:, index]) / math.sqrt(TRADING_DAYS)
         for index in range(trial_matrix.shape[1])],
        dtype=float,
    )
    finite_trial_sharpes = trial_sharpes[np.isfinite(trial_sharpes)]
    sr_trials_std = (
        float(np.std(finite_trial_sharpes, ddof=1))
        if len(finite_trial_sharpes) >= 2 else None
    )
    dsr = deflated_sharpe_ratio(
        candidate,
        raw_independent_n,
        sr_trials_std=sr_trials_std,
    )
    pbo = probability_backtest_overfitting(trial_matrix)
    min_btl = check_min_backtest_length(
        sharpe,
        raw_independent_n,
        actual_years=len(candidate) / TRADING_DAYS,
    )
    cpcv_cfg = bundle.get("cpcv") or {}
    cpcv = _cpcv_return_distribution(
        active,
        n_groups=int(cpcv_cfg.get("n_groups", 6)),
        k_test=int(cpcv_cfg.get("k_test", 2)),
        horizon=int(cpcv_cfg.get("horizon", 21)),
        embargo_frac=float(cpcv_cfg.get("embargo_frac", 0.01)),
    )
    stress_input = bundle.get("cost_stress_returns")
    if not isinstance(stress_input, dict) or not stress_input:
        raise QualificationV2Error("cost_stress_returns is required")
    stress: dict[str, Any] = {}
    worst_stress_mdd_ratio = 0.0
    for name, raw in sorted(stress_input.items()):
        values = _finite_array(raw, f"cost_stress_returns[{name}]")
        if len(values) != len(candidate):
            raise QualificationV2Error(f"cost stress {name} is misaligned")
        drawdown = _max_drawdown(values)
        ratio = abs(drawdown) / abs(benchmark_mdd) if abs(benchmark_mdd) > 0 else float("inf")
        worst_stress_mdd_ratio = max(worst_stress_mdd_ratio, ratio)
        stress[str(name)] = {
            "cagr": _annualized_return(values),
            "cagr_excess_vs_spy": _annualized_return(values) - benchmark_cagr,
            "max_drawdown": drawdown,
            "max_drawdown_vs_spy_ratio": ratio,
        }
    rolling = _rolling_excess_fraction(candidate, benchmark, 252)
    threshold_doc = bundle.get("freeze_thresholds") or {}
    rolling_min = float(threshold_doc.get("min_positive_rolling_fraction", 0.60))
    max_mdd_ratio = float(threshold_doc.get("max_drawdown_vs_spy_multiplier", 1.25))
    timing = bundle.get("candidate_specific_timing")
    timing_passed = bool(
        isinstance(timing, dict)
        and timing.get("prefix_invariance_passed") is True
        and timing.get("next_session_execution_passed") is True
        and timing.get("deterministic_replay_passed") is True
        and timing.get("future_mutation_passed") is True
    )
    gates = {
        "after_cost_cagr_excess_vs_spy": candidate_cagr > benchmark_cagr,
        "rolling_252d_excess_fraction": rolling is not None and rolling >= rolling_min,
        "base_drawdown_vs_spy": mdd_ratio <= max_mdd_ratio,
        "worst_cost_stress_drawdown_vs_spy": worst_stress_mdd_ratio <= max_mdd_ratio,
        "deflated_sharpe_probability": (
            math.isfinite(float(dsr["deflated_sharpe"]))
            and float(dsr["deflated_sharpe"])
            >= policy.min_deflated_sharpe_probability
        ),
        "probability_backtest_overfitting": (
            math.isfinite(float(pbo["pbo"]))
            and float(pbo["pbo"]) <= policy.max_probability_backtest_overfitting
        ),
        "minimum_backtest_length": min_btl.get("passed") is True,
        "cpcv_return_distribution": (
            cpcv["passed"] is True
            and cpcv["n_splits"] >= policy.minimum_cpcv_folds
        ),
        "candidate_specific_timing": timing_passed,
    }
    effective_n = effective_n_trials_onc(trial_matrix)
    return {
        "candidate_id": bundle.get("candidate_id"),
        "evidence_scope": "DEVELOPMENT_ONLY",
        "automatic_promotion_eligible": False,
        "periods": len(candidate),
        "raw_independent_n": raw_independent_n,
        "successful_trials_in_performance_matrix": int(trial_matrix.shape[1]),
        "effective_n_diagnostic_only": effective_n,
        "candidate": {
            "cagr": candidate_cagr,
            "annualized_sharpe": sharpe,
            "max_drawdown": candidate_mdd,
        },
        "benchmark": {
            "symbol": "SPY",
            "cagr": benchmark_cagr,
            "max_drawdown": benchmark_mdd,
        },
        "active": {
            "cagr_excess_vs_spy": candidate_cagr - benchmark_cagr,
            "rolling_252d_excess_fraction": rolling,
            "max_drawdown_vs_spy_ratio": mdd_ratio,
            "mean_confidence_interval": _newey_west_mean_ci(active),
            "beta_alpha": _beta_alpha(candidate, benchmark),
        },
        "overfit": {
            "deflated_sharpe": dsr,
            "probability_backtest_overfitting": pbo,
            "minimum_backtest_length": min_btl,
            "cpcv": cpcv,
        },
        "cost_stress": stress,
        "worst_cost_stress_drawdown_vs_spy_ratio": worst_stress_mdd_ratio,
        "candidate_specific_timing": timing,
        "gates": gates,
        "qualification_passed": all(gates.values()),
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
        raise QualificationV2Error("qualification inputs must be inside repo") from exc
    bundle = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict):
        raise QualificationV2Error("qualification input must be a mapping")
    snapshot = AppendOnlyTrialLedger(ledger).snapshot()
    if snapshot["incomplete_trial_ids"]:
        raise QualificationV2Error("trial ledger contains incomplete trials")
    computed = recompute_qualification(
        bundle,
        raw_independent_n=int(snapshot["raw_independent_n"]),
        governance_path=root / governance_path,
    )
    return {
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "candidate_id": bundle.get("candidate_id"),
        "code_commit": code_commit,
        "observed_through": bundle.get("observed_through"),
        "evidence_scope": "DEVELOPMENT_ONLY",
        "automatic_promotion_eligible": False,
        "input_bundle": {
            "path": str(input_relative),
            "sha256": sha256_file(input_path),
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
    governance_path: str | Path = "config/research_governance.yaml",
) -> QualificationV2Validation:
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
            raise QualificationV2Error("artifact is not a mapping")
        if artifact.get("schema_version") != QUALIFICATION_SCHEMA_VERSION:
            failed.append("qualification_schema_not_v2")
        if artifact.get("candidate_id") != expected_candidate_id:
            failed.append("qualification_candidate_mismatch")
        if expected_code_commit is not None and artifact.get("code_commit") != expected_code_commit:
            failed.append("qualification_commit_mismatch")
        input_ref = artifact.get("input_bundle") or {}
        ledger_ref = artifact.get("trial_ledger") or {}
        input_path = (root / str(input_ref.get("path", ""))).resolve()
        ledger_path = (root / str(ledger_ref.get("path", ""))).resolve()
        input_path.relative_to(root)
        ledger_path.relative_to(root)
        if sha256_file(input_path) != input_ref.get("sha256"):
            failed.append("qualification_input_hash_mismatch")
        ledger_snapshot = AppendOnlyTrialLedger(ledger_path).snapshot()
        for key in (
            "ledger_sha256",
            "head_event_hash",
            "event_count",
            "raw_independent_n",
            "independent_content_hashes_sha256",
        ):
            if ledger_snapshot.get(key) != ledger_ref.get(key):
                failed.append(f"qualification_ledger_snapshot_mismatch:{key}")
        if ledger_snapshot["incomplete_trial_ids"]:
            failed.append("qualification_ledger_incomplete")
        bundle = json.loads(input_path.read_text(encoding="utf-8"))
        recomputed = recompute_qualification(
            bundle,
            raw_independent_n=int(ledger_snapshot["raw_independent_n"]),
            governance_path=root / governance_path,
        )
        if canonical_sha256(recomputed) != artifact.get("computed_sha256"):
            failed.append("qualification_recomputed_digest_mismatch")
        if canonical_sha256(artifact.get("computed")) != artifact.get("computed_sha256"):
            failed.append("qualification_reported_metrics_tampered")
        if recomputed.get("qualification_passed") is not True:
            failed.append("qualification_canonical_gates_failed")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, QualificationV2Error) as exc:
        failed.append(f"qualification_unverifiable:{type(exc).__name__}")
    return QualificationV2Validation(
        candidate_id=expected_candidate_id,
        artifact_path=relative,
        artifact_sha256=artifact_sha,
        passed=not failed,
        failed_checks=tuple(dict.fromkeys(failed)),
        recomputed=recomputed,
    )


__all__ = [
    "QualificationV2Error",
    "QualificationV2Validation",
    "build_qualification_artifact",
    "canonical_sha256",
    "recompute_qualification",
    "sha256_file",
    "validate_qualification_artifact",
]
