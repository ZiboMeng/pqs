"""Tests for QQQ hard gate at the acceptance/report layer (closeout
2026-04-20).

The mining evaluator already enforces the QQQ gate (P0.4), but the
acceptance layer (WindowAnalyzer.acceptance_check + master_report
output) previously only compared vs SPY. After this closeout the
acceptance layer mirrors the evaluator: if the strategy doesn't at
least match QQQ, acceptance fails — report + evaluator cannot
disagree on whether a strategy is promotable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pathlib import Path

from core.backtest.backtest_engine import BacktestEngine, BacktestResult
from core.backtest.window_analyzer import (
    AcceptanceResult, WindowAnalyzer,
)
from core.config.loader import load_config
from core.execution.cost_model import CostModel


def _analyzer():
    cfg = load_config(Path("config"))
    engine = BacktestEngine(cost_model=CostModel(cfg.cost_model),
                            initial_capital=10_000)
    return WindowAnalyzer(engine=engine)


def _make_backtest_result(n_days: int, cagr: float) -> BacktestResult:
    idx = pd.bdate_range("2020-01-01", periods=n_days)
    years = n_days / 252.0
    end = (1.0 + cagr) ** years
    eq = pd.Series(np.linspace(1.0, end, n_days), index=idx)
    return BacktestResult(
        equity_curve=eq, positions=pd.DataFrame(),
        weights=pd.DataFrame(), cash_curve=pd.Series(dtype=float),
        trades=[], metrics={"cagr": cagr, "max_drawdown": -0.10},
    )


def _series_with_cagr(n_days: int, cagr: float) -> pd.Series:
    idx = pd.bdate_range("2020-01-01", periods=n_days)
    years = n_days / 252.0
    end = (1.0 + cagr) ** years
    return pd.Series(np.linspace(100.0, 100.0 * end, n_days), index=idx)


class TestAcceptanceQQQGate:

    def test_beat_spy_and_qqq_passes(self):
        """Strategy beats BOTH benchmarks → acceptance PASSES + qqq
        gate PASSED."""
        # Need strategy CAGR far enough above SPY to clear 5% threshold
        result = _make_backtest_result(n_days=504, cagr=0.15)
        spy = _series_with_cagr(504, 0.08)   # strat beats SPY by +7%
        qqq = _series_with_cagr(504, 0.10)   # strat beats QQQ by +5%
        analyzer = _analyzer()
        ar = analyzer.acceptance_check(result, spy, qqq_benchmark=qqq)
        assert ar.passed_qqq_gate is True
        assert ar.qqq_excess_return > 0

    def test_beat_spy_but_lose_to_qqq_fails_gate(self):
        """Strategy beats SPY but LOSES to QQQ — classic case that the
        evaluator and acceptance layer must BOTH flag."""
        result = _make_backtest_result(n_days=504, cagr=0.10)
        spy = _series_with_cagr(504, 0.04)   # strat beats SPY by +6%
        qqq = _series_with_cagr(504, 0.15)   # strat loses to QQQ by -5%
        analyzer = _analyzer()
        ar = analyzer.acceptance_check(result, spy, qqq_benchmark=qqq)
        assert ar.passed_qqq_gate is False
        assert ar.qqq_excess_return < 0
        assert not ar.passed, (
            "strategy should FAIL acceptance when it loses to QQQ "
            f"(failed_criteria={ar.failed_criteria})"
        )
        # The specific failure should be in the list
        assert any("qqq_excess" in f for f in ar.failed_criteria)

    def test_no_qqq_benchmark_preserves_legacy_behavior(self):
        result = _make_backtest_result(n_days=504, cagr=0.15)
        spy = _series_with_cagr(504, 0.08)
        analyzer = _analyzer()
        ar = analyzer.acceptance_check(result, spy)
        # Legacy: no QQQ check → gate defaults to True + NaN excess
        assert np.isnan(ar.qqq_excess_return)
        assert ar.passed_qqq_gate is True

    def test_configurable_min_excess_threshold(self):
        """min_qqq_excess allows tightening or loosening the gate."""
        result = _make_backtest_result(n_days=504, cagr=0.12)
        spy = _series_with_cagr(504, 0.06)
        qqq = _series_with_cagr(504, 0.10)   # strat beats QQQ by +2%
        analyzer = _analyzer()
        # Default 0.0 → passes
        ar_default = analyzer.acceptance_check(
            result, spy, qqq_benchmark=qqq,
        )
        assert ar_default.passed_qqq_gate is True
        # Raise threshold to 3% → fails
        ar_strict = analyzer.acceptance_check(
            result, spy, qqq_benchmark=qqq, min_qqq_excess=0.03,
        )
        assert ar_strict.passed_qqq_gate is False


class TestReportSurfacing:
    """master_report_builder captures qqq_excess + passed_qqq_gate into
    the acceptance dict; master_report renders a dedicated row for the
    QQQ hard gate."""

    def test_builder_captures_qqq_fields(self):
        from core.reporting.master_report_builder import MasterReportBuilder
        ar = AcceptanceResult(
            passed=False, excess_return=0.06,
            strategy_dd=-0.10, benchmark_dd=-0.08, dd_ratio=1.25,
            ir=0.5, details={},
            failed_criteria=["qqq_excess=-0.05 < +0.00"],
            qqq_excess_return=-0.05, passed_qqq_gate=False,
        )
        b = MasterReportBuilder().set_rolling_windows(
            windows=[], acceptance=ar,
        )
        assert b._acceptance["qqq_excess_return"] == -0.05
        assert b._acceptance["passed_qqq_gate"] is False

    def test_master_report_renders_qqq_row(self):
        from core.reporting.master_report import MasterReport
        mr = MasterReport(
            generated_at=pd.Timestamp("2026-04-20T00:00:00"),
            acceptance={
                "passed": False, "excess_return": 0.06, "ir": 0.5,
                "dd_ratio": 1.25, "strategy_dd": -0.10,
                "benchmark_dd": -0.08,
                "failed_criteria": ["qqq_excess=-0.05"],
                "qqq_excess_return": -0.05, "passed_qqq_gate": False,
            },
        )
        md = mr.to_markdown()
        assert "vs QQQ" in md
        assert "❌" in md  # gate fail badge present
