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

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestEngine, compute_metrics
from core.backtest.window_analyzer import WindowAnalyzer
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

    # Stage 4: Diversity
    diversity_corr:  float = float("nan")
    passed_diversity: bool = False

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
        self._score_w           = score_weights or {
            "oos_ir":             2.0,
            "oos_sharpe":         1.0,
            "oos_excess_return":  5.0,
            "max_dd_penalty":     3.0,
            "regime_robust":      1.0,
            "cost_robust":        0.5,
            "param_robust":       0.5,
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
    ) -> EvalResult:
        """
        运行完整多阶段评估。

        Parameters
        ----------
        spec              : 要评估的策略规格
        price_df          : 日收盘价（所有资产）
        regime_series     : RegimeDetector 输出
        benchmark_series  : 基准价格（SPY）
        risk_universe     : 风险资产列表（传给策略实例化）
        def_universe      : 防御资产列表（传给策略实例化）
        promoted_curves   : {spec_id: equity_curve} 已晋升策略的权益曲线（用于多样性检查）
        stop_after        : 在哪个阶段后停止（节省时间）
        """
        result = EvalResult(
            spec_id       = spec.spec_id,
            strategy_type = spec.strategy_type,
            params        = spec.params_dict,
        )

        # ── Stage 1: Quick ────────────────────────────────────────────────────
        try:
            strategy = instantiate_strategy(spec, risk_universe, def_universe)
            signals  = strategy.generate(price_df, regime_series)
            weights  = self._build_weights(signals, price_df, regime_series)
            bt_result = self._run_backtest(weights, price_df, regime_series, benchmark_series)
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

        # ── Stage 2: OOS ──────────────────────────────────────────────────────
        try:
            oos_metrics = self._run_walk_forward(
                spec, price_df, regime_series, benchmark_series, risk_universe, def_universe
            )
            result.oos_ir           = oos_metrics.get("mean_oos_ir", float("nan"))
            result.oos_pass_rate    = oos_metrics.get("pass_rate",   float("nan"))
            result.oos_sharpe       = oos_metrics.get("mean_oos_sharpe", float("nan"))
            result.oos_excess_return = oos_metrics.get("mean_oos_excess_return", float("nan"))
        except Exception as exc:
            logger.warning("Evaluator Stage2 error for %s: %s", spec.spec_id, exc)

        result.passed_oos = (
            not np.isnan(result.oos_ir)
            and result.oos_ir >= self._oos_ir
            and not np.isnan(result.oos_pass_rate)
            and result.oos_pass_rate >= self._oos_pass_rate
        )

        if stop_after == "oos" or not result.passed_oos:
            result.composite_score = self._score(result)
            return result

        # ── Stage 3: Robustness ───────────────────────────────────────────────
        result.regime_robust = self._check_regime_robustness(
            spec, price_df, regime_series, benchmark_series, risk_universe, def_universe
        )
        result.cost_robust = self._check_cost_robustness(
            weights, price_df, regime_series, benchmark_series
        )
        result.param_robust = self._check_param_robustness(
            spec, price_df, regime_series, benchmark_series,
            result.quick_sharpe, risk_universe, def_universe,
        )
        result.passed_robustness = result.regime_robust and result.cost_robust

        # ── Stage 4: Diversity ────────────────────────────────────────────────
        if promoted_curves and result.equity_curve is not None:
            result.diversity_corr = self._max_correlation(
                result.equity_curve, promoted_curves
            )
            result.passed_diversity = result.diversity_corr < self._div_corr
        else:
            result.passed_diversity = True  # first strategy always passes

        # ── Tier & score ──────────────────────────────────────────────────────
        result.tier            = self._assign_tier(result)
        result.composite_score = self._score(result)
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_weights(
        self,
        signals:       pd.DataFrame,
        price_df:      pd.DataFrame,
        regime_series: pd.Series,
    ) -> pd.DataFrame:
        constructor = PortfolioConstructor()
        return constructor.build(
            raw_signals   = signals,
            price_df      = price_df,
            regime_series = regime_series,
        )

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
        )
        return engine.run(
            signals_df    = weights,
            price_df      = price_df,
            regime_series = regime_series,
        )

    def _run_walk_forward(
        self,
        spec:             StrategySpec,
        price_df:         pd.DataFrame,
        regime_series:    pd.Series,
        benchmark_series: pd.Series,
        risk_universe:    Optional[List[str]],
        def_universe:     Optional[List[str]],
    ) -> Dict[str, float]:
        """Walk-forward OOS 评估，返回汇总统计。"""
        from core.backtest.window_analyzer import WindowAnalyzer

        engine   = BacktestEngine(cost_model=self._cost, initial_capital=self._capital)
        analyzer = WindowAnalyzer(engine=engine)

        strategy = instantiate_strategy(spec, risk_universe, def_universe)
        signals  = strategy.generate(price_df, regime_series)
        weights  = self._build_weights(signals, price_df, regime_series)

        windows = analyzer.walk_forward(
            signals_df = weights,
            price_df   = price_df,
            benchmark  = benchmark_series,
        )

        if not windows:
            return {}

        irs    = [w.metrics.get("ir",             float("nan")) for w in windows]
        sharps = [w.metrics.get("sharpe",          float("nan")) for w in windows]
        excess = [w.metrics.get("excess_return",   float("nan")) for w in windows]

        n_pass = sum(
            1 for w in windows
            if w.metrics.get("excess_return", -99) > 0.05
            and w.metrics.get("ir", -99) > 0.30
        )
        pass_rate = n_pass / len(windows)

        def _mean(lst: list) -> float:
            v = [x for x in lst if not np.isnan(x)]
            return float(np.mean(v)) if v else float("nan")

        return {
            "mean_oos_ir":            _mean(irs),
            "mean_oos_sharpe":        _mean(sharps),
            "mean_oos_excess_return": _mean(excess),
            "pass_rate":              pass_rate,
            "n_windows":              len(windows),
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
        """至少在 regime_robust_n 个 regime 下超额收益为正。"""
        target_regimes = ["BULL", "RISK_ON", "NEUTRAL"]
        strategy = instantiate_strategy(spec, risk_universe, def_universe)
        signals  = strategy.generate(price_df, regime_series)
        weights  = self._build_weights(signals, price_df, regime_series)

        benchmark_ret = benchmark_series.pct_change().dropna()
        positive_count = 0

        for r in target_regimes:
            mask  = (regime_series.reindex(weights.index, method="ffill") == r)
            if mask.sum() < 60:
                continue
            r_weights = weights[mask]
            r_prices  = price_df.reindex(r_weights.index)
            r_bench   = benchmark_ret.reindex(r_weights.index).fillna(0)
            bt        = self._run_backtest(r_weights, r_prices, regime_series, benchmark_series)
            m         = bt.metrics
            excess    = m.get("cagr", 0.0) - float(
                (1 + r_bench.mean()) ** 252 - 1
            )
            if excess > 0:
                positive_count += 1

        return positive_count >= self._regime_n

    def _check_cost_robustness(
        self,
        weights:          pd.DataFrame,
        price_df:         pd.DataFrame,
        regime_series:    pd.Series,
        benchmark_series: pd.Series,
    ) -> bool:
        """2× 成本下 net alpha 仍为正。"""
        from core.execution.cost_model import CostModel, CostModelConfig
        try:
            stress_cost = CostModel(self._cost._config, stress_multiplier=self._cost_mult)
        except Exception:
            stress_cost = self._cost

        engine = BacktestEngine(cost_model=stress_cost, initial_capital=self._capital)
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
                    weights   = self._build_weights(signals, price_df, regime_series)
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

    def _assign_tier(self, r: EvalResult) -> str:
        if not r.passed_oos:
            return "D"
        ir = r.oos_ir if not np.isnan(r.oos_ir) else 0.0
        if ir >= _TIER_THRESHOLDS["S"] and r.passed_robustness:
            return "S"
        if ir >= _TIER_THRESHOLDS["A"]:
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
        return score

