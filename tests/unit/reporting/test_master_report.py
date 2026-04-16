"""Unit tests for MasterReport and MasterReportBuilder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from core.reporting.master_report import MasterReport
from core.reporting.master_report_builder import MasterReportBuilder


# ── 辅助构造器 ────────────────────────────────────────────────────────────────

def _make_backtest_result(
    n_days:     int   = 252,
    cagr:       float = 0.12,
    sharpe:     float = 1.2,
    max_dd:     float = -0.08,
    n_trades:   int   = 200,
):
    """构造最小化 BacktestResult mock。"""
    from core.backtest.backtest_engine import BacktestResult
    idx = pd.bdate_range("2022-01-03", periods=n_days)
    eq  = pd.Series(100_000.0 * (1 + cagr / 252) ** np.arange(n_days), index=idx)
    return BacktestResult(
        equity_curve = eq,
        positions    = pd.DataFrame(),
        weights      = pd.DataFrame(),
        cash_curve   = pd.Series(dtype=float),
        trades       = [object()] * n_trades,    # dummy 对象
        metrics      = {
            "cagr":         cagr,
            "total_return": (1 + cagr) - 1,
            "sharpe":       sharpe,
            "sortino":      sharpe * 1.1,
            "max_drawdown": max_dd,
            "calmar":       abs(cagr / max_dd),
            "volatility":   0.10,
        },
    )


def _make_window_results(n: int = 3) -> list:
    """构造 n 个 WindowResult mock。"""
    from core.backtest.window_analyzer import WindowResult
    results = []
    base = pd.Timestamp("2020-01-02")
    for i in range(n):
        start = base + pd.DateOffset(years=i)
        end   = start + pd.DateOffset(years=1) - pd.Timedelta(days=1)
        results.append(WindowResult(
            window_id   = i + 1,
            train_start = start,
            train_end   = start + pd.DateOffset(months=6),
            test_start  = start + pd.DateOffset(months=6),
            test_end    = end,
            metrics     = {
                "cagr":         0.10 + 0.02 * i,
                "sharpe":       1.0 + 0.1 * i,
                "max_drawdown": -0.07 - 0.01 * i,
            },
        ))
    return results


def _make_acceptance(passed: bool = True):
    """构造 AcceptanceResult mock。"""
    from core.backtest.window_analyzer import AcceptanceResult
    return AcceptanceResult(
        passed          = passed,
        excess_return   = 0.08 if passed else -0.02,
        strategy_dd     = -0.08,
        benchmark_dd    = -0.10,
        dd_ratio        = 0.8 if passed else 2.0,
        ir              = 0.45 if passed else 0.1,
        failed_criteria = [] if passed else ["excess_return", "ir"],
    )


def _make_factor_reports(n: int = 4, tiers: list = None) -> list:
    """构造 FactorReport mock 列表。"""
    from core.factors.factor_evaluator import FactorReport
    from core.factors.factor_engine import FactorStats
    from scipy.stats import t as t_dist

    if tiers is None:
        tiers = ["A", "B", "C", "D"]

    reports = []
    for i, tier in enumerate(tiers[:n]):
        ir       = 0.6 - i * 0.1
        mean_ic  = 0.05 - i * 0.01
        n_per    = 50
        ic_std   = 0.1
        t_stat   = mean_ic / (ic_std / np.sqrt(n_per)) if ic_std > 0 else 0.0
        p_value  = float(2 * (1 - t_dist.cdf(abs(t_stat), df=n_per - 1)))
        stats = FactorStats(
            factor_name       = f"factor_{i}",
            horizon           = 5,
            n_periods         = n_per,
            mean_ic           = mean_ic,
            ic_std            = ic_std,
            ir                = ir,
            t_stat            = t_stat,
            p_value           = p_value,
            ic_positive_ratio = 0.6,
            ic_gt_02_ratio    = 0.3,
        )
        # FactorReport 自动调用 _auto_tier，但我们通过 post_init 后手动覆盖
        r = FactorReport(
            factor_name  = f"factor_{i}",
            horizons     = [5],
            stats        = {5: stats},
            decay        = pd.DataFrame(),
            quantile_ret = pd.DataFrame(),
            sub_periods  = pd.DataFrame(),
        )
        r.tier = tier   # 直接覆盖以便测试
        reports.append(r)
    return reports


def _make_pnl_tracker(n_days: int = 10, initial: float = 100_000.0):
    """构造已有 n_days 记录的 PnLTracker。"""
    from core.paper_trading.pnl_tracker import PnLTracker
    from core.backtest.intraday_engine import DayResult
    t  = PnLTracker(initial)
    eq = initial
    for d in pd.bdate_range("2024-01-02", periods=n_days):
        eq += 50.0
        t.record(
            DayResult(date=d, trades=[], eod_positions={},
                      eod_cash=eq, gross_pnl=50.0, net_pnl=50.0,
                      forced_close=True),
            equity=eq,
        )
    return t


def _make_universe_manager():
    """构造最小化 UniverseManager mock。"""
    mgr = MagicMock()
    mgr.get_active_symbols.return_value = ["SPY", "QQQ"]
    mgr._candidates = {"SPY", "QQQ", "IWM", "TLT"}
    return mgr


# ── MasterReport 基础 ─────────────────────────────────────────────────────────

class TestMasterReportBasic:
    def _empty_report(self) -> MasterReport:
        return MasterReport(generated_at=pd.Timestamp("2024-01-15 16:00:00"))

    def test_to_dict_returns_dict(self):
        assert isinstance(self._empty_report().to_dict(), dict)

    def test_to_dict_has_generated_at(self):
        d = self._empty_report().to_dict()
        assert "generated_at" in d

    def test_to_dict_all_sections_present(self):
        d = self._empty_report().to_dict()
        for key in ["performance", "rolling_windows", "acceptance",
                    "factor_summary", "universe_status", "paper_trading", "risk_summary"]:
            assert key in d

    def test_to_markdown_returns_string(self):
        assert isinstance(self._empty_report().to_markdown(), str)

    def test_to_markdown_contains_title(self):
        md = self._empty_report().to_markdown()
        assert "PQS Master Report" in md

    def test_to_markdown_contains_timestamp(self):
        md = self._empty_report().to_markdown()
        assert "2024-01-15" in md

    def test_empty_report_no_section_headers(self):
        """空报告（所有 section 为 None）→ 不包含数字章节标题。"""
        md = self._empty_report().to_markdown()
        assert "## 1." not in md

    def test_all_none_sections_no_exception(self):
        """所有 section 为 None 时不抛异常。"""
        report = MasterReport(generated_at=pd.Timestamp.now())
        md = report.to_markdown()
        assert isinstance(md, str)


# ── MasterReport.save ─────────────────────────────────────────────────────────

class TestMasterReportSave:
    def test_save_markdown_creates_file(self, tmp_path):
        report = MasterReport(generated_at=pd.Timestamp.now())
        report.save(tmp_path / "report", fmt="markdown")
        assert (tmp_path / "report.md").exists()

    def test_save_markdown_content_non_empty(self, tmp_path):
        report = MasterReport(generated_at=pd.Timestamp.now())
        report.save(tmp_path / "report", fmt="markdown")
        content = (tmp_path / "report.md").read_text()
        assert len(content) > 10

    def test_save_json_creates_file(self, tmp_path):
        report = MasterReport(generated_at=pd.Timestamp.now())
        report.save(tmp_path / "report", fmt="json")
        assert (tmp_path / "report.json").exists()

    def test_save_json_parseable(self, tmp_path):
        report = MasterReport(generated_at=pd.Timestamp.now())
        report.save(tmp_path / "report", fmt="json")
        data = json.loads((tmp_path / "report.json").read_text())
        assert "generated_at" in data

    def test_save_unsupported_format_raises(self, tmp_path):
        report = MasterReport(generated_at=pd.Timestamp.now())
        with pytest.raises(ValueError):
            report.save(tmp_path / "report", fmt="csv")

    def test_save_creates_parent_dir(self, tmp_path):
        """深层目录不存在时，自动创建。"""
        report = MasterReport(generated_at=pd.Timestamp.now())
        report.save(tmp_path / "deep" / "nested" / "report", fmt="markdown")
        assert (tmp_path / "deep" / "nested" / "report.md").exists()


# ── MasterReportBuilder: set_backtest ─────────────────────────────────────────

class TestSetBacktest:
    def test_build_returns_master_report(self):
        result = _make_backtest_result()
        report = MasterReportBuilder().set_backtest(result).build()
        assert isinstance(report, MasterReport)

    def test_performance_section_populated(self):
        result = _make_backtest_result()
        report = MasterReportBuilder().set_backtest(result).build()
        assert report.performance is not None

    def test_n_trades_correct(self):
        result = _make_backtest_result(n_trades=150)
        report = MasterReportBuilder().set_backtest(result).build()
        assert report.performance["n_trades"] == 150

    def test_cagr_present(self):
        result = _make_backtest_result(cagr=0.15)
        report = MasterReportBuilder().set_backtest(result).build()
        assert report.performance["cagr"] == pytest.approx(0.15)

    def test_markdown_contains_cagr(self):
        result = _make_backtest_result()
        report = MasterReportBuilder().set_backtest(result).build()
        md = report.to_markdown()
        assert "CAGR" in md

    def test_markdown_contains_sharpe(self):
        result = _make_backtest_result()
        report = MasterReportBuilder().set_backtest(result).build()
        md = report.to_markdown()
        assert "Sharpe" in md

    def test_without_backtest_performance_is_none(self):
        report = MasterReportBuilder().build()
        assert report.performance is None


# ── MasterReportBuilder: set_rolling_windows ──────────────────────────────────

class TestSetRollingWindows:
    def test_rolling_windows_section_populated(self):
        windows = _make_window_results(3)
        report  = MasterReportBuilder().set_rolling_windows(windows).build()
        assert report.rolling_windows is not None

    def test_n_windows_correct(self):
        windows = _make_window_results(3)
        report  = MasterReportBuilder().set_rolling_windows(windows).build()
        assert report.rolling_windows["n_windows"] == 3

    def test_win_rate_all_positive(self):
        """所有窗口 CAGR > 0 → 胜率 100%。"""
        windows = _make_window_results(3)   # 所有 CAGR > 0
        report  = MasterReportBuilder().set_rolling_windows(windows).build()
        assert report.rolling_windows["win_rate_pct"] == pytest.approx(100.0)

    def test_empty_windows_handled(self):
        report = MasterReportBuilder().set_rolling_windows([]).build()
        assert report.rolling_windows["n_windows"] == 0

    def test_windows_table_length(self):
        windows = _make_window_results(4)
        report  = MasterReportBuilder().set_rolling_windows(windows).build()
        assert len(report.rolling_windows["windows_table"]) == 4

    def test_markdown_contains_window_table(self):
        windows = _make_window_results(2)
        report  = MasterReportBuilder().set_rolling_windows(windows).build()
        md      = report.to_markdown()
        assert "滚动窗口分析" in md

    def test_acceptance_populated_when_provided(self):
        windows    = _make_window_results(2)
        acceptance = _make_acceptance(passed=True)
        report     = MasterReportBuilder().set_rolling_windows(windows, acceptance).build()
        assert report.acceptance is not None
        assert report.acceptance["passed"] is True

    def test_acceptance_none_when_not_provided(self):
        windows = _make_window_results(2)
        report  = MasterReportBuilder().set_rolling_windows(windows).build()
        assert report.acceptance is None

    def test_markdown_pass_badge_when_acceptance_passes(self):
        windows    = _make_window_results(2)
        acceptance = _make_acceptance(passed=True)
        report     = MasterReportBuilder().set_rolling_windows(windows, acceptance).build()
        assert "PASS" in report.to_markdown()

    def test_markdown_fail_badge_when_acceptance_fails(self):
        windows    = _make_window_results(2)
        acceptance = _make_acceptance(passed=False)
        report     = MasterReportBuilder().set_rolling_windows(windows, acceptance).build()
        assert "FAIL" in report.to_markdown()

    def test_failed_criteria_listed_in_markdown(self):
        windows    = _make_window_results(2)
        acceptance = _make_acceptance(passed=False)
        report     = MasterReportBuilder().set_rolling_windows(windows, acceptance).build()
        md = report.to_markdown()
        assert "excess_return" in md or "未通过项" in md


# ── MasterReportBuilder: set_factors ─────────────────────────────────────────

class TestSetFactors:
    def test_factor_summary_populated(self):
        reports = _make_factor_reports(4)
        report  = MasterReportBuilder().set_factors(reports).build()
        assert report.factor_summary is not None

    def test_n_factors_correct(self):
        reports = _make_factor_reports(4)
        report  = MasterReportBuilder().set_factors(reports).build()
        assert report.factor_summary["n_factors"] == 4

    def test_tier_distribution(self):
        reports = _make_factor_reports(4, tiers=["A", "B", "B", "D"])
        report  = MasterReportBuilder().set_factors(reports).build()
        td = report.factor_summary["tier_distribution"]
        assert td.get("B", 0) == 2
        assert td.get("A", 0) == 1

    def test_top_factors_sorted_by_ir(self):
        """top_factors 应按 IR 降序排列。"""
        reports = _make_factor_reports(4)
        report  = MasterReportBuilder().set_factors(reports).build()
        irs = [f["ir"] for f in report.factor_summary["top_factors"]]
        assert irs == sorted(irs, reverse=True)

    def test_empty_factors_handled(self):
        report = MasterReportBuilder().set_factors([]).build()
        assert report.factor_summary["n_factors"] == 0

    def test_markdown_contains_factor_section(self):
        reports = _make_factor_reports(2)
        report  = MasterReportBuilder().set_factors(reports).build()
        assert "因子研究" in report.to_markdown()


# ── MasterReportBuilder: set_universe ─────────────────────────────────────────

class TestSetUniverse:
    def test_universe_section_populated(self):
        mgr    = _make_universe_manager()
        report = MasterReportBuilder().set_universe(mgr).build()
        assert report.universe_status is not None

    def test_active_symbols_correct(self):
        mgr    = _make_universe_manager()
        report = MasterReportBuilder().set_universe(mgr).build()
        assert report.universe_status["n_active"] == 2
        assert "SPY" in report.universe_status["active_symbols"]

    def test_candidate_count_correct(self):
        mgr    = _make_universe_manager()
        report = MasterReportBuilder().set_universe(mgr).build()
        assert report.universe_status["n_candidates"] == 4

    def test_markdown_contains_universe_section(self):
        mgr    = _make_universe_manager()
        report = MasterReportBuilder().set_universe(mgr).build()
        assert "投资宇宙" in report.to_markdown()

    def test_markdown_lists_active_symbols(self):
        mgr    = _make_universe_manager()
        report = MasterReportBuilder().set_universe(mgr).build()
        md = report.to_markdown()
        assert "SPY" in md


# ── MasterReportBuilder: set_paper_trading ────────────────────────────────────

class TestSetPaperTrading:
    def test_paper_trading_section_populated(self):
        tracker = _make_pnl_tracker(10)
        report  = MasterReportBuilder().set_paper_trading(tracker).build()
        assert report.paper_trading is not None

    def test_n_days_correct(self):
        tracker = _make_pnl_tracker(7)
        report  = MasterReportBuilder().set_paper_trading(tracker).build()
        assert report.paper_trading["n_days"] == 7

    def test_kill_switch_false_by_default(self):
        tracker = _make_pnl_tracker(5)
        report  = MasterReportBuilder().set_paper_trading(tracker).build()
        assert report.paper_trading["kill_switch"] is False

    def test_kill_switch_true_propagated(self):
        tracker = _make_pnl_tracker(5)
        report  = MasterReportBuilder().set_paper_trading(tracker, kill_switch=True).build()
        assert report.paper_trading["kill_switch"] is True

    def test_markdown_contains_paper_trading_section(self):
        tracker = _make_pnl_tracker(5)
        report  = MasterReportBuilder().set_paper_trading(tracker).build()
        assert "模拟盘" in report.to_markdown()

    def test_kill_switch_propagated_to_risk_summary(self):
        """kill_switch=True → risk_summary 中 kill_switch_triggered=True。"""
        tracker = _make_pnl_tracker(5)
        report  = MasterReportBuilder().set_paper_trading(tracker, kill_switch=True).build()
        assert report.risk_summary is not None
        assert report.risk_summary.get("kill_switch_triggered") is True


# ── MasterReportBuilder: build + risk_summary ─────────────────────────────────

class TestBuildAndRisk:
    def test_build_returns_master_report(self):
        report = MasterReportBuilder().build()
        assert isinstance(report, MasterReport)

    def test_empty_builder_all_sections_none(self):
        report = MasterReportBuilder().build()
        assert report.performance is None
        assert report.rolling_windows is None
        assert report.factor_summary is None

    def test_risk_summary_from_backtest(self):
        """仅注入 backtest → risk_summary 含 max_drawdown。"""
        result = _make_backtest_result(max_dd=-0.12)
        report = MasterReportBuilder().set_backtest(result).build()
        assert report.risk_summary is not None
        assert report.risk_summary["max_drawdown"] == pytest.approx(-0.12)

    def test_chaining_works(self):
        """链式调用不抛出异常。"""
        windows = _make_window_results(2)
        tracker = _make_pnl_tracker(5)
        mgr     = _make_universe_manager()
        report = (
            MasterReportBuilder()
            .set_backtest(_make_backtest_result())
            .set_rolling_windows(windows, _make_acceptance())
            .set_factors(_make_factor_reports(3))
            .set_universe(mgr)
            .set_paper_trading(tracker)
            .build()
        )
        assert isinstance(report, MasterReport)

    def test_full_report_markdown_has_multiple_sections(self):
        """完整报告的 Markdown 应包含多个章节标题。"""
        windows = _make_window_results(2)
        tracker = _make_pnl_tracker(5)
        mgr     = _make_universe_manager()
        report = (
            MasterReportBuilder()
            .set_backtest(_make_backtest_result())
            .set_rolling_windows(windows, _make_acceptance())
            .set_factors(_make_factor_reports(3))
            .set_universe(mgr)
            .set_paper_trading(tracker)
            .build()
        )
        md = report.to_markdown()
        # 应有至少 5 个带数字的章节标题
        import re
        sections = re.findall(r"^## \d+\.", md, re.MULTILINE)
        assert len(sections) >= 5

    def test_generated_at_is_timestamp(self):
        report = MasterReportBuilder().build()
        assert isinstance(report.generated_at, pd.Timestamp)

    def test_partial_report_no_missing_section_crash(self):
        """只注入部分 section，to_markdown() 不抛异常。"""
        report = (
            MasterReportBuilder()
            .set_backtest(_make_backtest_result())
            .set_factors(_make_factor_reports(2))
            .build()
        )
        md = report.to_markdown()
        assert "策略绩效" in md
        assert "因子研究" in md
        assert "模拟盘" not in md   # 未注入此 section
