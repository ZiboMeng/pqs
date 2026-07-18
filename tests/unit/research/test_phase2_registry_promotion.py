from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from core.research.phase2.paper_promotion import promote
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


def test_invalidated_experiment_is_retained_with_reason(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "registry.json")
    registry.preregister([_spec()])
    registry.mark_running("phase2-a-001")
    registry.complete(
        "phase2-a-001",
        result_path="bad.json",
        key_metrics={"cagr": 0.0},
        passed=False,
    )
    registry.invalidate("phase2-a-001", "insufficient asset history")
    record = registry.get("phase2-a-001")
    assert record["status"] == "INVALIDATED"
    assert record["pass_fail"] == "INVALID"
    assert record["invalidation_reason"] == "insufficient asset history"


def test_decision_correction_preserves_audit_history(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "registry.json")
    registry.preregister([_spec()])
    registry.mark_running("phase2-a-001")
    registry.complete(
        "phase2-a-001",
        result_path="result.json",
        key_metrics={"cagr": 0.1},
        passed=True,
    )
    registry.correct_completion_decision(
        "phase2-a-001",
        passed=False,
        reason="FULL_POLICY_GATE_FAILED",
    )
    record = registry.get("phase2-a-001")
    assert record["status"] == "COMPLETED"
    assert record["pass_fail"] == "FAIL"
    assert record["failure_reason"] == "FULL_POLICY_GATE_FAILED"
    assert record["decision_corrections"][0]["prior_pass_fail"] == "PASS"


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


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _paper_promotion_fixture(tmp_path: Path) -> dict[str, object]:
    validation = tmp_path / "validation.json"
    holdout = tmp_path / "holdout.json"
    operational = tmp_path / "operational.json"
    strategies = tmp_path / "strategies.json"
    promotions = tmp_path / "promotions.json"
    config_paths = tuple(
        tmp_path / name for name in ("strategy.yaml", "portfolio.yaml", "regime.yaml")
    )
    for path in config_paths:
        path.write_text(
            yaml.safe_dump({"schema_version": 1, "mode": "PAPER", "live_enabled": False}),
            encoding="utf-8",
        )
    metrics = {
        "cagr": 0.10,
        "sharpe": 0.80,
        "sortino": 1.0,
        "max_drawdown": -0.12,
        "calmar": 0.80,
        "best_year_positive_pnl_fraction": 0.30,
        "annual_turnover": 2.0,
        "beta": 0.40,
    }
    robustness = {
        "positive_walk_forward_fraction": 0.80,
        "cost_2x_cagr": 0.08,
        "cost_2x_sharpe": 0.70,
        "delayed_signal_sharpe": 0.60,
        "parameter_neighbor_pass_fraction": 0.70,
        "worst_stress_drawdown": -0.15,
        "max_tqqq_weight": 0.0,
    }
    controls = {
        "unresolved_p0": 0,
        "unresolved_research_p1": 0,
        "no_known_lookahead": True,
        "deterministic_rerun": True,
        "live_disabled": True,
        "cooldown_test": True,
        "risk_on_gate_test": True,
    }
    operational_controls = {
        "missing_data_fail_closed": True,
        "stale_data_fail_closed": True,
        "risk_veto_test": True,
        "restart_idempotency_test": True,
        "paper_replay": True,
        "live_disabled": True,
    }
    _write_json(
        validation,
        {
            "schema_version": 1,
            "evaluation_start": "2017-01-03",
            "evaluation_end": "2023-12-29",
            "families": {
                "dual_index_growth": {
                    "strategy_id": "dual_index_growth_v1",
                    "research_gate_pass": True,
                    "controls": controls,
                }
            },
        },
    )
    _write_json(
        holdout,
        {
            "schema_version": 1,
            "evaluation_start": "2024-01-02",
            "evaluation_end": "2026-07-17",
            "families": {
                "dual_index_growth": {
                    "strategy_id": "dual_index_growth_v1",
                    "holdout_gate_pass": True,
                    "logic_frozen_after_access": True,
                    "metrics": metrics,
                    "benchmark_metrics": {"calmar": 0.30},
                    "validation_robustness": robustness,
                }
            },
        },
    )
    _write_json(
        operational,
        {
            "schema_version": 1,
            "strategy_id": "dual_index_growth_v1",
            "code_commit": "tested",
            "status": "PASS",
            "checks": {"faults": True},
            "operational_controls": operational_controls,
        },
    )
    _write_json(
        strategies,
        {
            "schema_version": 1,
            "strategies": [
                {
                    "strategy_id": "dual_index_growth_v1",
                    "strategy_type": "growth_engine",
                    "status": "RESEARCH_QUALIFIED",
                    "live_enabled": False,
                    "promotion_evidence": {},
                }
            ],
        },
    )
    _write_json(promotions, {"schema_version": 1, "promotions": []})
    return {
        "policy_path": Path("config/strategy_promotion.yaml"),
        "validation_path": validation,
        "holdout_path": holdout,
        "operational_path": operational,
        "strategy_registry_path": strategies,
        "promotion_registry_path": promotions,
        "config_paths": config_paths,
        "code_commit": "candidate",
    }


def test_paper_promotion_is_complete_and_idempotent(tmp_path: Path) -> None:
    paths = _paper_promotion_fixture(tmp_path)
    first = promote(**paths)  # type: ignore[arg-type]
    second = promote(**paths)  # type: ignore[arg-type]
    assert first == second
    assert first["decision"] == "PAPER_APPROVED"
    strategy_registry = json.loads(Path(paths["strategy_registry_path"]).read_text())
    assert strategy_registry["strategies"][0]["status"] == "PAPER_APPROVED"
    promotion_registry = json.loads(Path(paths["promotion_registry_path"]).read_text())
    assert len(promotion_registry["promotions"]) == 1


def test_paper_promotion_fails_closed_on_missing_control(tmp_path: Path) -> None:
    paths = _paper_promotion_fixture(tmp_path)
    operational_path = Path(paths["operational_path"])
    operational = json.loads(operational_path.read_text())
    operational["operational_controls"]["restart_idempotency_test"] = False
    _write_json(operational_path, operational)
    with pytest.raises(RuntimeError, match="restart_idempotency_test"):
        promote(**paths)  # type: ignore[arg-type]
    strategy_registry = json.loads(Path(paths["strategy_registry_path"]).read_text())
    assert strategy_registry["strategies"][0]["status"] == "RESEARCH_QUALIFIED"
