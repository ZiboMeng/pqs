"""Tests for RCMArchive Track A metadata + C5 role-remint guard.

PRD: docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
Step A.4 — archive metadata wiring (split_sha256 + panel_max_date +
role per trial; codex R20 Q3 C5 same-spec-different-role guard).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from core.mining.rcm_archive import RCMArchive
from core.research.temporal_split import (
    enforce_c5_no_role_remint,
    load_temporal_split,
)


# ---------------------------------------------------------------------------
# Fake TrialResult / spec / metrics for archive insertion
# ---------------------------------------------------------------------------


@dataclass
class _Spec:
    features: list
    weights: list
    family_counts: dict


@dataclass
class _Metrics:
    n_features: int = 3
    n_families: int = 2
    n_dates: int = 200
    ic_mean: float = 0.01
    ic_std: float = 0.05
    ic_ir: float = 0.20
    turnover_proxy: float = 0.10
    corr_concentration: float = 0.30


@dataclass
class _Trial:
    spec: _Spec
    metrics: _Metrics
    objective: float = 0.5


def _make_trial(features=("rel_spy_20d", "amihud_20d", "mom_126d"),
                weights=(0.4, 0.3, 0.3)) -> _Trial:
    spec = _Spec(features=list(features), weights=list(weights),
                 family_counts={"momentum": 1, "rel_strength": 1})
    return _Trial(spec=spec, metrics=_Metrics())


# ---------------------------------------------------------------------------
# Schema migration tests (idempotent ALTER TABLE)
# ---------------------------------------------------------------------------


def test_track_a_columns_added_on_fresh_db(tmp_path):
    db = tmp_path / "fresh.db"
    archive = RCMArchive(db)
    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(rcm_studies)")}
    for col in ("split_name", "split_sha256", "role"):
        assert col in cols, f"rcm_studies missing column {col}"
    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(rcm_trials)")}
    for col in ("split_sha256", "panel_max_date", "role", "max_factor_lookback_days"):
        assert col in cols, f"rcm_trials missing column {col}"


def test_track_a_alter_idempotent_on_existing_db(tmp_path):
    """Init twice → second time silently skips ALTER (no error)."""
    db = tmp_path / "twice.db"
    RCMArchive(db)  # First init creates + migrates
    RCMArchive(db)  # Second init: ALTER fails with "duplicate column" → swallowed
    # If reached here, idempotency works


def test_track_a_alter_legacy_db_adds_columns(tmp_path):
    """Simulate a pre-Track-A DB by dropping the new columns, then re-init."""
    db = tmp_path / "legacy.db"
    archive = RCMArchive(db)
    # Manually rebuild table without Track A columns (simulating legacy).
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE rcm_studies")
        conn.execute("""
            CREATE TABLE rcm_studies (
                study_id TEXT PRIMARY KEY,
                lineage_tag TEXT NOT NULL,
                created_at TEXT NOT NULL,
                objective_weights_json TEXT,
                panel_description TEXT,
                n_trials_recorded INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
    # Re-init triggers ALTER TABLE ADD COLUMN
    RCMArchive(db)
    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(rcm_studies)")}
    assert "split_name" in cols
    assert "split_sha256" in cols
    assert "role" in cols


# ---------------------------------------------------------------------------
# record_study: Track A fields default to NULL but can be set
# ---------------------------------------------------------------------------


def test_record_study_legacy_path_nulls_track_a_fields(tmp_path):
    """Legacy mining flow does not pass split_name → fields stay NULL."""
    archive = RCMArchive(tmp_path / "study.db")
    archive.record_study(study_id="s1", lineage_tag="legacy")
    with sqlite3.connect(tmp_path / "study.db") as conn:
        row = conn.execute(
            "SELECT split_name, split_sha256, role FROM rcm_studies WHERE study_id='s1'"
        ).fetchone()
    assert row == (None, None, None)


def test_record_study_track_a_path_populates_fields(tmp_path):
    archive = RCMArchive(tmp_path / "study.db")
    archive.record_study(
        study_id="track_a_study",
        lineage_tag="ta-v1",
        split_name="alternating_regime_holdout_v1",
        split_sha256="a" * 64,
        role="core",
    )
    with sqlite3.connect(tmp_path / "study.db") as conn:
        row = conn.execute(
            "SELECT split_name, split_sha256, role FROM rcm_studies WHERE study_id='track_a_study'"
        ).fetchone()
    assert row == ("alternating_regime_holdout_v1", "a" * 64, "core")


# ---------------------------------------------------------------------------
# insert_trial: per-trial fingerprint fields
# ---------------------------------------------------------------------------


def test_insert_trial_legacy_path_nulls_track_a_fields(tmp_path):
    archive = RCMArchive(tmp_path / "trial.db")
    archive.record_study(study_id="s1", lineage_tag="legacy")
    archive.insert_trial(_make_trial(), lineage_tag="legacy", study_id="s1")
    with sqlite3.connect(tmp_path / "trial.db") as conn:
        row = conn.execute(
            "SELECT split_sha256, panel_max_date, role, max_factor_lookback_days "
            "FROM rcm_trials"
        ).fetchone()
    assert row == (None, None, None, None)


def test_insert_trial_track_a_fingerprint_persisted(tmp_path):
    archive = RCMArchive(tmp_path / "trial.db")
    archive.record_study(study_id="s2", lineage_tag="ta-v1",
                         split_name="alternating_regime_holdout_v1",
                         split_sha256="b" * 64, role="core")
    archive.insert_trial(
        _make_trial(),
        lineage_tag="ta-v1", study_id="s2",
        split_sha256="b" * 64,
        panel_max_date="2024-12-31",
        role="core",
        max_factor_lookback_days=252,
    )
    with sqlite3.connect(tmp_path / "trial.db") as conn:
        row = conn.execute(
            "SELECT split_sha256, panel_max_date, role, max_factor_lookback_days "
            "FROM rcm_trials"
        ).fetchone()
    assert row == ("b" * 64, "2024-12-31", "core", 252)


# ---------------------------------------------------------------------------
# find_studies_by_spec_role + C5 enforcement
# ---------------------------------------------------------------------------


def test_find_studies_returns_empty_when_no_match(tmp_path):
    archive = RCMArchive(tmp_path / "find.db")
    matches = archive.find_studies_by_spec_role(
        spec_sha256="abc123", split_name="any"
    )
    assert matches == []


def test_find_studies_returns_match_in_split(tmp_path):
    archive = RCMArchive(tmp_path / "find.db")
    archive.record_study(study_id="sA", lineage_tag="ta",
                         split_name="alternating_regime_holdout_v1",
                         split_sha256="x" * 64, role="core")
    trial = _make_trial()
    trial_id = archive.insert_trial(
        trial, lineage_tag="ta", study_id="sA",
        split_sha256="x" * 64, panel_max_date="2024-12-31",
        role="core", max_factor_lookback_days=252,
    )
    matches = archive.find_studies_by_spec_role(
        spec_sha256=trial_id,
        split_name="alternating_regime_holdout_v1",
    )
    assert len(matches) == 1
    assert matches[0]["role"] == "core"
    assert matches[0]["trial_id"] == trial_id


def test_find_studies_isolated_by_split_name(tmp_path):
    """Same spec under different split_name → no cross-contamination."""
    archive = RCMArchive(tmp_path / "split.db")
    archive.record_study(study_id="sV1", lineage_tag="ta",
                         split_name="v1_split", split_sha256="x" * 64, role="core")
    trial = _make_trial()
    trial_id = archive.insert_trial(
        trial, lineage_tag="ta", study_id="sV1",
        split_sha256="x" * 64, panel_max_date="2024-12-31", role="core",
    )
    # Look up under a DIFFERENT split name
    matches = archive.find_studies_by_spec_role(spec_sha256=trial_id,
                                                split_name="v2_split")
    assert matches == [], "split_name isolation broken"


def test_c5_guard_passes_when_no_prior_trial(tmp_path):
    archive = RCMArchive(tmp_path / "c5_clean.db")
    # No prior trials → no error
    enforce_c5_no_role_remint(
        archive, spec_sha256="newspec", split_name="any", role="core"
    )


def test_c5_guard_passes_when_same_role_reuse(tmp_path):
    """Same spec + same role + same split = deterministic re-run; OK."""
    archive = RCMArchive(tmp_path / "c5_same.db")
    archive.record_study(study_id="sA", lineage_tag="ta",
                         split_name="v1", split_sha256="x" * 64, role="core")
    trial = _make_trial()
    trial_id = archive.insert_trial(
        trial, lineage_tag="ta", study_id="sA",
        split_sha256="x" * 64, panel_max_date="2024-12-31", role="core",
    )
    # Same role re-run: NO raise
    enforce_c5_no_role_remint(archive, spec_sha256=trial_id,
                              split_name="v1", role="core")


def test_c5_guard_blocks_role_remint(tmp_path):
    """Same spec mined as core → cannot remint as diversifier in same split."""
    archive = RCMArchive(tmp_path / "c5_block.db")
    archive.record_study(study_id="sCore", lineage_tag="ta",
                         split_name="v1", split_sha256="x" * 64, role="core")
    trial = _make_trial()
    trial_id = archive.insert_trial(
        trial, lineage_tag="ta", study_id="sCore",
        split_sha256="x" * 64, panel_max_date="2024-12-31", role="core",
    )
    with pytest.raises(ValueError, match="M6 C5 violation"):
        enforce_c5_no_role_remint(
            archive, spec_sha256=trial_id, split_name="v1", role="diversifier"
        )


def test_c5_guard_message_lists_prior_roles(tmp_path):
    archive = RCMArchive(tmp_path / "c5_msg.db")
    archive.record_study(study_id="sCore", lineage_tag="ta",
                         split_name="alternating_regime_holdout_v1",
                         split_sha256="x" * 64, role="core")
    trial = _make_trial()
    trial_id = archive.insert_trial(
        trial, lineage_tag="ta", study_id="sCore",
        split_sha256="x" * 64, panel_max_date="2024-12-31", role="core",
    )
    with pytest.raises(ValueError) as excinfo:
        enforce_c5_no_role_remint(
            archive, spec_sha256=trial_id,
            split_name="alternating_regime_holdout_v1",
            role="diversifier",
        )
    msg = str(excinfo.value)
    assert "core" in msg
    assert "diversifier" in msg
    assert "bump split_name" in msg


def test_c5_guard_allows_remint_in_different_split(tmp_path):
    """Same spec under role=core in v1, role=diversifier in v2 → OK (different split)."""
    archive = RCMArchive(tmp_path / "c5_split.db")
    archive.record_study(study_id="sV1", lineage_tag="ta",
                         split_name="v1", split_sha256="x" * 64, role="core")
    trial = _make_trial()
    trial_id = archive.insert_trial(
        trial, lineage_tag="ta", study_id="sV1",
        split_sha256="x" * 64, panel_max_date="2024-12-31", role="core",
    )
    # Different split: allowed
    enforce_c5_no_role_remint(
        archive, spec_sha256=trial_id, split_name="v2", role="diversifier"
    )


def test_c5_guard_no_archive_is_noop():
    """Pure-test path with archive=None: no raise."""
    enforce_c5_no_role_remint(None, spec_sha256="x", split_name="y", role="z")
