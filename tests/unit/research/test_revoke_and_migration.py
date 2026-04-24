"""Tests for Phase E-0 R3: revoke CLI + RCMv1 migration.

Covers scripts/revoke_candidate.py + dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py.
Both scripts go through CandidateRegistry; these tests pin down the CLI
contract behavior on top of the registry unit tests (R1).
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from core.research.candidate_registry import (
    CandidateRegistry,
    CandidateStatus,
    RevokeReason,
)


ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _run(cmd: list[str], cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=check,
    )


# ── Revoke CLI ───────────────────────────────────────────────────────────────


def test_revoke_cli_help_runs():
    """--help smoke test (catches argparse regressions)."""
    result = _run([sys.executable, "scripts/revoke_candidate.py", "--help"])
    assert "revoke a research candidate" in result.stdout.lower()
    # All 6 reasons appear in help
    for reason in RevokeReason:
        assert reason.value in result.stdout


def test_revoke_cli_rejects_unknown_reason(tmp_path):
    """argparse enum validation."""
    reg_db = tmp_path / "r.db"
    reg = CandidateRegistry(reg_db)
    reg.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
    )
    result = _run(
        [sys.executable, "scripts/revoke_candidate.py",
         "--candidate-id", "c1", "--reason", "bogus_reason",
         "--registry-db", str(reg_db)],
        check=False,
    )
    assert result.returncode != 0
    assert "invalid choice" in result.stderr.lower()


def test_revoke_cli_changes_status_and_writes_reason(tmp_path):
    """End-to-end: CLI revoke with auto-memo updates registry."""
    reg_db = tmp_path / "r.db"
    reg = CandidateRegistry(reg_db)
    reg.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
        status=CandidateStatus.S1_CANDIDATE,
    )
    memo = tmp_path / "memo.md"
    memo.write_text("# revoke: leakage")
    result = _run(
        [sys.executable, "scripts/revoke_candidate.py",
         "--candidate-id", "c1", "--reason", "leakage_found",
         "--memo-path", str(memo),
         "--registry-db", str(reg_db)],
    )
    assert "Candidate revoked" in result.stdout

    # Verify registry state
    rec = reg.get("c1")
    assert rec.status == CandidateStatus.S5_DEPRECATED
    assert rec.revoke_reason == "leakage_found"
    assert rec.revoke_memo_path == str(memo)
    assert rec.revoked_at is not None


def test_revoke_cli_missing_candidate_exit1(tmp_path):
    reg_db = tmp_path / "r.db"
    _ = CandidateRegistry(reg_db)  # empty
    result = _run(
        [sys.executable, "scripts/revoke_candidate.py",
         "--candidate-id", "nonexistent", "--reason", "other",
         "--registry-db", str(reg_db)],
        check=False,
    )
    assert result.returncode == 1
    assert "not found" in (result.stderr + result.stdout).lower()


def test_revoke_cli_memo_path_must_exist(tmp_path):
    """If --memo-path is given, it must point to a real file."""
    reg_db = tmp_path / "r.db"
    reg = CandidateRegistry(reg_db)
    reg.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
    )
    result = _run(
        [sys.executable, "scripts/revoke_candidate.py",
         "--candidate-id", "c1", "--reason", "other",
         "--memo-path", str(tmp_path / "does_not_exist.md"),
         "--registry-db", str(reg_db)],
        check=False,
    )
    assert result.returncode == 1
    assert "does not exist" in (result.stderr + result.stdout).lower()


def test_revoke_cli_repro_failed_reverts_to_s0(tmp_path):
    """reason=reproducibility_failed reverts to S0 (not S5)."""
    reg_db = tmp_path / "r.db"
    reg = CandidateRegistry(reg_db)
    reg.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
        status=CandidateStatus.S1_CANDIDATE,
    )
    memo = tmp_path / "memo.md"
    memo.write_text("# repro failed")
    _run(
        [sys.executable, "scripts/revoke_candidate.py",
         "--candidate-id", "c1", "--reason", "reproducibility_failed",
         "--memo-path", str(memo),
         "--registry-db", str(reg_db)],
    )
    rec = reg.get("c1")
    # Reverted to S0, not S5
    assert rec.status == CandidateStatus.S0_PROTOTYPE
    # But reason still recorded for audit
    assert rec.revoke_reason == "reproducibility_failed"
    assert rec.revoked_at is not None


def test_revoke_cli_double_revoke_exit1(tmp_path):
    reg_db = tmp_path / "r.db"
    reg = CandidateRegistry(reg_db)
    reg.register(
        candidate_id="c1", source_trial_id="t", source_lineage_tag="l",
    )
    reg.revoke("c1", reason=RevokeReason.OTHER, memo_path="/tmp/x.md")
    # Try to revoke again via CLI
    memo = tmp_path / "m.md"
    memo.write_text("# m")
    result = _run(
        [sys.executable, "scripts/revoke_candidate.py",
         "--candidate-id", "c1", "--reason", "other",
         "--memo-path", str(memo),
         "--registry-db", str(reg_db)],
        check=False,
    )
    assert result.returncode == 1
    assert "already revoked" in (result.stderr + result.stdout).lower()


def test_revoke_cli_auto_generates_memo_stub(tmp_path):
    """When --memo-path omitted, script writes a stub and records it."""
    reg_db = tmp_path / "r.db"
    # Write registry to tmp_path so revoke_candidate.py's _MEMO_DIR
    # default still uses the repo convention — we verify by inspecting
    # the final record's memo path
    reg = CandidateRegistry(reg_db)
    reg.register(
        candidate_id="stub_test", source_trial_id="t",
        source_lineage_tag="l",
    )
    result = _run(
        [sys.executable, "scripts/revoke_candidate.py",
         "--candidate-id", "stub_test", "--reason", "other",
         "--registry-db", str(reg_db)],
    )
    assert result.returncode == 0
    rec = reg.get("stub_test")
    assert rec.status == CandidateStatus.S5_DEPRECATED
    # Auto-memo path was written (lives under data/research_candidates/
    # per the default _MEMO_DIR in revoke_candidate.py)
    assert rec.revoke_memo_path is not None
    assert "stub_test_revoke_" in rec.revoke_memo_path
    # Cleanup (best-effort) since this wrote to repo data/ dir
    try:
        Path(rec.revoke_memo_path).unlink(missing_ok=True)
    except Exception:
        pass


# ── Migration hermetic helper ───────────────────────────────────────────────


def _build_fixture_archive(db_path: Path, trial_id: str = "f24aefecc91a") -> None:
    """Create a minimal rcm_archive.db with one row — just enough for
    the migration prereq spot-check."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE rcm_trials (trial_id TEXT PRIMARY KEY, "
        "study_id TEXT, lineage_tag TEXT)"
    )
    conn.execute(
        "INSERT INTO rcm_trials(trial_id, study_id, lineage_tag) "
        "VALUES (?, ?, ?)",
        (trial_id, "fixture_study", "post-2026-04-24-rcm-v1-lag1"),
    )
    conn.commit()
    conn.close()


