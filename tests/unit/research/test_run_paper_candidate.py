"""Tests for scripts/run_paper_candidate.py (Phase E-2 R8).

Covers the paper runner MVP contract:
  - refuses candidate not at S1 or S2 (S0 / S5 rejected)
  - refuses missing candidate
  - writes the 5 expected artifacts
  - hard invariant: script source does not reference
    production_strategy.yaml / load_production_strategy /
    promote_strategy import (grep test)
"""
from __future__ import annotations

import re
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
SCRIPT = ROOT / "scripts" / "run_paper_candidate.py"


def _run(cmd: list[str], cwd: Path = ROOT, check: bool = True):
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=check,
    )


def _make_test_candidate(
    tmp_path: Path, status: CandidateStatus,
) -> tuple[Path, Path]:
    """Create registry + frozen spec at given status. Returns
    (registry_db_path, spec_path)."""
    registry_db = tmp_path / "reg.db"
    reg = CandidateRegistry(registry_db)
    spec_path = tmp_path / "spec.yaml"
    # Use real production-factor names so factor_generator produces them
    spec = FrozenStrategySpec(
        candidate_id="paper_test_c1",
        strategy_version="paper-test-v1",
        source_trial_id="abc123",
        feature_set=[
            FeatureEntry(name="mom_21d", weight=0.5),
            FeatureEntry(name="vol_21d", weight=0.5),
        ],
        benchmark_relative_summary={"note": "real"},
        oos_holdout_summary={"folds": 4},
        robustness_summary={"sens": 0.02},
        decision_memo="/tmp/memo.md",
    )
    spec.to_yaml_file(spec_path)
    reg.register(
        candidate_id="paper_test_c1",
        source_trial_id="abc123",
        source_lineage_tag="test-lineage",
        status=status,
        frozen_spec_path=str(spec_path),
    )
    return registry_db, spec_path


# ── Hard invariant: no production config reads ──────────────────────────────


def test_script_source_has_no_production_config_reads():
    """Grep the script source: it must not read production config.

    Tokens checked:
      - config/production_strategy.yaml
      - promote_strategy       (production promote module)
      - load_production_strategy
    These are fine in docstrings / comments that EXPLAIN the ban; we
    only flag actual import / open / load calls.
    """
    text = SCRIPT.read_text()
    # Lines that are NOT inside docstring markers / comment blocks
    # (pragmatic: strip lines starting with # or " or ' or containing
    # 'Must NOT' / 'DOES NOT' / 'NEVER')
    code_lines: list[str] = []
    in_triple = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if '"""' in line:
            in_triple = not in_triple
            continue
        if in_triple:
            continue
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        code_lines.append(line)
    code_body = "\n".join(code_lines)
    # Now assert forbidden tokens are NOT in pure code body
    forbidden_patterns = [
        r"from\s+scripts\.promote_strategy",
        r"import\s+scripts\.promote_strategy",
        r"\bload_production_strategy\b",
        r"\"config/production_strategy\.yaml\"",
        r"'config/production_strategy\.yaml'",
        # open(...production_strategy.yaml...) call
        r"open\([^)]*production_strategy\.yaml",
    ]
    for pat in forbidden_patterns:
        assert not re.search(pat, code_body), (
            f"Forbidden pattern {pat!r} in script source "
            f"(production config read leaked into paper runner)"
        )


# ── Status gate ──────────────────────────────────────────────────────────────


def test_refuses_s0_candidate(tmp_path):
    reg_db, spec_path = _make_test_candidate(
        tmp_path, CandidateStatus.S0_PROTOTYPE,
    )
    result = _run([
        sys.executable, str(SCRIPT),
        "--candidate-id", "paper_test_c1",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-10",
        "--registry-db", str(reg_db),
        "--out-dir", str(tmp_path / "out"),
    ], check=False)
    assert result.returncode == 1
    combined = (result.stderr + result.stdout).lower()
    assert "s0" in combined or "requires s1" in combined


def test_refuses_revoked_candidate(tmp_path):
    reg_db, spec_path = _make_test_candidate(
        tmp_path, CandidateStatus.S1_CANDIDATE,
    )
    reg = CandidateRegistry(reg_db)
    reg.revoke("paper_test_c1", reason=RevokeReason.LEAKAGE_FOUND,
               memo_path="/tmp/m.md")
    result = _run([
        sys.executable, str(SCRIPT),
        "--candidate-id", "paper_test_c1",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-10",
        "--registry-db", str(reg_db),
        "--out-dir", str(tmp_path / "out"),
    ], check=False)
    assert result.returncode == 1


