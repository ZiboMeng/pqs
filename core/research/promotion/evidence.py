"""Cryptographically bound evidence for prospective automatic promotion.

The validator deliberately separates a research result from permission to
promote it.  Missing, stale, malformed, or threshold-failing evidence returns
an explicit fail-closed result.  It never converts a manual exception into an
automatic gate pass.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from core.research.governance import load_research_governance


REQUIRED_BOUND_SOURCES = (
    "config/backtest.yaml",
    "config/cost_model.yaml",
    "config/research_governance.yaml",
    "config/risk.yaml",
    "config/strategy_promotion.yaml",
    "config/system.yaml",
    "config/universe.yaml",
    "core/backtest/backtest_engine.py",
    "core/data/cash_distribution_access.py",
    "core/data/exact_cash_total_return.py",
    "core/data/price_access.py",
    "core/execution/cost_model.py",
    "core/factors/factor_generator.py",
    "core/factors/factor_registry.py",
    "core/mining/acceptance_pack.py",
    "core/portfolio/constructor.py",
    "core/research/cpcv_acceptance.py",
    "core/research/label_leakage.py",
    "core/research/overfit_metrics.py",
    "core/research/phase2/promotion.py",
    "core/research/promotion/evidence.py",
    "core/research/temporal_split_acceptance.py",
    "core/signals/strategies/multi_factor.py",
    "scripts/promote_strategy.py",
    "scripts/run_strategy_phase2.py",
)


@dataclass(frozen=True, slots=True)
class PromotionEvidenceValidation:
    candidate_id: str
    artifact_path: str
    artifact_sha256: str
    passed: bool
    failed_checks: tuple[str, ...]
    payload: Mapping[str, Any]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _resolve_reference(repo_root: Path, value: Any) -> Path | None:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        return None
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _repo_relative(repo_root: Path, path: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(repo_root))
    except ValueError:
        return None


def validate_promotion_evidence(
    artifact_path: str | Path | None,
    *,
    expected_candidate_id: str,
    repo_root: str | Path,
    expected_code_commit: str | None = None,
    governance_path: str | Path = "config/research_governance.yaml",
) -> PromotionEvidenceValidation:
    """Validate a promotion-evidence artifact without a silent pass."""

    root = Path(repo_root).resolve()
    failed: list[str] = []
    payload: Mapping[str, Any] = {}
    resolved = _resolve_reference(root, artifact_path)
    artifact_sha = ""
    if resolved is None:
        failed.append("promotion_evidence_missing")
    elif _repo_relative(root, resolved) is None:
        failed.append("promotion_evidence_outside_repo")
    elif not resolved.is_file():
        failed.append("promotion_evidence_not_found")
    else:
        artifact_sha = sha256_file(resolved)
        try:
            decoded = json.loads(resolved.read_text(encoding="utf-8"))
            if isinstance(decoded, dict):
                payload = decoded
            else:
                failed.append("promotion_evidence_not_mapping")
        except (OSError, json.JSONDecodeError):
            failed.append("promotion_evidence_unreadable")

    try:
        governance = load_research_governance(
            root / governance_path
            if not Path(governance_path).is_absolute()
            else governance_path
        )
        policy = governance.automatic_promotion_evidence
    except Exception:
        failed.append("promotion_governance_unavailable")
        policy = None

    if payload:
        if payload.get("schema_version") != 1:
            failed.append("promotion_evidence_schema")
        if payload.get("candidate_id") != expected_candidate_id:
            failed.append("promotion_evidence_candidate_mismatch")
        code_commit = payload.get("code_commit")
        if not isinstance(code_commit, str) or len(code_commit) != 40:
            failed.append("promotion_evidence_commit_invalid")
        elif expected_code_commit is not None and code_commit != expected_code_commit:
            failed.append("promotion_evidence_commit_mismatch")

        benchmark = payload.get("benchmark")
        if not isinstance(benchmark, dict):
            failed.append("promotion_evidence_benchmark_missing")
        else:
            if benchmark.get("symbol") != "SPY":
                failed.append("promotion_evidence_primary_benchmark")
            if benchmark.get("comparison_basis") != "total_return_after_strategy_costs":
                failed.append("promotion_evidence_benchmark_basis")
            if benchmark.get("strategy_costs_included") is not True:
                failed.append("promotion_evidence_strategy_costs")

        lookahead = payload.get("lookahead")
        if not isinstance(lookahead, dict):
            failed.append("lookahead_evidence_missing")
        else:
            if lookahead.get("passed") is not True or lookahead.get("test_exit_code") != 0:
                failed.append("lookahead_tests_failed")
            tests = lookahead.get("tests")
            if not isinstance(tests, list) or not tests:
                failed.append("lookahead_test_scope_missing")
            source_hashes = lookahead.get("source_hashes")
            if not isinstance(source_hashes, dict) or not source_hashes:
                failed.append("lookahead_source_hashes_missing")
            else:
                missing_sources = sorted(
                    set(REQUIRED_BOUND_SOURCES) - set(source_hashes)
                )
                if missing_sources:
                    failed.append(
                        "lookahead_required_sources_missing:"
                        + ",".join(missing_sources)
                    )
                for relative, expected_sha in sorted(source_hashes.items()):
                    source = _resolve_reference(root, relative)
                    if (
                        source is None
                        or _repo_relative(root, source) is None
                        or not source.is_file()
                        or not isinstance(expected_sha, str)
                        or sha256_file(source) != expected_sha
                    ):
                        failed.append(f"lookahead_source_hash_mismatch:{relative}")

        overfit = payload.get("overfit")
        if not isinstance(overfit, dict):
            failed.append("overfit_evidence_missing")
        elif policy is not None:
            honest_n = overfit.get("honest_n_trials")
            if not isinstance(honest_n, int) or isinstance(honest_n, bool) or honest_n < 2:
                failed.append("overfit_honest_n_invalid")
            dsr = _finite_number(overfit.get("deflated_sharpe_probability"))
            if dsr is None or dsr < policy.min_deflated_sharpe_probability:
                failed.append("overfit_dsr_below_threshold")
            pbo = _finite_number(overfit.get("probability_backtest_overfitting"))
            if pbo is None or pbo > policy.max_probability_backtest_overfitting:
                failed.append("overfit_pbo_above_threshold")
            if overfit.get("minimum_backtest_length_passed") is not True:
                failed.append("overfit_minimum_backtest_length_failed")
            if overfit.get("cpcv_passed") is not True:
                failed.append("overfit_cpcv_failed")
            folds = overfit.get("cpcv_n_folds")
            if not isinstance(folds, int) or isinstance(folds, bool) or folds < policy.minimum_cpcv_folds:
                failed.append("overfit_cpcv_folds_insufficient")
            source = _resolve_reference(root, overfit.get("artifact_path"))
            expected_sha = overfit.get("artifact_sha256")
            if (
                source is None
                or _repo_relative(root, source) is None
                or not source.is_file()
                or not isinstance(expected_sha, str)
                or sha256_file(source) != expected_sha
            ):
                failed.append("overfit_source_artifact_mismatch")

        alignment = payload.get("paper_backtest_alignment")
        if not isinstance(alignment, dict):
            failed.append("paper_backtest_alignment_missing")
        elif policy is not None:
            drift = _finite_number(alignment.get("max_equity_drift_bps"))
            if alignment.get("passed") is not True:
                failed.append("paper_backtest_alignment_failed")
            if drift is None or drift > policy.max_paper_backtest_equity_drift_bps:
                failed.append("paper_backtest_alignment_drift")
            reference = _resolve_reference(root, alignment.get("artifact_path"))
            expected_sha = alignment.get("artifact_sha256")
            if (
                reference is None
                or _repo_relative(root, reference) is None
                or not reference.is_file()
                or not isinstance(expected_sha, str)
                or sha256_file(reference) != expected_sha
            ):
                failed.append("paper_backtest_alignment_artifact_mismatch")

    return PromotionEvidenceValidation(
        candidate_id=expected_candidate_id,
        artifact_path=(
            _repo_relative(root, resolved)
            if resolved is not None and _repo_relative(root, resolved) is not None
            else str(resolved) if resolved is not None else ""
        ),
        artifact_sha256=artifact_sha,
        passed=not failed,
        failed_checks=tuple(dict.fromkeys(failed)),
        payload=payload,
    )


__all__ = [
    "PromotionEvidenceValidation",
    "REQUIRED_BOUND_SOURCES",
    "sha256_file",
    "validate_promotion_evidence",
]