# ── Migration script (hermetic: every test injects its own fixture) ─────────
#
# Auditor P0-2 fix: these tests previously relied on the real repo
# `data/mining/rcm_archive.db` being present + populated with the
# f24aefecc91a trial. That made them non-hermetic (fail on a fresh
# clone / minimal CI env). Each test now builds its own fixture
# archive via _build_fixture_archive() and injects the path via
# --archive-db. The real repo archive is never read.


def test_migration_dry_run_validates_prereqs(tmp_path):
    fixture = tmp_path / "fixture_archive.db"
    _build_fixture_archive(fixture)
    result = _run(
        [sys.executable, "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--dry-run", "--archive-db", str(fixture)],
    )
    assert result.returncode == 0
    assert "DRY-RUN" in result.stdout
    assert "rcm_v1_defensive_composite_01" in result.stdout
    assert "f24aefecc91a" in result.stdout


def test_migration_idempotent(tmp_path):
    """Second run is a no-op."""
    fixture = tmp_path / "fixture_archive.db"
    _build_fixture_archive(fixture)
    reg_db = tmp_path / "r.db"
    # First run
    r1 = _run(
        [sys.executable, "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--registry-db", str(reg_db),
         "--archive-db", str(fixture)],
    )
    assert r1.returncode == 0
    # Second run
    r2 = _run(
        [sys.executable, "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--registry-db", str(reg_db),
         "--archive-db", str(fixture)],
    )
    assert r2.returncode == 0
    assert "no-op" in r2.stdout.lower()
    # Registry still has exactly one row for this candidate
    reg = CandidateRegistry(reg_db)
    assert reg.count() == 1
    rec = reg.get("rcm_v1_defensive_composite_01")
    assert rec.status == CandidateStatus.S1_CANDIDATE
    assert rec.source_trial_id == "f24aefecc91a"


def test_migration_produces_valid_s1_record(tmp_path):
    """End state after migration matches R3 contract."""
    fixture = tmp_path / "fixture_archive.db"
    _build_fixture_archive(fixture)
    reg_db = tmp_path / "r.db"
    _run(
        [sys.executable, "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--registry-db", str(reg_db),
         "--archive-db", str(fixture)],
    )
    reg = CandidateRegistry(reg_db)
    rec = reg.get("rcm_v1_defensive_composite_01")
    assert rec.status == CandidateStatus.S1_CANDIDATE
    assert rec.source_trial_id == "f24aefecc91a"
    assert rec.source_lineage_tag == "post-2026-04-24-rcm-v1-lag1"
    assert rec.promoted_at is not None
    # Paths on disk
    frozen = Path(rec.frozen_spec_path)
    memo = Path(rec.decision_memo_path)
    assert frozen.exists(), f"frozen_spec missing at {frozen}"
    assert memo.exists(), f"decision_memo missing at {memo}"


