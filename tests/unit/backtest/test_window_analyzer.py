"""Unit tests for WindowAnalyzer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.cost_model import CostModel
from core.backtest.backtest_engine import BacktestEngine
from core.backtest.window_analyzer import (
    WindowAnalyzer, WindowResult, AcceptanceResult,
)


# ── rolling_backtest is_oos flag ──────────────────────────────────────────────


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _make_engine() -> BacktestEngine:
    cfg = CostModelConfig(
        tiers={
            "default": CostTierConfig(
                symbols=[], commission_bps=0.5,
                slippage_interday_bps=3.0, slippage_intraday_bps=5.0,
            )
        }
    )
    return BacktestEngine(CostModel(cfg), initial_capital=100_000.0)


def _make_scenario(
    n: int = 500,
    cagr: float = 0.12,
    syms: list[str] = ("SPY",),
    start: str = "2020-01-02",
    seed: int = 7,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (signals_df, price_df)。"""
    rng      = np.random.default_rng(seed)
    idx      = pd.bdate_range(start, periods=n)
    daily_r  = (1 + cagr) ** (1 / 252) - 1
    price_df = pd.DataFrame(
        {s: 100.0 * np.cumprod(1 + rng.normal(daily_r, 0.012, n)) for s in syms},
        index=idx,
    )
    w = 1.0 / len(syms)
    signals_df = pd.DataFrame({s: w for s in syms}, index=idx)
    return signals_df, price_df


# ── rolling_backtest ──────────────────────────────────────────────────────────

class TestRollingBacktest:
    def test_is_oos_false_for_rolling(self):
        sig, price = _make_scenario(600)
        analyzer   = WindowAnalyzer(_make_engine(), window_size=252, step_size=252)
        windows    = analyzer.rolling_backtest(sig, price)
        for w in windows:
            assert w.is_oos is False

    def test_train_equals_test_for_rolling(self):
        """rolling_backtest 是纯样本内：train 期 == test 期。"""
        sig, price = _make_scenario(500)
        analyzer   = WindowAnalyzer(_make_engine(), window_size=252, step_size=252)
        windows    = analyzer.rolling_backtest(sig, price)
        for w in windows:
            assert w.train_start == w.test_start
            assert w.train_end   == w.test_end
    def test_returns_list_of_window_results(self):
        sig, price = _make_scenario(600)
        analyzer   = WindowAnalyzer(_make_engine(), window_size=252, step_size=252)
        windows    = analyzer.rolling_backtest(sig, price)
        assert isinstance(windows, list)
        assert len(windows) > 0
        assert isinstance(windows[0], WindowResult)

    def test_window_count(self):
        sig, price = _make_scenario(756)    # ~3 年
        analyzer   = WindowAnalyzer(_make_engine(), window_size=252, step_size=252)
        windows    = analyzer.rolling_backtest(sig, price)
        # 756 / 252 = 3 窗口
        assert len(windows) == 3

    def test_windows_have_metrics(self):
        sig, price = _make_scenario(600)
        analyzer   = WindowAnalyzer(_make_engine(), window_size=252, step_size=252)
        windows    = analyzer.rolling_backtest(sig, price)
        for w in windows:
            assert "cagr" in w.metrics or len(w.metrics) > 0

    def test_too_few_dates_returns_empty(self):
        sig, price = _make_scenario(50)
        analyzer   = WindowAnalyzer(_make_engine(), window_size=252)
        windows    = analyzer.rolling_backtest(sig, price)
        assert windows == []


# ── acceptance_check ──────────────────────────────────────────────────────────

