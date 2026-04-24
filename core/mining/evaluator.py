"""
MiningEvaluator: 多阶段策略评估管线。

评估阶段
--------
Stage 1 — Quick filter (全期回测)
  目的：快速淘汰明显不合格的策略
  通过标准：Sharpe > 0.30, MaxDD < 40%, CAGR > 2%
  耗时：~0.5s/策略

Stage 2 — OOS filter (Walk-forward)
  目的：验证真正的样本外稳定性
  通过标准：Tier D 通过率 ≥ 60%, OOS IR > 0.30
  耗时：~5-10s/策略

Stage 3 — Robustness checks
  目的：淘汰脆弱策略（依赖特定 regime / 成本 / 参数）
  3a. Regime robustness: 在 2+ regime 下超额收益为正
  3b. Cost robustness: 2× 成本后 net alpha 仍为正
  3c. Param robustness: 关键参数 ±20% → Sharpe 变化 < 50%

Stage 4 — Diversity check
  目的：避免新增与已晋升策略高度相关的重复策略
  通过标准：与所有已晋升策略的权益曲线相关系数 < 0.70
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestEngine
from core.execution.cost_model import CostModel
from core.portfolio.constructor import PortfolioConstructor
from core.mining.strategy_space import StrategySpec, instantiate_strategy
from core.logging_setup import get_logger

logger = get_logger(__name__)

# Tier thresholds (from FactorEvaluator convention)
_TIER_THRESHOLDS = {
    "S": 0.8,
    "A": 0.5,
    "B": 0.3,
    "C": 0.1,
}


# ── EvalResult ────────────────────────────────────────────────────────────────

@dataclass
class EvalResult:
    """单次策略评估的完整结果。"""
    spec_id:       str
    strategy_type: str
    params:        Dict[str, Any]

    # Stage 1: Quick
    quick_sharpe:    float = float("nan")
    quick_max_dd:    float = float("nan")
    quick_cagr:      float = float("nan")
    passed_quick:    bool  = False

    # Stage 2: OOS
    oos_ir:           float = float("nan")
    oos_pass_rate:    float = float("nan")
    oos_sharpe:       float = float("nan")
    oos_excess_return: float = float("nan")
    passed_oos:        bool  = False

    # Stage 3: Robustness
    regime_robust:     bool  = False
    cost_robust:       bool  = False
    param_robust:      bool  = False
    passed_robustness: bool  = False

    # Stage 3b: Stress periods
    stress_passed:     bool  = False
    stress_results:    Dict[str, Dict] = field(default_factory=dict)

    # Stage 4: Diversity
    diversity_corr:  float = float("nan")
    passed_diversity: bool = False

    # Stage 5: Holdout
    holdout_ir:             float = float("nan")
    holdout_excess_return:  float = float("nan")
    holdout_max_dd:         float = float("nan")
    passed_holdout:         bool  = False

    # OOS/IS overfit ratio
    oos_is_sharpe_ratio: float = float("nan")

    # Stage 6: QQQ hard gate (P0.4, 2026-04-20).
    # Excess CAGR/return vs QQQ across 3 windows — all must clear their
    # threshold for promotion. None → gate disabled (legacy runs).
    qqq_full_period_excess: float = float("nan")
    qqq_holdout_excess:     float = float("nan")
    qqq_oos_avg_excess:     float = float("nan")
    passed_qqq_gate:        bool  = True  # True when gate disabled OR cleared

    # Overall
    tier:            str   = "D"
    composite_score: float = 0.0
    equity_curve:    Optional[pd.Series] = field(default=None, repr=False)
    evaluated_at:    str   = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        return {
            k: v for k, v in self.__dict__.items()
            if k != "equity_curve"
        }


# ── MiningEvaluator ───────────────────────────────────────────────────────────

class MiningEvaluator:
    """
    多阶段策略评估管线。

    Parameters
    ----------
    cost_model        : CostModel 实例
    initial_capital   : 初始资金
    quick_min_sharpe  : Stage 1 最低 Sharpe
    quick_max_dd      : Stage 1 最大允许回撤（正值，如 0.40）
    quick_min_cagr    : Stage 1 最低 CAGR
    oos_min_pass_rate : Stage 2 OOS 窗口通过率下限
    oos_min_ir        : Stage 2 最低 IR vs 基准
    oos_min_excess_ret: Stage 2 最低超额收益
    regime_robust_n   : Stage 3a 至少在 N 个 regime 下有超额收益
    cost_multiplier   : Stage 3b 成本压力倍数（默认 2.0）
    param_max_change  : Stage 3c Sharpe 最大允许变化比例（默认 0.50）
    diversity_max_corr: Stage 4 最大允许相关系数
    score_weights     : composite_score 各项权重
    """

    def __init__(
        self,
        cost_model:         CostModel,
        initial_capital:    float = 10_000.0,
        quick_min_sharpe:   float = 0.30,
        quick_max_dd:       float = 0.40,
        quick_min_cagr:     float = 0.02,
        oos_min_pass_rate:  float = 0.60,
        oos_min_ir:         float = 0.30,
        oos_min_excess_ret: float = 0.03,
        regime_robust_n:    int   = 2,
        cost_multiplier:    float = 2.0,
        param_max_change:   float = 0.50,
        diversity_max_corr: float = 0.70,
        score_weights:      Optional[Dict[str, float]] = None,
        holdout_bars:       int   = 252,
        quick_data_fraction: float = 0.70,
        stress_periods:     Optional[List[Dict]] = None,
        crisis_dd_vs_spy:   float = 1.0,
        wf_test_bars_by_type: Optional[Dict[str, int]] = None,
        min_oos_is_sharpe_ratio: float = 0.50,
        defensive_window_dd_mult: float = 1.3,
        # QQQ hard gate (P0.4, 2026-04-20). When a qqq_series is passed
        # to evaluate(), strategies must clear all three thresholds or
        # be demoted to tier "D" (non-promotable). Defaults = 0.0, i.e.
        # strategy CAGR must be ≥ QQQ on each window.
        min_cagr_excess_vs_qqq:       float = 0.0,
        min_holdout_excess_vs_qqq:    float = 0.0,
        min_avg_oos_excess_vs_qqq:    float = 0.0,
        # Share mode (P0.5, 2026-04-20). Passed through to every internal
        # BacktestEngine so mining trials match paper/backtest production
        # execution. Default False = legacy fractional; production now
        # passes True from run_mining.py (sourced from config/risk.yaml).
        integer_shares:               bool  = False,
    ) -> None:
        self._cost              = cost_model
        self._capital           = initial_capital
        self._q_sharpe          = quick_min_sharpe
        self._q_dd              = quick_max_dd
        self._q_cagr            = quick_min_cagr
        self._oos_pass_rate     = oos_min_pass_rate
        self._oos_ir            = oos_min_ir
        self._oos_excess        = oos_min_excess_ret
        self._regime_n          = regime_robust_n
        self._cost_mult         = cost_multiplier
        self._param_change      = param_max_change
        self._div_corr          = diversity_max_corr
        self._holdout_bars      = holdout_bars
        self._quick_frac        = quick_data_fraction
        self._stress_periods    = stress_periods or []
        self._crisis_dd_spy     = crisis_dd_vs_spy
        self._wf_test_bars      = wf_test_bars_by_type or {}
        self._min_oos_is_ratio  = min_oos_is_sharpe_ratio
        self._def_win_dd_mult   = defensive_window_dd_mult
        self._min_qqq_cagr_exc     = min_cagr_excess_vs_qqq
        self._min_qqq_holdout_exc  = min_holdout_excess_vs_qqq
        self._min_qqq_oos_avg_exc  = min_avg_oos_excess_vs_qqq
        self._integer_shares       = integer_shares
        self._open_df: Optional[pd.DataFrame] = None
        self._score_w           = score_weights or {
            "oos_ir":             2.0,
            "oos_sharpe":         1.0,
            "oos_excess_return":  5.0,
            "max_dd_penalty":     3.0,
            "regime_robust":      1.0,
            "cost_robust":        0.5,
            "param_robust":       0.5,
            "stress_bonus":       1.5,
            "holdout_bonus":      2.0,
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def evaluate(
        self,
        spec:              StrategySpec,
        price_df:          pd.DataFrame,
        regime_series:     pd.Series,
        benchmark_series:  pd.Series,
        risk_universe:     Optional[List[str]] = None,
        def_universe:      Optional[List[str]] = None,
        promoted_curves:   Optional[Dict[str, pd.Series]] = None,
        stop_after:        str = "full",   # "quick" | "oos" | "full"
        qqq_series:        Optional[pd.Series] = None,
    ) -> EvalResult:
        """
        运行完整多阶段评估（含数据隔离）。

        数据切分逻辑:
          holdout  = 最后 holdout_bars 天（Stage 5 专用，Stages 1-4 不可见）
          non_holdout = price_df 去掉 holdout
          quick_data = non_holdout 的前 quick_data_fraction（Stage 1 快筛）
          oos_data = 完整 non_holdout（Stage 2-4 walk-forward / robustness）
        """
        result = EvalResult(
            spec_id       = spec.spec_id,
            strategy_type = spec.strategy_type,
            params        = spec.params_dict,
        )

        # ── Data isolation ────────────────────────────────────────────────────
        n_total = len(price_df)
        holdout_start_idx = max(0, n_total - self._holdout_bars)

        non_holdout_df   = price_df.iloc[:holdout_start_idx]
        holdout_df       = price_df.iloc[holdout_start_idx:]

        n_nh = len(non_holdout_df)
        quick_end_idx    = int(n_nh * self._quick_frac)
        quick_df         = non_holdout_df.iloc[:quick_end_idx]

        non_holdout_regime = regime_series.reindex(non_holdout_df.index, method="ffill")
        quick_regime       = regime_series.reindex(quick_df.index, method="ffill")
        non_holdout_bench  = benchmark_series.reindex(non_holdout_df.index, method="ffill")
        quick_bench        = benchmark_series.reindex(quick_df.index, method="ffill")

        logger.debug(
            "Data isolation: total=%d, non_holdout=%d, quick=%d, holdout=%d",
            n_total, n_nh, quick_end_idx, len(holdout_df),
        )

        # ── Stage 1: Quick (uses only first 70% of non-holdout) ──────────────
        try:
            strategy = instantiate_strategy(spec, risk_universe, def_universe)
            signals  = strategy.generate(quick_df, quick_regime)
            weights  = self._build_weights(signals, quick_df, quick_regime, spec.strategy_type)
            bt_result = self._run_backtest(weights, quick_df, quick_regime, quick_bench)
        except Exception as exc:
            logger.warning("Evaluator Stage1 error for %s: %s", spec.spec_id, exc)
            result.composite_score = -999.0
            return result

        m = bt_result.metrics
        result.quick_sharpe = m.get("sharpe",       float("nan"))
        result.quick_max_dd = m.get("max_drawdown", float("nan"))
        result.quick_cagr   = m.get("cagr",         float("nan"))
        result.equity_curve = bt_result.equity_curve

        result.passed_quick = (
            not np.isnan(result.quick_sharpe)
            and result.quick_sharpe >= self._q_sharpe
            and result.quick_max_dd >= -self._q_dd
            and not np.isnan(result.quick_cagr)
            and result.quick_cagr >= self._q_cagr
        )

        if stop_after == "quick" or not result.passed_quick:
            result.composite_score = self._score(result)
            return result

        # ── Stage 2: OOS (uses full non-holdout for walk-forward) ─────────────
        try:
            oos_metrics = self._run_walk_forward(
                spec, non_holdout_df, non_holdout_regime, non_holdout_bench,
                risk_universe, def_universe,
            )
            result.oos_ir           = oos_metrics.get("mean_oos_ir", float("nan"))
            result.oos_pass_rate    = oos_metrics.get("pass_rate",   float("nan"))
            result.oos_sharpe       = oos_metrics.get("mean_oos_sharpe", float("nan"))
            result.oos_excess_return = oos_metrics.get("mean_oos_excess_return", float("nan"))
        except Exception as exc:
            logger.warning("Evaluator Stage2 error for %s: %s", spec.spec_id, exc)

        if not np.isnan(result.quick_sharpe) and not np.isnan(result.oos_sharpe) and abs(result.quick_sharpe) > 1e-6:
            result.oos_is_sharpe_ratio = result.oos_sharpe / result.quick_sharpe

        result.passed_oos = (
            not np.isnan(result.oos_ir)
            and result.oos_ir >= self._oos_ir
            and not np.isnan(result.oos_pass_rate)
            and result.oos_pass_rate >= self._oos_pass_rate
        )

        if stop_after == "oos" or not result.passed_oos:
            result.composite_score = self._score(result)
            return result

        # ── Stage 3: Robustness (uses full non-holdout) ───────────────────────
        nh_strategy = instantiate_strategy(spec, risk_universe, def_universe)
        nh_signals  = nh_strategy.generate(non_holdout_df, non_holdout_regime)
        nh_weights  = self._build_weights(nh_signals, non_holdout_df, non_holdout_regime, spec.strategy_type)

        result.regime_robust = self._check_regime_robustness(
            spec, non_holdout_df, non_holdout_regime, non_holdout_bench,
            risk_universe, def_universe,
        )
        result.cost_robust = self._check_cost_robustness(
            nh_weights, non_holdout_df, non_holdout_regime, non_holdout_bench
        )
        result.param_robust = self._check_param_robustness(
            spec, non_holdout_df, non_holdout_regime, non_holdout_bench,
            result.quick_sharpe, risk_universe, def_universe,
        )

        # Stage 3b: Stress periods (uses full price_df since stress periods may be outside non-holdout)
        result.stress_passed, result.stress_results = self._check_stress_periods(
            spec, price_df, regime_series, benchmark_series, risk_universe, def_universe,
        )

        # Stage 3c: Subperiod robustness (no single subperiod > 50% of total return)
        subperiod_ok = self._check_subperiod_robustness(result.equity_curve)

        result.passed_robustness = result.regime_robust and result.cost_robust and result.stress_passed and subperiod_ok

        # ── Stage 4: Diversity ────────────────────────────────────────────────
        if promoted_curves and result.equity_curve is not None:
            result.diversity_corr = self._max_correlation(
                result.equity_curve, promoted_curves
            )
            result.passed_diversity = result.diversity_corr < self._div_corr
        else:
            result.passed_diversity = True

        # ── Stage 5: Holdout (last 252 bars, invisible until now) ─────────────
        if len(holdout_df) >= 60:
            try:
                holdout_regime = regime_series.reindex(holdout_df.index, method="ffill")
                holdout_bench  = benchmark_series.reindex(holdout_df.index, method="ffill")
                h_strategy = instantiate_strategy(spec, risk_universe, def_universe)
                h_signals  = h_strategy.generate(holdout_df, holdout_regime)
                h_weights  = self._build_weights(h_signals, holdout_df, holdout_regime, spec.strategy_type)
                h_bt       = self._run_backtest(h_weights, holdout_df, holdout_regime, holdout_bench)
                h_m        = h_bt.metrics

                result.holdout_max_dd = h_m.get("max_drawdown", float("nan"))

                bench_ret = holdout_bench.pct_change().dropna()
                bench_cagr = float((1 + bench_ret.mean()) ** 252 - 1) if len(bench_ret) > 0 else 0.0
                h_cagr = h_m.get("cagr", float("nan"))
                if not np.isnan(h_cagr):
                    result.holdout_excess_return = h_cagr - bench_cagr

                strat_ret = h_bt.equity_curve.pct_change().dropna() if not h_bt.equity_curve.empty else pd.Series(dtype=float)
                b_ret_aligned = bench_ret.reindex(strat_ret.index).fillna(0)
                if len(strat_ret) > 10:
                    te = (strat_ret - b_ret_aligned).std() * np.sqrt(252)
                    if te > 1e-6:
                        result.holdout_ir = float((strat_ret.mean() - b_ret_aligned.mean()) * 252 / te)

                result.passed_holdout = (
                    not np.isnan(result.holdout_ir) and result.holdout_ir >= 0.20
                )
            except Exception as exc:
                logger.warning("Evaluator Stage5 holdout error for %s: %s", spec.spec_id, exc)
        else:
            result.passed_holdout = True
            logger.debug("Holdout data too short (%d bars), skipping holdout check", len(holdout_df))

        # ── Stage 6: QQQ hard gate (P0.4, 2026-04-20) ─────────────────────────
        # When qqq_series provided, compute excess at 3 windows. All
        # three must meet their threshold or tier is demoted to "D".
        if qqq_series is not None and result.equity_curve is not None \
                and not result.equity_curve.empty:
            result.passed_qqq_gate = self._check_qqq_gate(
                result, price_df, holdout_df, qqq_series,
                non_holdout_df, spec, risk_universe, def_universe,
            )
        else:
            result.passed_qqq_gate = True  # gate disabled when no qqq

        # ── Tier & score ──────────────────────────────────────────────────────
        result.tier            = self._assign_tier(result)
        result.composite_score = self._score(result)
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    _NO_VOL_PARITY_TYPES = {"multi_factor"}

    def _build_weights(
        self,
        signals:        pd.DataFrame,
        price_df:       pd.DataFrame,
        regime_series:  pd.Series,
        strategy_type:  str = "",
    ) -> pd.DataFrame:
        use_vp = strategy_type not in self._NO_VOL_PARITY_TYPES
        constructor = PortfolioConstructor(use_vol_parity=use_vp)
        return constructor.build(
            raw_signals   = signals,
            price_df      = price_df,
            regime_series = regime_series,
        )

    def set_open_df(self, open_df: pd.DataFrame) -> None:
        """Set open price data for realistic T+1 open execution."""
        self._open_df = open_df

    def _run_backtest(
        self,
        weights:          pd.DataFrame,
        price_df:         pd.DataFrame,
        regime_series:    pd.Series,
        benchmark_series: pd.Series,
    ):
        engine = BacktestEngine(
            cost_model      = self._cost,
            initial_capital = self._capital,
            integer_shares  = self._integer_shares,
        )
        open_slice = self._open_df.reindex(price_df.index) if self._open_df is not None else None
        return engine.run(
            signals_df       = weights,
            price_df         = price_df,
            open_df          = open_slice,
            regime_series    = regime_series,
            benchmark_series = benchmark_series,
        )

    def _get_test_bars(self, strategy_type: str) -> int:
        """Look up walk-forward test_bars for a strategy type."""
        if strategy_type in self._wf_test_bars:
            return self._wf_test_bars[strategy_type]
        return self._wf_test_bars.get("_default", 126)

    def _is_defensive_window(
        self,
        window,
        regime_series: pd.Series,
    ) -> bool:
        """Check if a walk-forward test window falls in a defensive regime."""
        defensive = {"CRISIS", "RISK_OFF", "CAUTIOUS"}
        aligned = regime_series.reindex(
            pd.date_range(window.test_start, window.test_end, freq="B"),
            method="ffill",
        )
        if aligned.empty:
            return False
        counts = aligned.value_counts()
        dominant = counts.index[0] if not counts.empty else "NEUTRAL"
        return dominant in defensive

    def _run_walk_forward(
        self,
        spec:             StrategySpec,
        price_df:         pd.DataFrame,
        regime_series:    pd.Series,
        benchmark_series: pd.Series,
        risk_universe:    Optional[List[str]],
        def_universe:     Optional[List[str]],
    ) -> Dict[str, float]:
        """Walk-forward OOS with type-specific test_bars and regime-aware pass criteria."""
        from core.backtest.window_analyzer import WindowAnalyzer

        test_bars = self._get_test_bars(spec.strategy_type)
        engine    = BacktestEngine(cost_model=self._cost, initial_capital=self._capital,
                                    integer_shares=self._integer_shares)
        analyzer  = WindowAnalyzer(engine=engine)

        strategy = instantiate_strategy(spec, risk_universe, def_universe)
        signals  = strategy.generate(price_df, regime_series)
        weights  = self._build_weights(signals, price_df, regime_series, spec.strategy_type)

        windows = analyzer.walk_forward(
            signals_df = weights,
            price_df   = price_df,
            benchmark  = benchmark_series,
            test_size  = test_bars,
        )

        if not windows:
            return {}

        irs    = [w.metrics.get("ir",             float("nan")) for w in windows]
        sharps = [w.metrics.get("sharpe",          float("nan")) for w in windows]
        excess = [w.metrics.get("excess_return",   float("nan")) for w in windows]

        n_pass = 0
        for w in windows:
            is_def = self._is_defensive_window(w, regime_series)
            if is_def:
                strat_dd = abs(w.metrics.get("max_drawdown", -1.0))
                b_slice = benchmark_series.loc[w.test_start:w.test_end].dropna()
                if len(b_slice) > 1:
                    b_cummax = b_slice.cummax()
                    bench_dd = abs(float(((b_slice - b_cummax) / b_cummax).min()))
                else:
                    bench_dd = strat_dd
                if bench_dd < 1e-6:
                    bench_dd = strat_dd
                if strat_dd <= bench_dd * self._def_win_dd_mult:
                    n_pass += 1
            else:
                if (w.metrics.get("excess_return", -99) > self._oos_excess
                        and w.metrics.get("ir", -99) > self._oos_ir):
                    n_pass += 1

        pass_rate = n_pass / len(windows)

        def _mean(lst: list) -> float:
            # Drop non-finite (NaN AND ±inf). Compute_metrics std-floor at
            # source now returns NaN for near-flat windows, but this is
            # defense-in-depth against any path returning inf. Per D4
            # semantics: fail-soft (drop), but WARN so pollution is visible.
            # See `4b5f36ed9ab5` in R39 archive — oos_sharpe came out -4.87e15
            # before compute_metrics got the std-floor guard.
            bad_idx = [i for i, x in enumerate(lst) if not np.isfinite(x)]
            if bad_idx:
                logger.warning(
                    "_run_walk_forward._mean: dropping %d non-finite value(s) at indices %s "
                    "(likely near-flat OOS window producing inf Sharpe)",
                    len(bad_idx), bad_idx,
                )
            v = [x for x in lst if np.isfinite(x)]
            return float(np.mean(v)) if v else float("nan")

        return {
            "mean_oos_ir":            _mean(irs),
            "mean_oos_sharpe":        _mean(sharps),
            "mean_oos_excess_return": _mean(excess),
            "pass_rate":              pass_rate,
            "n_windows":              len(windows),
            "test_bars_used":         test_bars,
        }

    def _check_regime_robustness(
        self,
        spec:          StrategySpec,
        price_df:      pd.DataFrame,
        regime_series: pd.Series,
        benchmark_series: pd.Series,
        risk_universe: Optional[List[str]],
        def_universe:  Optional[List[str]],
    ) -> bool:
        """
        All 6 regimes tested with differentiated criteria:
          Growth regimes (BULL/RISK_ON/NEUTRAL): excess_return > 0 in >= regime_robust_n
          Defensive regimes (CAUTIOUS/RISK_OFF/CRISIS): drawdown <= SPY × crisis_dd_vs_spy in >= 1
        """
        growth_regimes    = ["BULL", "RISK_ON", "NEUTRAL"]
        defensive_regimes = ["CAUTIOUS", "RISK_OFF", "CRISIS"]

        strategy = instantiate_strategy(spec, risk_universe, def_universe)
        signals  = strategy.generate(price_df, regime_series)
        weights  = self._build_weights(signals, price_df, regime_series, spec.strategy_type)

        benchmark_ret = benchmark_series.pct_change().dropna()
        aligned_regime = regime_series.reindex(weights.index, method="ffill")

        growth_pass = 0
        defensive_pass = 0
        defensive_tested = 0

        for r in growth_regimes:
            mask = (aligned_regime == r)
            if mask.sum() < 60:
                continue
            r_weights = weights[mask]
            r_prices  = price_df.reindex(r_weights.index)
            r_bench   = benchmark_ret.reindex(r_weights.index).fillna(0)
            bt = self._run_backtest(r_weights, r_prices, regime_series, benchmark_series)
            m  = bt.metrics
            excess = m.get("cagr", 0.0) - float((1 + r_bench.mean()) ** 252 - 1)
            if excess > 0:
                growth_pass += 1

        for r in defensive_regimes:
            mask = (aligned_regime == r)
            if mask.sum() < 30:
                continue
            defensive_tested += 1
            r_weights = weights[mask]
            r_prices  = price_df.reindex(r_weights.index)
            r_bench   = benchmark_ret.reindex(r_weights.index).fillna(0)
            bt = self._run_backtest(r_weights, r_prices, regime_series, benchmark_series)
            strat_dd = abs(bt.metrics.get("max_drawdown", -1.0))

            bench_eq = (1 + r_bench).cumprod()
            bench_dd = abs(float((bench_eq / bench_eq.cummax() - 1).min())) if len(bench_eq) > 0 else 1.0
            if strat_dd <= bench_dd * self._crisis_dd_spy:
                defensive_pass += 1

        growth_ok    = growth_pass >= self._regime_n
        defensive_ok = defensive_tested == 0 or defensive_pass >= 1
        return growth_ok and defensive_ok

    def _check_stress_periods(
        self,
        spec:             StrategySpec,
        price_df:         pd.DataFrame,
        regime_series:    pd.Series,
        benchmark_series: pd.Series,
        risk_universe:    Optional[List[str]],
        def_universe:     Optional[List[str]],
    ) -> Tuple[bool, Dict[str, Dict]]:
        """
        Run backtest on each configured stress period.
        Strategy must not exceed max_drawdown_abs in any period with sufficient data.
        Returns (all_passed, {period_name: metrics_dict}).
        """
        if not self._stress_periods:
            return True, {}

        results: Dict[str, Dict] = {}
        all_passed = True

        for sp in self._stress_periods:
            name      = sp.get("name", "unknown")
            sp_start  = pd.Timestamp(sp["start"])
            sp_end    = pd.Timestamp(sp["end"])
            max_dd    = sp.get("max_drawdown_abs", 0.25)

            period_df = price_df[(price_df.index >= sp_start) & (price_df.index <= sp_end)]
            if len(period_df) < 30:
                results[name] = {"skipped": True, "reason": f"insufficient_data({len(period_df)}<30)"}
                logger.debug("Stress period %s: only %d bars, skipping", name, len(period_df))
                continue

            try:
                p_regime = regime_series.reindex(period_df.index, method="ffill")
                p_bench  = benchmark_series.reindex(period_df.index, method="ffill")
                strategy = instantiate_strategy(spec, risk_universe, def_universe)
                signals  = strategy.generate(period_df, p_regime)
                weights  = self._build_weights(signals, period_df, p_regime, spec.strategy_type)
                bt       = self._run_backtest(weights, period_df, p_regime, p_bench)
                strat_dd = abs(bt.metrics.get("max_drawdown", -1.0))

                bench_ret = p_bench.pct_change().dropna()
                bench_eq  = (1 + bench_ret).cumprod()
                bench_dd  = abs(float((bench_eq / bench_eq.cummax() - 1).min())) if len(bench_eq) > 0 else 1.0

                passed = strat_dd <= max_dd
                results[name] = {
                    "skipped": False,
                    "strat_max_dd": strat_dd,
                    "bench_max_dd": bench_dd,
                    "max_dd_limit": max_dd,
                    "passed": passed,
                    "strat_cagr": bt.metrics.get("cagr", float("nan")),
                }
                if not passed:
                    all_passed = False
                    logger.debug(
                        "Stress period %s FAILED: strat_dd=%.2f%% > limit=%.2f%%",
                        name, strat_dd * 100, max_dd * 100,
                    )
            except Exception as exc:
                results[name] = {"skipped": True, "reason": str(exc)}
                logger.warning("Stress period %s error: %s", name, exc)

        return all_passed, results

    @staticmethod
    def _check_subperiod_robustness(
        equity_curve: Optional[pd.Series],
        n_periods: int = 4,
        max_contribution: float = 0.50,
    ) -> bool:
        """No single subperiod should contribute > max_contribution of total return."""
        if equity_curve is None or len(equity_curve) < n_periods * 60:
            return True
        total_ret = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1)
        if abs(total_ret) < 1e-6:
            return True
        n = len(equity_curve)
        for i in range(n_periods):
            seg = equity_curve.iloc[i * n // n_periods:(i + 1) * n // n_periods]
            seg_ret = float(seg.iloc[-1] / seg.iloc[0] - 1)
            if abs(seg_ret / total_ret) > max_contribution:
                return False
        return True

    def _check_cost_robustness(
        self,
        weights:          pd.DataFrame,
        price_df:         pd.DataFrame,
        regime_series:    pd.Series,
        benchmark_series: pd.Series,
    ) -> bool:
        """Nx 成本下 net alpha 仍为正。"""
        import copy
        from core.execution.cost_model import CostModel

        stress_cfg = copy.deepcopy(self._cost._cfg)
        for tier_name, tier in stress_cfg.tiers.items():
            tier.commission_bps *= self._cost_mult
            tier.slippage_interday_bps *= self._cost_mult
            tier.slippage_intraday_bps *= self._cost_mult
        stress_cost = CostModel(stress_cfg)

        engine = BacktestEngine(cost_model=stress_cost, initial_capital=self._capital,
                                 integer_shares=self._integer_shares)
        bt     = engine.run(signals_df=weights, price_df=price_df, regime_series=regime_series)
        bench  = benchmark_series.pct_change().dropna()
        cagr   = bt.metrics.get("cagr", float("nan"))
        if np.isnan(cagr):
            return False
        bench_cagr = float((1 + bench.mean()) ** 252 - 1)
        return cagr > bench_cagr

    def _check_param_robustness(
        self,
        spec:             StrategySpec,
        price_df:         pd.DataFrame,
        regime_series:    pd.Series,
        benchmark_series: pd.Series,
        base_sharpe:      float,
        risk_universe:    Optional[List[str]],
        def_universe:     Optional[List[str]],
    ) -> bool:
        """
        关键参数 ±20% 扰动后 Sharpe 变化 < param_max_change。
        只对数值型参数做扰动；布尔/分类型参数跳过。
        """
        if np.isnan(base_sharpe) or abs(base_sharpe) < 1e-6:
            return False

        params = spec.params_dict
        perturb_count = 0
        robust_count  = 0

        for key, val in params.items():
            if not isinstance(val, (int, float)):
                continue
            if val == 0:
                continue
            for delta in [0.8, 1.2]:
                perturbed = dict(params)
                perturbed[key] = type(val)(val * delta)
                try:
                    from core.mining.strategy_space import StrategySpec as SS
                    p_spec    = SS.from_dict(spec.strategy_type, perturbed)
                    strategy  = instantiate_strategy(p_spec, risk_universe, def_universe)
                    signals   = strategy.generate(price_df, regime_series)
                    weights   = self._build_weights(signals, price_df, regime_series, spec.strategy_type)
                    bt        = self._run_backtest(weights, price_df, regime_series, benchmark_series)
                    p_sharpe  = bt.metrics.get("sharpe", float("nan"))
                    if np.isnan(p_sharpe):
                        continue
                    change = abs(p_sharpe - base_sharpe) / max(abs(base_sharpe), 1e-6)
                    perturb_count += 1
                    if change < self._param_change:
                        robust_count += 1
                except Exception:
                    continue

        if perturb_count == 0:
            return True  # no numerical params to test
        return (robust_count / perturb_count) >= 0.6

    def _max_correlation(
        self,
        equity:   pd.Series,
        promoted: Dict[str, pd.Series],
    ) -> float:
        """与已晋升策略的权益曲线最大相关系数。"""
        ret = equity.pct_change().dropna()
        max_corr = 0.0
        for _, p_eq in promoted.items():
            p_ret = p_eq.pct_change().dropna()
            common = ret.index.intersection(p_ret.index)
            if len(common) < 30:
                continue
            corr = float(ret.loc[common].corr(p_ret.loc[common]))
            if not np.isnan(corr):
                max_corr = max(max_corr, abs(corr))
        return max_corr

    def _check_qqq_gate(
        self,
        result,
        price_df:       pd.DataFrame,
        holdout_df:     pd.DataFrame,
        qqq_series:     pd.Series,
        non_holdout_df: pd.DataFrame,
        spec:           StrategySpec,
        risk_universe,
        def_universe,
    ) -> bool:
        """Evaluate the QQQ hard gate on 3 windows (约束: QQQ
        Outperformance Rule, CLAUDE.md).

        All three must clear their configured threshold for the gate
        to pass; failure flips tier to "D". Windows:

          1. Full-period (price_df) excess CAGR
          2. Holdout (last 252 bars) excess return
          3. Non-holdout (OOS proxy) excess CAGR

        Non-holdout is used as a cheap proxy for the walk-forward
        "mean OOS excess" metric — running a true per-window excess
        would require re-running walk-forward against QQQ (expensive).
        The per-window average and the single non-holdout CAGR
        differ in practice, but we accept the approximation for now;
        the net sign (pass/fail) is what matters for gating.
        """
        def _cagr(series: pd.Series) -> float:
            # M14 extension: trim leading/trailing NaN before iloc. Pre-fix,
            # expanded universes with a ticker starting one day earlier (e.g.
            # BRK-B 2015-01-02 vs SPY/QQQ 2015-01-03) pulled the equity index
            # start to a date where the engine's NAV is NaN, producing
            # NaN/NaN = NaN in the ratio. Result: `qqq_full_period_excess`
            # never got set and was archived as None. TODO: consolidate with
            # core/backtest/backtest_engine.compute_metrics which has the
            # same guard.
            if series is None or series.empty:
                return float("nan")
            fvi = series.first_valid_index()
            lvi = series.last_valid_index()
            if fvi is None or lvi is None or fvi == lvi:
                return float("nan")
            series = series.loc[fvi:lvi]
            n = len(series)
            if n < 2:
                return float("nan")
            total = float(series.iloc[-1] / series.iloc[0])
            if total <= 0:
                return float("nan")
            years = max(n / 252.0, 1.0 / 252.0)
            return total ** (1.0 / years) - 1.0

        def _total_return(series: pd.Series) -> float:
            # Same M14 extension as _cagr above.
            if series is None or series.empty:
                return float("nan")
            fvi = series.first_valid_index()
            lvi = series.last_valid_index()
            if fvi is None or lvi is None or fvi == lvi:
                return float("nan")
            series = series.loc[fvi:lvi]
            if len(series) < 2:
                return float("nan")
            return float(series.iloc[-1] / series.iloc[0] - 1.0)

        # Prepare regime series that cover the requested dataframes.
        regime_full = pd.Series("NEUTRAL", index=price_df.index)

        # (1) Full-period backtest
        try:
            strat_full = instantiate_strategy(spec, risk_universe, def_universe)
            signals = strat_full.generate(price_df, regime_full)
            weights = self._build_weights(signals, price_df, regime_full,
                                          spec.strategy_type)
            bt = self._run_backtest(weights, price_df, regime_full, qqq_series)
            strat_eq = bt.equity_curve
            qqq_full = qqq_series.reindex(strat_eq.index, method="ffill")
            strat_cagr = _cagr(strat_eq)
            qqq_cagr   = _cagr(qqq_full)
            if not (np.isnan(strat_cagr) or np.isnan(qqq_cagr)):
                result.qqq_full_period_excess = strat_cagr - qqq_cagr
        except Exception as exc:
            logger.warning("QQQ gate: full-period bt failed for %s: %s",
                           spec.spec_id, exc)

        # (2) Holdout
        if not holdout_df.empty:
            try:
                regime_h = pd.Series("NEUTRAL", index=holdout_df.index)
                strat_h = instantiate_strategy(spec, risk_universe, def_universe)
                sig_h = strat_h.generate(holdout_df, regime_h)
                w_h = self._build_weights(sig_h, holdout_df, regime_h,
                                          spec.strategy_type)
                bt_h = self._run_backtest(w_h, holdout_df, regime_h, qqq_series)
                strat_eq_h = bt_h.equity_curve
                qqq_h = qqq_series.reindex(strat_eq_h.index, method="ffill")
                strat_ret_h = _total_return(strat_eq_h)
                qqq_ret_h   = _total_return(qqq_h)
                if not (np.isnan(strat_ret_h) or np.isnan(qqq_ret_h)):
                    result.qqq_holdout_excess = strat_ret_h - qqq_ret_h
            except Exception as exc:
                logger.warning("QQQ gate: holdout bt failed for %s: %s",
                               spec.spec_id, exc)

        # (3) Non-holdout (OOS proxy) — compute excess CAGR
        if not non_holdout_df.empty:
            try:
                regime_nh = pd.Series("NEUTRAL", index=non_holdout_df.index)
                strat_nh = instantiate_strategy(spec, risk_universe, def_universe)
                sig_nh = strat_nh.generate(non_holdout_df, regime_nh)
                w_nh = self._build_weights(sig_nh, non_holdout_df, regime_nh,
                                           spec.strategy_type)
                bt_nh = self._run_backtest(w_nh, non_holdout_df, regime_nh,
                                           qqq_series)
                strat_eq_nh = bt_nh.equity_curve
                qqq_nh = qqq_series.reindex(strat_eq_nh.index, method="ffill")
                strat_cagr_nh = _cagr(strat_eq_nh)
                qqq_cagr_nh   = _cagr(qqq_nh)
                if not (np.isnan(strat_cagr_nh) or np.isnan(qqq_cagr_nh)):
                    result.qqq_oos_avg_excess = strat_cagr_nh - qqq_cagr_nh
            except Exception as exc:
                logger.warning("QQQ gate: non-holdout bt failed for %s: %s",
                               spec.spec_id, exc)

        # Gate decision: every configured threshold must clear.
        checks = []
        if not np.isnan(result.qqq_full_period_excess):
            checks.append(result.qqq_full_period_excess
                          >= self._min_qqq_cagr_exc)
        if not np.isnan(result.qqq_holdout_excess):
            checks.append(result.qqq_holdout_excess
                          >= self._min_qqq_holdout_exc)
        if not np.isnan(result.qqq_oos_avg_excess):
            checks.append(result.qqq_oos_avg_excess
                          >= self._min_qqq_oos_avg_exc)
        if not checks:
            # No window could be computed → conservative: fail gate
            return False
        return all(checks)

    def _assign_tier(self, r: EvalResult) -> str:
        if not r.passed_oos:
            return "D"
        if not np.isnan(r.oos_is_sharpe_ratio) and r.oos_is_sharpe_ratio < self._min_oos_is_ratio:
            return "D"
        # QQQ hard gate (P0.4): strategy that doesn't beat QQQ on full
        # period + holdout + OOS-proxy is unpromotable regardless of
        # other metrics. See CLAUDE.md "QQQ Outperformance Rule".
        if not r.passed_qqq_gate:
            return "D"
        if not r.passed_holdout:
            return "C"
        ir = r.oos_ir if not np.isnan(r.oos_ir) else 0.0
        if ir >= _TIER_THRESHOLDS["S"] and r.passed_robustness:
            return "S"
        if ir >= _TIER_THRESHOLDS["A"] and r.passed_robustness:
            return "A"
        if ir >= _TIER_THRESHOLDS["B"]:
            return "B"
        if ir >= _TIER_THRESHOLDS["C"]:
            return "C"
        return "D"

    def _score(self, r: EvalResult) -> float:
        if not r.passed_quick:
            return -10.0
        w = self._score_w
        score = 0.0
        if r.passed_oos:
            if not np.isnan(r.oos_ir):
                score += r.oos_ir * w.get("oos_ir", 2.0)
            if not np.isnan(r.oos_sharpe):
                score += r.oos_sharpe * w.get("oos_sharpe", 1.0)
            if not np.isnan(r.oos_excess_return):
                score += max(0, r.oos_excess_return) * w.get("oos_excess_return", 5.0)
        else:
            if not np.isnan(r.quick_sharpe):
                score += r.quick_sharpe * 0.3
        if not np.isnan(r.quick_max_dd):
            score -= abs(min(r.quick_max_dd, 0)) * w.get("max_dd_penalty", 3.0)
        if r.regime_robust:
            score += w.get("regime_robust", 1.0)
        if r.cost_robust:
            score += w.get("cost_robust", 0.5)
        if r.param_robust:
            score += w.get("param_robust", 0.5)
        if r.stress_passed:
            score += w.get("stress_bonus", 1.5)
        if r.passed_holdout:
            score += w.get("holdout_bonus", 2.0)
            if not np.isnan(r.holdout_ir):
                score += max(0, r.holdout_ir) * 1.0
        if not np.isnan(r.oos_is_sharpe_ratio) and r.oos_is_sharpe_ratio < 0.5:
            score -= 2.0
        return score