# ── Migration hermetic — injection contract (E-post-5A) ─────────────────────


def test_migration_dry_run_accepts_injected_archive(tmp_path):
    """--dry-run + --archive-db pointing at a fixture db must succeed
    without touching data/mining/rcm_archive.db."""
    fixture = tmp_path / "fixture_archive.db"
    _build_fixture_archive(fixture)
    result = _run(
        [sys.executable,
         "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--dry-run", "--archive-db", str(fixture)],
    )
    assert result.returncode == 0
    assert "DRY-RUN" in result.stdout
    assert str(fixture) in result.stdout  # plan echoes injected path


def test_migration_dry_run_rejects_missing_archive(tmp_path):
    """Injected path that doesn't exist → rc=1 with clear message."""
    missing = tmp_path / "does_not_exist.db"
    result = _run(
        [sys.executable,
         "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--dry-run", "--archive-db", str(missing)],
        check=False,
    )
    assert result.returncode == 1
    assert "rcm_archive db" in result.stderr or "rcm_archive db" in result.stdout


def test_migration_dry_run_rejects_archive_without_trial(tmp_path):
    """Fixture archive without the expected trial_id → rc=1."""
    fixture = tmp_path / "empty_archive.db"
    # Build an archive with the table but no matching row
    _build_fixture_archive(fixture, trial_id="some_other_trial")
    result = _run(
        [sys.executable,
         "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--dry-run", "--archive-db", str(fixture)],
        check=False,
    )
    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "f24aefecc91a" in combined


def test_migration_full_run_accepts_injected_archive(tmp_path):
    """Full run (write) with both --registry-db and --archive-db injected
    — the hermetic path for the whole migration, no repo state touched."""
    fixture_archive = tmp_path / "fixture_archive.db"
    _build_fixture_archive(fixture_archive)
    reg_db = tmp_path / "hermetic_registry.db"
    result = _run(
        [sys.executable,
         "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--registry-db", str(reg_db),
         "--archive-db", str(fixture_archive)],
    )
    assert result.returncode == 0
    reg = CandidateRegistry(reg_db)
    rec = reg.get("rcm_v1_defensive_composite_01")
    assert rec.status == CandidateStatus.S1_CANDIDATE
    assert rec.source_trial_id == "f24aefecc91a"


# ── Frozen YAML contract ────────────────────────────────────────────────────


def test_frozen_yaml_parses_and_has_required_fields():
    """The migration-prep frozen YAML must be valid + contain the key
    fields R4 FrozenStrategySpec will later require."""
    import yaml
    path = Path("data/research_candidates/rcm_v1_defensive_composite_01.yaml")
    assert path.exists()
    d = yaml.safe_load(path.read_text())
    assert d["candidate_id"] == "rcm_v1_defensive_composite_01"
    assert d["strategy_version"] == "rcm-v1-2026-04-24"
    assert len(d["feature_set"]) == 4
    names = {f["name"] for f in d["feature_set"]}
    assert names == {"beta_spy_60d", "drawup_from_252d_low",
                     "days_since_52w_high", "amihud_20d"}
    # Weights sum to ~1.0 (TPE-tuned rounded to 3 decimals; tolerance
    # 2% per R19 weight-sensitivity finding that ±10% doesn't matter)
    ws = sum(f["weight"] for f in d["feature_set"])
    assert abs(ws - 1.0) < 0.01
    # Source points back to rcm_archive
    assert d["source"]["trial_id"] == "f24aefecc91a"
    assert d["source"]["lineage_tag"] == "post-2026-04-24-rcm-v1-lag1"


def test_migration_dry_run_rejects_archive_missing_rcm_trials_table(tmp_path):
    """Archive file exists but has no rcm_trials table — rc=1 with
    a message that preserves the sqlite error detail (auditor P0-2:
    don't collapse to a vague 'rcm_archive query failed')."""
    import sqlite3 as _sq
    fixture = tmp_path / "schema_missing.db"
    # Create an empty sqlite db (file exists, no tables)
    conn = _sq.connect(str(fixture))
    conn.execute("CREATE TABLE some_unrelated_table (x INTEGER)")
    conn.commit()
    conn.close()
    result = _run(
        [sys.executable,
         "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--dry-run", "--archive-db", str(fixture)],
        check=False,
    )
    assert result.returncode == 1
    combined = (result.stdout + result.stderr).lower()
    # Must mention either the archive db OR the table name — not a
    # bare 'query failed' with no context
    assert "rcm_trials" in combined or "no such table" in combined or \
        "rcm_archive" in combined, (
        f"Error message too vague to diagnose missing-table case. "
        f"Output: {result.stdout + result.stderr}"
    )
