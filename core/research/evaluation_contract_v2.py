"""Frozen evaluation contract for Qualification V4 and Mining V5."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.research.governance import load_research_governance


class EvaluationContractV2Error(RuntimeError):
    """Raised when the V5 evaluation contract is absent or drifts."""


class BenchmarkContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: Literal["SPY"]
    return_basis: Literal["split_and_distribution_adjusted_total_return"]
    cost_policy: Literal["costless_total_return_hurdle"]
    distributions: Literal["reinvested"]
    source_path: str = Field(min_length=1)
    source_sha256: str = Field(min_length=64, max_length=64)
    returns_sha256: str = Field(min_length=64, max_length=64)


class CostScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["base_30bps", "double_60bps", "triple_90bps"]
    execution_cost_bps: Literal[30.0, 60.0, 90.0]


class ReturnGateContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_30bps_cagr_strictly_greater_than_spy: Literal[True]
    double_60bps_cagr_not_less_than_spy: Literal[True]
    triple_90bps_cagr_role: Literal["diagnostic"]
    rolling_window_months: Literal[36]
    rolling_sample_at_month_end: Literal[True]
    min_rolling_excess_positive_fraction: Literal[0.6]
    rolling_252_session_role: Literal["diagnostic"]


class DrawdownGateContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_period_strictly_better: Literal[True]
    rolling_window_months: Literal[36]
    rolling_sample_at_month_end: Literal[True]
    min_rolling_win_fraction: Literal[0.6]
    effective_count_method: Literal["conservative_non_overlapping_36m"]
    material_episode_trigger: Literal[0.15]
    every_material_episode_strictly_better: Literal[True]
    monthly_downside_capture_strict_max: Literal[1.0]
    annual_material_harm_max_pp: Literal[3.0]
    annual_all_years_strict_dominance: Literal[False]
    apply_to_all_cost_scenarios: Literal[True]
    raw_strategy_absolute_cap_enabled: Literal[False]


class AccountRiskContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_candidate_gate: Literal[False]
    paper_status_on_incomplete: Literal["SHADOW_PAPER_OBSERVATION"]
    operating_target_min: Literal[0.15]
    operating_target_max: Literal[0.2]
    stress_path_max_drawdown: Literal[0.25]
    required_path_scenarios: tuple[
        Literal["gfc_2008", "covid_2020", "rate_hike_2022"], ...
    ]
    terminal_weighted_shock_can_pass: Literal[False]
    capital_eligible_in_this_phase: Literal[False]


class CPCVContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_groups: int = Field(ge=3)
    k_test: int = Field(ge=1)
    horizon: int = Field(ge=1)
    embargo_frac: float = Field(ge=0.0, le=0.5)


class EvaluationContractV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    protocol_id: str = Field(min_length=1)
    governance_policy_id: Literal["pqs-governance-reconciliation-v3"]
    evaluation_start: date
    evaluation_end: date
    return_dates_sha256: str = Field(min_length=64, max_length=64)
    month_end_dates_sha256: str = Field(min_length=64, max_length=64)
    calendar_years: tuple[int, ...]
    minimum_history_sessions: int = Field(ge=756)
    float_comparison_tolerance: float = Field(gt=0.0, le=1e-8)
    cost_scenarios: tuple[CostScenario, ...]
    benchmark: BenchmarkContract
    return_gates: ReturnGateContract
    drawdown_gates: DrawdownGateContract
    account_risk: AccountRiskContract
    cpcv: CPCVContract

    @model_validator(mode="after")
    def _internally_consistent(self) -> "EvaluationContractV2":
        if self.evaluation_end < self.evaluation_start:
            raise ValueError("evaluation end precedes start")
        if self.calendar_years != tuple(sorted(set(self.calendar_years))):
            raise ValueError("calendar years must be sorted and unique")
        expected_costs = (
            ("base_30bps", 30.0),
            ("double_60bps", 60.0),
            ("triple_90bps", 90.0),
        )
        actual_costs = tuple(
            (item.name, item.execution_cost_bps) for item in self.cost_scenarios
        )
        if actual_costs != expected_costs:
            raise ValueError("cost scenarios must be ordered 30/60/90bps")
        if self.account_risk.required_path_scenarios != (
            "gfc_2008",
            "covid_2020",
            "rate_hike_2022",
        ):
            raise ValueError("account risk path scenarios drifted")
        return self


def load_evaluation_contract_v2(
    path: str | Path,
    *,
    governance_path: str | Path = "config/research_governance.yaml",
) -> EvaluationContractV2:
    contract_path = Path(path)
    try:
        payload = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EvaluationContractV2Error(
            f"cannot load evaluation contract: {contract_path}"
        ) from exc
    if not isinstance(payload, dict):
        raise EvaluationContractV2Error("evaluation contract must be a mapping")
    try:
        contract = EvaluationContractV2.model_validate(payload)
        governance = load_research_governance(governance_path)
        if governance.schema_version != 3:
            raise ValueError("V2 evaluation contract requires governance schema v3")
        if contract.governance_policy_id != governance.policy_id:
            raise ValueError("evaluation contract governance policy ID drifted")
        drawdown = governance.automatic_promotion_evidence.balanced_drawdown_comparison
        if contract.drawdown_gates.min_rolling_win_fraction != (
            drawdown.min_rolling_drawdown_win_fraction
        ):
            raise ValueError("rolling drawdown threshold differs from governance")
        if contract.drawdown_gates.annual_material_harm_max_pp != (
            drawdown.annual_material_harm_max_pp
        ):
            raise ValueError("annual material-harm budget differs from governance")
        if contract.benchmark.return_basis != governance.benchmark.benchmark_return_basis:
            raise ValueError("benchmark return basis differs from governance")
        if contract.benchmark.cost_policy != governance.benchmark.benchmark_cost_policy:
            raise ValueError("benchmark cost policy differs from governance")
        account = governance.automatic_promotion_evidence.account_deployment_risk
        if contract.account_risk.stress_path_max_drawdown != (
            account.stress_path_max_drawdown
        ):
            raise ValueError("account stress cap differs from governance")
        return contract
    except Exception as exc:
        if isinstance(exc, EvaluationContractV2Error):
            raise
        raise EvaluationContractV2Error(
            f"invalid evaluation contract: {exc}"
        ) from exc


__all__ = [
    "EvaluationContractV2",
    "EvaluationContractV2Error",
    "load_evaluation_contract_v2",
]
