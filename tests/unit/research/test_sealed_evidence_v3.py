from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from core.research.sealed_evidence import (
    HypothesisRegistration,
    SealedBatchInput,
    SealedBudgetError,
    SealedBudgetPolicy,
    SealedChainError,
    SealedEvaluationError,
    SealedEvaluator,
    SealedEvidenceStore,
    SealedGovernance,
    SealedSubmission,
    load_hypothesis_registry,
)

ARTIFACT_PATH = (
    "research/registries/strategy_artifacts/dual_index_growth_v1/observation_v1.json"
)
ARTIFACT_ROOT = "21a268f103295c0b11243f4264885844b019cdeeab8da89106e83d91a3b306ee"
EVENT_TIME = datetime(2026, 7, 21, 20, 0, tzinfo=UTC)


def _batch(batch_id: str = "batch-1", **changes) -> SealedBatchInput:
    values = {
        "batch_id": batch_id,
        "source": "future-forward-authority",
        "event_time": EVENT_TIME,
        "available_time": EVENT_TIME + timedelta(minutes=5),
        "received_time": EVENT_TIME + timedelta(minutes=6),
        "data_schema": "sealed_artifact_returns_v1",
        "rows": [
            {
                "session": "2026-07-20",
                "artifact_root_sha256": ARTIFACT_ROOT,
                "strategy_return": 0.01,
                "benchmark_return": 0.005,
            },
            {
                "session": "2026-07-21",
                "artifact_root_sha256": ARTIFACT_ROOT,
                "strategy_return": -0.002,
                "benchmark_return": -0.004,
            },
        ],
    }
    values.update(changes)
    return SealedBatchInput(**values)


def _policy(**changes) -> SealedBudgetPolicy:
    values = {
        "policy_id": "sealed-budget-v1",
        "global_attempts": 20,
        "family_attempts": 10,
        "lineage_attempts": 4,
        "artifact_version_attempts": 4,
    }
    values.update(changes)
    return SealedBudgetPolicy(**values)


def _hypothesis(hypothesis_id: str = "hypothesis-1", **changes):
    values = {
        "hypothesis_id": hypothesis_id,
        "family_id": "defensive-allocation",
        "lineage_id": "lineage-economic-idea-1",
        "title": "Future defensive allocation evidence",
        "economic_rationale": "Lower exposure during independently observed stress.",
        "eligible_data_start": date(2026, 7, 20),
        "evidence_origin": "FUTURE_UNSEEN",
    }
    values.update(changes)
    return HypothesisRegistration(**values)


def _submission(submission_id: str = "submission-1", **changes):
    values = {
        "submission_id": submission_id,
        "hypothesis_id": "hypothesis-1",
        "artifact_path": ARTIFACT_PATH,
        "artifact_id": "dual_index_growth_v1",
        "artifact_version": "v1",
        "artifact_root_sha256": ARTIFACT_ROOT,
        "sealed_batch_id": "batch-1",
        "metric_policy_id": "daily_return_summary_v1",
        "benchmark_policy_id": "spy_total_return_after_costs_v1",
        "cost_policy_id": "frozen_artifact_cost_v1",
    }
    values.update(changes)
    return SealedSubmission(**values)


def _governance(tmp_path: Path, policy: SealedBudgetPolicy | None = None):
    governance = SealedGovernance(
        tmp_path / "governance.db",
        policy or _policy(),
    )
    governance.preregister(
        _hypothesis(),
        now=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
    )
    governance.register_submission(
        _submission(),
        now=datetime(2026, 7, 20, 12, 1, tzinfo=UTC),
    )
    return governance


def _evaluator(tmp_path: Path, store, governance, **changes):
    values = {
        "repo_root": Path.cwd(),
        "store": store,
        "governance": governance,
        "results_directory": tmp_path / "results",
        "worker_path": "core/research/sealed_worker.py",
        "metric_policies": {
            "daily_return_summary_v1": {
                "annualization_sessions": 252,
                "minimum_sessions": 2,
                "maximum_drawdown_abs": 0.25,
                "minimum_sharpe": -10.0,
                "maximum_beta": 10.0,
                "maximum_annualized_volatility": 10.0,
            }
        },
        "allowed_benchmark_policies": ["spy_total_return_after_costs_v1"],
        "allowed_cost_policies": ["frozen_artifact_cost_v1"],
    }
    values.update(changes)
    return SealedEvaluator(**values)


