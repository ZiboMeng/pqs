from __future__ import annotations

from pathlib import Path

import pytest

from core.research.composite_trial_universe import (
    CompositeTrialUniverseError,
    composite_trial_snapshot,
    validate_trial_matrix_ids,
)
from core.research.qualification_v2 import sha256_file
from core.research.trial_ledger import AppendOnlyTrialLedger, TrialIntent


def _intent(trial_id: str, seed: int) -> TrialIntent:
    return TrialIntent(
        trial_id=trial_id,
        hypothesis_family="family",
        mechanism_id="mechanism",
        universe_hash="u" * 64,
        data_hash="d" * 64,
        config_hash="c" * 64,
        code_commit="commit",
        feature_id="feature",
        model_id="model",
        label_id="label",
        construction_id="construction",
        cost_id="cost",
        execution_id="execution",
        seed=seed,
        period_start="2020-01-01",
        period_end="2021-01-01",
        observed_through="2026-07-17",
    )


def test_composite_trial_universe_counts_across_campaigns_and_deduplicates(
    tmp_path: Path,
) -> None:
    historical_path = tmp_path / "historical.jsonl"
    historical = AppendOnlyTrialLedger(historical_path)
    historical.register_intent(_intent("old-a", 1))
    historical.record_outcome("old-a", {"status": "PASS"})
    historical.register_intent(_intent("old-b", 2))
    historical.record_outcome("old-b", {"status": "FAIL"})
    current_path = tmp_path / "current.jsonl"
    current = AppendOnlyTrialLedger(current_path)
    current.register_intent(_intent("renamed-old-a", 1))
    current.record_outcome("renamed-old-a", {"status": "REPLAY"})
    current.register_intent(_intent("new-c", 3))
    current.record_outcome("new-c", {"status": "PASS"})
    snapshot = composite_trial_snapshot(
        repo_root=tmp_path,
        current_ledger_path=current_path,
        historical_ledger_refs=[{
            "path": historical_path.name,
            "sha256": sha256_file(historical_path),
        }],
    )
    assert snapshot["raw_independent_n"] == 3
    assert [row["role"] for row in snapshot["ledgers"]] == [
        "historical", "current"
    ]


def test_historical_ledger_drift_fails_closed(tmp_path: Path) -> None:
    historical_path = tmp_path / "historical.jsonl"
    historical = AppendOnlyTrialLedger(historical_path)
    historical.register_intent(_intent("old-a", 1))
    historical.record_outcome("old-a", {"status": "PASS"})
    expected = sha256_file(historical_path)
    current_path = tmp_path / "current.jsonl"
    current = AppendOnlyTrialLedger(current_path)
    current.register_intent(_intent("new", 2))
    current.record_outcome("new", {"status": "PASS"})
    historical.register_intent(_intent("late", 3))
    historical.record_outcome("late", {"status": "FAIL"})
    with pytest.raises(CompositeTrialUniverseError, match="hash mismatch"):
        composite_trial_snapshot(
            repo_root=tmp_path,
            current_ledger_path=current_path,
            historical_ledger_refs=[{
                "path": historical_path.name,
                "sha256": expected,
            }],
        )


def test_unregistered_trial_matrix_column_fails_closed(tmp_path: Path) -> None:
    current_path = tmp_path / "current.jsonl"
    current = AppendOnlyTrialLedger(current_path)
    current.register_intent(_intent("registered", 1))
    current.record_outcome("registered", {"status": "PASS"})
    with pytest.raises(CompositeTrialUniverseError, match="unregistered"):
        validate_trial_matrix_ids(
            repo_root=tmp_path,
            current_ledger_path=current_path,
            historical_ledger_refs=[],
            trial_ids=["registered", "invented"],
        )
