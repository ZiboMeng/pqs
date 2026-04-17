"""
WindowAnalyzer: 滚动窗口回测与样本外验证。

功能
----
  rolling_backtest    — 样本内分段评估：将全历史分成 N 段，每段独立运行回测。
                        用途：策略稳定性分析（非 OOS）。
  walk_forward        — 真正的样本外 walk-forward：训练期 → 测试期严格分离。
                        用途：估算真实 OOS 绩效、防过拟合。
  oos_consistency_check — 汇总 walk-forward 窗口的 OOS 一致性统计。
  acceptance_check    — 对照 Tier D 标准（超额收益 / IR / 回撤比）判断是否达标。
  summarize_windows   — 将窗口列表汇总为 DataFrame。

Walk-forward 语义
-----------------
  每个窗口：
    训练期 [t, t+train_size)   → 调用方在此区间生成/训练信号（外部完成）
    测试期 [t+train_size, t+train_size+test_size)  → 严格 OOS，WindowResult 仅报告此期绩效
  滚动步长 = test_size（测试期无重叠）
  调用方必须确保 signals_df 在测试期不含未来数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestEngine, BacktestResult, compute_metrics
from core.logging_setup import get_logger

logger = get_logger(__name__)

# 默认 walk-forward 参数（对应 config/backtest.yaml 中的 walk_forward_* 字段）
_DEFAULT_TRAIN_BARS = 756   # 约 3 年
_DEFAULT_TEST_BARS  = 126   # 约 6 个月


# ── 窗口绩效结果 ──────────────────────────────────────────────────────────────

@dataclass
class WindowResult:
    """
    单个窗口的回测绩效。

    Attributes
    ----------
    window_id   : 窗口序号（从 0 开始）
    train_start : 训练期起始日（walk_forward 模式才有意义）
    train_end   : 训练期结束日
    test_start  : 测试期起始日（metrics 基于此区间）
    test_end    : 测试期结束日
    is_oos      : True = walk-forward OOS 窗口；False = rolling 样本内窗口
    metrics     : 绩效指标字典
    """
    window_id:   int
    train_start: pd.Timestamp
    train_end:   pd.Timestamp
    test_start:  pd.Timestamp
    test_end:    pd.Timestamp
    metrics:     Dict[str, float] = field(default_factory=dict)
    is_oos:      bool = False

    @property
    def sharpe(self) -> float:
        return self.metrics.get("sharpe", float("nan"))

    @property
    def max_drawdown(self) -> float:
        return self.metrics.get("max_drawdown", float("nan"))

    @property
    def cagr(self) -> float:
        return self.metrics.get("cagr", float("nan"))

    @property
    def excess_return(self) -> float:
        return self.metrics.get("excess_return", float("nan"))


# ── Tier D 验收结果 ────────────────────────────────────────────────────────────

@dataclass
class AcceptanceResult:
    """Tier D 达标检验输出。"""
    passed:            bool
    excess_return:     float    # 策略 CAGR - benchmark CAGR
    strategy_dd:       float    # 策略最大回撤
    benchmark_dd:      float    # benchmark 最大回撤
    dd_ratio:          float    # strategy_dd / benchmark_dd
    ir:                float    # 信息比率
    details:           Dict[str, float] = field(default_factory=dict)
    failed_criteria:   List[str]  = field(default_factory=list)

    def __str__(self) -> str:
        status = "PASS ★" if self.passed else "FAIL ✗"
        return (
            f"[{status}] Tier D Acceptance\n"
            f"  excess_return = {self.excess_return:.2%} (需 > 5%)\n"
            f"  IR            = {self.ir:.3f} (需 > 0.3)\n"
            f"  dd_ratio      = {self.dd_ratio:.2f}x (需 ≤ 1.5x)\n"
            f"  failed        : {self.failed_criteria or 'None'}"
        )


# ── WindowAnalyzer ────────────────────────────────────────────────────────────

class WindowAnalyzer:
    """
    滚动窗口回测与 Tier D 验收。

    Parameters
    ----------
    engine      : BacktestEngine 实例（含 cost_model）
    window_size : rolling_backtest 中每个评估窗口的天数（交易日）
    step_size   : rolling_backtest 中滚动步长（交易日）；默认等于 window_size（不重叠）
    """

    # Tier D 验收阈值（与 BacktestConfig.ValidationConfig 一致）
    TIER_D_MIN_EXCESS_RETURN   = 0.05   # +5% 年化超额收益
    TIER_D_MIN_IR              = 0.30
    TIER_D_MAX_DD_MULTIPLIER   = 1.50   # 回撤不超过 benchmark 的 1.5×

    def __init__(
        self,
        engine:      BacktestEngine,
        window_size: int = 252,
        step_size:   Optional[int] = None,
    ):
        self._engine      = engine
        self._window_size = window_size
        self._step_size   = step_size or window_size

    # ── 样本内分段评估 ────────────────────────────────────────────────────────

    def rolling_backtest(
        self,
        signals_df:  pd.DataFrame,
        price_df:    pd.DataFrame,
        open_df:     Optional[pd.DataFrame] = None,
        vix_series:  Optional[pd.Series] = None,
        benchmark:   Optional[pd.Series] = None,
    ) -> List[WindowResult]:
        """
        样本内分段评估（纯样本内，非 OOS）。

        将全历史按 window_size 分段，每段独立运行 BacktestEngine，
        输出各段绩效。用途：策略稳定性可视化、跨期一致性分析。

        注意：train_start == test_start，所有 metrics 均为样本内绩效。
             如需真正 OOS 验证，请使用 walk_forward()。
        """
        dates = signals_df.index.intersection(price_df.index)
        n     = len(dates)

        if n < self._window_size:
            logger.warning(
                "rolling_backtest: only %d dates, less than window_size=%d",
                n, self._window_size,
            )
            return []

        results: List[WindowResult] = []
        w_id = 0

        start_idx = 0
        while start_idx + self._window_size <= n:
            end_idx   = start_idx + self._window_size
            sub_dates = dates[start_idx:end_idx]

            s_sub = signals_df.loc[sub_dates]
            p_sub = price_df.loc[sub_dates]
            o_sub = open_df.loc[sub_dates]     if open_df    is not None else None
            v_sub = vix_series.loc[sub_dates]  if vix_series is not None else None
            b_sub = benchmark.loc[sub_dates]   if benchmark  is not None else None

            result = self._engine.run(s_sub, p_sub, o_sub, v_sub)

            metrics = result.metrics.copy()
            if b_sub is not None and not result.equity_curve.empty:
                extra = compute_metrics(
                    result.equity_curve,
                    initial_capital = result.equity_curve.iloc[0],
                    benchmark       = b_sub,
                )
                metrics.update({k: v for k, v in extra.items() if k not in metrics})

            # 样本内：train == test
            results.append(WindowResult(
                window_id   = w_id,
                train_start = sub_dates[0],
                train_end   = sub_dates[-1],
                test_start  = sub_dates[0],
                test_end    = sub_dates[-1],
                metrics     = metrics,
                is_oos      = False,
            ))

            start_idx += self._step_size
            w_id      += 1

        logger.info("rolling_backtest: completed %d in-sample windows", len(results))
        return results

    # ── 真正的 walk-forward OOS 验证 ─────────────────────────────────────────

    def walk_forward(
        self,
        signals_df:  pd.DataFrame,
        price_df:    pd.DataFrame,
        open_df:     Optional[pd.DataFrame] = None,
        vix_series:  Optional[pd.Series] = None,
        benchmark:   Optional[pd.Series] = None,
        train_size:  int = _DEFAULT_TRAIN_BARS,
        test_size:   int = _DEFAULT_TEST_BARS,
    ) -> List[WindowResult]:
        """
        真正的样本外 walk-forward 验证。

        每个窗口：
          训练期 [t, t+train_size)         — 调用方在此区间完成信号生成/参数优化
          测试期 [t+train_size, t+train_size+test_size) — 严格 OOS，metrics 仅反映此期
        滚动步长 = test_size（测试期无重叠）。

        ⚠️  调用方必须确保传入的 signals_df 是在不使用测试期数据的情况下生成的。
             本方法仅负责在测试期上评估性能，不会检查信号是否含未来数据。

        Parameters
        ----------
        train_size : 训练期长度（交易日），默认 756（≈ 3 年）
        test_size  : 测试期长度（交易日），默认 126（≈ 6 个月）
        """
        dates = signals_df.index.intersection(price_df.index)
        n     = len(dates)

        min_bars = train_size + test_size
        if n < min_bars:
            logger.warning(
                "walk_forward: only %d dates, need ≥ %d (train=%d + test=%d)",
                n, min_bars, train_size, test_size,
            )
            return []

        results: List[WindowResult] = []
        w_id      = 0
        start_idx = 0

        while start_idx + train_size + test_size <= n:
            train_end_idx = start_idx + train_size
            test_end_idx  = train_end_idx + test_size

            train_dates = dates[start_idx:train_end_idx]
            test_dates  = dates[train_end_idx:test_end_idx]

            # 仅在测试期评估（严格 OOS）
            s_test = signals_df.loc[test_dates]
            p_test = price_df.loc[test_dates]
            o_test = open_df.loc[test_dates]    if open_df    is not None else None
            v_test = vix_series.loc[test_dates] if vix_series is not None else None
            b_test = benchmark.loc[test_dates]  if benchmark  is not None else None

            result = self._engine.run(s_test, p_test, o_test, v_test)

            metrics = result.metrics.copy()
            if b_test is not None and not result.equity_curve.empty:
                extra = compute_metrics(
                    result.equity_curve,
                    initial_capital = result.equity_curve.iloc[0],
                    benchmark       = b_test,
                )
                metrics.update({k: v for k, v in extra.items() if k not in metrics})
                # 记录超额收益便于 OOS 一致性检查
                b_m = compute_metrics(b_test, initial_capital=b_test.iloc[0])
                metrics["excess_return"] = (
                    metrics.get("cagr", float("nan"))
                    - b_m.get("cagr", float("nan"))
                )

            results.append(WindowResult(
                window_id   = w_id,
                train_start = train_dates[0],
                train_end   = train_dates[-1],
                test_start  = test_dates[0],
                test_end    = test_dates[-1],
                metrics     = metrics,
                is_oos      = True,
            ))

            start_idx += test_size   # 无重叠：步长 = 测试期
            w_id      += 1

        logger.info("walk_forward: completed %d OOS windows", len(results))
        return results

    # ── Expanding window 验证 ──────────────────────────────────────────────────

    def expanding_window(
        self,
        signals_df:  pd.DataFrame,
        price_df:    pd.DataFrame,
        open_df:     Optional[pd.DataFrame] = None,
        benchmark:   Optional[pd.Series] = None,
        min_train:   int = 504,
        test_size:   int = 126,
    ) -> List[WindowResult]:
        """
        Expanding window validation: training set grows, test set fixed size.

        Each window:
          Train: [0, t)              — expands over time
          Test:  [t, t+test_size)    — fixed size, no overlap
        """
        dates = signals_df.index.intersection(price_df.index)
        n = len(dates)

        results: List[WindowResult] = []
        w_id = 0
        train_end = min_train

        while train_end + test_size <= n:
            test_end = train_end + test_size
            train_dates = dates[:train_end]
            test_dates = dates[train_end:test_end]

            s_test = signals_df.loc[test_dates]
            p_test = price_df.loc[test_dates]
            o_test = open_df.loc[test_dates] if open_df is not None else None
            b_test = benchmark.loc[test_dates] if benchmark is not None else None

            result = self._engine.run(s_test, p_test, o_test)

            metrics = result.metrics.copy()
            if b_test is not None and not result.equity_curve.empty:
                extra = compute_metrics(
                    result.equity_curve,
                    initial_capital=result.equity_curve.iloc[0],
                    benchmark=b_test,
                )
                metrics.update({k: v for k, v in extra.items() if k not in metrics})
                b_m = compute_metrics(b_test, initial_capital=b_test.iloc[0])
                metrics["excess_return"] = (
                    metrics.get("cagr", float("nan")) - b_m.get("cagr", float("nan"))
                )

            results.append(WindowResult(
                window_id=w_id,
                train_start=train_dates[0],
                train_end=train_dates[-1],
                test_start=test_dates[0],
                test_end=test_dates[-1],
                metrics=metrics,
                is_oos=True,
            ))

            train_end += test_size
            w_id += 1

        logger.info("expanding_window: completed %d windows (min_train=%d)", len(results), min_train)
        return results

    # ── OOS 一致性检查 ────────────────────────────────────────────────────────

    @staticmethod
    def oos_consistency_check(
        windows:               List[WindowResult],
        min_positive_fraction: float = 0.60,
    ) -> Dict:
        """
        汇总 walk-forward 窗口的样本外一致性统计。

        Parameters
        ----------
        min_positive_fraction : 需要超过多少比例的 OOS 窗口 CAGR > 0 才算通过

        Returns
        -------
        dict with keys:
          passed, n_windows, positive_fraction,
          mean_cagr, min_cagr, mean_sharpe,
          mean_excess_return（若 benchmark 已提供）
        """
        if not windows:
            return {"passed": False, "n_windows": 0, "positive_fraction": 0.0}

        cagrs    = [w.metrics.get("cagr",           float("nan")) for w in windows]
        sharpes  = [w.metrics.get("sharpe",          float("nan")) for w in windows]
        excesses = [w.metrics.get("excess_return",   float("nan")) for w in windows]

        valid_cagrs = [c for c in cagrs if not np.isnan(c)]
        if not valid_cagrs:
            return {"passed": False, "n_windows": len(windows), "positive_fraction": 0.0}

        pos_frac = sum(1 for c in valid_cagrs if c > 0) / len(valid_cagrs)

        out: Dict = {
            "passed":            pos_frac >= min_positive_fraction,
            "n_windows":         len(windows),
            "positive_fraction": pos_frac,
            "mean_cagr":         float(np.mean(valid_cagrs)),
            "min_cagr":          float(np.min(valid_cagrs)),
            "mean_sharpe":       float(np.nanmean(sharpes)),
        }
        valid_ex = [e for e in excesses if not np.isnan(e)]
        if valid_ex:
            out["mean_excess_return"] = float(np.mean(valid_ex))

        return out

    # ── Tier D 验收 ───────────────────────────────────────────────────────────

    def acceptance_check(
        self,
        result:    BacktestResult,
        benchmark: pd.Series,
    ) -> AcceptanceResult:
        """
        对照 Tier D 标准，判断策略是否达标。

        Parameters
        ----------
        result    : BacktestEngine.run() 的输出
        benchmark : benchmark 权益曲线（e.g. SPY close price）
        """
        if result.equity_curve.empty or benchmark.empty:
            return AcceptanceResult(
                passed=False, excess_return=np.nan,
                strategy_dd=np.nan, benchmark_dd=np.nan,
                dd_ratio=np.nan, ir=np.nan,
                failed_criteria=["empty_result"],
            )

        common   = result.equity_curve.index.intersection(benchmark.index)
        strat_eq = result.equity_curve.loc[common]
        bench_eq = benchmark.loc[common]

        strat_metrics = compute_metrics(strat_eq, initial_capital=strat_eq.iloc[0])
        bench_metrics = compute_metrics(bench_eq, initial_capital=bench_eq.iloc[0])

        strat_cagr = strat_metrics.get("cagr", np.nan)
        bench_cagr = bench_metrics.get("cagr", np.nan)
        strat_dd   = strat_metrics.get("max_drawdown", np.nan)
        bench_dd   = bench_metrics.get("max_drawdown", np.nan)

        excess_return = (
            strat_cagr - bench_cagr
            if not (np.isnan(strat_cagr) or np.isnan(bench_cagr))
            else np.nan
        )
        dd_ratio = (
            abs(strat_dd) / abs(bench_dd)
            if bench_dd != 0 and not np.isnan(bench_dd)
            else np.nan
        )

        full_metrics = compute_metrics(
            strat_eq, initial_capital=strat_eq.iloc[0], benchmark=bench_eq
        )
        ir = full_metrics.get("ir", np.nan)

        failed: List[str] = []
        if np.isnan(excess_return) or excess_return < self.TIER_D_MIN_EXCESS_RETURN:
            failed.append(f"excess_return={excess_return:.2%} < {self.TIER_D_MIN_EXCESS_RETURN:.0%}")
        if np.isnan(ir) or ir < self.TIER_D_MIN_IR:
            failed.append(f"ir={ir:.3f} < {self.TIER_D_MIN_IR}")
        if np.isnan(dd_ratio) or dd_ratio > self.TIER_D_MAX_DD_MULTIPLIER:
            failed.append(f"dd_ratio={dd_ratio:.2f} > {self.TIER_D_MAX_DD_MULTIPLIER}")

        return AcceptanceResult(
            passed          = len(failed) == 0,
            excess_return   = excess_return if not np.isnan(excess_return) else 0.0,
            strategy_dd     = strat_dd,
            benchmark_dd    = bench_dd,
            dd_ratio        = dd_ratio if not np.isnan(dd_ratio) else 99.9,
            ir              = ir if not np.isnan(ir) else 0.0,
            details         = full_metrics,
            failed_criteria = failed,
        )

    # ── 窗口结果汇总 ──────────────────────────────────────────────────────────

    @staticmethod
    def summarize_windows(windows: List[WindowResult]) -> pd.DataFrame:
        """
        将窗口列表汇总为 DataFrame（每行一个窗口）。
        包含 test_start / test_end / is_oos 及全部 metrics。
        """
        if not windows:
            return pd.DataFrame()

        rows = []
        for w in windows:
            row = {
                "window_id":  w.window_id,
                "train_start": w.train_start,
                "train_end":   w.train_end,
                "test_start":  w.test_start,
                "test_end":    w.test_end,
                "is_oos":      w.is_oos,
            }
            row.update(w.metrics)
            rows.append(row)

        return pd.DataFrame(rows).set_index("window_id")
