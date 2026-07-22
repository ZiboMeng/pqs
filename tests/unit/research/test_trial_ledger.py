from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.research.trial_ledger import (
    AppendOnlyTrialLedger,
    TrialIntent,
    TrialLedgerError,
)


def _intent(trial_id: str, *, model: str = "xgb", seed: int = 42):
    return TrialIntent(
        trial_id=trial_id,
        hypothesis_family="numeric_rank",
        mechanism_id="cross_sectional_rank",
        universe_hash="u" * 64,
        data_hash="d" * 64,
        config_hash="c" * 64,
        code_commit="a" * 40,
        feature_id="causal_features_v1",
        model_id=model,
        label_id="residual_rank_21d",
        construction_id="spy35_active65",
        cost_id="cost_30bps",
        execution_id="next_open",
        seed=seed,
        period_start="2012-01-01",
        period_end="2026-07-17",
        observed_through="2026-07-17",
    )


def test_register_complete_verify_and_incomplete_summary(tmp_path):
    ledger = AppendOnlyTrialLedger(tmp_path / "trials.jsonl")
    registration = ledger.register_intent(_intent("trial-1"))
    assert registration.independent_trial is True
    assert ledger.independent_trial_count() == 1
    assert ledger.incomplete_trial_ids() == ["trial-1"]
    ledger.record_outcome("trial-1", {"verdict": "FAIL", "sharpe": 0.4})
    assert ledger.incomplete_trial_ids() == []
    assert [event["sequence"] for event in ledger.verified_events()] == [1, 2]


def test_rename_cannot_reset_independent_trial_count(tmp_path):
    ledger = AppendOnlyTrialLedger(tmp_path / "trials.jsonl")
    first = ledger.register_intent(_intent("human-name-a"))
    replay = ledger.register_intent(_intent("renamed-same-content"))
    assert first.content_hash == replay.content_hash
    assert replay.event_type == "REPLAY_INTENT"
    assert replay.independent_trial is False
    assert replay.original_trial_id == "human-name-a"
    assert ledger.independent_trial_count() == 1


def test_same_id_different_content_and_duplicate_outcome_fail_closed(tmp_path):
    ledger = AppendOnlyTrialLedger(tmp_path / "trials.jsonl")
    ledger.register_intent(_intent("trial-1"))
    with pytest.raises(TrialLedgerError, match="different content"):
        ledger.register_intent(_intent("trial-1", model="linear"))
    ledger.record_outcome("trial-1", {"verdict": "PASS"})
    with pytest.raises(TrialLedgerError, match="already exists"):
        ledger.record_outcome("trial-1", {"verdict": "FAIL"})
    with pytest.raises(TrialLedgerError, match="before intent"):
        ledger.record_outcome("missing", {"verdict": "FAIL"})


def test_tamper_and_truncated_line_are_detected(tmp_path):
    path = tmp_path / "trials.jsonl"
    ledger = AppendOnlyTrialLedger(path)
    ledger.register_intent(_intent("trial-1"))
    event = json.loads(path.read_text().splitlines()[0])
    event["payload"]["intent"]["model_id"] = "tampered"
    path.write_text(json.dumps(event) + "\n")
    with pytest.raises(TrialLedgerError, match="hash mismatch"):
        ledger.verified_events()

    truncated = tmp_path / "truncated.jsonl"
    truncated.write_text('{"schema_version":1}')
    with pytest.raises(TrialLedgerError, match="truncated"):
        AppendOnlyTrialLedger(truncated).verified_events()


def test_concurrent_intents_form_one_contiguous_chain(tmp_path):
    ledger = AppendOnlyTrialLedger(tmp_path / "trials.jsonl")

    def register(i: int):
        return ledger.register_intent(_intent(f"trial-{i}", seed=i))

    with ThreadPoolExecutor(max_workers=8) as pool:
        registrations = list(pool.map(register, range(16)))
    assert all(item.independent_trial for item in registrations)
    events = ledger.verified_events()
    assert [event["sequence"] for event in events] == list(range(1, 17))
    assert ledger.independent_trial_count("numeric_rank") == 16


def test_failed_aborted_and_artifact_lifecycle_are_append_only(tmp_path):
    ledger = AppendOnlyTrialLedger(tmp_path / "trials.jsonl")
    ledger.register_intent(_intent("success"))
    ledger.record_started("success")
    ledger.record_outcome("success", {"verdict": "PASS"})
    ledger.bind_artifact(
        "success", path="result.json", sha256="a" * 64,
        artifact_type="trial_result",
    )

    ledger.register_intent(_intent("failed", seed=43))
    ledger.record_failed(
        "failed", error_type="DataError", message="missing borrow snapshot")
    ledger.register_intent(_intent("aborted", seed=44))
    ledger.record_aborted("aborted", reason="pre-registered feasibility gate")

    assert ledger.independent_trial_count() == 3
    assert ledger.incomplete_trial_ids() == []
    snapshot = ledger.snapshot()
    assert snapshot["terminal_counts"] == {
        "OUTCOME": 1, "FAILED": 1, "ABORTED": 1, "INTENT": 0,
    }
    assert snapshot["event_count"] == 8


def test_crash_after_intent_is_recoverable_as_counted_failure(tmp_path):
    ledger = AppendOnlyTrialLedger(tmp_path / "trials.jsonl")
    ledger.register_intent(_intent("crashed"))
    assert ledger.snapshot()["incomplete_trial_ids"] == ["crashed"]
    ledger.record_failed(
        "crashed", error_type="RecoveredProcessCrash", message="no outcome found")
    assert ledger.snapshot()["incomplete_trial_ids"] == []
    assert ledger.independent_trial_count() == 1
