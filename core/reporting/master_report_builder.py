"""
MasterReportBuilder: 流式构建 MasterReport。

用法
----
    report = (
        MasterReportBuilder()
        .set_backtest(result, benchmark=spy_prices)
        .set_rolling_windows(windows, acceptance)
        .set_factors(factor_reports)
        .set_universe(universe_manager)
        .set_paper_trading(pnl_tracker, kill_switch=engine.is_kill_switch_triggered)
        .build()
    )
    report.save("reports/2024-01-15", fmt="markdown")

设计原则
--------
- 每个 set_* 方法独立调用，返回 self 支持链式调用
- 未调用的 set_* → 对应 section 为 None（to_markdown 跳过）
- build() 自动聚合 risk_summary（综合各 section 的风险字段）
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Dict, List, Optional

import numpy as np
import pandas as pd

from core.reporting.master_report import MasterReport

if TYPE_CHECKING:
    from core.backtest.backtest_engine import BacktestResult
    from core.backtest.window_analyzer import WindowResult, AcceptanceResult
    from core.factors.factor_evaluator import FactorReport
    from core.universe.universe_manager import UniverseManager
    from core.paper_trading.pnl_tracker import PnLTracker


class MasterReportBuilder:
    """流式报告构建器（Builder 模式）。"""

    def __init__(self) -> None:
        self._performance:     Optional[Dict] = None
        self._rolling_windows: Optional[Dict] = None
        self._acceptance:      Optional[Dict] = None
        self._factor_summary:  Optional[Dict] = None
        self._universe_status: Optional[Dict] = None
        self._paper_trading:   Optional[Dict] = None
        self._regime_performance:      Optional[Dict] = None
        self._strategy_attribution:    Optional[Dict] = None
        self._bt_paper_reconciliation: Optional[Dict] = None

    # ── set_backtest ──────────────────────────────────────────────────────────

    def set_backtest(
        self,
        result:    "BacktestResult",
        benchmark: Optional[pd.Series] = None,
    ) -> "MasterReportBuilder":
        """
        注入 BacktestResult。

        Parameters
        ----------
        result    : BacktestEngine.run() 返回值
        benchmark : 可选 benchmark 价格序列（注入后 metrics 含 alpha/beta/ir）
        """
        m = dict(result.metrics or {})
        m["n_trades"] = len(result.trades)
        self._performance = m
        return self

    # ── set_rolling_windows ───────────────────────────────────────────────────

    def set_rolling_windows(
        self,
        windows:    "List[WindowResult]",
        acceptance: "Optional[AcceptanceResult]" = None,
    ) -> "MasterReportBuilder":
        """
        注入滚动窗口分析结果。

        Parameters
        ----------
        windows    : WindowAnalyzer.rolling_backtest() 返回值
        acceptance : WindowAnalyzer.acceptance_check() 返回值（可选）
        """
        if not windows:
            self._rolling_windows = {
                "n_windows": 0,
                "win_rate_pct": 0.0,
                "avg_cagr": float("nan"),
                "avg_sharpe": float("nan"),
                "windows_table": [],
            }
        else:
            cagrs   = [w.cagr   for w in windows if not np.isnan(w.cagr)]
            sharpes = [w.sharpe for w in windows if not np.isnan(w.sharpe)]
            win_n   = sum(1 for c in cagrs if c > 0)

            self._rolling_windows = {
                "n_windows":    len(windows),
                "win_rate_pct": 100.0 * win_n / len(windows),
                "avg_cagr":     float(np.mean(cagrs))   if cagrs   else float("nan"),
                "avg_sharpe":   float(np.mean(sharpes)) if sharpes else float("nan"),
                "windows_table": [
                    {
                        "id":           w.window_id,
                        "start":        str(w.test_start.date())
                                        if hasattr(w.test_start, "date")
                                        else str(w.test_start),
                        "end":          str(w.test_end.date())
                                        if hasattr(w.test_end, "date")
                                        else str(w.test_end),
                        "cagr":         w.cagr,
                        "sharpe":       w.sharpe,
                        "max_drawdown": w.max_drawdown,
                    }
                    for w in windows
                ],
            }

        if acceptance is not None:
            self._acceptance = {
                "passed":          acceptance.passed,
                "excess_return":   acceptance.excess_return,
                "ir":              acceptance.ir,
                "dd_ratio":        acceptance.dd_ratio,
                "strategy_dd":     acceptance.strategy_dd,
                "benchmark_dd":    acceptance.benchmark_dd,
                "failed_criteria": list(acceptance.failed_criteria),
            }

        return self

    # ── set_factors ───────────────────────────────────────────────────────────

    def set_factors(
        self,
        reports: "List[FactorReport]",
    ) -> "MasterReportBuilder":
        """
        注入因子评估报告列表。

        Parameters
        ----------
        reports : FactorEvaluator.evaluate() 返回值列表
        """
        if not reports:
            self._factor_summary = {
                "n_factors": 0,
                "tier_distribution": {},
                "top_factors": [],
            }
            return self

        tiers = Counter(r.tier for r in reports)
        top   = sorted(reports, key=_primary_ir, reverse=True)[:10]

        self._factor_summary = {
            "n_factors":        len(reports),
            "tier_distribution": dict(tiers),
            "top_factors": [
                {
                    "name":    r.factor_name,
                    "tier":    r.tier,
                    "ir":      _primary_ir(r),
                    "mean_ic": _primary_mean_ic(r),
                }
                for r in top
            ],
        }
        return self

    # ── set_universe ──────────────────────────────────────────────────────────

    def set_universe(self, manager: "UniverseManager") -> "MasterReportBuilder":
        """
        注入 UniverseManager 当前状态。

        Parameters
        ----------
        manager : UniverseManager 实例（调用 refresh() 后的状态）
        """
        active      = manager.get_active_symbols()
        n_candidates = (
            len(manager._candidates)
            if hasattr(manager, "_candidates")
            else 0
        )
        self._universe_status = {
            "n_active":      len(active),
            "n_candidates":  n_candidates,
            "active_symbols": active,
        }
        return self

    # ── set_paper_trading ─────────────────────────────────────────────────────

    def set_paper_trading(
        self,
        tracker:      "PnLTracker",
        kill_switch:  bool = False,
    ) -> "MasterReportBuilder":
        """
        注入模拟盘 PnLTracker 状态。

        Parameters
        ----------
        tracker     : PnLTracker 实例
        kill_switch : PaperTradingEngine.is_kill_switch_triggered 值
        """
        summary = tracker.summary()
        self._paper_trading = {**summary, "kill_switch": kill_switch}
        return self

    # ── set_regime_performance ───────────────────────────────────────────────

    def set_regime_performance(
        self,
        equity_curve:     pd.Series,
        regime_series:    pd.Series,
        benchmark_series: pd.Series,
    ) -> "MasterReportBuilder":
        """Compute per-regime stratified performance."""
        from core.backtest.backtest_engine import compute_metrics

        if equity_curve.empty or regime_series.empty:
            return self

        strat_ret = equity_curve.pct_change().dropna()
        bench_ret = benchmark_series.pct_change().dropna()
        aligned_regime = regime_series.reindex(strat_ret.index, method="ffill")

        rows = []
        for regime in ["BULL", "RISK_ON", "NEUTRAL", "CAUTIOUS", "RISK_OFF", "CRISIS"]:
            mask = aligned_regime == regime
            n_days = int(mask.sum())
            if n_days < 10:
                continue
            s_r = strat_ret[mask]
            b_r = bench_ret.reindex(s_r.index).fillna(0)
            s_eq = (1 + s_r).cumprod()
            b_eq = (1 + b_r).cumprod()
            s_m = compute_metrics(s_eq, initial_capital=1.0)
            b_m = compute_metrics(b_eq, initial_capital=1.0)
            rows.append({
                "regime": regime,
                "n_days": n_days,
                "cagr": s_m.get("cagr"),
                "sharpe": s_m.get("sharpe"),
                "max_dd": s_m.get("max_drawdown"),
                "excess_vs_spy": (s_m.get("cagr", 0) or 0) - (b_m.get("cagr", 0) or 0),
            })

        self._regime_performance = {"regimes": rows}
        return self

    # ── set_strategy_attribution ──────────────────────────────────────────────

    def set_strategy_attribution(
        self,
        strategy_results: Dict[str, Dict],
    ) -> "MasterReportBuilder":
        """
        Inject per-strategy performance for attribution.

        Parameters
        ----------
        strategy_results : {name: {"result": BacktestResult, ...}} from run_backtest
        """
        from core.backtest.backtest_engine import compute_metrics

        rows = []
        total_return = 0.0
        returns_by_name = {}

        for name, run in strategy_results.items():
            bt = run.get("result")
            if bt is None:
                continue
            m = bt.metrics or {}
            cagr = m.get("cagr", 0) or 0
            returns_by_name[name] = cagr
            total_return += cagr

        for name, run in strategy_results.items():
            bt = run.get("result")
            if bt is None:
                continue
            m = bt.metrics or {}
            cagr = m.get("cagr", 0) or 0
            contrib = cagr / total_return if abs(total_return) > 1e-8 else 0
            rows.append({
                "name": name,
                "cagr": m.get("cagr"),
                "sharpe": m.get("sharpe"),
                "max_dd": m.get("max_drawdown"),
                "contribution_pct": contrib,
            })

        self._strategy_attribution = {"strategies": rows}
        return self

    # ── set_bt_paper_reconciliation ───────────────────────────────────────────

    def set_bt_paper_reconciliation(
        self,
        backtest_equity:  pd.Series,
        paper_equity:     pd.Series,
        tolerance_bps:    float = 150.0,
    ) -> "MasterReportBuilder":
        """Compare daily backtest vs paper trading equity curves."""
        if backtest_equity.empty or paper_equity.empty:
            return self

        common = backtest_equity.index.intersection(paper_equity.index)
        if len(common) < 2:
            return self

        bt_ret = backtest_equity.loc[common].pct_change().dropna()
        pp_ret = paper_equity.loc[common].pct_change().dropna()
        common2 = bt_ret.index.intersection(pp_ret.index)
        if len(common2) < 1:
            return self

        diff_bps = (bt_ret.loc[common2] - pp_ret.loc[common2]).abs() * 10000
        cum_bt = float((1 + bt_ret.loc[common2]).prod() - 1)
        cum_pp = float((1 + pp_ret.loc[common2]).prod() - 1)

        self._bt_paper_reconciliation = {
            "n_days": len(common2),
            "mean_daily_diff_bps": float(diff_bps.mean()),
            "max_daily_diff_bps": float(diff_bps.max()),
            "cumulative_diff": cum_bt - cum_pp,
            "tolerance_bps": tolerance_bps,
            "within_tolerance": float(diff_bps.mean()) <= tolerance_bps,
        }
        return self

    # ── build ─────────────────────────────────────────────────────────────────

    def build(self) -> MasterReport:
        """
        构建并返回 MasterReport 实例。

        自动合成 risk_summary（汇聚各 section 的风险指标）。
        """
        risk: Dict = {}

        if self._performance:
            dd = self._performance.get("max_drawdown")
            if dd is not None:
                risk["max_drawdown"] = dd

        if self._paper_trading:
            risk["current_drawdown"]    = self._paper_trading.get("running_drawdown")
            risk["kill_switch_triggered"] = self._paper_trading.get("kill_switch", False)
        elif self._performance:
            risk["kill_switch_triggered"] = False

        return MasterReport(
            generated_at    = pd.Timestamp.now(),
            performance     = self._performance,
            rolling_windows = self._rolling_windows,
            acceptance      = self._acceptance,
            factor_summary  = self._factor_summary,
            universe_status = self._universe_status,
            paper_trading   = self._paper_trading,
            risk_summary    = risk if risk else None,
            regime_performance      = self._regime_performance,
            strategy_attribution    = self._strategy_attribution,
            bt_paper_reconciliation = self._bt_paper_reconciliation,
        )


# ── 内部工具函数 ──────────────────────────────────────────────────────────────

def _primary_ir(report: "FactorReport") -> float:
    """取最短预测期的 IR（用于排序）。"""
    if not report.stats:
        return float("nan")
    h = min(report.stats.keys())
    v = report.stats[h].ir
    return float(v) if not np.isnan(v) else float("-inf")


def _primary_mean_ic(report: "FactorReport") -> float:
    """取最短预测期的 mean_ic。"""
    if not report.stats:
        return float("nan")
    h = min(report.stats.keys())
    return float(report.stats[h].mean_ic)
