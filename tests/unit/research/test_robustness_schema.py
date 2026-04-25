"""Schema validation tests for ``CandidateRobustnessWindow``.

PRD: docs/prd/20260425-oos_mvp_ralph_loop_execution.md §3 R1
Acceptance: 5+ schema test cases pass; pytest no regression.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from core.research.robustness import (
    CandidateRobustnessWindow,
    DataIntegritySnapshot,
    EvidenceClass,
    ShrinkReason,
    ShrinkReasonCode,
)
from core.research.robustness.runner import evaluate


def _valid_snapshot() -> DataIntegritySnapshot:
    return DataIntegritySnapshot(
        daily_store_rebuild_commit="abcdef012345",
        baseline_snapshot_path="data/baseline/latest.json",
        generated_at_utc=datetime(2026, 4, 25, 23, 0, 0, tzinfo=timezone.utc),
    )


def _full_window_kwargs(**overrides):
    base = dict(
        candidate_id="rcm_v1",
        evidence_class=EvidenceClass.pseudo_oos_robustness,
        start_date=date(2023, 4, 24),
        end_date=date(2024, 4, 24),
        actual_trading_days=252,
        target_trading_days=252,
        data_integrity_snapshot=_valid_snapshot(),
    )
    base.update(overrides)
    return base


def test_valid_full_window_accepted():
    """Sanity: a fully populated valid window object passes."""
    win = CandidateRobustnessWindow(**_full_window_kwargs())
    assert win.candidate_id == "rcm_v1"
    assert win.evidence_class == EvidenceClass.pseudo_oos_robustness
    assert win.actual_trading_days == win.target_trading_days


def test_missing_evidence_class_rejected():
    kwargs = _full_window_kwargs()
    del kwargs["evidence_class"]
    with pytest.raises(ValidationError) as exc:
        CandidateRobustnessWindow(**kwargs)
    assert "evidence_class" in str(exc.value)


def test_evidence_class_has_no_default():
    """No silent default: evidence_class must be supplied explicitly."""
    fields = CandidateRobustnessWindow.model_fields
    assert "evidence_class" in fields
    assert fields["evidence_class"].is_required()


def test_actual_lt_target_without_shrink_reason_rejected():
    kwargs = _full_window_kwargs(actual_trading_days=200, target_trading_days=252)
    with pytest.raises(ValidationError) as exc:
        CandidateRobustnessWindow(**kwargs)
    assert "shrink_reason" in str(exc.value)


def test_actual_lt_target_with_shrink_reason_accepted():
    kwargs = _full_window_kwargs(
        actual_trading_days=200,
        target_trading_days=252,
        shrink_reason=ShrinkReason(
            code=ShrinkReasonCode.data_coverage_short,
            note="pre-2024-04-24 polygon coverage starts 2023-08",
        ),
    )
    win = CandidateRobustnessWindow(**kwargs)
    assert win.shrink_reason is not None
    assert win.shrink_reason.code == ShrinkReasonCode.data_coverage_short


def test_shrink_reason_code_invalid_rejected():
    """shrink_reason.code must be in the allowed enum."""
    with pytest.raises(ValidationError):
        ShrinkReason(code="not_a_real_code", note="x")


def test_data_integrity_snapshot_missing_field_rejected():
    """All three snapshot fields are mandatory; dropping any → reject."""
    bad_kwargs_list = [
        dict(
            baseline_snapshot_path="data/baseline/latest.json",
            generated_at_utc=datetime(2026, 4, 25, tzinfo=timezone.utc),
        ),
        dict(
            daily_store_rebuild_commit="abcdef012345",
            generated_at_utc=datetime(2026, 4, 25, tzinfo=timezone.utc),
        ),
        dict(
            daily_store_rebuild_commit="abcdef012345",
            baseline_snapshot_path="data/baseline/latest.json",
        ),
    ]
    for bad in bad_kwargs_list:
        with pytest.raises(ValidationError):
            DataIntegritySnapshot(**bad)


def test_data_integrity_snapshot_short_commit_rejected():
    """Commit hash shorter than 12 chars → reject."""
    with pytest.raises(ValidationError):
        DataIntegritySnapshot(
            daily_store_rebuild_commit="abc",
            baseline_snapshot_path="data/baseline/latest.json",
            generated_at_utc=datetime(2026, 4, 25, tzinfo=timezone.utc),
        )


def test_end_date_before_start_date_rejected():
    kwargs = _full_window_kwargs(
        start_date=date(2024, 4, 24),
        end_date=date(2023, 4, 24),
    )
    with pytest.raises(ValidationError) as exc:
        CandidateRobustnessWindow(**kwargs)
    assert "end_date" in str(exc.value)


def test_runner_raises_notimplementederror():
    """R1 runner is a stub; calling it must raise NotImplementedError."""
    win = CandidateRobustnessWindow(**_full_window_kwargs())
    with pytest.raises(NotImplementedError):
        evaluate(win)
