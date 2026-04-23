"""Unit tests for core/research/candidate_registry.py (Phase E-0 R1)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.research.candidate_registry import (
    CandidateNotFoundError,
    CandidateRecord,
    CandidateRegistry,
    CandidateStatus,
    DuplicateCandidateError,
    InvalidTransitionError,
    RevokeReason,
)


@pytest.fixture
def tmp_registry(tmp_path):
    return CandidateRegistry(tmp_path / "reg.db")


# ── Schema + init ────────────────────────────────────────────────────────────


def test_registry_creates_schema_on_init(tmp_path):
    reg = CandidateRegistry(tmp_path / "reg.db")
    assert reg.db_path.exists()
    with sqlite3.connect(str(reg.db_path)) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "research_candidates" in tables


def test_registry_creates_nested_parent_dirs(tmp_path):
    nested = tmp_path / "a" / "b" / "c" / "reg.db"
    assert not nested.parent.exists()
    reg = CandidateRegistry(nested)
    assert nested.exists()


def test_registry_idempotent_schema(tmp_path):
    """Second init over same DB doesn't error."""
    path = tmp_path / "reg.db"
    _ = CandidateRegistry(path)
    _ = CandidateRegistry(path)


# ── Registration ─────────────────────────────────────────────────────────────


def test_register_default_is_s0(tmp_registry):
    rec = tmp_registry.register(
        candidate_id="c1",
        source_trial_id="trial_abc",
        source_lineage_tag="lineage_1",
    )
    assert rec.status == CandidateStatus.S0_PROTOTYPE
    assert rec.candidate_id == "c1"
    assert rec.source_trial_id == "trial_abc"
    assert rec.source_lineage_tag == "lineage_1"
    assert rec.created_at is not None
    assert rec.updated_at is not None
    assert rec.promoted_at is None


def test_register_with_higher_status_sets_promoted_at(tmp_registry):
    """R3 migration case: ingest existing S1 candidate with non-S0 status."""
    rec = tmp_registry.register(
        candidate_id="rcm_v1_defensive_composite_01",
        source_trial_id="f24aefecc91a",
        source_lineage_tag="post-2026-04-24-rcm-v1-lag1",
        status=CandidateStatus.S1_CANDIDATE,
        frozen_spec_path="data/research_candidates/rcm_v1.yaml",
        decision_memo_path="docs/20260424-rcm_v1_s1_candidate_memo.md",
    )
    assert rec.status == CandidateStatus.S1_CANDIDATE
    assert rec.promoted_at is not None  # auto-stamped
    assert rec.decision_memo_path.endswith("memo.md")


def test_register_duplicate_raises(tmp_registry):
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
    )
    with pytest.raises(DuplicateCandidateError):
        tmp_registry.register(
            candidate_id="c1", source_trial_id="t2", source_lineage_tag="l2",
        )


def test_register_rejects_s3_s4(tmp_registry):
    """Phase E business rule: S3/S4 out of scope."""
    for status in (CandidateStatus.S3_DEPLOYMENT, CandidateStatus.S4_PRODUCTION):
        with pytest.raises(InvalidTransitionError, match="out of scope"):
            tmp_registry.register(
                candidate_id=f"bad_{status.value}",
                source_trial_id="t", source_lineage_tag="l",
                status=status,
            )


# ── Read ─────────────────────────────────────────────────────────────────────


def test_get_missing_raises(tmp_registry):
    with pytest.raises(CandidateNotFoundError):
        tmp_registry.get("nonexistent")


def test_exists(tmp_registry):
    assert not tmp_registry.exists("c1")
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
    )
    assert tmp_registry.exists("c1")


def test_list_by_status(tmp_registry):
    tmp_registry.register(
        candidate_id="a", source_trial_id="t", source_lineage_tag="l",
    )
    tmp_registry.register(
        candidate_id="b", source_trial_id="t", source_lineage_tag="l",
    )
    tmp_registry.register(
        candidate_id="c", source_trial_id="t", source_lineage_tag="l",
        status=CandidateStatus.S1_CANDIDATE,
    )
    s0_list = tmp_registry.list_by_status(CandidateStatus.S0_PROTOTYPE)
    assert len(s0_list) == 2
    assert {r.candidate_id for r in s0_list} == {"a", "b"}
    s1_list = tmp_registry.list_by_status(CandidateStatus.S1_CANDIDATE)
    assert len(s1_list) == 1
    all_rows = tmp_registry.list_by_status()  # no filter
    assert len(all_rows) == 3


def test_count(tmp_registry):
    assert tmp_registry.count() == 0
    for i in range(5):
        tmp_registry.register(
            candidate_id=f"c_{i}", source_trial_id="t",
            source_lineage_tag="l",
        )
    assert tmp_registry.count() == 5


# ── State transitions ────────────────────────────────────────────────────────


def test_transition_s0_to_s1(tmp_registry):
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
    )
    rec = tmp_registry.transition("c1", CandidateStatus.S1_CANDIDATE)
    assert rec.status == CandidateStatus.S1_CANDIDATE
    assert rec.promoted_at is not None