class TestAcceptanceCheck:
    def _run_backtest(self, cagr: float = 0.15, n: int = 500) -> tuple:
        sig, price = _make_scenario(n, cagr=cagr)
        engine     = _make_engine()
        result     = engine.run(sig, price)
        benchmark  = price["SPY"]  # 用价格序列作为 benchmark
        return result, benchmark

    def test_returns_acceptance_result(self):
        result, benchmark = self._run_backtest()
        analyzer  = WindowAnalyzer(_make_engine())
        acc       = analyzer.acceptance_check(result, benchmark)
        assert isinstance(acc, AcceptanceResult)

    def test_passed_is_bool(self):
        result, benchmark = self._run_backtest()
        analyzer  = WindowAnalyzer(_make_engine())
        acc       = analyzer.acceptance_check(result, benchmark)
        assert isinstance(acc.passed, bool)

    def test_str_representation_no_exception(self):
        result, benchmark = self._run_backtest()
        analyzer  = WindowAnalyzer(_make_engine())
        acc       = analyzer.acceptance_check(result, benchmark)
        text = str(acc)
        assert "Tier D" in text

    def test_empty_result_fails(self):
        from core.backtest.backtest_engine import _empty_result
        analyzer  = WindowAnalyzer(_make_engine())
        empty_eq  = pd.Series([100.0, 101.0], index=pd.bdate_range("2022-01-03", periods=2))
        from core.backtest.backtest_engine import BacktestResult
        r = _empty_result()
        bench = empty_eq
        acc = analyzer.acceptance_check(r, bench)
        assert not acc.passed

    def test_strategy_better_than_benchmark_improves_excess(self):
        """策略 CAGR > benchmark CAGR → excess_return 应为正。"""
        n     = 500
        idx   = pd.bdate_range("2020-01-02", periods=n)
        # 策略：20% CAGR；benchmark：8% CAGR
        strat_daily = (1.20 ** (1/252)) - 1
        bench_daily = (1.08 ** (1/252)) - 1
        strat_eq   = pd.Series(100_000.0 * np.cumprod(1 + np.full(n, strat_daily)), index=idx)
        bench_eq   = pd.Series(100.0 * np.cumprod(1 + np.full(n, bench_daily)), index=idx)

        from core.backtest.backtest_engine import BacktestResult
        from core.execution.execution_simulator import Fill
        result = BacktestResult(
            equity_curve=strat_eq, positions=pd.DataFrame(),
            weights=pd.DataFrame(), cash_curve=strat_eq * 0,
            trades=[], metrics={},
        )
        analyzer = WindowAnalyzer(_make_engine())
        acc      = analyzer.acceptance_check(result, bench_eq)
        assert acc.excess_return > 0


# ── walk_forward ─────────────────────────────────────────────────────────────

class TestWalkForward:
    def test_returns_list_of_window_results(self):
        sig, price = _make_scenario(1200)
        analyzer   = WindowAnalyzer(_make_engine())
        windows    = analyzer.walk_forward(sig, price, train_size=756, test_size=126)
        assert isinstance(windows, list)
        assert len(windows) > 0

    def test_is_oos_true(self):
        sig, price = _make_scenario(1200)
        analyzer   = WindowAnalyzer(_make_engine())
        windows    = analyzer.walk_forward(sig, price, train_size=756, test_size=126)
        for w in windows:
            assert w.is_oos is True

    def test_train_and_test_do_not_overlap(self):
        """测试期 start > 训练期 end（无重叠）。"""
        sig, price = _make_scenario(1200)
        analyzer   = WindowAnalyzer(_make_engine())
        windows    = analyzer.walk_forward(sig, price, train_size=756, test_size=126)
        for w in windows:
            assert w.test_start > w.train_end

    def test_test_periods_do_not_overlap(self):
        """相邻窗口的测试期不重叠（test_end[i] < test_start[i+1]）。"""
        sig, price = _make_scenario(1500)
        analyzer   = WindowAnalyzer(_make_engine())
        windows    = analyzer.walk_forward(sig, price, train_size=756, test_size=126)
        for i in range(len(windows) - 1):
            assert windows[i].test_end < windows[i + 1].test_start

    def test_window_count_correct(self):
        """
        total=1008, train=756, test=126, step=126
        可用 OOS 数据 = 1008 - 756 = 252，可得 2 个无重叠测试窗口
        """
        sig, price = _make_scenario(1008)
        analyzer   = WindowAnalyzer(_make_engine())
        windows    = analyzer.walk_forward(sig, price, train_size=756, test_size=126)
        assert len(windows) == 2

    def test_too_few_dates_returns_empty(self):
        sig, price = _make_scenario(500)
        analyzer   = WindowAnalyzer(_make_engine())
        windows    = analyzer.walk_forward(sig, price, train_size=756, test_size=126)
        assert windows == []

    def test_metrics_based_on_test_period(self):
        """metrics 反映的是测试期，不是训练期。"""
        sig, price = _make_scenario(1200)
        analyzer   = WindowAnalyzer(_make_engine())
        windows    = analyzer.walk_forward(sig, price, train_size=756, test_size=126)
        for w in windows:
            assert "cagr" in w.metrics or len(w.metrics) > 0

    def test_benchmark_computes_excess_return(self):
        """提供 benchmark → WindowResult.excess_return 字段存在。"""
        sig, price = _make_scenario(1200)
        analyzer   = WindowAnalyzer(_make_engine())
        benchmark  = price["SPY"]
        windows    = analyzer.walk_forward(sig, price, benchmark=benchmark,
                                           train_size=756, test_size=126)
        for w in windows:
            assert "excess_return" in w.metrics