def test_store_appends_verifies_reuses_and_links_revisions(tmp_path) -> None:
    store = SealedEvidenceStore(tmp_path / "sealed")
    first = store.append(_batch())
    assert first.sequence == 1
    assert first.previous_record_sha256 == "0" * 64
    assert store.append(_batch()).reused is True
    second = store.append(
        _batch(
            "batch-2",
            revision_of="batch-1",
            rows=[
                {
                    "session": "2026-07-20",
                    "artifact_root_sha256": ARTIFACT_ROOT,
                    "strategy_return": 0.011,
                    "benchmark_return": 0.005,
                }
            ],
        )
    )
    assert second.sequence == 2
    assert second.previous_record_sha256 == first.record_sha256
    assert second.revision_of == "batch-1"
    assert [item.batch_id for item in store.verify_chain()] == ["batch-1", "batch-2"]


def test_store_rejects_conflicts_traversal_symlinks_and_chain_tamper(tmp_path) -> None:
    store = SealedEvidenceStore(tmp_path / "sealed")
    first = store.append(_batch())
    with pytest.raises(SealedChainError, match="different content"):
        store.append(_batch(rows=[]))
    with pytest.raises(ValueError, match="unsafe batch id"):
        _batch("../escape")
    with pytest.raises(SealedChainError, match="parent does not exist"):
        store.append(_batch("batch-2", revision_of="absent"))

    record = next((tmp_path / "sealed" / "journal").iterdir())
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["source"] = "tampered"
    os.chmod(record, 0o600)
    record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SealedChainError, match="content hash"):
        store.verify_chain()
    assert first.record_sha256 in record.name

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "linked-store"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(Exception, match="symlink"):
        SealedEvidenceStore(link)


def test_store_concurrent_appends_have_one_contiguous_chain(tmp_path) -> None:
    store = SealedEvidenceStore(tmp_path / "sealed")
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda number: store.append(_batch(f"batch-{number}")),
                range(1, 9),
            )
        )
    assert len(results) == 8
    chain = store.verify_chain()
    assert [item.sequence for item in chain] == list(range(1, 9))
    assert len({item.record_sha256 for item in chain}) == 8


def test_store_rejects_unexpected_files_and_duplicate_record_keys(tmp_path) -> None:
    store = SealedEvidenceStore(tmp_path / "unexpected")
    (store.journal / "notes.txt").write_text("not a record", encoding="utf-8")
    with pytest.raises(SealedChainError, match="unexpected entries"):
        store.verify_chain()

    duplicate_store = SealedEvidenceStore(tmp_path / "duplicate")
    record = duplicate_store.journal / f"{1:012d}_{'0' * 64}.json"
    record.write_text('{"sequence":1,"sequence":1}', encoding="utf-8")
    with pytest.raises(SealedChainError, match="duplicate JSON key"):
        duplicate_store.verify_chain()


def test_budget_policy_and_alias_lineage_are_immutable(tmp_path) -> None:
    policy = _policy(lineage_attempts=2, artifact_version_attempts=10)
    governance = _governance(tmp_path, policy)
    governance.preregister(
        _hypothesis("hypothesis-alias"),
        now=datetime(2026, 7, 20, 12, 2, tzinfo=UTC),
    )
    governance.register_submission(
        _submission(
            "submission-alias",
            hypothesis_id="hypothesis-alias",
        )
    )
    governance.reserve_attempt("submission-1")
    governance.reserve_attempt("submission-alias")
    with pytest.raises(SealedBudgetError, match="lineage"):
        governance.reserve_attempt("submission-alias")
    with pytest.raises(SealedBudgetError, match="policy drift"):
        SealedGovernance(tmp_path / "governance.db", replace(policy, lineage_attempts=3))