def test_transition_s1_to_s2(tmp_registry):
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
        status=CandidateStatus.S1_CANDIDATE,
    )
    rec = tmp_registry.transition("c1", CandidateStatus.S2_PAPER)
    assert rec.status == CandidateStatus.S2_PAPER


def test_transition_s1_to_s0_allowed_for_reset(tmp_registry):
    """S1 -> S0 is the designed reset path (for reproducibility)."""
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
        status=CandidateStatus.S1_CANDIDATE,
    )
    rec = tmp_registry.transition("c1", CandidateStatus.S0_PROTOTYPE)
    assert rec.status == CandidateStatus.S0_PROTOTYPE


def test_transition_rejects_s3(tmp_registry):
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
        status=CandidateStatus.S2_PAPER,
    )
    with pytest.raises(InvalidTransitionError, match="out of scope"):
        tmp_registry.transition("c1", CandidateStatus.S3_DEPLOYMENT)


def test_transition_rejects_s0_to_s2_direct(tmp_registry):
    """Must go through S1 (research_promote) first."""
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
    )
    with pytest.raises(InvalidTransitionError, match="Not allowed"):
        tmp_registry.transition("c1", CandidateStatus.S2_PAPER)


def test_transition_rejects_s5_directly(tmp_registry):
    """S5 must go through revoke() (carries reason + memo)."""
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
    )
    with pytest.raises(InvalidTransitionError, match="revoke"):
        tmp_registry.transition("c1", CandidateStatus.S5_DEPRECATED)


# ── Revoke ───────────────────────────────────────────────────────────────────


def test_revoke_default_to_s5(tmp_registry):
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
        status=CandidateStatus.S1_CANDIDATE,
    )
    rec = tmp_registry.revoke(
        "c1", reason=RevokeReason.LEAKAGE_FOUND,
        memo_path="/tmp/memo.md",
    )
    assert rec.status == CandidateStatus.S5_DEPRECATED
    assert rec.revoke_reason == "leakage_found"
    assert rec.revoke_memo_path == "/tmp/memo.md"
    assert rec.revoked_at is not None


def test_revoke_reproducibility_failed_reverts_to_s0(tmp_registry):
    """Special case: 'reproducibility_failed' means retry, not deprecate.

    Sends candidate back to S0 so it can be re-frozen.
    """
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
        status=CandidateStatus.S1_CANDIDATE,
    )
    rec = tmp_registry.revoke(
        "c1", reason=RevokeReason.REPRODUCIBILITY_FAILED,
    )
    assert rec.status == CandidateStatus.S0_PROTOTYPE
    # But revoke_reason is still recorded for audit
    assert rec.revoke_reason == "reproducibility_failed"
    assert rec.revoked_at is not None


def test_revoke_on_missing_raises(tmp_registry):
    with pytest.raises(CandidateNotFoundError):
        tmp_registry.revoke("nonexistent", reason=RevokeReason.OTHER)


def test_revoke_twice_raises(tmp_registry):
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
    )
    tmp_registry.revoke("c1", reason=RevokeReason.OTHER, memo_path="/m.md")
    with pytest.raises(InvalidTransitionError, match="already revoked"):
        tmp_registry.revoke("c1", reason=RevokeReason.OTHER)


def test_revoke_requires_reason_enum(tmp_registry):
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
    )
    with pytest.raises(InvalidTransitionError, match="must be RevokeReason"):
        tmp_registry.revoke("c1", reason="leakage_found")  # string, not enum


# ── Update paths ─────────────────────────────────────────────────────────────


def test_update_paths(tmp_registry):
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
    )
    rec = tmp_registry.update_paths(
        "c1", frozen_spec_path="/path/spec.yaml",
        decision_memo_path="/path/memo.md",
    )
    assert rec.frozen_spec_path == "/path/spec.yaml"
    assert rec.decision_memo_path == "/path/memo.md"


def test_update_paths_preserves_unset(tmp_registry):
    """Passing None for a field doesn't clear it."""
    tmp_registry.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
        frozen_spec_path="/original.yaml",
    )
    rec = tmp_registry.update_paths(
        "c1", decision_memo_path="/new/memo.md",
    )
    # frozen_spec_path stays
    assert rec.frozen_spec_path == "/original.yaml"
    assert rec.decision_memo_path == "/new/memo.md"


# ── Record serialization ─────────────────────────────────────────────────────


def test_record_to_dict():
    rec = CandidateRecord(
        candidate_id="c1",
        source_trial_id="t",
        source_lineage_tag="l",
        status=CandidateStatus.S1_CANDIDATE,
        created_at="2026-04-24T00:00:00+00:00",
        updated_at="2026-04-24T00:00:00+00:00",
    )
    d = rec.to_dict()
    assert d["candidate_id"] == "c1"
    assert d["status"] == "S1_research_candidate"  # serialized as value string


# ── status enum helper ──────────────────────────────────────────────────────


def test_phase_e_active_set():
    active = CandidateStatus.phase_e_active()
    assert CandidateStatus.S0_PROTOTYPE in active
    assert CandidateStatus.S1_CANDIDATE in active
    assert CandidateStatus.S2_PAPER in active
    assert CandidateStatus.S5_DEPRECATED in active
    assert CandidateStatus.S3_DEPLOYMENT not in active
    assert CandidateStatus.S4_PRODUCTION not in active
