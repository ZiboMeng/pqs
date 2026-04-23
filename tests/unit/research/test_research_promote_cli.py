"""Tests for scripts/research_promote.py (Phase E-1 R6).

Covers the S0 -> S1 gate:
  - happy path
  - already-S1 idempotent no-op
  - rejects stub summaries (auditor hard block)
  - rejects placeholder/missing/short decision memo
  - rejects missing/failing acceptance JSON
  - does NOT write config/production_strategy.yaml
  - revoked-candidate cannot be promoted (wrong status)
"""
from __future__ import annotations

import json
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
from core.research.frozen_spec import FeatureEntry, FrozenStrategySpec


ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _run(cmd: list[str], cwd: Path = ROOT, check: bool = True):
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=check,
    )


def _build_spec(candidate_id: str, trial_id: str = "abc123",
                stubbed: bool = False) -> FrozenStrategySpec:
    if stubbed:
        summary = {"note": "stub derived from rcm_archive at freeze time"}
    else:
        summary = {"note": "real evidence", "ic_ir": 0.5}
    return FrozenStrategySpec(
        candidate_id=candidate_id,
        strategy_version=f"{candidate_id}-v1",
        source_trial_id=trial_id,
        feature_set=[FeatureEntry(name="x", weight=1.0)],
        benchmark_relative_summary=summary,
        oos_holdout_summary=summary if not stubbed else {
            "note": "stub derived from rcm_archive at freeze time",
            "ic_ir_full_period": 0.5,
        },
        robustness_summary=summary if not stubbed else {
            "note": "stub derived from rcm_archive at freeze time",
            "turnover_proxy": 0.2,
        },
        decision_memo="unused by this helper — script reads --decision-memo-path",
    )


def _build_acceptance(path: Path, outcome: str = "promote_to_paper",
                      reasons: list | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "timestamp": "2026-04-24T00:00:00+00:00",
        "trial_id": "abc123",
        "decision": {"outcome": outcome, "blocking_reasons": reasons or []},
    }))


def _author_memo(path: Path, length: int = 200):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Decision memo\n\n" + ("Lorem ipsum. " * (length // 13)))


def _setup_s0_candidate(tmp_path: Path, stubbed: bool = False):
    """Helper: create a registry with a candidate at S0, frozen YAML
    on disk, plus an acceptance JSON stub (outcome=promote_to_paper)."""
    registry_db = tmp_path / "reg.db"
    reg = CandidateRegistry(registry_db)
    spec_path = tmp_path / "c.yaml"
    spec = _build_spec("prom_test", stubbed=stubbed)
    spec.to_yaml_file(spec_path)
    reg.register(
        candidate_id="prom_test",
        source_trial_id="abc123",
        source_lineage_tag="t-lineage",
        status=CandidateStatus.S0_PROTOTYPE,
        frozen_spec_path=str(spec_path),
    )
    # Place acceptance JSON where the auto-discover looks
    # (data/ml/research_miner/<study>/acceptance/acceptance_<trial>.json)
    # Use tmp data root so tests are isolated.
    accept_dir = tmp_path / "research_miner" / "study1" / "acceptance"
    accept_path = accept_dir / "acceptance_abc123.json"
    _build_acceptance(accept_path)
    memo = tmp_path / "memo.md"
    _author_memo(memo)
    return registry_db, spec_path, memo, accept_path


# ── Happy path ───────────────────────────────────────────────────────────────


def test_promote_happy_path(tmp_path):
    registry_db, spec_path, memo, accept = _setup_s0_candidate(tmp_path)
    result = _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "prom_test",
        "--decision-memo-path", str(memo),
        "--acceptance-json", str(accept),
        "--registry-db", str(registry_db),
    ])
    assert result.returncode == 0, result.stderr + result.stdout
    # Verify registry state
    reg = CandidateRegistry(registry_db)
    rec = reg.get("prom_test")
    assert rec.status == CandidateStatus.S1_CANDIDATE
    assert rec.promoted_at is not None
    assert rec.decision_memo_path == str(memo)


# ── Idempotency ──────────────────────────────────────────────────────────────


def test_promote_idempotent_on_already_s1(tmp_path):
    registry_db, spec_path, memo, accept = _setup_s0_candidate(tmp_path)
    # First promote
    _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "prom_test",
        "--decision-memo-path", str(memo),
        "--acceptance-json", str(accept),
        "--registry-db", str(registry_db),
    ])
    # Second promote — no-op success
    result = _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "prom_test",
        "--decision-memo-path", str(memo),
        "--acceptance-json", str(accept),
        "--registry-db", str(registry_db),
    ])
    assert result.returncode == 0
    assert "no-op" in result.stdout.lower() or "already at s1" in result.stdout.lower()


# ── Hard blocks ──────────────────────────────────────────────────────────────


def test_promote_rejects_stub_summaries(tmp_path):
    """The freeze CLI writes stub summaries; promote must refuse them."""
    registry_db, spec_path, memo, accept = _setup_s0_candidate(
        tmp_path, stubbed=True,
    )
    result = _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "prom_test",
        "--decision-memo-path", str(memo),
        "--acceptance-json", str(accept),
        "--registry-db", str(registry_db),
    ], check=False)
    assert result.returncode == 1
    combined = (result.stderr + result.stdout).lower()
    assert "hard block" in combined or "stub" in combined


