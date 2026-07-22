from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from core.research.qualification_v2 import build_qualification_artifact
from core.research.trial_ledger import AppendOnlyTrialLedger, TrialIntent


def write_passing_qualification_v2(
    root: Path,
    *,
    candidate_id: str,
    code_commit: str,
) -> Path:
    ledger_path = root / f"{candidate_id}-trials.jsonl"
    ledger = AppendOnlyTrialLedger(ledger_path)
    for index in range(3):
        trial_id = f"{candidate_id}-trial-{index}"
        ledger.register_intent(TrialIntent(
            trial_id=trial_id,
            hypothesis_family="fixture",
            mechanism_id=f"mechanism-{index}",
            universe_hash="u" * 64,
            data_hash="d" * 64,
            config_hash="c" * 64,
            code_commit=code_commit,
            feature_id=f"feature-{index}",
            model_id=f"model-{index}",
            label_id="daily-return",
            construction_id="long-only",
            cost_id="30bps",
            execution_id="next-open",
            seed=index,
            period_start="2020-01-01",
            period_end="2022-12-31",
            observed_through="2026-07-17",
        ))
        ledger.record_outcome(trial_id, {"status": "PASS"})

    rng = np.random.default_rng(7)
    benchmark = rng.normal(0.00030, 0.0090, 756)
    candidate = 0.00075 + 0.35 * (benchmark - benchmark.mean()) + rng.normal(
        0.0, 0.0025, 756
    )
    bundle = {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "observed_through": "2026-07-17",
        "dates": [f"session-{index:04d}" for index in range(756)],
        "candidate_net_returns": candidate.tolist(),
        "benchmark_total_returns": benchmark.tolist(),
        "trial_ids": [f"{candidate_id}-trial-{index}" for index in range(3)],
        "trial_period_returns": np.column_stack([
            candidate, candidate - 0.00045, candidate - 0.00080,
        ]).tolist(),
        "cost_stress_returns": {
            "base": candidate.tolist(),
            "2x": (candidate - 0.00002).tolist(),
            "3x": (candidate - 0.00004).tolist(),
        },
        "candidate_specific_timing": {
            "prefix_invariance_passed": True,
            "next_session_execution_passed": True,
            "deterministic_replay_passed": True,
            "future_mutation_passed": True,
        },
    }
    input_path = root / f"{candidate_id}-qualification-input.json"
    input_path.write_text(json.dumps(bundle), encoding="utf-8")
    artifact_path = root / f"{candidate_id}-qualification-v2.json"
    artifact = build_qualification_artifact(
        input_bundle_path=input_path,
        ledger_path=ledger_path,
        repo_root=root,
        code_commit=code_commit,
    )
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    return artifact_path
