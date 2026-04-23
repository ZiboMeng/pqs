"""Tests for scripts/freeze_research_candidate.py (Phase E-1 R5).

Covers: freeze from explicit trial_id, freeze from lineage+top-k,
freeze-writes-YAML, freeze-inserts-registry-row, duplicate-rejected,
missing-trial-rejected, dry-run, arg mutex.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from core.research.candidate_registry import (
    CandidateRegistry,
    CandidateStatus,
    RevokeReason,
)


ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _run(cmd: list[str], cwd: Path = ROOT, check: bool = True):
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=check,
    )


def _seed_rcm_archive(db_path: Path) -> str:
    """Seed a tmp rcm_archive.db with one trial. Returns trial_id."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    trial_id = "tst1234trial"
    spec_json = json.dumps({
        "features": ["mom_21d", "vol_21d", "rel_spy_20d"],
        "weights": [0.4, 0.3, 0.3],
        "family_counts": {"A": 1, "C": 1, "D": 1},
    })
    with sqlite3.connect(str(db_path)) as conn:
        # Schema must match core/mining/rcm_archive.py (nullable metric fields
        # per R12 R15 fix)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rcm_trials (
                trial_id TEXT PRIMARY KEY,
                study_id TEXT NOT NULL,
                lineage_tag TEXT NOT NULL,
                created_at TEXT NOT NULL,
                spec_json TEXT NOT NULL,
                n_features INTEGER NOT NULL,
                n_families INTEGER NOT NULL,
                features_csv TEXT NOT NULL,
                weights_csv TEXT NOT NULL,
                family_counts_json TEXT NOT NULL,
                n_dates INTEGER NOT NULL,
                ic_mean REAL, ic_std REAL, ic_ir REAL,
                turnover_proxy REAL, corr_concentration REAL,
                benchmark_excess REAL NOT NULL DEFAULT 0.0,
                regime_stddev REAL NOT NULL DEFAULT 0.0,
                objective REAL
            );
        """)
        conn.execute(
            """INSERT INTO rcm_trials (
                   trial_id, study_id, lineage_tag, created_at,
                   spec_json, n_features, n_families,
                   features_csv, weights_csv, family_counts_json,
                   n_dates, ic_mean, ic_std, ic_ir,
                   turnover_proxy, corr_concentration, objective
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (trial_id, "tst-study", "tst-lineage", "2026-04-24T00:00:00+00:00",
             spec_json, 3, 3,
             "mom_21d,vol_21d,rel_spy_20d", "0.4,0.3,0.3",
             json.dumps({"A": 1, "C": 1, "D": 1}),
             100, 0.02, 0.04, 0.35, 0.15, 0.08, 0.25),
        )
        conn.commit()
    return trial_id


# ── Happy path ───────────────────────────────────────────────────────────────


def test_freeze_from_trial_id_writes_yaml_and_registers(tmp_path):
    archive = tmp_path / "rcm_archive.db"
    registry_db = tmp_path / "registry.db"
    out_yaml = tmp_path / "c1.yaml"
    trial_id = _seed_rcm_archive(archive)
    result = _run([
        sys.executable, "scripts/freeze_research_candidate.py",
        "--trial-id", trial_id,
        "--candidate-id", "freeze_test_c1",
        "--archive-db", str(archive),
        "--registry-db", str(registry_db),
        "--out-path", str(out_yaml),
    ])
    assert result.returncode == 0, result.stderr + result.stdout
    assert out_yaml.exists()
    # YAML content
    d = yaml.safe_load(out_yaml.read_text())
    assert d["candidate_id"] == "freeze_test_c1"
    assert d["source_trial_id"] == trial_id
    assert len(d["feature_set"]) == 3
    # Registry row
    reg = CandidateRegistry(registry_db)
    rec = reg.get("freeze_test_c1")
    assert rec.status == CandidateStatus.S0_PROTOTYPE
    assert rec.source_trial_id == trial_id
    assert rec.source_lineage_tag == "tst-lineage"
    assert rec.frozen_spec_path == str(out_yaml)


def test_freeze_from_lineage_top_k_index(tmp_path):
    """Without --trial-id, pick N-th best from lineage (0 = top-1)."""
    archive = tmp_path / "rcm_archive.db"
    registry_db = tmp_path / "registry.db"
    out_yaml = tmp_path / "c2.yaml"
    _seed_rcm_archive(archive)  # only 1 trial seeded, top-k-index=0 works
    result = _run([
        sys.executable, "scripts/freeze_research_candidate.py",
        "--lineage-tag", "tst-lineage",
        "--top-k-index", "0",
        "--candidate-id", "freeze_test_c2",
        "--archive-db", str(archive),
        "--registry-db", str(registry_db),
        "--out-path", str(out_yaml),
    ])
    assert result.returncode == 0, result.stderr
    reg = CandidateRegistry(registry_db)
    rec = reg.get("freeze_test_c2")
    assert rec.status == CandidateStatus.S0_PROTOTYPE


def test_freeze_fills_minimal_summary_stubs(tmp_path):
    """The generated YAML must have non-empty summary stubs so the
    FrozenStrategySpec schema (R4) accepts it."""
    archive = tmp_path / "rcm_archive.db"
    registry_db = tmp_path / "registry.db"
    out_yaml = tmp_path / "c3.yaml"
    _seed_rcm_archive(archive)
    _run([
        sys.executable, "scripts/freeze_research_candidate.py",
        "--trial-id", "tst1234trial",
        "--candidate-id", "freeze_test_c3",
        "--archive-db", str(archive),
        "--registry-db", str(registry_db),
        "--out-path", str(out_yaml),
    ])
    # Load via FrozenStrategySpec to verify schema-compliant
    from core.research.frozen_spec import FrozenStrategySpec
    spec = FrozenStrategySpec.from_yaml_file(out_yaml)
    # Summary stubs must be non-empty
    assert isinstance(spec.benchmark_relative_summary, dict)
    assert "stub" in str(spec.benchmark_relative_summary).lower()
    assert spec.oos_holdout_summary.get("ic_ir_full_period") == pytest.approx(
        0.35, abs=0.01,
    )
    assert spec.robustness_summary.get("turnover_proxy") == pytest.approx(0.15)


