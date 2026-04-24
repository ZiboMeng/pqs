"""Tests for scripts/paper_enter.py (Phase E-2 R11)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from core.research.candidate_registry import (
    CandidateRegistry,
    CandidateStatus,
    InvalidTransitionError,
    RevokeReason,
)


ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _run(cmd: list[str], cwd: Path = ROOT, check: bool = True):
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=check,
    )


def _register_candidate(reg_db: Path, cid: str, status: CandidateStatus):
    reg = CandidateRegistry(reg_db)
    reg.register(
        candidate_id=cid, source_trial_id="t", source_lineage_tag="l",
        status=status,
    )


def _create_fake_paper_run(candidate_id: str, run_dir_root: Path,
                           with_drift: bool = True):
    """Create a minimal paper-run directory so paper_enter sees it."""
    run_dir = run_dir_root / candidate_id / "20240101T000000Z"
    run_dir.mkdir(parents=True, exist_ok=True)
    # Minimal artifacts the gate checks for (file existence only)
    (run_dir / "live_like_pnl.csv").write_text("date,nav\n")
    (run_dir / "target_portfolio_daily.csv").write_text("date\n")
    (run_dir / "run_meta.json").write_text("{}")
    if with_drift:
        (run_dir / "drift_report_20240101T000000Z.md").write_text(
            "# Drift report stub\n"
        )
    return run_dir


# ── Happy path ───────────────────────────────────────────────────────────────


def test_paper_enter_s1_to_s2_happy_path(tmp_path, monkeypatch):
    """When candidate is S1 + has paper run + has drift report, transition
    to S2 succeeds."""
    reg_db = tmp_path / "reg.db"
    _register_candidate(reg_db, "pe_test", CandidateStatus.S1_CANDIDATE)
    # Fake paper_runs tree under tmp_path; override default via env-style
    # path. The script's _DEFAULT_PAPER_ROOT is fixed at data/paper_runs.
    # Simplest reliable test: create under real data/paper_runs under a
    # test-only candidate_id, with cleanup after.
    paper_root = ROOT / "data" / "paper_runs"
    run_dir = _create_fake_paper_run("pe_test", paper_root, with_drift=True)
    try:
        result = _run([
            sys.executable, "scripts/paper_enter.py",
            "--candidate-id", "pe_test",
            "--registry-db", str(reg_db),
        ])
        assert result.returncode == 0, result.stderr + result.stdout
        reg = CandidateRegistry(reg_db)
        assert reg.get("pe_test").status == CandidateStatus.S2_PAPER
    finally:
        # Clean up fake paper run
        import shutil
        shutil.rmtree(run_dir.parent, ignore_errors=True)


def test_paper_enter_idempotent_on_s2(tmp_path):
    reg_db = tmp_path / "reg.db"
    _register_candidate(reg_db, "pe_idem", CandidateStatus.S1_CANDIDATE)
    # Transition manually first
    reg = CandidateRegistry(reg_db)
    reg.transition("pe_idem", CandidateStatus.S2_PAPER)
    result = _run([
        sys.executable, "scripts/paper_enter.py",
        "--candidate-id", "pe_idem",
        "--registry-db", str(reg_db),
        "--skip-paper-run-check",   # bypass the prereq since we faked it
    ])
    assert result.returncode == 0
    assert "Already at S2" in result.stdout


# ── Refusal: wrong status ────────────────────────────────────────────────────


def test_paper_enter_refuses_s0_candidate(tmp_path):
    reg_db = tmp_path / "reg.db"
    _register_candidate(reg_db, "pe_s0", CandidateStatus.S0_PROTOTYPE)
    result = _run([
        sys.executable, "scripts/paper_enter.py",
        "--candidate-id", "pe_s0",
        "--registry-db", str(reg_db),
        "--skip-paper-run-check",
        "--skip-drift-report-check",
    ], check=False)
    assert result.returncode == 1
    combined = (result.stderr + result.stdout).lower()
    assert "must be s1" in combined or "cannot paper_enter" in combined


def test_paper_enter_refuses_revoked(tmp_path):
    reg_db = tmp_path / "reg.db"
    _register_candidate(reg_db, "pe_rev", CandidateStatus.S1_CANDIDATE)
    reg = CandidateRegistry(reg_db)
    reg.revoke("pe_rev", reason=RevokeReason.LEAKAGE_FOUND,
               memo_path="/tmp/m.md")
    result = _run([
        sys.executable, "scripts/paper_enter.py",
        "--candidate-id", "pe_rev",
        "--registry-db", str(reg_db),
        "--skip-paper-run-check",
        "--skip-drift-report-check",
    ], check=False)
    assert result.returncode == 1


def test_paper_enter_refuses_missing_candidate(tmp_path):
    reg_db = tmp_path / "reg.db"
    _ = CandidateRegistry(reg_db)
    result = _run([
        sys.executable, "scripts/paper_enter.py",
        "--candidate-id", "does_not_exist",
        "--registry-db", str(reg_db),
    ], check=False)
    assert result.returncode == 1


# ── Refusal: missing paper run / drift report ───────────────────────────────


def test_paper_enter_refuses_no_paper_run(tmp_path):
    """No paper run dir under data/paper_runs/<id>/ -> reject unless
    --skip-paper-run-check."""
    reg_db = tmp_path / "reg.db"
    _register_candidate(reg_db, "pe_nopaper", CandidateStatus.S1_CANDIDATE)
    # (no fake paper run created)
    result = _run([
        sys.executable, "scripts/paper_enter.py",
        "--candidate-id", "pe_nopaper",
        "--registry-db", str(reg_db),
    ], check=False)
    assert result.returncode == 1
    assert "no paper run" in (result.stderr + result.stdout).lower()


def test_paper_enter_refuses_no_drift_report(tmp_path):
    reg_db = tmp_path / "reg.db"
    _register_candidate(reg_db, "pe_nodrift", CandidateStatus.S1_CANDIDATE)
    paper_root = ROOT / "data" / "paper_runs"
    run_dir = _create_fake_paper_run("pe_nodrift", paper_root,
                                     with_drift=False)
    try:
        result = _run([
            sys.executable, "scripts/paper_enter.py",
            "--candidate-id", "pe_nodrift",
            "--registry-db", str(reg_db),
        ], check=False)
        assert result.returncode == 1
        assert "drift_report" in (result.stderr + result.stdout).lower()
    finally:
        import shutil
        shutil.rmtree(run_dir.parent, ignore_errors=True)


def test_paper_enter_skip_flags_work(tmp_path):
    """--skip-paper-run-check + --skip-drift-report-check allows a
    S1 candidate without paper artifacts to transition (documented
    escape hatch)."""
    reg_db = tmp_path / "reg.db"
    _register_candidate(reg_db, "pe_skip", CandidateStatus.S1_CANDIDATE)
    result = _run([
        sys.executable, "scripts/paper_enter.py",
        "--candidate-id", "pe_skip",
        "--registry-db", str(reg_db),
        "--skip-paper-run-check",
        "--skip-drift-report-check",
    ])
    assert result.returncode == 0
    reg = CandidateRegistry(reg_db)
    assert reg.get("pe_skip").status == CandidateStatus.S2_PAPER


# ── S2 → S3 boundary ────────────────────────────────────────────────────────


def test_s3_transition_raises_notimplementederror():
    """The registry guard must reject S2 → S3 at the data layer."""
    from core.research.candidate_registry import (
        CandidateRegistry, CandidateStatus, InvalidTransitionError,
    )
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        reg = CandidateRegistry(Path(td) / "r.db")
        reg.register(
            candidate_id="s3test", source_trial_id="t",
            source_lineage_tag="l",
            status=CandidateStatus.S2_PAPER,
        )
        with pytest.raises(InvalidTransitionError,
                           match="out of scope"):
            reg.transition("s3test", CandidateStatus.S3_DEPLOYMENT)


def test_paper_enter_module_has_s3_guard():
    """The paper_enter.py script exposes an _assert_s3_path_is_blocked
    helper that raises NotImplementedError — documented boundary."""
    from importlib import import_module
    m = import_module("scripts.paper_enter")
    with pytest.raises(NotImplementedError, match="Phase E"):
        m._assert_s3_path_is_blocked()


# ── End-to-end with RCMv1 real candidate already in registry ────────────────


def test_rcmv1_candidate_in_s2_after_r11():
    """Acceptance test for PHASEEDONE prereq: RCMv1 candidate must be
    at S2 after R11 execution. The script was run at R11 commit time
    against the real registry; this test pins that state and catches
    silent revocations.
    """
    from core.research.candidate_registry import (
        CandidateRegistry, CandidateStatus,
    )
    reg_path = ROOT / "data" / "research_candidates" / "registry.db"
    if not reg_path.exists():
        pytest.skip("real registry not present")
    reg = CandidateRegistry(reg_path)
    if not reg.exists("rcm_v1_defensive_composite_01"):
        pytest.skip("RCMv1 candidate not in registry")
    rec = reg.get("rcm_v1_defensive_composite_01")
    # R11 transitions this to S2
    assert rec.status == CandidateStatus.S2_PAPER, (
        f"Expected S2 after R11; got {rec.status.value}. "
        "Either R11 was rolled back or the candidate was revoked."
    )
