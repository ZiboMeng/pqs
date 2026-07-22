from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from core.research.qualification_v2 import canonical_sha256, sha256_file
from core.research.qualification_v4 import (
    _annual_material_harm,
    _episode_comparison,
    _month_end_indices,
    build_qualification_artifact,
    validate_qualification_artifact,
)
from core.research.trial_ledger import AppendOnlyTrialLedger, TrialIntent

ROOT = Path(__file__).resolve().parents[3]


def _write_fixture(
    tmp_path: Path,
    *,
    candidate_id: str = "fixture-balanced-v5",
    with_account_risk: bool = False,
) -> tuple[Path, Path, Path]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    governance_path = config_dir / "research_governance.yaml"
    shutil.copyfile(ROOT / "config/research_governance.yaml", governance_path)

    dates_index = pd.bdate_range("2016-01-01", "2024-12-31")
    dates = tuple(item.date() for item in dates_index)
    rng = np.random.default_rng(20260722)
    benchmark = rng.normal(0.00030, 0.0085, len(dates))
    # Guarantee a benchmark-defined material episode with a later recovery.
    benchmark[900:905] = -0.048
    benchmark[905:930] = 0.011
    candidate = (
        0.00085
        + 0.20 * (benchmark - float(np.mean(benchmark)))
        + rng.normal(0.0, 0.0018, len(dates))
    )
    scenarios = {
        "base_30bps": candidate,
        "double_60bps": candidate - 0.000002,
        "triple_90bps": candidate - 0.000004,
    }

    source_path = tmp_path / "benchmark-source.json"
    source_path.write_text(
        json.dumps({
            "dates": [value.isoformat() for value in dates],
            "total_returns": benchmark.tolist(),
        }),
        encoding="utf-8",
    )
    date_values = [value.isoformat() for value in dates]
    month_ends = [
        dates[index].isoformat() for index in _month_end_indices(dates)
    ]
    contract = {
        "schema_version": 2,
        "protocol_id": "fixture-mining-v5-balanced-v1",
        "governance_policy_id": "pqs-governance-reconciliation-v3",
        "evaluation_start": dates[0].isoformat(),
        "evaluation_end": dates[-1].isoformat(),
        "return_dates_sha256": canonical_sha256(date_values),
        "month_end_dates_sha256": canonical_sha256(month_ends),
        "calendar_years": list(range(2016, 2025)),
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
            "source_path": source_path.name,
            "source_sha256": sha256_file(source_path),
            "returns_sha256": canonical_sha256(benchmark.tolist()),
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
        "cpcv": {
            "n_groups": 6,
            "k_test": 2,
            "horizon": 63,
            "embargo_frac": 0.01,
        },
    }
    contract_path = tmp_path / "evaluation-contract-v2.yaml"
    contract_path.write_text(
        yaml.safe_dump(contract, sort_keys=False), encoding="utf-8"
    )

    ledger_path = tmp_path / "trial-ledger.jsonl"
    ledger = AppendOnlyTrialLedger(ledger_path)
    trial_ids: list[str] = []
    for index in range(3):
        trial_id = f"{candidate_id}-trial-{index}"
        trial_ids.append(trial_id)
        ledger.register_intent(TrialIntent(
            trial_id=trial_id,
            hypothesis_family="fixture-balanced",
            mechanism_id=f"mechanism-{index}",
            universe_hash="u" * 64,
            data_hash="d" * 64,
            config_hash="c" * 64,
            code_commit="fixture-commit",
            feature_id=f"feature-{index}",
            model_id=f"model-{index}",
            label_id="daily-return",
            construction_id="long-only",
            cost_id="30-60-90bps",
            execution_id="next-open",
            seed=index,
            period_start=dates[0].isoformat(),
            period_end=dates[-1].isoformat(),
            observed_through="2026-07-17",
        ))
        ledger.record_outcome(trial_id, {"status": "PASS"})

    bundle = {
        "schema_version": 3,
        "candidate_id": candidate_id,
        "observed_through": "2026-07-17",
        "dates": date_values,
        "evaluation_contract": {
            "path": contract_path.name,
            "sha256": sha256_file(contract_path),
        },
        "candidate_net_returns": candidate.tolist(),
        "benchmark_total_returns": benchmark.tolist(),
        "trial_ids": trial_ids,
        "trial_period_returns": np.column_stack([
            candidate,
            candidate - 0.00010,
            candidate - 0.00020,
        ]).tolist(),
        "cost_stress_returns": {
            name: values.tolist() for name, values in scenarios.items()
        },
        "cpcv": contract["cpcv"],
        "candidate_specific_timing": {
            "prefix_invariance_passed": True,
            "next_session_execution_passed": True,
            "deterministic_replay_passed": True,
            "future_mutation_passed": True,
        },
    }
    if with_account_risk:
        bundle["account_deployment_evidence"] = {
            "evidence_type": "daily_path_returns",
            "path_capable": True,
            "terminal_weighted_shock_only": False,
            "operating_max_drawdown_target": 0.18,
            "runtime_thresholds": {
                "alert": 0.15,
                "derisk": 0.20,
                "halt": 0.25,
            },
            "next_session_execution_passed": True,
            "future_mutation_passed": True,
            "deterministic_replay_passed": True,
            "paper_replay_passed": True,
            "stress_path_returns": {
                "gfc_2008": [0.01, -0.08, -0.07, 0.04, 0.03],
                "covid_2020": [0.00, -0.10, -0.06, 0.08, 0.04],
                "rate_hike_2022": [0.01, -0.05, -0.04, 0.02, 0.01],
            },
            "path_source_sha256": {
                "gfc_2008": canonical_sha256(
                    [0.01, -0.08, -0.07, 0.04, 0.03]
                ),
                "covid_2020": canonical_sha256(
                    [0.00, -0.10, -0.06, 0.08, 0.04]
                ),
                "rate_hike_2022": canonical_sha256(
                    [0.01, -0.05, -0.04, 0.02, 0.01]
                ),
            },
        }
    input_path = tmp_path / "qualification-input-v3.json"
    input_path.write_text(json.dumps(bundle), encoding="utf-8")
    artifact = build_qualification_artifact(
        input_bundle_path=input_path,
        ledger_path=ledger_path,
        repo_root=tmp_path,
        code_commit="fixture-commit",
        governance_path=governance_path,
    )
    artifact_path = tmp_path / "qualification-v4.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    return artifact_path, input_path, governance_path