# ── Refusal cases ────────────────────────────────────────────────────────────


def test_freeze_rejects_duplicate_candidate_id(tmp_path):
    archive = tmp_path / "rcm_archive.db"
    registry_db = tmp_path / "registry.db"
    _seed_rcm_archive(archive)
    # First freeze — OK
    _run([
        sys.executable, "scripts/freeze_research_candidate.py",
        "--trial-id", "tst1234trial",
        "--candidate-id", "freeze_dup",
        "--archive-db", str(archive),
        "--registry-db", str(registry_db),
        "--out-path", str(tmp_path / "dup.yaml"),
    ])
    # Second freeze with same candidate_id — rejected
    result = _run([
        sys.executable, "scripts/freeze_research_candidate.py",
        "--trial-id", "tst1234trial",
        "--candidate-id", "freeze_dup",
        "--archive-db", str(archive),
        "--registry-db", str(registry_db),
        "--out-path", str(tmp_path / "dup2.yaml"),
    ], check=False)
    assert result.returncode == 1
    combined = (result.stderr + result.stdout).lower()
    assert "already exists" in combined


def test_freeze_rejects_missing_trial(tmp_path):
    archive = tmp_path / "rcm_archive.db"
    registry_db = tmp_path / "registry.db"
    _seed_rcm_archive(archive)
    result = _run([
        sys.executable, "scripts/freeze_research_candidate.py",
        "--trial-id", "nonexistent_trial_id",
        "--candidate-id", "freeze_missing",
        "--archive-db", str(archive),
        "--registry-db", str(registry_db),
    ], check=False)
    assert result.returncode == 1
    assert "no trial found" in (result.stderr + result.stdout).lower()


def test_freeze_rejects_both_trial_and_lineage(tmp_path):
    """Mutually exclusive: can't provide both --trial-id AND --lineage-tag."""
    archive = tmp_path / "rcm_archive.db"
    registry_db = tmp_path / "registry.db"
    _seed_rcm_archive(archive)
    result = _run([
        sys.executable, "scripts/freeze_research_candidate.py",
        "--trial-id", "tst1234trial",
        "--lineage-tag", "something",
        "--candidate-id", "freeze_both",
        "--archive-db", str(archive),
        "--registry-db", str(registry_db),
    ], check=False)
    assert result.returncode == 1
    assert "provide exactly one" in (result.stderr + result.stdout).lower()


def test_freeze_rejects_neither_trial_nor_lineage(tmp_path):
    """Must provide one of --trial-id / --lineage-tag."""
    registry_db = tmp_path / "registry.db"
    result = _run([
        sys.executable, "scripts/freeze_research_candidate.py",
        "--candidate-id", "freeze_neither",
        "--registry-db", str(registry_db),
    ], check=False)
    assert result.returncode == 1


# ── Dry-run ──────────────────────────────────────────────────────────────────


def test_dry_run_does_not_write(tmp_path):
    archive = tmp_path / "rcm_archive.db"
    registry_db = tmp_path / "registry.db"
    out_yaml = tmp_path / "dry.yaml"
    _seed_rcm_archive(archive)
    result = _run([
        sys.executable, "scripts/freeze_research_candidate.py",
        "--trial-id", "tst1234trial",
        "--candidate-id", "freeze_dryrun",
        "--archive-db", str(archive),
        "--registry-db", str(registry_db),
        "--out-path", str(out_yaml),
        "--dry-run",
    ])
    assert result.returncode == 0
    assert "DRY-RUN" in result.stdout
    assert not out_yaml.exists()
    reg = CandidateRegistry(registry_db)
    assert not reg.exists("freeze_dryrun")


# ── revoke-then-re-freeze cycle ──────────────────────────────────────────────


def test_revoke_then_re_freeze_allowed(tmp_path):
    """After revoking an existing candidate, a fresh freeze with the
    same id should ... still be rejected, because revoke leaves the row.
    This pins down the contract: to REPLACE, you must pick a new
    candidate_id. Revoke is terminal wrt the id."""
    archive = tmp_path / "rcm_archive.db"
    registry_db = tmp_path / "registry.db"
    _seed_rcm_archive(archive)
    _run([
        sys.executable, "scripts/freeze_research_candidate.py",
        "--trial-id", "tst1234trial",
        "--candidate-id", "freeze_replace_test",
        "--archive-db", str(archive),
        "--registry-db", str(registry_db),
        "--out-path", str(tmp_path / "rr.yaml"),
    ])
    # Revoke
    reg = CandidateRegistry(registry_db)
    reg.revoke("freeze_replace_test", reason=RevokeReason.LEAKAGE_FOUND,
               memo_path="/tmp/memo.md")
    # Re-freeze with same id -> still rejected (row exists at S5)
    result = _run([
        sys.executable, "scripts/freeze_research_candidate.py",
        "--trial-id", "tst1234trial",
        "--candidate-id", "freeze_replace_test",
        "--archive-db", str(archive),
        "--registry-db", str(registry_db),
        "--out-path", str(tmp_path / "rr2.yaml"),
    ], check=False)
    assert result.returncode == 1
    assert "already exists" in (result.stderr + result.stdout).lower()
