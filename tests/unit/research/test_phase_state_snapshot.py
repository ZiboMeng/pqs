"""Tests for dev/scripts/export/dump_phase_state_snapshot.py.

Auditor P1-2 — the snapshot script must:
  - accept an injected --registry-db
  - render a valid markdown with registry rows + paper-run lists
  - exit 1 with a clear message when registry DB is missing
  - NOT touch the real repo registry or paper_runs
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from core.research.candidate_registry import (
    CandidateRegistry,
    CandidateStatus,
)


ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT = ROOT / "dev" / "scripts" / "export" / "dump_phase_state_snapshot.py"


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, check=check,
    )


def _populate_fixture_registry(db_path: Path) -> None:
    reg = CandidateRegistry(db_path)
    reg.register(
        candidate_id="fixture_cand_s1",
        source_trial_id="trial_abc",
        source_lineage_tag="fixture-lineage",
        status=CandidateStatus.S1_CANDIDATE,
        frozen_spec_path="data/research_candidates/fixture.yaml",
        decision_memo_path="docs/fixture_memo.md",
    )
    reg.register(
        candidate_id="fixture_cand_s2",
        source_trial_id="trial_def",
        source_lineage_tag="fixture-lineage",
        status=CandidateStatus.S2_PAPER,
        frozen_spec_path="data/research_candidates/fixture2.yaml",
    )


def test_snapshot_renders_populated_registry(tmp_path):
    """Happy path — two-row registry produces markdown listing both."""
    reg_db = tmp_path / "reg.db"
    _populate_fixture_registry(reg_db)
    out_md = tmp_path / "snapshot.md"
    result = _run([
        sys.executable, str(SCRIPT),
        "--registry-db", str(reg_db),
        "--out", str(out_md),
    ])
    assert result.returncode == 0
    assert out_md.exists()
    text = out_md.read_text()
    assert "Phase State Snapshot" in text
    assert "fixture_cand_s1" in text
    assert "fixture_cand_s2" in text
    assert "S1_research_candidate" in text
    assert "S2_paper_candidate" in text
    # Registry DB field reflects the injected path, not the real one.
    # tmp_path is outside ROOT, so the script should have printed the
    # absolute path (via _rel_to_root fallback).
    assert str(reg_db) in text


def test_snapshot_handles_empty_registry(tmp_path):
    """Empty registry renders cleanly — placeholder block instead of
    per-record tables."""
    reg_db = tmp_path / "empty.db"
    CandidateRegistry(reg_db)  # creates empty schema
    out_md = tmp_path / "snapshot.md"
    result = _run([
        sys.executable, str(SCRIPT),
        "--registry-db", str(reg_db),
        "--out", str(out_md),
    ])
    assert result.returncode == 0
    assert "registry is empty" in out_md.read_text()


def test_snapshot_rejects_missing_registry_db(tmp_path):
    """Registry DB path that doesn't exist → rc=1 + clear stderr."""
    missing = tmp_path / "does_not_exist.db"
    out_md = tmp_path / "snapshot.md"
    result = _run([
        sys.executable, str(SCRIPT),
        "--registry-db", str(missing),
        "--out", str(out_md),
    ], check=False)
    assert result.returncode == 1
    assert "registry DB not found" in result.stderr
    assert not out_md.exists()


def test_snapshot_stdout_flag_echoes_content(tmp_path):
    """--stdout prints the rendered markdown to stdout too."""
    reg_db = tmp_path / "reg.db"
    _populate_fixture_registry(reg_db)
    out_md = tmp_path / "snapshot.md"
    result = _run([
        sys.executable, str(SCRIPT),
        "--registry-db", str(reg_db),
        "--out", str(out_md),
        "--stdout",
    ])
    assert result.returncode == 0
    assert "Phase State Snapshot" in result.stdout
    assert "fixture_cand_s1" in result.stdout


def test_snapshot_does_not_touch_real_registry(tmp_path):
    """Running the script against a tmp_path fixture must not modify
    data/research_candidates/registry.db."""
    real_db = ROOT / "data" / "research_candidates" / "registry.db"
    if not real_db.exists():
        # CI env without the real db — test is vacuously true
        return
    mtime_before = real_db.stat().st_mtime_ns
    content_before = real_db.read_bytes()

    reg_db = tmp_path / "reg.db"
    _populate_fixture_registry(reg_db)
    out_md = tmp_path / "snapshot.md"
    result = _run([
        sys.executable, str(SCRIPT),
        "--registry-db", str(reg_db),
        "--out", str(out_md),
    ])
    assert result.returncode == 0

    assert real_db.stat().st_mtime_ns == mtime_before
    assert real_db.read_bytes() == content_before
