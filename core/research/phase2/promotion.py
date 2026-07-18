"""Machine-executable strategy promotion gates frozen in YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class CandidateEvidence:
    strategy_id: str
    strategy_type: str
    metrics: Mapping[str, Any]
    benchmark_metrics: Mapping[str, Any]
    robustness: Mapping[str, Any]
    controls: Mapping[str, Any]


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    actual: Any
    required: Any


@dataclass(frozen=True)
class PromotionDecision:
    strategy_id: str
    eligible: bool
    gates: tuple[GateResult, ...] = field(default_factory=tuple)

    @property
    def failed_gates(self) -> tuple[str, ...]:
        return tuple(gate.name for gate in self.gates if not gate.passed)


class PromotionPolicy:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = dict(payload)
        if self.payload.get("schema_version") != 1:
            raise ValueError("unsupported strategy promotion policy schema")
        if not self.payload.get("frozen_before_candidate_results"):
            raise ValueError("promotion policy is not marked frozen")

    @classmethod
    def load(cls, path: str | Path = "config/strategy_promotion.yaml") -> "PromotionPolicy":
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("promotion policy must be a mapping")
        return cls(payload)

    def evaluate(
        self,
        evidence: CandidateEvidence,
        *,
        include_operational: bool = True,
    ) -> PromotionDecision:
        common = self.payload["common_hard_gates"]
        type_gates = self.payload["strategy_type_gates"].get(evidence.strategy_type)
        if type_gates is None:
            raise KeyError(f"unknown strategy type: {evidence.strategy_type}")
        m = evidence.metrics
        b = evidence.benchmark_metrics
        r = evidence.robustness
        c = evidence.controls
        gates: list[GateResult] = []

        def minimum(name: str, actual: Any, required: float) -> None:
            value = float(actual) if actual is not None else float("-inf")
            gates.append(GateResult(name, value >= float(required), actual, required))

        def maximum(name: str, actual: Any, required: float) -> None:
            value = float(actual) if actual is not None else float("inf")
            gates.append(GateResult(name, value <= float(required), actual, required))

        def required_true(name: str, actual: Any) -> None:
            gates.append(GateResult(name, bool(actual), actual, True))

        maximum("unresolved_p0", c.get("unresolved_p0"), common["unresolved_p0_max"])
        maximum("unresolved_research_p1", c.get("unresolved_research_p1"), common["unresolved_research_p1_max"])
        required_true("no_known_lookahead", c.get("no_known_lookahead"))
        minimum("validation_cagr", m.get("cagr"), max(common["min_validation_cagr"], type_gates["min_validation_cagr"]))
        minimum("validation_sharpe", m.get("sharpe"), max(common["min_validation_sharpe"], type_gates["min_validation_sharpe"]))
        minimum("validation_sortino", m.get("sortino"), max(common["min_validation_sortino"], type_gates["min_validation_sortino"]))
        maximum("max_drawdown", abs(float(m.get("max_drawdown", 1.0))), min(common["max_drawdown"], type_gates["max_drawdown"]))
        minimum("calmar", m.get("calmar"), type_gates["min_calmar"])
        minimum("positive_walk_forward_fraction", r.get("positive_walk_forward_fraction"), common["min_positive_walk_forward_fraction"])
        minimum("cost_2x_cagr", r.get("cost_2x_cagr"), common["min_cost_2x_cagr"])
        minimum("cost_2x_sharpe", r.get("cost_2x_sharpe"), common["min_cost_2x_sharpe"])
        minimum("delayed_signal_sharpe", r.get("delayed_signal_sharpe"), common["min_delayed_signal_sharpe"])
        minimum("parameter_neighbor_pass_fraction", r.get("parameter_neighbor_pass_fraction"), common["min_parameter_neighbor_pass_fraction"])
        maximum("single_year_pnl_concentration", m.get("best_year_positive_pnl_fraction"), common["max_single_year_positive_pnl_fraction"])
        maximum("stress_drawdown", abs(float(r.get("worst_stress_drawdown", 1.0))), common["max_stress_drawdown"])
        maximum("annual_turnover", m.get("annual_turnover"), min(common["max_annual_turnover"], type_gates.get("max_annual_turnover", float("inf"))))

        if evidence.strategy_type == "stable_core":
            minimum("market_participation", m.get("market_participation"), type_gates["min_market_participation"])
            minimum(
                "calmar_improvement_vs_spy",
                float(m.get("calmar", 0.0)) - float(b.get("calmar", 0.0)),
                type_gates["min_calmar_improvement_vs_spy"],
            )
            minimum(
                "maxdd_improvement_vs_spy",
                abs(float(b.get("max_drawdown", 0.0))) - abs(float(m.get("max_drawdown", 1.0))),
                type_gates["min_max_drawdown_improvement_vs_spy"],
            )
        elif evidence.strategy_type == "growth_engine":
            minimum(
                "calmar_improvement_vs_qqq",
                float(m.get("calmar", 0.0)) - float(b.get("calmar", 0.0)),
                type_gates["min_calmar_improvement_vs_qqq"],
            )
            maximum("beta_to_qqq", m.get("beta"), type_gates["max_beta_to_qqq"])
            maximum("tqqq_weight", r.get("max_tqqq_weight"), type_gates["max_tqqq_weight"])
            required_true("cooldown_test", c.get("cooldown_test"))
            required_true("risk_on_gate_test", c.get("risk_on_gate_test"))
        elif evidence.strategy_type == "etf_rotation":
            minimum(
                "calmar_improvement_vs_spy",
                float(m.get("calmar", 0.0)) - float(b.get("calmar", 0.0)),
                type_gates["min_calmar_improvement_vs_spy"],
            )
            minimum(
                "maxdd_improvement_vs_spy",
                abs(float(b.get("max_drawdown", 0.0))) - abs(float(m.get("max_drawdown", 1.0))),
                type_gates["min_max_drawdown_improvement_vs_spy"],
            )

        required_true("deterministic_rerun", c.get("deterministic_rerun"))
        required_true("live_disabled", c.get("live_disabled"))
        if include_operational:
            required_true("missing_data_fail_closed", c.get("missing_data_fail_closed"))
            required_true("stale_data_fail_closed", c.get("stale_data_fail_closed"))
            required_true("risk_veto_test", c.get("risk_veto_test"))
            required_true("restart_idempotency_test", c.get("restart_idempotency_test"))
            required_true("paper_replay", c.get("paper_replay"))
        return PromotionDecision(
            strategy_id=evidence.strategy_id,
            eligible=all(gate.passed for gate in gates),
            gates=tuple(gates),
        )
