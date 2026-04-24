"""Tests for core/research/paper_artifacts.py (Phase E-2 R9)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.research.paper_artifacts import (
    compute_benchmark_relative,
    compute_turnover,
    write_benchmark_relative_paper,
    write_live_like_pnl,
    write_turnover_log,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_panel(n: int = 30):
    idx = pd.bdate_range("2024-01-02", periods=n)
    equity = pd.Series(
        100_000.0 * np.cumprod(1.0 + np.linspace(-0.001, 0.002, n)),
        index=idx, name="equity_curve",
    )
    cash = pd.Series(np.linspace(50_000, 20_000, n), index=idx, name="cash_curve")
    return idx, equity, cash


# ── live_like_pnl ───────────────────────────────────────────────────────────


def test_live_like_pnl_schema(tmp_path):
    idx, eq, cash = _make_panel()
    path = write_live_like_pnl(eq, cash, 100_000.0, tmp_path / "live.csv")
    assert path.exists()
    df = pd.read_csv(path, index_col="date", parse_dates=["date"])
    # Schema columns
    assert list(df.columns) == ["nav", "cash", "ret_daily", "ret_cumulative", "dd"]
    # First-row daily return is 0
    assert df["ret_daily"].iloc[0] == 0.0
    # cum_return agrees with nav
    assert df["ret_cumulative"].iloc[-1] == pytest.approx(
        eq.iloc[-1] / 100_000.0 - 1.0, rel=1e-9,
    )
    # dd non-positive
    assert (df["dd"] <= 1e-12).all()


def test_live_like_pnl_rejects_non_series(tmp_path):
    with pytest.raises(TypeError):
        write_live_like_pnl(
            equity_curve=[1.0, 2.0, 3.0],  # list, not Series
            cash_curve=pd.Series([1.0]),
            initial_capital=100_000.0,
            out_path=tmp_path / "bad.csv",
        )


# ── benchmark_relative ──────────────────────────────────────────────────────


def test_benchmark_relative_paper_computes_excess(tmp_path):
    idx, eq, _ = _make_panel(20)
    spy = pd.Series(
        np.linspace(400.0, 410.0, 20), index=idx,
    )
    qqq = pd.Series(
        np.linspace(350.0, 365.0, 20), index=idx,
    )
    df = compute_benchmark_relative(
        eq, {"SPY": spy, "QQQ": qqq}, 100_000.0,
    )
    assert "paper_cum_ret" in df.columns
    assert "SPY_cum_ret" in df.columns
    assert "QQQ_cum_ret" in df.columns
    assert "excess_vs_SPY_bps" in df.columns
    assert "excess_vs_QQQ_bps" in df.columns
    # Benchmark cumret at t=0 is 0
    assert df["SPY_cum_ret"].iloc[0] == pytest.approx(0.0, abs=1e-9)
    # At T, QQQ cum return = 365/350 - 1 ≈ +4.29%
    assert df["QQQ_cum_ret"].iloc[-1] == pytest.approx(365 / 350 - 1.0, rel=1e-6)
    # Excess = (paper - bench) × 10000
    expected_excess = (df["paper_cum_ret"].iloc[-1] - df["SPY_cum_ret"].iloc[-1]) * 10000
    assert df["excess_vs_SPY_bps"].iloc[-1] == pytest.approx(expected_excess, rel=1e-6)


def test_benchmark_relative_writes_file(tmp_path):
    idx, eq, _ = _make_panel(15)
    spy = pd.Series(np.linspace(400, 420, 15), index=idx)
    path = write_benchmark_relative_paper(
        eq, {"SPY": spy}, 100_000.0, tmp_path / "bench.csv",
    )
    assert path.exists()
    df = pd.read_csv(path, index_col="date", parse_dates=["date"])
    assert "SPY_cum_ret" in df.columns
    # No QQQ column since not provided
    assert "QQQ_cum_ret" not in df.columns
    assert "excess_vs_QQQ_bps" not in df.columns


def test_benchmark_relative_skips_all_nan_benchmark(tmp_path):
    """Benchmark with all-NaN close is silently skipped (no column written)."""
    idx, eq, _ = _make_panel(15)
    spy = pd.Series(np.linspace(400, 420, 15), index=idx)
    qqq_empty = pd.Series([np.nan] * 15, index=idx)
    df = compute_benchmark_relative(
        eq, {"SPY": spy, "QQQ": qqq_empty}, 100_000.0,
    )
    assert "SPY_cum_ret" in df.columns
    assert "QQQ_cum_ret" not in df.columns  # skipped


# ── turnover ────────────────────────────────────────────────────────────────


def test_turnover_stable_portfolio():
    """Constant weights -> zero turnover (after row 0 entry)."""
    idx = pd.bdate_range("2024-01-02", periods=10)
    syms = ["A", "B", "C"]
    wts = pd.DataFrame(0.33, index=idx, columns=syms)
    df = compute_turnover(wts)
    # Row 0: sum(|w_0|)/2 = 0.99/2 ≈ 0.495
    assert df["turnover"].iloc[0] == pytest.approx(0.33 * 3 / 2.0, rel=1e-6)
    # Subsequent rows: 0
    for i in range(1, 10):
        assert df["turnover"].iloc[i] == pytest.approx(0.0, abs=1e-9)
    # n_positions stable at 3
    assert (df["n_positions"] == 3).all()


def test_turnover_churning_portfolio():
    """Alternating allocations -> high daily turnover."""
    idx = pd.bdate_range("2024-01-02", periods=6)
    # Alternate between 100% A and 100% B
    data = [
        [1.0, 0.0],
        [0.0, 1.0],
        [1.0, 0.0],
        [0.0, 1.0],
        [1.0, 0.0],
        [0.0, 1.0],
    ]
    wts = pd.DataFrame(data, index=idx, columns=["A", "B"])
    df = compute_turnover(wts)
    # Row 0 entering: |1|/2 = 0.5
    assert df["turnover"].iloc[0] == pytest.approx(0.5)
    # Row 1+: diff is (1,-1) or (-1,1), abs sum 2, /2 = 1.0
    for i in range(1, 6):
        assert df["turnover"].iloc[i] == pytest.approx(1.0, rel=1e-9)
    assert (df["n_positions"] == 1).all()


def test_turnover_log_writes_file(tmp_path):
    idx = pd.bdate_range("2024-01-02", periods=5)
    wts = pd.DataFrame(
        [[0.5, 0.5], [0.3, 0.7], [0.3, 0.7], [0.6, 0.4], [0.5, 0.5]],
        index=idx, columns=["X", "Y"],
    )
    path = write_turnover_log(wts, tmp_path / "turn.csv")
    assert path.exists()
    df = pd.read_csv(path, index_col="date", parse_dates=["date"])
    assert list(df.columns) == ["turnover", "n_positions", "total_weight"]
    assert len(df) == 5


def test_turnover_empty_weights_safe():
    """All-zero weights -> turnover 0, n_positions 0."""
    idx = pd.bdate_range("2024-01-02", periods=5)
    wts = pd.DataFrame(0.0, index=idx, columns=["A", "B"])
    df = compute_turnover(wts)
    assert (df["turnover"] == 0.0).all()
    assert (df["n_positions"] == 0).all()
    assert (df["total_weight"] == 0.0).all()


# ── End-to-end (via run_paper_candidate) ────────────────────────────────────


def test_run_paper_candidate_writes_r9_artifacts(tmp_path):
    """When run_paper_candidate.py completes, all 3 R9 extended
    artifacts appear on disk."""
    import subprocess
    import sys
    from core.research.candidate_registry import (
        CandidateRegistry, CandidateStatus,
    )
    from core.research.frozen_spec import FeatureEntry, FrozenStrategySpec

    registry_db = tmp_path / "reg.db"
    spec_path = tmp_path / "spec.yaml"
    spec = FrozenStrategySpec(
        candidate_id="r9_test",
        strategy_version="r9-test-v1",
        source_trial_id="abc",
        feature_set=[
            FeatureEntry(name="mom_21d", weight=0.5),
            FeatureEntry(name="vol_21d", weight=0.5),
        ],
        benchmark_relative_summary={"note": "real"},
        oos_holdout_summary={"folds": 4},
        robustness_summary={"sens": 0.02},
        decision_memo="/tmp/m.md",
    )
    spec.to_yaml_file(spec_path)
    reg = CandidateRegistry(registry_db)
    reg.register(
        candidate_id="r9_test",
        source_trial_id="abc", source_lineage_tag="t",
        status=CandidateStatus.S1_CANDIDATE,
        frozen_spec_path=str(spec_path),
    )

    out_dir = tmp_path / "out"
    root = Path(__file__).resolve().parent.parent.parent.parent
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "run_paper_candidate.py"),
         "--candidate-id", "r9_test",
         "--start-date", "2024-01-02",
         "--end-date", "2024-01-20",
         "--top-n", "5",
         "--registry-db", str(registry_db),
         "--out-dir", str(out_dir)],
        cwd=str(root), capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    # R9 artifacts present
    assert (out_dir / "live_like_pnl.csv").exists()
    assert (out_dir / "benchmark_relative_paper.csv").exists()  # SPY/QQQ on panel
    assert (out_dir / "turnover_log.csv").exists()
    # Validate schemas
    live = pd.read_csv(out_dir / "live_like_pnl.csv", index_col="date",
                      parse_dates=["date"])
    assert set(live.columns) == {"nav", "cash", "ret_daily",
                                  "ret_cumulative", "dd"}
    bench = pd.read_csv(out_dir / "benchmark_relative_paper.csv",
                       index_col="date", parse_dates=["date"])
    assert "paper_cum_ret" in bench.columns
    assert "SPY_cum_ret" in bench.columns
    turn = pd.read_csv(out_dir / "turnover_log.csv", index_col="date",
                      parse_dates=["date"])
    assert list(turn.columns) == ["turnover", "n_positions", "total_weight"]