def test_promote_force_overrides_stub_check(tmp_path):
    """--force disables stub detection (discouraged but supported)."""
    registry_db, spec_path, memo, accept = _setup_s0_candidate(
        tmp_path, stubbed=True,
    )
    result = _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "prom_test",
        "--decision-memo-path", str(memo),
        "--acceptance-json", str(accept),
        "--registry-db", str(registry_db),
        "--force",
    ])
    assert result.returncode == 0


def test_promote_rejects_missing_memo(tmp_path):
    registry_db, spec_path, _, accept = _setup_s0_candidate(tmp_path)
    result = _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "prom_test",
        "--decision-memo-path", str(tmp_path / "nonexistent.md"),
        "--acceptance-json", str(accept),
        "--registry-db", str(registry_db),
    ], check=False)
    assert result.returncode == 1
    assert "does not exist" in (result.stderr + result.stdout).lower()


def test_promote_rejects_todo_placeholder(tmp_path):
    """Freeze CLI's 'TODO: author decision memo...' placeholder must be rejected."""
    registry_db, spec_path, _, accept = _setup_s0_candidate(tmp_path)
    result = _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "prom_test",
        "--decision-memo-path", "TODO: author decision memo for prom_test",
        "--acceptance-json", str(accept),
        "--registry-db", str(registry_db),
    ], check=False)
    assert result.returncode == 1
    assert "placeholder" in (result.stderr + result.stdout).lower()


def test_promote_rejects_short_memo(tmp_path):
    registry_db, spec_path, _, accept = _setup_s0_candidate(tmp_path)
    short_memo = tmp_path / "short.md"
    short_memo.write_text("too short")
    result = _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "prom_test",
        "--decision-memo-path", str(short_memo),
        "--acceptance-json", str(accept),
        "--registry-db", str(registry_db),
    ], check=False)
    assert result.returncode == 1
    assert "too short" in (result.stderr + result.stdout).lower()


def test_promote_rejects_bad_acceptance(tmp_path):
    registry_db, spec_path, memo, _ = _setup_s0_candidate(tmp_path)
    bad_accept = tmp_path / "bad_accept.json"
    _build_acceptance(bad_accept, outcome="hold_in_research",
                      reasons=["IR below threshold"])
    result = _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "prom_test",
        "--decision-memo-path", str(memo),
        "--acceptance-json", str(bad_accept),
        "--registry-db", str(registry_db),
    ], check=False)
    assert result.returncode == 1
    combined = (result.stderr + result.stdout).lower()
    assert "hold_in_research" in combined or "acceptance" in combined


def test_promote_rejects_missing_acceptance(tmp_path):
    registry_db, spec_path, memo, _ = _setup_s0_candidate(tmp_path)
    result = _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "prom_test",
        "--decision-memo-path", str(memo),
        "--acceptance-json", str(tmp_path / "does_not_exist.json"),
        "--registry-db", str(registry_db),
    ], check=False)
    assert result.returncode == 1


def test_promote_rejects_revoked_candidate(tmp_path):
    """A revoked S5 candidate cannot be promoted."""
    registry_db, spec_path, memo, accept = _setup_s0_candidate(tmp_path)
    reg = CandidateRegistry(registry_db)
    reg.revoke("prom_test", reason=RevokeReason.LEAKAGE_FOUND,
               memo_path="/tmp/x.md")
    result = _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "prom_test",
        "--decision-memo-path", str(memo),
        "--acceptance-json", str(accept),
        "--registry-db", str(registry_db),
    ], check=False)
    assert result.returncode == 1
    combined = (result.stderr + result.stdout).lower()
    assert "cannot promote" in combined or "must be s0" in combined


def test_promote_rejects_missing_candidate(tmp_path):
    registry_db = tmp_path / "reg.db"
    _ = CandidateRegistry(registry_db)
    memo = tmp_path / "m.md"
    _author_memo(memo)
    result = _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "nonexistent",
        "--decision-memo-path", str(memo),
        "--registry-db", str(registry_db),
    ], check=False)
    assert result.returncode == 1


# ── Production-config invariant ──────────────────────────────────────────────


def test_promote_does_not_touch_production_config(tmp_path):
    """Hard invariant — the happy-path promote must NOT modify
    config/production_strategy.yaml, config/universe.yaml, or
    core/mining/archive.db. Snapshot mtime before/after.
    """
    registry_db, spec_path, memo, accept = _setup_s0_candidate(tmp_path)

    forbidden = [
        Path("config/production_strategy.yaml"),
        Path("config/universe.yaml"),
        Path("core/mining/archive.py"),  # source file not DB (path sanity)
    ]
    # Snapshot mtime + content hash
    before = {}
    for p in forbidden:
        if p.exists():
            before[p] = (p.stat().st_mtime_ns, p.read_bytes())

    # Run promote
    result = _run([
        sys.executable, "scripts/research_promote.py",
        "--candidate-id", "prom_test",
        "--decision-memo-path", str(memo),
        "--acceptance-json", str(accept),
        "--registry-db", str(registry_db),
    ])
    assert result.returncode == 0

    # Re-check
    for p, (mtime_before, content_before) in before.items():
        assert p.exists(), f"{p} was deleted"
        assert p.stat().st_mtime_ns == mtime_before, (
            f"{p} mtime changed during promote"
        )
        assert p.read_bytes() == content_before, (
            f"{p} content changed during promote"
        )
