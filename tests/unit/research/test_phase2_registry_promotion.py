from __future__ import annotations

import json

import pytest

from core.research.phase2.promotion import CandidateEvidence, PromotionPolicy
from core.research.phase2.registry import ExperimentRegistry, ExperimentSpec


def _spec(commit: str = "abc123") -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id="phase2-a-001",
        strategy_family="adaptive_core",
        strategy_version="v1",
        hypothesis="bounded test",
        parameters={"volatility_target": 0.12},
        data_range={"start": "2008-01-01", "end": "2016-12-30"},
        cost_model="config/cost_model.yaml",
        benchmark="SPY",
        code_commit=commit,
    )


def test_experiment_must_be_planned_and_is_never_hidden(tmp_path) -> None:
    path = tmp_path / "registry.json"
    registry = ExperimentRegistry(path)
    registry.preregister([_spec()])
    assert registry.get("phase2-a-001")["status"] == "PLANNED"
    registry.mark_running("phase2-a-001")
    registry.complete(
        "phase2-a-001",
        result_path="research/results/a.json",
        key_metrics={"cagr": 0.1},
        passed=False,
        failure_reason="gate",
    )
    record = registry.get("phase2-a-001")
    assert record["status"] == "COMPLETED"
    assert record["pass_fail"] == "FAIL"
    assert json.loads(path.read_text())["experiments"][0]["failure_reason"] == "gate"
    with pytest.raises(ValueError, match="specification drift"):
        registry.preregister([_spec("different")])


def test_unregistered_experiment_cannot_start(tmp_path) -> None:
    with pytest.raises(KeyError):
        ExperimentRegistry(tmp_path / "registry.json").mark_running("not-planned")


def test_frozen_promotion_policy_is_executable() -> None:
    policy = PromotionPolicy.load()
    evidence = CandidateEvidence(
        strategy_id="adaptive_core_v1",
        strategy_type="stable_core",
        metrics={
            "cagr": 0.08,
            "sharpe": 0.80,
            "sortino": 1.0,
            "max_drawdown": -0.12,
            "calmar": 0.67,
            "market_participation": 0.80,
            "best_year_positive_pnl_fraction": 0.30,
            "annual_turnover": 1.0,
        },
        benchmark_metrics={"calmar": 0.30, "max_drawdown": -0.30},
        robustness={
            "positive_walk_forward_fraction": 0.80,
            "cost_2x_cagr": 0.07,
            "cost_2x_sharpe": 0.70,
            "delayed_signal_sharpe": 0.60,
            "parameter_neighbor_pass_fraction": 0.70,
            "worst_stress_drawdown": -0.15,
        },
        controls={
            "unresolved_p0": 0,
            "unresolved_research_p1": 0,
            "no_known_lookahead": True,
            "missing_data_fail_closed": True,
            "stale_data_fail_closed": True,
            "deterministic_rerun": True,
            "risk_veto_test": True,
            "restart_idempotency_test": True,
            "paper_replay": True,
            "live_disabled": True,
        },
    )
    decision = policy.evaluate(evidence)
    assert decision.eligible, decision.failed_gates


def test_promotion_policy_rejects_missing_operational_evidence() -> None:
    decision = PromotionPolicy.load().evaluate(
        CandidateEvidence(
            strategy_id="adaptive_core_v1",
            strategy_type="stable_core",
            metrics={},
            benchmark_metrics={},
            robustness={},
            controls={},
        )
    )
    assert not decision.eligible
    assert "paper_replay" in decision.failed_gates
