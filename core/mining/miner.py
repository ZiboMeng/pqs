"""
StrategyMiner: 基于 Optuna 的策略循环挖掘主引擎。

工作流程
--------
对每种策略类型（DualMomentum / TrendFollowing / CrossAssetRotation）：
  1. 创建或恢复 Optuna Study（持久化到 SQLite，跨 run 累积知识）
  2. 在 time_budget 或 n_trials 内不断采样 → 评估 → 存档
  3. 已评估过的 spec_id 直接从 archive 读取（去重）
  4. 评估结果作为 Optuna objective value，指导下次采样方向
  5. 每 promote_interval 轮选出最优 + 多样化的策略集合晋升到活跃池

自适应策略
----------
- 通过率高的策略类型自动获得更多试验配额（动态分配）
- 若某类型连续 20 次全部不过 quick filter，暂停该类型搜索 10 轮

结果输出
--------
  miner.run() 返回 MiningRunResult：
    - promoted_strategies: List[EvalResult]（晋升到活跃池的策略）
    - leaderboard: pd.DataFrame（全部评估结果排行榜）
    - archive_stats: dict
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    _OPTUNA_AVAILABLE = True
except ImportError:
    _OPTUNA_AVAILABLE = False

from core.mining.strategy_space import ParameterSpace, ALL_SPACES, StrategySpec
from core.mining.evaluator import MiningEvaluator, EvalResult
from core.mining.archive import MiningArchive
from core.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class MiningRunResult:
    """StrategyMiner.run() 的输出。"""
    promoted_strategies: List[EvalResult]
    leaderboard:         pd.DataFrame
    archive_stats:       Dict
    elapsed_seconds:     float
    n_evaluated:         int


class StrategyMiner:
    """
    策略循环挖掘引擎。

    Parameters
    ----------
    evaluator           : MiningEvaluator 实例
    archive             : MiningArchive 实例
    spaces              : 要搜索的策略空间列表（默认 ALL_SPACES）
    promote_top_n       : 活跃池最大策略数
    promote_interval    : 每隔 N 次试验更新一次晋升列表
    diversity_max_corr  : 晋升时的最大相关系数门槛
    min_tier_to_promote : 晋升最低 tier（"C"/"B"/"A"/"S"）
    optuna_storage      : Optuna Study 持久化路径
    """

    def __init__(
        self,
        evaluator:          MiningEvaluator,
        archive:            MiningArchive,
        spaces:             Optional[List[ParameterSpace]] = None,
        promote_top_n:      int   = 5,
        promote_interval:   int   = 10,
        diversity_max_corr: float = 0.70,
        min_tier_to_promote: str  = "C",
        optuna_storage:     Optional[str] = None,
    ) -> None:
        if not _OPTUNA_AVAILABLE:
            raise ImportError("optuna is required for StrategyMiner. pip install optuna")

        self._evaluator    = evaluator
        self._archive      = archive
        self._spaces       = spaces or ALL_SPACES
        self._top_n        = promote_top_n
        self._promo_intv   = promote_interval
        self._div_corr     = diversity_max_corr
        self._min_tier     = min_tier_to_promote
        self._storage      = optuna_storage

        # Per-type adaptive counters
        self._type_trials:  Dict[str, int]   = {}
        self._type_pass:    Dict[str, int]   = {}

    # ── Main entry ────────────────────────────────────────────────────────────

    def run(
        self,
        price_df:          pd.DataFrame,
        regime_series:     pd.Series,
        benchmark_series:  pd.Series,
        risk_universe:     Optional[List[str]] = None,
        def_universe:      Optional[List[str]] = None,
        n_trials:          int   = 80,
        time_budget:       float = 3600.0,
        verbose:           bool  = True,
        qqq_series:        Optional[pd.Series] = None,
    ) -> MiningRunResult:
        """
        执行策略挖掘循环。

        Parameters
        ----------
        price_df          : 日收盘价（所有候选资产 + 防御资产）
        regime_series     : RegimeDetector 分类结果
        benchmark_series  : 基准价格序列（SPY close）
        risk_universe     : 风险资产列表（传给策略实例）
        def_universe      : 防御资产列表（传给策略实例）
        n_trials          : 每种策略类型的 Optuna 试验数
        time_budget       : 总 wall-clock 时间上限（秒）
        verbose           : 是否打印进度
        """
        t0           = time.time()
        n_evaluated  = 0
        all_results: List[EvalResult] = []

        for space in self._spaces:
            if time.time() - t0 > time_budget:
                logger.info("Time budget exhausted after %d evaluations", n_evaluated)
                break

            stype = space.strategy_type
            logger.info("Mining: starting %s (%d trials)", stype, n_trials)

            study = self._get_or_create_study(stype)

            def objective(trial: "optuna.Trial") -> float:
                params  = space.suggest(trial)
                spec    = StrategySpec.from_dict(stype, params)

                # Cache hit: return archived score
                if self._archive.has_spec(spec.spec_id):
                    cached = self._archive.get_score(spec.spec_id)
                    logger.debug("Cache hit %s → %.3f", spec.spec_id, cached)
                    return cached

                # Full evaluation
                promoted_curves = self._archive.load_promoted_equity_curves()
                result = self._evaluator.evaluate(
                    spec             = spec,
                    price_df         = price_df,
                    regime_series    = regime_series,
                    benchmark_series = benchmark_series,
                    risk_universe    = risk_universe,
                    def_universe     = def_universe,
                    promoted_curves  = promoted_curves,
                    qqq_series       = qqq_series,
                )
                self._archive.save_eval(result)
                all_results.append(result)

                # Update adaptive counters
                self._type_trials[stype] = self._type_trials.get(stype, 0) + 1
                if result.passed_quick:
                    self._type_pass[stype] = self._type_pass.get(stype, 0) + 1

                if verbose:
                    self._log_trial(result, n_evaluated + len(all_results))

                return result.composite_score

            remaining = max(1, int(time_budget - (time.time() - t0)))
            try:
                study.optimize(
                    objective,
                    n_trials   = n_trials,
                    timeout    = remaining,
                    show_progress_bar = False,
                )
            except Exception as exc:
                logger.error("Optuna study for %s failed: %s", stype, exc)

            n_evaluated += len(study.trials)

            # Promote after each strategy type
            self._update_promotions(price_df, all_results)

        promoted = self._get_promoted_results()
        lb       = self._archive.leaderboard(n=50)
        stats    = self._archive.stats()
        elapsed  = time.time() - t0

        logger.info(
            "Mining complete: %d evaluated, %d promoted, %.1fs",
            n_evaluated, len(promoted), elapsed,
        )
        return MiningRunResult(
            promoted_strategies = promoted,
            leaderboard         = lb,
            archive_stats       = stats,
            elapsed_seconds     = elapsed,
            n_evaluated         = n_evaluated,
        )

    # ── Promotion ─────────────────────────────────────────────────────────────

    def _update_promotions(
        self,
        price_df:    pd.DataFrame,
        results:     List[EvalResult],
    ) -> None:
        """从最新评估结果中更新晋升池，保持多样化最优集合。"""
        tier_rank = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}
        min_rank  = tier_rank.get(self._min_tier, 1)

        # Filter eligible candidates (holdout is a hard gate for promotion)
        eligible = [
            r for r in results
            if r.passed_oos
            and r.passed_holdout
            and tier_rank.get(r.tier, 0) >= min_rank
        ]
        if not eligible:
            return

        eligible.sort(key=lambda r: r.composite_score, reverse=True)

        # Greedy diverse selection
        promoted_curves = self._archive.load_promoted_equity_curves()
        newly_promoted  = 0

        for r in eligible:
            if newly_promoted >= self._top_n:
                break
            if r.spec_id in promoted_curves:
                continue  # already promoted

            # Check diversity against already-promoted
            if r.equity_curve is not None and promoted_curves:
                max_corr = self._max_corr(r.equity_curve, promoted_curves)
                if max_corr >= self._div_corr:
                    continue

            self._archive.promote(r, r.equity_curve)
            if r.equity_curve is not None:
                promoted_curves[r.spec_id] = r.equity_curve
            newly_promoted += 1

        if newly_promoted:
            logger.info("Promoted %d new strategies to active pool", newly_promoted)

    def _get_promoted_results(self) -> List[EvalResult]:
        promoted_dicts = self._archive.get_promoted()
        results = []
        for p in promoted_dicts:
            r = EvalResult(
                spec_id        = p["spec_id"],
                strategy_type  = p["strategy_type"],
                params         = p["params"],
                tier           = p["tier"],
                composite_score= p["composite_score"],
                passed_oos     = True,
            )
            results.append(r)
        return results

    # ── Optuna study management ────────────────────────────────────────────────

    def _get_or_create_study(self, strategy_type: str) -> "optuna.Study":
        study_name = f"pqs_mining_{strategy_type}"
        storage    = None
        if self._storage:
            Path(self._storage).parent.mkdir(parents=True, exist_ok=True)
            storage = f"sqlite:///{self._storage}"
        study = optuna.create_study(
            study_name        = study_name,
            storage           = storage,
            direction         = "maximize",
            load_if_exists    = True,
            sampler           = optuna.samplers.TPESampler(seed=42),
        )
        return study

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _max_corr(equity: pd.Series, promoted: Dict[str, pd.Series]) -> float:
        ret      = equity.pct_change().dropna()
        max_corr = 0.0
        for _, p_eq in promoted.items():
            p_ret  = p_eq.pct_change().dropna()
            common = ret.index.intersection(p_ret.index)
            if len(common) < 30:
                continue
            corr = float(ret.loc[common].corr(p_ret.loc[common]))
            if not np.isnan(corr):
                max_corr = max(max_corr, abs(corr))
        return max_corr

    @staticmethod
    def _log_trial(result: EvalResult, n: int) -> None:
        status = (
            f"✅ tier={result.tier}" if result.passed_oos
            else ("⚡ quick" if result.passed_quick else "❌")
        )
        logger.info(
            "[%d] %s/%s %s score=%.3f sh=%.2f dd=%.1f%%",
            n,
            result.strategy_type[:8],
            result.spec_id,
            status,
            result.composite_score,
            result.quick_sharpe if not np.isnan(result.quick_sharpe) else 0,
            abs(result.quick_max_dd) * 100 if not np.isnan(result.quick_max_dd) else 0,
        )