def test_v4_recomputes_all_balanced_gates_and_fails_closed_to_shadow(
    tmp_path: Path,
) -> None:
    artifact_path, _, governance_path = _write_fixture(tmp_path)
    validation = validate_qualification_artifact(
        artifact_path,
        expected_candidate_id="fixture-balanced-v5",
        expected_code_commit="fixture-commit",
        repo_root=tmp_path,
        governance_path=governance_path,
    )
    assert validation.passed, validation.failed_checks
    assert validation.recomputed["research_qualification_passed"] is True
    assert validation.recomputed["paper_status"] == "SHADOW_PAPER_OBSERVATION"
    assert validation.recomputed["account_deployment"][
        "absolute_risk_contract_passed"
    ] is False
    for metrics in validation.recomputed["balanced_drawdown"][
        "scenario_metrics"
    ].values():
        assert all(metrics["drawdown_gates"].values())


def test_exact_three_pp_annual_harm_is_allowed_but_more_is_not() -> None:
    dates = (pd.Timestamp("2024-01-02").date(), pd.Timestamp("2024-01-03").date())
    benchmark = np.asarray([0.0, 0.0])
    at_limit = _annual_material_harm(
        np.asarray([-0.03, 0.0]),
        benchmark,
        dates,
        max_extra_pp=3.0,
        tolerance=1e-12,
    )
    above_limit = _annual_material_harm(
        np.asarray([-0.030001, 0.0]),
        benchmark,
        dates,
        max_extra_pp=3.0,
        tolerance=1e-12,
    )
    assert at_limit["passed"] is True
    assert above_limit["passed"] is False


def test_candidate_path_cannot_change_benchmark_defined_episode_boundaries() -> None:
    dates = tuple(item.date() for item in pd.bdate_range("2020-01-02", periods=12))
    benchmark = np.asarray([0.02, 0.01, -0.08, -0.09, 0.03, 0.04, 0.05, 0.06,
                            0.02, 0.01, 0.0, 0.0])
    first = _episode_comparison(
        np.zeros(len(benchmark)), benchmark, dates, trigger=0.15, tolerance=1e-12
    )
    second = _episode_comparison(
        np.asarray([0.10, -0.20] * 6),
        benchmark,
        dates,
        trigger=0.15,
        tolerance=1e-12,
    )
    first_boundaries = [
        (row["start_index"], row["end_index_exclusive"])
        for row in first["episodes"]
    ]
    second_boundaries = [
        (row["start_index"], row["end_index_exclusive"])
        for row in second["episodes"]
    ]
    assert first_boundaries == second_boundaries
    assert first_boundaries


def test_benchmark_mutation_breaks_contract_binding(tmp_path: Path) -> None:
    artifact_path, input_path, governance_path = _write_fixture(tmp_path)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    payload["benchmark_total_returns"][0] += 0.000001
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    # Rebind only the outer input hash to demonstrate that the contract's
    # independent benchmark-return hash is the controlling check.
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["input_bundle"]["sha256"] = sha256_file(input_path)
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    validation = validate_qualification_artifact(
        artifact_path,
        expected_candidate_id="fixture-balanced-v5",
        repo_root=tmp_path,
        governance_path=governance_path,
    )
    assert validation.passed is False
    assert any("QualificationV4Error" in item for item in validation.failed_checks)
