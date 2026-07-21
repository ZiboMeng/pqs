"""Machine-enforced reconciliation of research, promotion, and PAPER authority."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class GovernanceError(RuntimeError):
    """Raised when an action conflicts with the active governance policy."""


class BenchmarkPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: Literal["SPY"]
    comparison_basis: Literal["total_return_after_strategy_costs"]
    automatic_promotion_requires_positive_excess: Literal[True]
    automatic_retirement_on_failure: Literal[False]
    failure_disposition: Literal["REVIEW_HOLD"]
    qqq_role: Literal["diagnostic_only"]
    risk_matched_passive_required_for_review: Literal[True]
    manual_exception_requires_explicit_user_approval: Literal[True]
    manual_exception_must_not_be_relabelled_as_gate_pass: Literal[True]


class AutomaticPromotionEvidencePolicy(BaseModel):
    """Evidence required for a new automatic promotion decision.

    These controls apply prospectively.  Historical artifacts remain
    immutable, but absence of the evidence below can never be interpreted as
    an automatic pass for a new promotion.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    require_bound_artifact: Literal[True]
    require_clean_code_commit: Literal[True]
    require_lookahead_test_pass: Literal[True]
    min_deflated_sharpe_probability: float = Field(ge=0.0, le=1.0)
    max_probability_backtest_overfitting: float = Field(ge=0.0, le=1.0)
    require_minimum_backtest_length_pass: Literal[True]
    require_cpcv_pass: Literal[True]
    minimum_cpcv_folds: int = Field(ge=2)
    require_paper_backtest_alignment: Literal[True]
    max_paper_backtest_equity_drift_bps: float = Field(ge=0.0)
    failure_disposition: Literal["REVIEW_HOLD"]


class ObservedInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    end: date
    status: Literal["OBSERVED_NOT_PRISTINE"]
    forbid_sealed_claim: Literal[True]
    evidence: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered(self) -> "ObservedInterval":
        if self.end < self.start:
            raise ValueError("observed interval end precedes start")
        return self


class ResearchBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_through: date
    next_unseen_session_must_be_after: date
    legacy_split_name: str = Field(min_length=1)
    legacy_split_status: Literal["CONSUMED_NOT_PRISTINE"]
    require_new_protocol_id: Literal[True]
    forbid_name_bump_as_novelty_reset: Literal[True]
    observed_intervals: list[ObservedInterval] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent_cutoff(self) -> "ResearchBoundary":
        if self.next_unseen_session_must_be_after != self.observed_through:
            raise ValueError("next unseen boundary must equal the observed cutoff")
        if max(item.end for item in self.observed_intervals) != self.observed_through:
            raise ValueError("observed intervals do not reach the declared cutoff")
        return self


class StrategyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(min_length=1)
    historical_status: str = Field(min_length=1)
    effective_status: Literal[
        "PAPER_APPROVED", "PAPER_OBSERVATION_ONLY", "REJECTED"
    ]
    review_status: Literal["REVIEW_HOLD"]
    paper_observation_enabled: bool
    automatic_promotion_eligible: bool
    capital_eligible: bool
    reason: str = Field(min_length=20)
    evidence: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _safe_observation_boundary(self) -> "StrategyDecision":
        if self.effective_status == "PAPER_OBSERVATION_ONLY":
            if not self.paper_observation_enabled:
                raise ValueError("observation-only strategy must enable PAPER observation")
            if self.automatic_promotion_eligible or self.capital_eligible:
                raise ValueError("observation-only strategy cannot be promotion/capital eligible")
        if self.effective_status == "REJECTED" and self.paper_observation_enabled:
            raise ValueError("rejected strategy cannot remain PAPER enabled")
        return self


class ForwardAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_runtime: Literal["core/paper_trading/forward_runtime.py"]
    legacy_research_forward_status: Literal["EVIDENCE_ONLY_NOT_EXECUTION_AUTHORITY"]
    source_batch_binding_required_before_real_session: Literal[True]


class CloudPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["PARKED"]
    paid_resource_creation_enabled: Literal[False]
    templates_are_runtime_authority: Literal[False]


class ResearchGovernancePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    policy_id: str = Field(min_length=1)
    approved_at_utc: str = Field(min_length=1)
    authority: Literal["user_explicit_direction"]
    benchmark: BenchmarkPolicy
    automatic_promotion_evidence: AutomaticPromotionEvidencePolicy
    research_boundary: ResearchBoundary
    strategy_decisions: list[StrategyDecision] = Field(min_length=1)
    forward_authority: ForwardAuthority
    cloud: CloudPolicy

    @model_validator(mode="after")
    def _unique_strategy_decisions(self) -> "ResearchGovernancePolicy":
        strategy_ids = [item.strategy_id for item in self.strategy_decisions]
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("governance policy contains duplicate strategy decisions")
        return self


@dataclass(frozen=True, slots=True)
class EffectiveStrategyGovernance:
    strategy_id: str
    historical_status: str
    effective_status: str
    review_status: str
    paper_observation_enabled: bool
    automatic_promotion_eligible: bool
    capital_eligible: bool
    policy_id: str
    policy_sha256: str
    decision_sha256: str


