"""F PRD step 4 + codex round-18 §3: regression tests for the backfill
utility ``dev/scripts/forward/backfill_config_snapshot.py``.

Covers PRD F §6 #9 (backfill utility exists, opt-in stamp) plus the
explicit codex round-18 ask: idempotency + migration_note presence +
real-data sanity (the one-shot ``rcm_v1`` / ``cand2`` manifests round-
trip cleanly).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from core.research.forward.manifest_io import load_manifest, save_manifest
from core.research.forward.manifest_schema import (
    CheckpointCadence,
    CostAssumptions,
    EvidenceClass,
    ForwardRun,
    ForwardRunManifest,
)
from core.research.robustness.window_spec import DataIntegritySnapshot

# Importing via dev.scripts.forward isn't available because the
# script lives outside the package; load it as a path-prefixed module.
import importlib.util
import sys

_BACKFILL_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "dev" / "scripts" / "forward" / "backfill_config_snapshot.py"
)
_spec = importlib.util.spec_from_file_location(
    "_backfill_module", _BACKFILL_PATH,
)
_backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_backfill)


# ── helpers ─────────────────────────────────────────────────────────


def _write_legacy_manifest(p: Path) -> ForwardRunManifest:
    """Pre-PRD-F manifest: config_snapshot is None, all runs lack
    legacy_unhashed_inputs marker (matches RCMv1 / Cand-2 on-disk shape
    pre-2026-04-28)."""
    m = ForwardRunManifest(
        candidate_id="legacy_cand",
        evidence_class=EvidenceClass.forward_oos,
        spec_hash="abcdef0123456789",
        start_date=date(2026, 4, 25),
        cost_assumptions=CostAssumptions(
            source="config/cost_model.yaml",
            config_hash="cafebabe1234deadbeef",
        ),
        checkpoint_cadence=CheckpointCadence(),
        data_integrity_snapshot=DataIntegritySnapshot(
            daily_store_rebuild_commit="abcdef012345",
            baseline_snapshot_path="x",
            generated_at_utc=datetime.now(timezone.utc),
        ),
        config_snapshot=None,                          # pre-PRD-F
        runs=[
            ForwardRun(
                checkpoint_label="TD001",
                as_of_date=date(2026, 4, 25),
                n_observed_trading_days=1,
            ),
        ],
    )
    save_manifest(m, p)
    return m


def _make_fake_config_dir(tmp_path: Path) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "universe.yaml").write_text("seed_pool: [SPY, QQQ]\n")
    (cfg / "research_mask.yaml").write_text("min_price: 5.0\n")
    (cfg / "risk.yaml").write_text("long_only: true\n")
    (cfg / "system.yaml").write_text("env: test\n")
    return cfg


# ── primary contract: backfill stamps a legacy manifest ─────────────


class TestBackfillContract:
    def test_legacy_manifest_gets_snapshot_with_migration_note(self, tmp_path: Path):
        """PRD F §5.6: stamping a legacy manifest must:
          (a) populate config_snapshot with all 5 hashes;
          (b) stamp migration_note marker so future drift events know
              the snapshot is post-init not at-init.
        """
        mp = tmp_path / "m.json"
        _write_legacy_manifest(mp)
        cfg_dir = _make_fake_config_dir(tmp_path)

        result = _backfill.backfill_one(
            mp, config_dir=cfg_dir, today=date(2026, 4, 29),
        )
        assert result["action"] == "backfilled"
        assert result["snapshot_before_was_none"] is True

        m = load_manifest(mp)
        assert m.config_snapshot is not None
        assert len(m.config_snapshot.universe_hash) == 64
        assert len(m.config_snapshot.factor_registry_hash) == 64
        assert m.config_snapshot.migration_note == (
            "backfilled_2026-04-29_assumed_unchanged_since_init"
        )

    def test_existing_runs_untouched(self, tmp_path: Path):
        """Backfill must NOT mutate runs[] — append-only invariant on
        the manifest preserves legacy TD numerics."""
        mp = tmp_path / "m.json"
        _write_legacy_manifest(mp)
        cfg_dir = _make_fake_config_dir(tmp_path)

        m_before = load_manifest(mp)
        n_before = len(m_before.runs)
        first_label_before = m_before.runs[0].checkpoint_label

        _backfill.backfill_one(mp, config_dir=cfg_dir, today=date(2026, 4, 29))

        m_after = load_manifest(mp)
        assert len(m_after.runs) == n_before
        assert m_after.runs[0].checkpoint_label == first_label_before
        # Numeric fields preserved
        assert m_after.runs[0].as_of_date == m_before.runs[0].as_of_date


# ── idempotency: re-running a backfilled manifest is a no-op ────────


class TestBackfillIdempotency:
    def test_second_run_is_skipped_without_force(self, tmp_path: Path):
        """Codex round-18 §3 explicit ask: re-running on an already-
        backfilled manifest is a no-op. This is the main idempotency
        contract — operators can safely script daily backfill checks."""
        mp = tmp_path / "m.json"
        _write_legacy_manifest(mp)
        cfg_dir = _make_fake_config_dir(tmp_path)

        # First run — backfilled
        r1 = _backfill.backfill_one(mp, config_dir=cfg_dir, today=date(2026, 4, 29))
        assert r1["action"] == "backfilled"
        first_note = load_manifest(mp).config_snapshot.migration_note

        # Second run a day later WITHOUT --force
        r2 = _backfill.backfill_one(mp, config_dir=cfg_dir, today=date(2026, 4, 30))
        assert r2["action"] == "skipped_already_present"
        assert r2["snapshot_before_was_none"] is False
        # migration_note was NOT touched
        assert load_manifest(mp).config_snapshot.migration_note == first_note

    def test_force_overwrites_with_new_migration_note(self, tmp_path: Path):
        """``--force`` is the explicit override path: re-stamp with
        today's date. Used when the operator knows the live config has
        re-aligned with the original init state and wants to clear the
        backfill telemetry."""
        mp = tmp_path / "m.json"
        _write_legacy_manifest(mp)
        cfg_dir = _make_fake_config_dir(tmp_path)

        _backfill.backfill_one(mp, config_dir=cfg_dir, today=date(2026, 4, 29))
        r2 = _backfill.backfill_one(
            mp, config_dir=cfg_dir, today=date(2026, 4, 30), force=True,
        )
        assert r2["action"] == "force_overwritten"
        assert load_manifest(mp).config_snapshot.migration_note == (
            "backfilled_2026-04-30_assumed_unchanged_since_init"
        )


# ── dry-run: preview without writing ───────────────────────────────


class TestBackfillDryRun:
    def test_dry_run_does_not_write(self, tmp_path: Path):
        mp = tmp_path / "m.json"
        _write_legacy_manifest(mp)
        cfg_dir = _make_fake_config_dir(tmp_path)
        raw_before = mp.read_bytes()

        result = _backfill.backfill_one(
            mp, config_dir=cfg_dir, dry_run=True, today=date(2026, 4, 29),
        )
        assert result["action"] == "dry_run_preview"
        assert result["snapshot_before_was_none"] is True
        # File contents byte-identical
        assert mp.read_bytes() == raw_before
        # And the manifest in-memory still has config_snapshot=None
        assert load_manifest(mp).config_snapshot is None


# ── reverse-validation + drift detection re-engages after backfill ──


class TestBackfillReverseValidate:
    def test_drift_detection_re_engages_after_backfill(self, tmp_path: Path):
        """End-to-end: a legacy manifest's revalidate skips drift
        detection (config_drift_skipped_legacy=True). After backfill,
        the same revalidate path detects drift again. Reverse-validates
        the lazy-migration boundary handoff."""
        from core.research.forward.runner import _build_config_snapshot
        from core.research.forward.revalidate import revalidate_manifest

        mp = tmp_path / "m.json"
        _write_legacy_manifest(mp)
        cfg_dir = _make_fake_config_dir(tmp_path)

        # Step 1: legacy manifest → revalidate skips drift detection
        m_legacy = load_manifest(mp)
        # Use the SAME config dir on both sides to isolate the drift
        # check from state mutation. With manifest.config_snapshot=None,
        # the result is config_drift_skipped_legacy regardless of what
        # the current snapshot looks like.
        current_snap = _build_config_snapshot(cfg_dir)
        s1 = revalidate_manifest(
            m_legacy, spec=None, universe=[],
            panel={"close": None}, benchmark_symbols=["SPY"],
            detected_by_run_label="t1",
            current_config_snapshot=current_snap,
        )
        assert s1.config_drift_skipped_legacy is True
        assert s1.config_drift_event is None

        # Step 2: backfill
        _backfill.backfill_one(mp, config_dir=cfg_dir, today=date(2026, 4, 29))

        # Step 3: edit universe.yaml → halt-class drift
        (cfg_dir / "universe.yaml").write_text("seed_pool: [SPY, QQQ, AAPL]\n")
        edited_snap = _build_config_snapshot(cfg_dir)
        m_after = load_manifest(mp)
        s2 = revalidate_manifest(
            m_after, spec=None, universe=[],
            panel={"close": None}, benchmark_symbols=["SPY"],
            detected_by_run_label="t2",
            current_config_snapshot=edited_snap,
        )
        # Drift detection now active and fires on universe edit
        assert s2.config_drift_skipped_legacy is False
        assert s2.config_drift_event is not None
        assert s2.config_drift_event.severity == "halt"
        assert "universe_hash" in s2.config_drift_event.drifted_sources


# ── real-data sanity: the production manifests round-trip cleanly ──


_REAL_MANIFEST_PATHS = [
    Path("data/research_candidates/rcm_v1_defensive_composite_01_forward_manifest.json"),
    Path("data/research_candidates/candidate_2_orthogonal_01_forward_manifest.json"),
]


@pytest.mark.parametrize(
    "real_manifest_path",
    [p for p in _REAL_MANIFEST_PATHS if p.exists()],
)
def test_real_production_manifests_dry_run_works(real_manifest_path, tmp_path: Path):
    """The two on-disk RCMv1 / Cand-2 manifests are still legacy
    (config_snapshot=None); a dry-run backfill must complete without
    error and report the same. We never WRITE in this test (production
    manifests must not be touched by the test suite)."""
    # Copy to a tmp location so we don't risk modifying disk
    tmp_manifest = tmp_path / real_manifest_path.name
    tmp_manifest.write_bytes(real_manifest_path.read_bytes())

    result = _backfill.backfill_one(
        tmp_manifest, dry_run=True, today=date(2026, 4, 29),
    )
    # Pre-PRD-F manifest expectation: snapshot_before_was_none=True
    assert result["snapshot_before_was_none"] is True
    assert result["action"] == "dry_run_preview"
    assert result["candidate_id"]  # non-empty string
