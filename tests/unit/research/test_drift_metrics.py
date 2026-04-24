"""Unit tests for core/research/drift_metrics.py + scripts/paper_drift_report.py
(Phase E-2 R10)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.research.drift_metrics import (
    DriftThresholds,
    compute_nav_drift,
    compute_position_drift,
    worst_drift_day,
)


ROOT = Path(__file__).resolve().parent.parent.parent.parent


# ── compute_nav_drift ───────────────────────────────────────────────────────


def test_nav_drift_identical_series_zero_delta():
    idx = pd.bdate_range("2024-01-02", periods=10)
    nav = pd.Series(100_000.0 * np.linspace(1.0, 1.05, 10), index=idx)
    df = compute_nav_drift(nav, nav)
    assert len(df) == 10
    assert (df["delta_bps"].abs() < 1e-9).all()
    assert list(df.columns) == ["paper_nav", "replay_nav",
                                "delta_abs", "delta_bps"]


def test_nav_drift_constant_offset_bps():
    idx = pd.bdate_range("2024-01-02", periods=10)
    paper = pd.Series(100_000.0, index=idx)
    replay = pd.Series(100_100.0, index=idx)  # +100 bps
    df = compute_nav_drift(paper, replay)
    assert df["delta_abs"].iloc[-1] == pytest.approx(100.0)
    assert df["delta_bps"].iloc[-1] == pytest.approx(10.0)  # 100/100000*10000


def test_nav_drift_empty_intersection_returns_empty():
    p = pd.Series([100.0, 101.0], index=pd.bdate_range("2024-01-02", periods=2))
    r = pd.Series([100.0, 101.0], index=pd.bdate_range("2025-01-02", periods=2))
    df = compute_nav_drift(p, r)
    assert df.empty
    assert list(df.columns) == ["paper_nav", "replay_nav",
                                "delta_abs", "delta_bps"]


def test_nav_drift_rejects_non_series():
    with pytest.raises(TypeError):
        compute_nav_drift([1.0, 2.0], pd.Series([1.0]))


def test_nav_drift_handles_zero_nav_safely():
    idx = pd.bdate_range("2024-01-02", periods=3)
    paper = pd.Series([0.0, 100.0, 101.0], index=idx)
    replay = pd.Series([1.0, 100.0, 101.0], index=idx)
    df = compute_nav_drift(paper, replay)
    # Row 0: paper=0 -> delta_bps guarded to 0 (not inf)
    assert np.isfinite(df["delta_bps"]).all()
    assert df["delta_bps"].iloc[0] == 0.0


# ── worst_drift_day ─────────────────────────────────────────────────────────


def test_worst_drift_day_identifies_max_abs():
    idx = pd.bdate_range("2024-01-02", periods=5)
    p = pd.Series([100.0] * 5, index=idx)
    r = pd.Series([100.0, 100.5, 99.0, 100.2, 100.0], index=idx)  # max |d|=-100 at idx 2
    df = compute_nav_drift(p, r)
    worst = worst_drift_day(df)
    assert worst is not None
    assert worst["date"] == "2024-01-04"  # idx 2
    assert worst["delta_bps"] == pytest.approx(-100.0)


def test_worst_drift_day_on_empty_returns_none():
    assert worst_drift_day(pd.DataFrame()) is None


# ── compute_position_drift ─────────────────────────────────────────────────


def test_position_drift_identical_panels_zero_diff():
    idx = pd.bdate_range("2024-01-02", periods=5)
    w = pd.DataFrame({"A": [0.5] * 5, "B": [0.5] * 5}, index=idx)
    df = compute_position_drift(w, w)
    assert (df["n_symbol_diff"] == 0).all()
    assert (df["weight_l1_diff"] == 0).all()


def test_position_drift_different_universes_unions():
    idx = pd.bdate_range("2024-01-02", periods=3)
    p = pd.DataFrame({"A": [0.5] * 3, "B": [0.5] * 3}, index=idx)
    r = pd.DataFrame({"A": [0.5] * 3, "C": [0.5] * 3}, index=idx)
    df = compute_position_drift(p, r)
    # A shared; B in paper only; C in replay only -> 2 symbol diffs per row
    assert (df["n_symbol_diff"] == 2).all()
    # L1 = |0.5-0| + |0-0.5| = 1.0 per day
    assert df["weight_l1_diff"].iloc[0] == pytest.approx(1.0)


def test_position_drift_empty_intersection():
    p = pd.DataFrame({"A": [0.5]}, index=pd.bdate_range("2024-01-02", periods=1))
    r = pd.DataFrame({"A": [0.5]}, index=pd.bdate_range("2025-01-02", periods=1))
    df = compute_position_drift(p, r)
    assert df.empty


# ── DriftThresholds ─────────────────────────────────────────────────────────


def test_thresholds_defaults_per_prd():
    t = DriftThresholds()
    assert t.mean_drift_bps == 50.0
    assert t.worst_day_fraction == 0.02


def test_thresholds_frozen():
    t = DriftThresholds()
    with pytest.raises(Exception):  # dataclass frozen
        t.mean_drift_bps = 100.0  # type: ignore[misc]


# ── End-to-end CLI ──────────────────────────────────────────────────────────


def _run(cmd: list[str], check: bool = True):
    return subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, check=check,
    )


def test_cli_report_runs_on_real_rcmv1_paper_run(tmp_path):
    """Integration test: assumes R10 committed a real paper run for
    rcm_v1_defensive_composite_01. If not present, this test skips."""
    paper_root = ROOT / "data" / "paper_runs" / "rcm_v1_defensive_composite_01"
    if not paper_root.exists():
        pytest.skip("No RCMv1 paper run on disk (expected after R10 smoke)")
    runs = [d for d in paper_root.iterdir() if d.is_dir()]
    if not runs:
        pytest.skip("No RCMv1 paper run directories")

    result = _run([
        sys.executable, "scripts/paper_drift_report.py",
        "--candidate-id", "rcm_v1_defensive_composite_01",
    ])
    assert result.returncode == 0, result.stderr + result.stdout

    # Drift artifacts should be written into the latest paper run dir
    latest = max(runs, key=lambda d: d.stat().st_mtime)
    md_files = list(latest.glob("drift_report_*.md"))
    assert md_files, "no drift_report markdown produced"
    # Report contains expected sections
    md = md_files[0].read_text()
    assert "NAV drift" in md
    assert "Position-set drift" in md
    assert "Informational flags" in md
    assert "informational only" in md.lower()


def test_cli_refuses_missing_paper_run(tmp_path):
    result = _run([
        sys.executable, "scripts/paper_drift_report.py",
        "--paper-run-dir", str(tmp_path / "does_not_exist"),
    ], check=False)
    assert result.returncode == 1


def test_cli_refuses_under_5_nav_rows(tmp_path):
    """Charter §6.3 requires ≥ 5 NAV rows for drift report."""
    # Create a fake paper run dir with 3 NAV rows
    from core.research.candidate_registry import (
        CandidateRegistry, CandidateStatus,
    )
    from core.research.frozen_spec import FeatureEntry, FrozenStrategySpec

    reg_db = tmp_path / "reg.db"
    reg = CandidateRegistry(reg_db)
    spec_path = tmp_path / "spec.yaml"
    spec = FrozenStrategySpec(
        candidate_id="under5", strategy_version="u5-v1",
        source_trial_id="abc",
        feature_set=[FeatureEntry(name="mom_21d", weight=1.0)],
        benchmark_relative_summary={"n": "x"},
        oos_holdout_summary={"n": "x"},
        robustness_summary={"n": "x"},
        decision_memo="/tmp/m.md",
    )
    spec.to_yaml_file(spec_path)
    reg.register(
        candidate_id="under5",
        source_trial_id="abc", source_lineage_tag="t",
        status=CandidateStatus.S1_CANDIDATE,
        frozen_spec_path=str(spec_path),
    )

    fake_run = tmp_path / "fake_run"
    fake_run.mkdir()
    idx = pd.bdate_range("2024-01-02", periods=3)
    pd.DataFrame({
        "nav": [100000.0] * 3, "cash": [50000.0] * 3,
        "ret_daily": [0.0] * 3, "ret_cumulative": [0.0] * 3,
        "dd": [0.0] * 3,
    }, index=idx).to_csv(fake_run / "live_like_pnl.csv", index_label="date")
    pd.DataFrame(0.0, index=idx, columns=["A"]).to_csv(
        fake_run / "target_portfolio_daily.csv", index_label="date",
    )
    (fake_run / "run_meta.json").write_text(json.dumps({
        "candidate_id": "under5", "start_date": "2024-01-02",
        "end_date": "2024-01-04", "top_n": 5,
    }))
    result = _run([
        sys.executable, "scripts/paper_drift_report.py",
        "--paper-run-dir", str(fake_run),
        "--registry-db", str(reg_db),
    ], check=False)
    assert result.returncode == 1
    assert "5" in (result.stderr + result.stdout)
