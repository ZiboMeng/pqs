"""Tests for forward `recover()` + `PolicyRecoveryEvent` schema.

PRD: docs/prd/20260505-revalidate_e4_near_zero_cum_ret_exemption_prd.md

Coverage strategy:
  - Schema-level: PolicyRecoveryEvent construction + ForwardRunManifest
    lazy migration (manifests pre-PRD load with empty
    policy_recovery_log + a Literal field rejection check).
  - Status guard: recover() refuses to operate on a non-halted
    manifest (the most error-prone guard; doesn't require panel load).

Full integration of the recover flow (panel load → revalidate →
event downgrade → status flip → audit append) is verified by R3
self-audit on trial9_diversifier_001 in production
(`docs/memos/20260505-trial9_recovery_log.md` records the run).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.research.forward import (
    CheckpointCadence,
    CostAssumptions,
    ForwardHaltError,
    ForwardRun,
    ForwardRunManifest,
    ForwardRunStatus,
    PolicyRecoveryEvent,
    manifest_path,
    recover,
    save_manifest,
)
from core.research.robustness.window_spec import (
    DataIntegritySnapshot,
    EvidenceClass,
)


# ── PolicyRecoveryEvent schema ────────────────────────────────────


def test_policy_recovery_event_minimal_construction():
    """Required fields plus literal constraints honored."""
    ev = PolicyRecoveryEvent(
        detected_at_utc=datetime(2026, 5, 5, 21, 45, tzinfo=timezone.utc),
        recovered_run_label="TD001",
        prior_policy_decision="invalidated",
        new_policy_decision="flagged_only",
        prior_triggers=["E4 cum_ret sign flip"],
        new_triggers=[],
        prd_reference="docs/prd/20260505-revalidate_e4_near_zero_cum_ret_exemption_prd.md",
    )
    assert ev.recovered_run_label == "TD001"
    assert ev.prior_policy_decision == "invalidated"
    assert ev.new_policy_decision == "flagged_only"
    assert ev.operator_note is None


def test_policy_recovery_event_rejects_wrong_literal_values():
    """prior=invalidated, new=flagged_only are the ONLY valid pairings
    by Literal type — recover() can never write any other combination."""
    base = dict(
        detected_at_utc=datetime(2026, 5, 5, tzinfo=timezone.utc),
        recovered_run_label="TD001",
        prior_triggers=[],
        new_triggers=[],
        prd_reference="x",
    )
    # prior must be 'invalidated'
    with pytest.raises(ValidationError):
        PolicyRecoveryEvent(
            **base, prior_policy_decision="flagged_only",
            new_policy_decision="flagged_only",
        )
    # new must be 'flagged_only'
    with pytest.raises(ValidationError):
        PolicyRecoveryEvent(
            **base, prior_policy_decision="invalidated",
            new_policy_decision="invalidated",
        )


def test_policy_recovery_event_extra_fields_forbidden():
    """extra='forbid' (matches codex round-13/14 strict-schema convention)."""
    with pytest.raises(ValidationError):
        PolicyRecoveryEvent(
            detected_at_utc=datetime(2026, 5, 5, tzinfo=timezone.utc),
            recovered_run_label="TD001",
            prior_policy_decision="invalidated",
            new_policy_decision="flagged_only",
            prd_reference="x",
            unknown_field="should reject",
        )


# ── ForwardRunManifest lazy migration ─────────────────────────────


def _bare_manifest() -> ForwardRunManifest:
    return ForwardRunManifest(
        candidate_id="test_recover_cand",
        evidence_class=EvidenceClass.forward_oos,
        spec_hash="abcdef012345",
        start_date=date(2026, 5, 4),
        cost_assumptions=CostAssumptions(
            source="config/cost_model.yaml",
            config_hash="cafe1234567890abcdef",
        ),
        checkpoint_cadence=CheckpointCadence(),
        current_status=ForwardRunStatus.in_progress,
        data_integrity_snapshot=DataIntegritySnapshot(
            daily_store_rebuild_commit="abcdef012345",
            baseline_snapshot_path="data/baseline/latest.json",
            generated_at_utc=datetime(2026, 5, 4, tzinfo=timezone.utc),
        ),
    )


def test_manifest_policy_recovery_log_defaults_empty():
    """PRD 20260505 added an additive field; pre-PRD manifests must
    load with policy_recovery_log = [] (lazy-migration boundary)."""
    m = _bare_manifest()
    assert m.policy_recovery_log == []


def test_manifest_policy_recovery_log_round_trip(tmp_path: Path):
    """PolicyRecoveryEvent persists through save_manifest + load_manifest."""
    from core.research.forward.manifest_io import load_manifest
    m = _bare_manifest()
    m = m.model_copy(update={"policy_recovery_log": [
        PolicyRecoveryEvent(
            detected_at_utc=datetime(2026, 5, 5, 21, 45, tzinfo=timezone.utc),
            recovered_run_label="TD001",
            prior_policy_decision="invalidated",
            new_policy_decision="flagged_only",
            prior_triggers=["E4 cum_ret sign flip"],
            new_triggers=[],
            prd_reference="docs/prd/20260505-revalidate_e4_near_zero_cum_ret_exemption_prd.md",
            operator_note="trial9 day-2 false-positive, ppm yfinance round-trip",
        )
    ]})
    p = tmp_path / "test_recover_cand_forward_manifest.json"
    save_manifest(m, p)
    m2 = load_manifest(p)
    assert len(m2.policy_recovery_log) == 1
    rec = m2.policy_recovery_log[0]
    assert rec.recovered_run_label == "TD001"
    assert rec.operator_note.startswith("trial9 day-2")
    assert rec.prior_triggers == ["E4 cum_ret sign flip"]


# ── recover() top-level status guard ──────────────────────────────


def test_recover_refuses_non_halted_manifest(tmp_path: Path):
    """recover() may ONLY operate on requires_data_review manifests.
    Other statuses raise ForwardHaltError before any heavy work."""
    out_dir = tmp_path / "candidates"
    out_dir.mkdir()
    m = _bare_manifest()
    # status=in_progress (default in fixture)
    save_manifest(m, manifest_path("test_recover_cand", out_dir))

    with pytest.raises(ForwardHaltError) as excinfo:
        recover(
            candidate_id="test_recover_cand",
            output_dir=out_dir,
            cost_model_path=tmp_path / "any_cost.yaml",  # never read
        )
    msg = str(excinfo.value)
    assert "in_progress" in msg
    assert "requires_data_review" in msg


def test_recover_refuses_terminal_manifest(tmp_path: Path):
    """Terminal statuses (completed_*, aborted) must also be rejected
    by recover() — they're outside its remit."""
    out_dir = tmp_path / "candidates"
    out_dir.mkdir()
    m = _bare_manifest().model_copy(update={
        "current_status": ForwardRunStatus.aborted,
    })
    save_manifest(m, manifest_path("test_recover_cand", out_dir))

    with pytest.raises(ForwardHaltError) as excinfo:
        recover(
            candidate_id="test_recover_cand",
            output_dir=out_dir,
            cost_model_path=tmp_path / "any_cost.yaml",
        )
    assert "aborted" in str(excinfo.value)
