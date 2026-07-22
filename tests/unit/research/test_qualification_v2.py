from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

from core.research.qualification_v2 import (
    build_qualification_artifact,
    validate_qualification_artifact,
)
from core.research.trial_ledger import AppendOnlyTrialLedger, TrialIntent

ROOT = Path(__file__).resolve().parents[3]


def _intent(trial_id: str, seed: int) -> TrialIntent:
    return TrialIntent(
        trial_id=trial_id,
        hypothesis_family="fixture",
        mechanism_id=f"mechanism-{seed}",
        universe_hash="u" * 64,
        data_hash="d" * 64,
        config_hash="c" * 64,
        code_commit="a" * 40,
        feature_id=f"features-{seed}",
        model_id=f"model-{seed}",
        label_id="daily-return",
        construction_id="long-only",
        cost_id="30bps",
        execution_id="next-open",
        seed=seed,
        period_start="2020-01-01",
        period_end="2022-12-31",
        observed_through="2026-07-17",
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    (tmp_path / "config").mkdir(parents=True)
    shutil.copy(ROOT / "config/research_governance.yaml", tmp_path / "config")
    ledger_path = tmp_path / "trials.jsonl"
    ledger = AppendOnlyTrialLedger(ledger_path)
    for index in range(3):
        trial_id = f"trial-{index}"
        ledger.register_intent(_intent(trial_id, index))
        ledger.record_started(trial_id)
        ledger.record_outcome(trial_id, {"status": "PASS"})

    rng = np.random.default_rng(7)
    benchmark = rng.normal(0.00030, 0.0090, 756)
    candidate = 0.00075 + 0.35 * (benchmark - benchmark.mean()) + rng.normal(
        0.0, 0.0025, 756
    )
    weaker = candidate - 0.00045
    weakest = candidate - 0.00080
    bundle = {
        "schema_version": 1,
        "candidate_id": "candidate-1",
        "observed_through": "2026-07-17",
        "dates": [f"session-{index:04d}" for index in range(756)],
        "candidate_net_returns": candidate.tolist(),
        "benchmark_total_returns": benchmark.tolist(),
        "trial_ids": ["trial-0", "trial-1", "trial-2"],
        "trial_period_returns": np.column_stack(
            [candidate, weaker, weakest]
        ).tolist(),
        "cost_stress_returns": {
            "base": candidate.tolist(),
            "2x": (candidate - 0.00002).tolist(),
            "3x": (candidate - 0.00004).tolist(),
        },
        "cpcv": {
            "n_groups": 6,
            "k_test": 2,
            "horizon": 21,
            "embargo_frac": 0.01,
        },
        "candidate_specific_timing": {
            "prefix_invariance_passed": True,
            "next_session_execution_passed": True,
            "deterministic_replay_passed": True,
            "future_mutation_passed": True,
        },
    }
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(bundle), encoding="utf-8")
    artifact_path = tmp_path / "qualification.json"
    artifact = build_qualification_artifact(
        input_bundle_path=input_path,
        ledger_path=ledger_path,
        repo_root=tmp_path,
        code_commit="a" * 40,
    )
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    return input_path, ledger_path, artifact_path


def test_v2_recomputes_and_passes_from_raw_inputs(tmp_path: Path) -> None:
    _, _, artifact = _fixture(tmp_path)
    result = validate_qualification_artifact(
        artifact,
        expected_candidate_id="candidate-1",
        expected_code_commit="a" * 40,
        repo_root=tmp_path,
    )
    assert result.passed, result.failed_checks
    assert result.recomputed["raw_independent_n"] == 3
    assert result.recomputed["overfit"]["cpcv"]["n_splits"] == 15
    assert result.recomputed["overfit"]["cpcv"]["n_paths"] == 5


def test_hand_edited_gate_cannot_create_pass(tmp_path: Path) -> None:
    _, _, artifact = _fixture(tmp_path)
    payload = json.loads(artifact.read_text())
    payload["computed"]["gates"]["probability_backtest_overfitting"] = False
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_qualification_artifact(
        artifact, expected_candidate_id="candidate-1", repo_root=tmp_path
    )
    assert not result.passed
    assert "qualification_reported_metrics_tampered" in result.failed_checks


def test_raw_return_or_ledger_append_invalidates_artifact(tmp_path: Path) -> None:
    input_path, ledger_path, artifact = _fixture(tmp_path)
    payload = json.loads(input_path.read_text())
    payload["candidate_net_returns"][10] += 0.01
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    changed_input = validate_qualification_artifact(
        artifact, expected_candidate_id="candidate-1", repo_root=tmp_path
    )
    assert not changed_input.passed
    assert "qualification_input_hash_mismatch" in changed_input.failed_checks

    # Restore a clean fixture and prove that an extra failed/pruned trial also
    # changes raw N and invalidates the frozen ledger head.
    _, ledger_path, artifact = _fixture(tmp_path / "second")
    ledger = AppendOnlyTrialLedger(ledger_path)
    ledger.register_intent(_intent("trial-3", 3))
    ledger.record_failed("trial-3", error_type="DataError", message="missing")
    changed_ledger = validate_qualification_artifact(
        artifact,
        expected_candidate_id="candidate-1",
        repo_root=tmp_path / "second",
    )
    assert not changed_ledger.passed
    assert any(
        item.startswith("qualification_ledger_snapshot_mismatch")
        for item in changed_ledger.failed_checks
    )
