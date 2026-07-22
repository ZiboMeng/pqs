from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from core.research.governance import (
    GovernanceError,
    assert_sealed_interval_available,
    evaluate_automatic_promotion_benchmark,
    load_research_governance,
    resolve_strategy_governance,
)

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "config/research_governance.yaml"


def test_active_policy_preserves_spy_gate_without_automatic_drop() -> None:
    policy = load_research_governance(POLICY)
    assert policy.schema_version == 3
    assert policy.policy_id == "pqs-governance-reconciliation-v3"
    assert policy.benchmark.primary == "SPY"
    assert policy.benchmark.benchmark_return_basis == (
        "split_and_distribution_adjusted_total_return"
    )
    assert policy.benchmark.benchmark_cost_policy == "costless_total_return_hurdle"
    assert policy.benchmark.automatic_promotion_requires_positive_excess is True
    assert policy.benchmark.automatic_retirement_on_failure is False
    assert policy.benchmark.failure_disposition == "REVIEW_HOLD"
    assert policy.benchmark.risk_matched_passive_required_for_review is True
    assert policy.benchmark.qqq_role == "diagnostic_only"


def test_balanced_drawdown_and_account_risk_contract_are_exact() -> None:
    policy = load_research_governance(POLICY).automatic_promotion_evidence
    drawdown = policy.balanced_drawdown_comparison
    assert drawdown.candidate_cost_scenarios == (
        "base_30bps",
        "double_60bps",
        "triple_90bps",
    )
    assert drawdown.rolling_window_months == 36
    assert drawdown.min_rolling_drawdown_win_fraction == 0.60
    assert drawdown.material_episode_trigger == 0.15
    assert drawdown.annual_material_harm_max_pp == 3.0
    assert drawdown.annual_all_years_strict_dominance is False
    assert drawdown.raw_strategy_absolute_max_drawdown_gate_enabled is False
    account = policy.account_deployment_risk
    assert account.required_path_scenarios == (
        "gfc_2008",
        "covid_2020",
        "rate_hike_2022",
    )
    assert account.stress_path_max_drawdown == 0.25
    assert account.capital_eligible_in_this_phase is False


def test_automatic_benchmark_gate_is_strict_and_basis_bound() -> None:
    passed = evaluate_automatic_promotion_benchmark(
        strategy_cagr=0.11,
        benchmark_cagr=0.10,
        benchmark_symbol="SPY",
        comparison_basis="total_return_after_strategy_costs",
        strategy_costs_included=True,
        path=POLICY,
    )
    assert passed.passed
    equal = evaluate_automatic_promotion_benchmark(
        strategy_cagr=0.10,
        benchmark_cagr=0.10,
        benchmark_symbol="SPY",
        comparison_basis="total_return_after_strategy_costs",
        strategy_costs_included=True,
        path=POLICY,
    )
    assert not equal.passed
    assert equal.disposition == "REVIEW_HOLD"
    wrong_basis = evaluate_automatic_promotion_benchmark(
        strategy_cagr=0.20,
        benchmark_cagr=0.10,
        benchmark_symbol="QQQ",
        comparison_basis="raw_close",
        strategy_costs_included=False,
        path=POLICY,
    )
    assert not wrong_basis.passed


def test_dual_index_is_observation_only_and_never_capital_eligible() -> None:
    decision = resolve_strategy_governance(
        "dual_index_growth_v1",
        "PAPER_APPROVED",
        path=POLICY,
    )
    assert decision.effective_status == "PAPER_OBSERVATION_ONLY"
    assert decision.review_status == "REVIEW_HOLD"
    assert decision.paper_observation_enabled is True
    assert decision.automatic_promotion_eligible is False
    assert decision.capital_eligible is False
    assert len(decision.policy_sha256) == 64
    assert len(decision.decision_sha256) == 64


def test_historical_status_drift_fails_closed() -> None:
    with pytest.raises(GovernanceError, match="historical strategy status drift"):
        resolve_strategy_governance(
            "dual_index_growth_v1",
            "RESEARCH_QUALIFIED",
            path=POLICY,
        )


def test_legacy_split_and_observed_interval_cannot_be_reminted() -> None:
    with pytest.raises(GovernanceError, match="CONSUMED_NOT_PRISTINE"):
        assert_sealed_interval_available(
            split_name="alternating_regime_holdout_v1",
            start="2026-01-01",
            end="2026-07-17",
            path=POLICY,
        )
    with pytest.raises(GovernanceError, match="overlaps observed data"):
        assert_sealed_interval_available(
            split_name="renamed-but-not-new-v99",
            start="2025-01-01",
            end="2026-01-31",
            path=POLICY,
        )


def test_strictly_future_interval_is_not_blocked_by_historical_overlay() -> None:
    assert_sealed_interval_available(
        split_name="semantic-alpha-forward-v1",
        start=date(2026, 7, 20),
        end=date(2027, 7, 20),
        path=POLICY,
    )


def test_unsafe_observation_decision_is_rejected(tmp_path: Path) -> None:
    payload = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    decision = payload["strategy_decisions"][0]
    decision["capital_eligible"] = True
    bad_policy = tmp_path / "bad.yaml"
    bad_policy.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(GovernanceError, match="observation-only strategy"):
        load_research_governance(bad_policy)