@dataclass(frozen=True, slots=True)
class AutomaticBenchmarkGate:
    benchmark_symbol: str
    comparison_basis: str
    strategy_costs_included: bool
    strategy_cagr: float | None
    benchmark_cagr: float | None
    cagr_excess: float | None
    passed: bool
    disposition: str
    reason: str


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def load_research_governance(
    path: str | Path = "config/research_governance.yaml",
) -> ResearchGovernancePolicy:
    policy_path = Path(path)
    try:
        raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise GovernanceError(f"cannot load research governance policy: {policy_path}") from exc
    if not isinstance(raw, dict):
        raise GovernanceError("research governance policy must be a mapping")
    try:
        return ResearchGovernancePolicy.model_validate(raw)
    except Exception as exc:
        raise GovernanceError(f"invalid research governance policy: {exc}") from exc


def resolve_strategy_governance(
    strategy_id: str,
    historical_status: str,
    *,
    path: str | Path = "config/research_governance.yaml",
) -> EffectiveStrategyGovernance:
    policy = load_research_governance(path)
    matches = [item for item in policy.strategy_decisions if item.strategy_id == strategy_id]
    if len(matches) != 1:
        raise GovernanceError(f"strategy has no unique governance decision: {strategy_id}")
    decision = matches[0]
    if decision.historical_status != historical_status:
        raise GovernanceError(
            f"historical strategy status drift: {historical_status!r} != "
            f"{decision.historical_status!r}"
        )
    policy_payload = policy.model_dump(mode="json")
    decision_payload = decision.model_dump(mode="json")
    return EffectiveStrategyGovernance(
        strategy_id=strategy_id,
        historical_status=historical_status,
        effective_status=decision.effective_status,
        review_status=decision.review_status,
        paper_observation_enabled=decision.paper_observation_enabled,
        automatic_promotion_eligible=decision.automatic_promotion_eligible,
        capital_eligible=decision.capital_eligible,
        policy_id=policy.policy_id,
        policy_sha256=_sha256(policy_payload),
        decision_sha256=_sha256(decision_payload),
    )


def evaluate_automatic_promotion_benchmark(
    *,
    strategy_cagr: object,
    benchmark_cagr: object,
    benchmark_symbol: str,
    comparison_basis: str,
    strategy_costs_included: bool,
    path: str | Path = "config/research_governance.yaml",
) -> AutomaticBenchmarkGate:
    """Apply the project-wide SPY return gate on a declared price basis.

    The comparison is deliberately strict: equality is not outperformance.
    A failure is a ``REVIEW_HOLD`` rather than automatic retirement.
    """

    policy = load_research_governance(path).benchmark

    def finite(value: object) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    strategy = finite(strategy_cagr)
    benchmark = finite(benchmark_cagr)
    symbol = str(benchmark_symbol).upper()
    basis = str(comparison_basis)
    excess = None if strategy is None or benchmark is None else strategy - benchmark
    reasons: list[str] = []
    if symbol != policy.primary:
        reasons.append(f"primary benchmark must be {policy.primary}, got {symbol or 'missing'}")
    if basis != policy.comparison_basis:
        reasons.append(
            f"comparison basis must be {policy.comparison_basis}, got {basis or 'missing'}"
        )
    if strategy_costs_included is not True:
        reasons.append("strategy returns must include costs")
    if excess is None:
        reasons.append("strategy or benchmark CAGR is missing/non-finite")
    elif excess <= 0.0:
        reasons.append(f"SPY CAGR excess must be strictly positive, got {excess:+.8f}")
    passed = not reasons
    return AutomaticBenchmarkGate(
        benchmark_symbol=symbol,
        comparison_basis=basis,
        strategy_costs_included=bool(strategy_costs_included),
        strategy_cagr=strategy,
        benchmark_cagr=benchmark,
        cagr_excess=excess,
        passed=passed,
        disposition="AUTOMATIC_GATE_PASS" if passed else policy.failure_disposition,
        reason="; ".join(reasons) if reasons else "strict positive CAGR excess vs SPY",
    )


def assert_sealed_interval_available(
    *,
    split_name: str,
    start: date | str,
    end: date | str,
    path: str | Path = "config/research_governance.yaml",
) -> None:
    """Refuse any claim that a known/consumed interval is pristine sealed evidence."""

    policy = load_research_governance(path)
    start_date = date.fromisoformat(start) if isinstance(start, str) else start
    end_date = date.fromisoformat(end) if isinstance(end, str) else end
    if end_date < start_date:
        raise GovernanceError("sealed interval end precedes start")
    boundary = policy.research_boundary
    if split_name == boundary.legacy_split_name:
        raise GovernanceError(
            f"sealed split {split_name!r} is {boundary.legacy_split_status}; "
            "renaming or rerunning cannot restore novelty"
        )
    for interval in boundary.observed_intervals:
        overlaps = start_date <= interval.end and end_date >= interval.start
        if overlaps and interval.forbid_sealed_claim:
            raise GovernanceError(
                f"requested sealed interval {start_date}..{end_date} overlaps observed data "
                f"{interval.start}..{interval.end}"
            )