def test_refuses_missing_candidate(tmp_path):
    reg_db = tmp_path / "reg.db"
    _ = CandidateRegistry(reg_db)
    result = _run([
        sys.executable, str(SCRIPT),
        "--candidate-id", "nonexistent",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-10",
        "--registry-db", str(reg_db),
        "--out-dir", str(tmp_path / "out"),
    ], check=False)
    assert result.returncode == 1


# ── Happy path on S1 candidate (writes artifacts) ───────────────────────────


def test_writes_all_five_artifacts_s1(tmp_path):
    """S1 candidate runs end-to-end and writes signals / target /
    pnl / fills / run_meta artifacts.

    Uses a short window on the real daily data to exercise the full
    factor_generator + zscore + BacktestEngine pipeline.
    """
    reg_db, spec_path = _make_test_candidate(
        tmp_path, CandidateStatus.S1_CANDIDATE,
    )
    out_dir = tmp_path / "out"
    result = _run([
        sys.executable, str(SCRIPT),
        "--candidate-id", "paper_test_c1",
        "--start-date", "2024-01-01",
        "--end-date", "2024-02-01",
        "--top-n", "5",
        "--registry-db", str(reg_db),
        "--out-dir", str(out_dir),
    ])
    assert result.returncode == 0, result.stderr + result.stdout

    # 5 expected artifacts
    expected = [
        "signals_daily.csv",
        "target_portfolio_daily.csv",
        "pnl_daily.csv",
        "fills.csv",
        "run_meta.json",
    ]
    for name in expected:
        p = out_dir / name
        assert p.exists(), f"missing artifact: {name}"
        assert p.stat().st_size > 0, f"empty artifact: {name}"

    # run_meta.json contents
    import json
    meta = json.loads((out_dir / "run_meta.json").read_text())
    assert meta["candidate_id"] == "paper_test_c1"
    assert meta["status_at_run"] == "S1_research_candidate"
    assert meta["top_n"] == 5
    assert meta["n_dates"] > 0


def test_also_runs_on_s2_candidate(tmp_path):
    """S2 candidate is also a valid input (paper-re-run after enter)."""
    reg_db, spec_path = _make_test_candidate(
        tmp_path, CandidateStatus.S1_CANDIDATE,
    )
    reg = CandidateRegistry(reg_db)
    reg.transition("paper_test_c1", CandidateStatus.S2_PAPER)
    out_dir = tmp_path / "out"
    result = _run([
        sys.executable, str(SCRIPT),
        "--candidate-id", "paper_test_c1",
        "--start-date", "2024-01-01",
        "--end-date", "2024-01-25",
        "--top-n", "5",
        "--registry-db", str(reg_db),
        "--out-dir", str(out_dir),
    ])
    assert result.returncode == 0
    assert (out_dir / "run_meta.json").exists()


# ── Does-not-touch production config (live check) ───────────────────────────


def test_live_run_does_not_modify_production_config(tmp_path):
    """Run happy path + snapshot config/* mtime+content before/after."""
    reg_db, spec_path = _make_test_candidate(
        tmp_path, CandidateStatus.S1_CANDIDATE,
    )
    out_dir = tmp_path / "out"

    forbidden = [
        ROOT / "config" / "production_strategy.yaml",
        ROOT / "config" / "universe.yaml",
    ]
    before = {}
    for p in forbidden:
        if p.exists():
            before[p] = (p.stat().st_mtime_ns, p.read_bytes())

    result = _run([
        sys.executable, str(SCRIPT),
        "--candidate-id", "paper_test_c1",
        "--start-date", "2024-01-02",
        "--end-date", "2024-01-15",
        "--top-n", "5",
        "--registry-db", str(reg_db),
        "--out-dir", str(out_dir),
    ])
    assert result.returncode == 0

    for p, (mtime_before, content_before) in before.items():
        assert p.exists()
        assert p.stat().st_mtime_ns == mtime_before, (
            f"{p} mtime changed during paper run"
        )
        assert p.read_bytes() == content_before, (
            f"{p} content changed during paper run"
        )
