"""Tests for Phase E-0 R3: revoke CLI + RCMv1 migration.

Covers scripts/revoke_candidate.py + dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py.
Both scripts go through CandidateRegistry; these tests pin down the CLI
contract behavior on top of the registry unit tests (R1).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

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


# ── Migration script ────────────────────────────────────────────────────────


def test_migration_dry_run_validates_prereqs():
    result = _run(
        [sys.executable, "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--dry-run"],
    )
    assert result.returncode == 0
    assert "DRY-RUN" in result.stdout
    assert "rcm_v1_defensive_composite_01" in result.stdout
    assert "f24aefecc91a" in result.stdout


def test_migration_idempotent(tmp_path):
    """Second run is a no-op."""
    reg_db = tmp_path / "r.db"
    # First run
    r1 = _run(
        [sys.executable, "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--registry-db", str(reg_db)],
    )
    assert r1.returncode == 0
    # Second run
    r2 = _run(
        [sys.executable, "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--registry-db", str(reg_db)],
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
    reg_db = tmp_path / "r.db"
    _run(
        [sys.executable, "dev/scripts/migrations/migrate_rcm_v1_memo_to_registry.py",
         "--registry-db", str(reg_db)],
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
