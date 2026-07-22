from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.research.evaluation_contract_v2 import (
    EvaluationContractV2Error,
    load_evaluation_contract_v2,
)

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "config/research_governance.yaml"


def _payload() -> dict:
    return {
        "schema_version": 2,
        "protocol_id": "pqs-mining-v5-balanced-v1",
        "governance_policy_id": "pqs-governance-reconciliation-v3",
        "evaluation_start": "2015-01-02",
        "evaluation_end": "2024-12-31",
        "return_dates_sha256": "a" * 64,
        "month_end_dates_sha256": "b" * 64,
        "calendar_years": list(range(2015, 2025)),
        "minimum_history_sessions": 756,
        "float_comparison_tolerance": 1e-12,
        "cost_scenarios": [
            {"name": "base_30bps", "execution_cost_bps": 30.0},
            {"name": "double_60bps", "execution_cost_bps": 60.0},
            {"name": "triple_90bps", "execution_cost_bps": 90.0},
        ],
        "benchmark": {
            "symbol": "SPY",
            "return_basis": "split_and_distribution_adjusted_total_return",
            "cost_policy": "costless_total_return_hurdle",
            "distributions": "reinvested",
            "source_path": "data/research/SPY.parquet",
            "source_sha256": "c" * 64,
            "returns_sha256": "d" * 64,
        },
        "return_gates": {
            "base_30bps_cagr_strictly_greater_than_spy": True,
            "double_60bps_cagr_not_less_than_spy": True,
            "triple_90bps_cagr_role": "diagnostic",
            "rolling_window_months": 36,
            "rolling_sample_at_month_end": True,
            "min_rolling_excess_positive_fraction": 0.60,
            "rolling_252_session_role": "diagnostic",
        },
        "drawdown_gates": {
            "full_period_strictly_better": True,
            "rolling_window_months": 36,
            "rolling_sample_at_month_end": True,
            "min_rolling_win_fraction": 0.60,
            "effective_count_method": "conservative_non_overlapping_36m",
            "material_episode_trigger": 0.15,
            "every_material_episode_strictly_better": True,
            "monthly_downside_capture_strict_max": 1.0,
            "annual_material_harm_max_pp": 3.0,
            "annual_all_years_strict_dominance": False,
            "apply_to_all_cost_scenarios": True,
            "raw_strategy_absolute_cap_enabled": False,
        },
        "account_risk": {
            "research_candidate_gate": False,
            "paper_status_on_incomplete": "SHADOW_PAPER_OBSERVATION",
            "operating_target_min": 0.15,
            "operating_target_max": 0.20,
            "stress_path_max_drawdown": 0.25,
            "required_path_scenarios": [
                "gfc_2008",
                "covid_2020",
                "rate_hike_2022",
            ],
            "terminal_weighted_shock_can_pass": False,
            "capital_eligible_in_this_phase": False,
        },
        "cpcv": {"n_groups": 6, "k_test": 2, "horizon": 63, "embargo_frac": 0.01},
    }


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "contract.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_contract_loads_only_when_it_matches_governance(tmp_path: Path) -> None:
    contract = load_evaluation_contract_v2(
        _write(tmp_path, _payload()), governance_path=POLICY
    )
    assert contract.drawdown_gates.annual_material_harm_max_pp == 3.0
    assert contract.benchmark.cost_policy == "costless_total_return_hurdle"


def test_five_pp_material_harm_budget_is_rejected(tmp_path: Path) -> None:
    payload = _payload()
    payload["drawdown_gates"]["annual_material_harm_max_pp"] = 5.0
    with pytest.raises(EvaluationContractV2Error):
        load_evaluation_contract_v2(_write(tmp_path, payload), governance_path=POLICY)


def test_cost_scenario_order_and_values_are_frozen(tmp_path: Path) -> None:
    payload = _payload()
    payload["cost_scenarios"].reverse()
    with pytest.raises(EvaluationContractV2Error, match="30/60/90"):
        load_evaluation_contract_v2(_write(tmp_path, payload), governance_path=POLICY)
