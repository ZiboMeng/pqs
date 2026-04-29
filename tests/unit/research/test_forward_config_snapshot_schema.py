"""F PRD step 1: schema-only tests for ``ConfigSnapshot`` + ``ConfigDriftEvent``.

After this step the schema exists and ``ForwardRunManifest.config_snapshot`` /
``ForwardRun.config_drift_event`` are Optional; nothing populates them yet.

Step 2 will wire ``init()``; step 3 will wire revalidate; step 4 ships
the backfill utility. This file covers schema-side acceptance criteria
(PRD §6 #1-4 + #8).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.research.forward import (
    CheckpointCadence,
    ConfigDriftEvent,
    ConfigSnapshot,
    CostAssumptions,
    ForwardRun,
    ForwardRunManifest,
    ForwardRunStatus,
)
from core.research.robustness.window_spec import (
    DataIntegritySnapshot,
    EvidenceClass,
)


# ── helpers ──────────────────────────────────────────────────────────


def _valid_snapshot() -> DataIntegritySnapshot:
    return DataIntegritySnapshot(
        daily_store_rebuild_commit="abcdef012345",
        baseline_snapshot_path="data/baseline/latest.json",
        generated_at_utc=datetime(2026, 4, 25, tzinfo=timezone.utc),
    )


def _valid_costs() -> CostAssumptions:
    return CostAssumptions(
        source="config/cost_model.yaml",
        config_hash="cafebabe1234deadbeef",
    )


def _valid_config_snapshot(**overrides) -> ConfigSnapshot:
    base = dict(
        universe_hash="u" * 16,
        factor_registry_hash="f" * 16,
        research_mask_hash="m" * 16,
        risk_config_hash="r" * 16,
        system_config_hash="s" * 16,
        snapshot_at_utc=datetime(2026, 4, 29, tzinfo=timezone.utc),
        sources={
            "universe_hash": "config/universe.yaml",
            "factor_registry_hash": "core/factors/factor_registry.py::PRODUCTION+RESEARCH+MAP",
            "research_mask_hash": "config/research_mask.yaml",
            "risk_config_hash": "config/risk.yaml",
            "system_config_hash": "config/system.yaml",
        },
    )
    base.update(overrides)
    return ConfigSnapshot(**base)


def _full_manifest_kwargs(**overrides) -> dict:
    base = dict(
        candidate_id="probe_candidate",
        evidence_class=EvidenceClass.forward_oos,
        spec_hash="abcdef012345",
        start_date=date(2026, 4, 25),
        cost_assumptions=_valid_costs(),
        data_integrity_snapshot=_valid_snapshot(),
    )
    base.update(overrides)
    return base


# ── ConfigSnapshot construction ──────────────────────────────────────


class TestConfigSnapshotConstruction:
    def test_valid_snapshot_accepted(self):
        snap = _valid_config_snapshot()
        assert snap.schema_version == "1.0"
        assert snap.universe_hash == "u" * 16
        assert snap.migration_note is None

    def test_short_hash_rejected(self):
        with pytest.raises(ValidationError, match=r"at least 12"):
            _valid_config_snapshot(universe_hash="abc")

    def test_missing_required_hash_rejected(self):
        with pytest.raises(ValidationError):
            ConfigSnapshot(
                # universe_hash missing
                factor_registry_hash="f" * 16,
                research_mask_hash="m" * 16,
                risk_config_hash="r" * 16,
                system_config_hash="s" * 16,
                snapshot_at_utc=datetime(2026, 4, 29, tzinfo=timezone.utc),
            )

    def test_migration_note_optional_default_none(self):
        snap = _valid_config_snapshot()
        assert snap.migration_note is None

    def test_migration_note_settable_for_backfill(self):
        snap = _valid_config_snapshot(
            migration_note="backfilled_2026-04-29_assumed_unchanged_since_init",
        )
        assert "backfilled" in snap.migration_note


# ── ConfigDriftEvent construction ────────────────────────────────────


class TestConfigDriftEventConstruction:
    def test_minimal_event_accepted(self):
        evt = ConfigDriftEvent(
            detected_at_utc=datetime(2026, 5, 1, tzinfo=timezone.utc),
            detected_by_run_label="TD007",
            drifted_sources=["universe_hash"],
            snapshot_hashes={"universe_hash": "u" * 16},
            current_hashes={"universe_hash": "v" * 16},
            severity="halt",
        )
        assert evt.severity == "halt"
        assert evt.drifted_sources == ["universe_hash"]
        assert evt.affected_run_id is None

    def test_severity_must_be_warn_or_halt(self):
        with pytest.raises(ValidationError):
            ConfigDriftEvent(
                detected_at_utc=datetime(2026, 5, 1, tzinfo=timezone.utc),
                detected_by_run_label="TD007",
                drifted_sources=["universe_hash"],
                snapshot_hashes={"universe_hash": "u" * 16},
                current_hashes={"universe_hash": "v" * 16},
                severity="info",  # invalid
            )

    def test_drifted_sources_cannot_be_empty(self):
        with pytest.raises(ValidationError):
            ConfigDriftEvent(
                detected_at_utc=datetime(2026, 5, 1, tzinfo=timezone.utc),
                detected_by_run_label="TD007",
                drifted_sources=[],
                snapshot_hashes={},
                current_hashes={},
                severity="warn",
            )

    def test_multi_source_event_accepted(self):
        evt = ConfigDriftEvent(
            detected_at_utc=datetime(2026, 5, 1, tzinfo=timezone.utc),
            detected_by_run_label="TD012",
            drifted_sources=["universe_hash", "research_mask_hash"],
            snapshot_hashes={"universe_hash": "u" * 16, "research_mask_hash": "m" * 16},
            current_hashes={"universe_hash": "v" * 16, "research_mask_hash": "n" * 16},
            severity="halt",
        )
        assert len(evt.drifted_sources) == 2


# ── ForwardRunManifest carries Optional[ConfigSnapshot] ──────────────


class TestManifestConfigSnapshotField:
    def test_manifest_without_config_snapshot_loads_legacy(self):
        """Pre-PRD-F manifests do not have a config_snapshot — the field is
        Optional and defaults to None."""
        m = ForwardRunManifest(**_full_manifest_kwargs())
        assert m.config_snapshot is None

    def test_manifest_with_config_snapshot_round_trips(self):
        snap = _valid_config_snapshot()
        m = ForwardRunManifest(**_full_manifest_kwargs(config_snapshot=snap))
        assert m.config_snapshot is not None
        assert m.config_snapshot.universe_hash == "u" * 16

        # JSON round-trip preserves the snapshot
        as_json = m.model_dump_json()
        m2 = ForwardRunManifest.model_validate_json(as_json)
        assert m2.config_snapshot is not None
        assert m2.config_snapshot.universe_hash == "u" * 16
        assert m2.config_snapshot.factor_registry_hash == "f" * 16


# ── ForwardRun carries Optional[ConfigDriftEvent] separate from data_revision_event ──


class TestForwardRunConfigDriftField:
    def test_run_without_config_drift_event_default_none(self):
        run = ForwardRun(
            checkpoint_label="TD001",
            as_of_date=date(2026, 4, 24),
            n_observed_trading_days=1,
        )
        assert run.config_drift_event is None
        assert run.data_revision_event is None

    def test_run_with_config_drift_event_serializes_separately(self):
        evt = ConfigDriftEvent(
            detected_at_utc=datetime(2026, 5, 1, tzinfo=timezone.utc),
            detected_by_run_label="TD007",
            drifted_sources=["universe_hash"],
            snapshot_hashes={"universe_hash": "u" * 16},
            current_hashes={"universe_hash": "v" * 16},
            severity="halt",
        )
        run = ForwardRun(
            checkpoint_label="TD007",
            as_of_date=date(2026, 5, 5),
            n_observed_trading_days=7,
            config_drift_event=evt,
        )
        assert run.config_drift_event is evt
        assert run.data_revision_event is None

        # JSON round-trip keeps both event slots distinct (codex round-11
        # §B3 — never collapse the two event classes)
        round_trip = ForwardRun.model_validate_json(run.model_dump_json())
        assert round_trip.config_drift_event is not None
        assert round_trip.data_revision_event is None
        assert round_trip.config_drift_event.severity == "halt"


# ── lazy-migration: real production manifests still load post-step-1 ──


_REAL_MANIFEST_PATHS = [
    Path("data/research_candidates/rcm_v1_defensive_composite_01_forward_manifest.json"),
    Path("data/research_candidates/candidate_2_orthogonal_01_forward_manifest.json"),
]


@pytest.mark.parametrize(
    "manifest_path", [p for p in _REAL_MANIFEST_PATHS if p.exists()]
)
def test_legacy_v2_1_3_manifests_load_with_config_snapshot_none(manifest_path):
    """Lazy migration boundary (PRD F §5.6): existing TD001-TD003 manifests
    written before PRD F shipped MUST load with ``config_snapshot=None``
    and the runs must each have ``config_drift_event=None``.
    """
    raw = json.loads(manifest_path.read_text())
    m = ForwardRunManifest.model_validate(raw)
    assert m.config_snapshot is None, (
        f"{manifest_path.name}: legacy manifest should load with "
        f"config_snapshot=None (pre-PRD-F)"
    )
    for run in m.runs:
        assert run.config_drift_event is None, (
            f"{manifest_path.name} {run.checkpoint_label}: legacy run should "
            f"have config_drift_event=None (pre-PRD-F)"
        )