def test_preregistration_conflicts_and_family_hopping_are_audited(tmp_path) -> None:
    governance = _governance(tmp_path)
    with pytest.raises(Exception, match="different preregistration"):
        governance.preregister(
            _hypothesis(economic_rationale="Changed after registration."),
        )
    with pytest.raises(Exception, match="cannot move between families"):
        governance.preregister(
            _hypothesis(
                "hypothesis-alias",
                family_id="new-family",
            )
        )
    event_types = [item["event_type"] for item in governance.audit_events()]
    assert "HYPOTHESIS_CONFLICT_REJECTED" in event_types
    assert "HYPOTHESIS_LINEAGE_REJECTED" in event_types


def test_concurrent_budget_reservation_cannot_overspend(tmp_path) -> None:
    governance = _governance(
        tmp_path,
        _policy(global_attempts=2, lineage_attempts=10, artifact_version_attempts=10),
    )

    def reserve():
        try:
            return governance.reserve_attempt("submission-1").attempt_id
        except SealedBudgetError:
            return "BLOCKED"

    with ThreadPoolExecutor(max_workers=6) as executor:
        outcomes = list(executor.map(lambda _: reserve(), range(6)))
    assert sum(value != "BLOCKED" for value in outcomes) == 2
    assert governance.status()["global_counted_attempts"] == 2


def test_only_explicit_infrastructure_failure_refunds_budget(tmp_path) -> None:
    governance = _governance(tmp_path)
    failed = governance.reserve_attempt("submission-1")
    governance.complete_attempt(
        failed.attempt_id,
        status="EVALUATION_FAILED",
        error_category="INVALID_DATA",
    )
    infrastructure = governance.reserve_attempt("submission-1")
    governance.complete_attempt(
        infrastructure.attempt_id,
        status="INFRASTRUCTURE_FAILED",
        error_category="WORKER_TIMEOUT",
        infrastructure_refund=True,
    )
    attempts = governance.attempts()
    assert [item["counted"] for item in attempts] == [1, 0]
    assert governance.status()["global_counted_attempts"] == 1


def test_evaluator_returns_only_fixed_summary_and_duplicate_consumes_budget(
    tmp_path,
    monkeypatch,
) -> None:
    store = SealedEvidenceStore(tmp_path / "sealed")
    store.append(_batch())
    governance = _governance(tmp_path)
    evaluator = _evaluator(tmp_path, store, governance)
    monkeypatch.setenv("PQS_TEST_SECRET", "must-not-cross-worker-boundary")

    first = evaluator.evaluate("submission-1")
    assert first["reused"] is False
    assert first["raw_rows_returned"] is False
    assert first["summary"]["n_sessions"] == 2
    assert '"rows":' not in json.dumps(first)
    assert "must-not-cross" not in json.dumps(first)

    duplicate = evaluator.evaluate("submission-1")
    assert duplicate["reused"] is True
    assert duplicate["attempt_id"] != duplicate["original_attempt_id"]
    statuses = [item["status"] for item in governance.attempts()]
    assert statuses == ["SUCCEEDED", "DUPLICATE"]
    result_files = list((tmp_path / "results").rglob("*.json"))
    assert len(result_files) == 1
    rendered = result_files[0].read_text(encoding="utf-8")
    assert "strategy_return" not in rendered
    assert "2026-07-20" not in rendered


def test_invalid_worker_data_is_counted_and_returns_no_raw_detail(tmp_path) -> None:
    store = SealedEvidenceStore(tmp_path / "sealed")
    store.append(
        _batch(
            rows=[
                {
                    "session": "2026-07-21",
                    "artifact_root_sha256": "b" * 64,
                    "strategy_return": 0.01,
                    "benchmark_return": 0.005,
                }
            ]
        )
    )
    governance = _governance(tmp_path)
    evaluator = _evaluator(tmp_path, store, governance)
    with pytest.raises(SealedEvaluationError, match="worker rejected"):
        evaluator.evaluate("submission-1")
    attempt = governance.attempts()[0]
    assert attempt["status"] == "EVALUATION_FAILED"
    assert attempt["counted"] == 1
    assert "strategy_return" not in json.dumps(governance.audit_events())