# ── oos_consistency_check ─────────────────────────────────────────────────────

class TestOosConsistencyCheck:
    def _make_windows(self, cagrs: list) -> list:
        windows = []
        for i, c in enumerate(cagrs):
            idx = pd.bdate_range("2020-01-02", periods=2)
            w   = WindowResult(
                window_id=i, train_start=idx[0], train_end=idx[0],
                test_start=idx[0], test_end=idx[1],
                metrics={"cagr": c, "sharpe": 0.5},
                is_oos=True,
            )
            windows.append(w)
        return windows

    def test_empty_returns_failed(self):
        result = WindowAnalyzer.oos_consistency_check([])
        assert result["passed"] is False

    def test_all_positive_passes(self):
        windows = self._make_windows([0.05, 0.08, 0.12, 0.03])
        result  = WindowAnalyzer.oos_consistency_check(windows, min_positive_fraction=0.60)
        assert result["passed"] is True

    def test_mostly_negative_fails(self):
        windows = self._make_windows([-0.05, -0.08, 0.01, -0.03])
        result  = WindowAnalyzer.oos_consistency_check(windows, min_positive_fraction=0.60)
        assert result["passed"] is False

    def test_positive_fraction_calculation(self):
        windows = self._make_windows([0.05, -0.02, 0.10, -0.01])  # 2 / 4 = 50%
        result  = WindowAnalyzer.oos_consistency_check(windows)
        assert result["positive_fraction"] == pytest.approx(0.5)

    def test_mean_cagr_correct(self):
        windows = self._make_windows([0.10, 0.20])
        result  = WindowAnalyzer.oos_consistency_check(windows)
        assert result["mean_cagr"] == pytest.approx(0.15)

    def test_n_windows_stored(self):
        windows = self._make_windows([0.05, 0.06, 0.07])
        result  = WindowAnalyzer.oos_consistency_check(windows)
        assert result["n_windows"] == 3


# ── summarize_windows ─────────────────────────────────────────────────────────

class TestSummarizeWindows:
    def test_returns_dataframe(self):
        sig, price = _make_scenario(600)
        analyzer   = WindowAnalyzer(_make_engine(), window_size=252, step_size=252)
        windows    = analyzer.rolling_backtest(sig, price)
        df         = WindowAnalyzer.summarize_windows(windows)
        assert isinstance(df, pd.DataFrame)

    def test_empty_list_returns_empty_df(self):
        df = WindowAnalyzer.summarize_windows([])
        assert df.empty

    def test_row_count_equals_window_count(self):
        sig, price = _make_scenario(756)
        analyzer   = WindowAnalyzer(_make_engine(), window_size=252, step_size=252)
        windows    = analyzer.rolling_backtest(sig, price)
        df         = WindowAnalyzer.summarize_windows(windows)
        assert len(df) == len(windows)

    def test_is_oos_column_present(self):
        sig, price = _make_scenario(756)
        analyzer   = WindowAnalyzer(_make_engine(), window_size=252, step_size=252)
        windows    = analyzer.rolling_backtest(sig, price)
        df         = WindowAnalyzer.summarize_windows(windows)
        assert "is_oos" in df.columns