@pytest.mark.parametrize(
    "rows",
    [
        [
            {
                "session": "2026-07-21",
                "artifact_root_sha256": ARTIFACT_ROOT,
                "strategy_return": 0.01,
                "benchmark_return": 0.005,
            },
            {
                "session": "2026-07-20",
                "artifact_root_sha256": ARTIFACT_ROOT,
                "strategy_return": 0.01,
                "benchmark_return": 0.005,
            },
        ],
        [
            {
                "session": "2026-07-21",
                "artifact_root_sha256": ARTIFACT_ROOT,
                "strategy_return": -1.0,
                "benchmark_return": 0.005,
            }
        ],
    ],
)
def test_worker_rejects_out_of_order_or_impossible_returns(tmp_path, rows) -> None:
    store = SealedEvidenceStore(tmp_path / "sealed")
    store.append(_batch(rows=rows))
    governance = _governance(tmp_path)
    evaluator = _evaluator(tmp_path, store, governance)
    with pytest.raises(SealedEvaluationError, match="worker rejected"):
        evaluator.evaluate("submission-1")
    assert governance.attempts()[0]["counted"] == 1


def test_hypothesis_registered_after_event_is_counted_failure(tmp_path) -> None:
    store = SealedEvidenceStore(tmp_path / "sealed")
    store.append(_batch())
    governance = SealedGovernance(tmp_path / "governance.db", _policy())
    governance.preregister(
        _hypothesis(),
        now=EVENT_TIME + timedelta(seconds=1),
    )
    governance.register_submission(_submission(), now=EVENT_TIME + timedelta(seconds=2))
    evaluator = _evaluator(tmp_path, store, governance)
    with pytest.raises(SealedEvaluationError, match="registered after"):
        evaluator.evaluate("submission-1")
    assert governance.attempts()[0]["status"] == "EVALUATION_FAILED"


def test_evaluator_policy_is_frozen_with_worker_and_metric_hashes(tmp_path) -> None:
    store = SealedEvidenceStore(tmp_path / "sealed")
    governance = _governance(tmp_path)
    _evaluator(tmp_path, store, governance)
    with pytest.raises(SealedEvaluationError, match="policy drift"):
        _evaluator(
            tmp_path,
            store,
            governance,
            metric_policies={
                "daily_return_summary_v1": {
                    "annualization_sessions": 252,
                    "minimum_sessions": 99,
                    "maximum_drawdown_abs": 0.25,
                    "minimum_sharpe": -10.0,
                    "maximum_beta": 10.0,
                    "maximum_annualized_volatility": 10.0,
                }
            },
        )


def test_worker_timeout_is_automatically_audited_and_refunded(tmp_path) -> None:
    store = SealedEvidenceStore(tmp_path / "sealed")
    store.append(_batch())
    governance = _governance(tmp_path)
    worker = tmp_path / "slow_worker.py"
    worker.write_text(
        "import time\ntime.sleep(5)\n",
        encoding="utf-8",
    )
    evaluator = _evaluator(
        tmp_path,
        store,
        governance,
        worker_path=worker,
        timeout_seconds=1,
    )
    with pytest.raises(SealedEvaluationError, match="infrastructure failed"):
        evaluator.evaluate("submission-1")
    attempt = governance.attempts()[0]
    assert attempt["status"] == "INFRASTRUCTURE_FAILED"
    assert attempt["counted"] == 0


def test_tracked_future_hypothesis_registry_verifies_and_tamper_fails(tmp_path) -> None:
    registry = Path("research/registries/hypothesis_registry.json")
    records = load_hypothesis_registry(registry)
    assert len(records) == 1
    registration, registered_at = records[0]
    assert registration.hypothesis_id == "spy_defensive_vol_target_v1"
    assert registration.eligible_data_start == date(2026, 7, 21)
    assert registered_at < datetime(2026, 7, 21, tzinfo=UTC)

    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["registrations"][0]["economic_rationale"] = "tampered"
    tampered = tmp_path / "registry.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Exception, match="hash mismatch"):
        load_hypothesis_registry(tampered)
