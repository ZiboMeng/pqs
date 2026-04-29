"""
FactorEvaluator: 多维度因子评估，产出结构化报告。

功能
----
  layered_backtest    — 按因子分位数分层，计算各层累积收益（Quintile Backtest）
  sub_period_stability — 将样本分 N 段，每段独立计算 IC 统计，检验跨期稳定性
  evaluate            — 综合以上两项，返回 FactorReport dataclass

FactorReport 字段
-----------------
  stats       : Dict[horizon → FactorStats]   各预测期汇总统计
  decay       : pd.DataFrame                  IC 衰减曲线
  quantile_ret: pd.DataFrame                  各分位数累计收益
  sub_periods : pd.DataFrame                  子区间 IC 统计
  tier        : str                           自动评级 S/A/B/C/D

评级标准（Tier）
---------------
  S : IR > s_min_ir 且显著（默认 0.80）
  A : IR > a_min_ir 且显著（默认 0.50）
  B : IR > b_min_ir 且显著（默认 0.30）
  C : IR > c_min_ir          （默认 0.10）
  D : 其余

实际 IR cuts 来源：``AcceptanceThresholds.factor_tiers``
（``config/acceptance.yaml::factor_tiers``）。修改 yaml 后调用方需通过
``FactorEvaluator(thresholds=cfg.acceptance)`` 注入；不注入则使用 schema
默认。直接构造 ``FactorReport(...)`` 会调用 ``__post_init__`` 用默认 cuts —
若需 yaml 驱动 tiering，请走 ``FactorEvaluator.evaluate()`` 或显式调用
``_auto_tier(stats, thresholds=cfg.acceptance)``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.config.schemas import AcceptanceThresholds
from core.factors.factor_engine import FactorEngine, FactorStats
from core.logging_setup import get_logger

logger = get_logger(__name__)


# ── 报告数据类 ────────────────────────────────────────────────────────────────

@dataclass
class FactorReport:
    """因子评估完整报告。"""
    factor_name:  str
    horizons:     List[int]
    stats:        Dict[int, FactorStats]        # horizon → FactorStats
    decay:        pd.DataFrame                   # lag → mean_ic/ir/n
    quantile_ret: pd.DataFrame                   # date → q1..qN cumret
    sub_periods:  pd.DataFrame                   # period_id → mean_ic/ir/n
    tier:         str = "D"

    def __post_init__(self):
        self.tier = _auto_tier(self.stats)

    def summary(self) -> str:
        lines = [
            f"FactorReport: {self.factor_name}  [Tier {self.tier}]",
            "=" * 60,
        ]
        for h, s in sorted(self.stats.items()):
            lines.append(f"  H{h:3d}: {s}")
        if not self.sub_periods.empty and "ir" in self.sub_periods.columns:
            ir_vals = self.sub_periods["ir"].dropna()
            lines.append(
                f"\n  Sub-period IR: min={ir_vals.min():.3f}  "
                f"max={ir_vals.max():.3f}  std={ir_vals.std():.3f}"
            )
        return "\n".join(lines)


# ── FactorEvaluator ───────────────────────────────────────────────────────────

class FactorEvaluator:
    """
    综合评估单因子的预测能力和稳定性。

    Parameters
    ----------
    horizons    : 评估的预测期列表（天数），如 [1, 5, 10, 20]
    n_quantiles : 分层回测的分组数（通常 5 = quintile）
    n_sub_periods : 子区间数量（检验跨期稳定性）
    decay_max_lag : IC 衰减最大 lag
    ic_method   : 'spearman'（默认）或 'pearson'
    thresholds  : AcceptanceThresholds (可选)；factor_tiers IR cuts 来源。
                  若为 None，``evaluate()`` 仍使用 ``AcceptanceThresholds()``
                  schema 默认；调用方传 ``cfg.acceptance`` 即可让
                  ``config/acceptance.yaml`` 生效（codex round-16 follow-up）。
    """

    def __init__(
        self,
        horizons:      List[int] = (1, 5, 10, 20),
        n_quantiles:   int = 5,
        n_sub_periods: int = 4,
        decay_max_lag: int = 20,
        ic_method:     str = "spearman",
        thresholds:    Optional[AcceptanceThresholds] = None,
    ):
        self.horizons      = list(horizons)
        self.n_quantiles   = n_quantiles
        self.n_sub_periods = n_sub_periods
        self.decay_max_lag = decay_max_lag
        self.ic_method     = ic_method
        self._thresholds   = thresholds
        self._engine       = FactorEngine()

    # ── 主入口 ────────────────────────────────────────────────────────────────

    def evaluate(
        self,
        factor_df:   pd.DataFrame,
        price_df:    pd.DataFrame,
        factor_name: str = "factor",
    ) -> FactorReport:
        """
        综合评估因子。

        Parameters
        ----------
        factor_df  : 因子暴露矩阵，index=日期，columns=symbol
        price_df   : close 价格矩阵，index=日期，columns=symbol
        factor_name: 因子标识

        Returns
        -------
        FactorReport
        """
        logger.info("Evaluating factor '%s' on %d dates × %d symbols",
                    factor_name, len(factor_df), factor_df.shape[1])

        # 1. 各预测期 IC 统计
        stats: Dict[int, FactorStats] = {}
        for h in self.horizons:
            fwd  = self._engine.make_forward_returns(price_df, horizon=h)
            ic   = self._engine.compute_rank_ic(factor_df, fwd) \
                   if self.ic_method == "spearman" \
                   else self._engine.compute_ic(factor_df, fwd)
            stats[h] = self._engine.compute_factor_stats(ic, factor_name=factor_name, horizon=h)

        # 2. IC 衰减（以 price_df 直接计算）
        try:
            decay = self._engine.compute_ic_decay(
                factor_df, price_df,
                max_lag=self.decay_max_lag,
                method=self.ic_method,
            )
        except Exception as exc:
            logger.warning("IC decay computation failed: %s", exc)
            decay = pd.DataFrame()

        # 3. 分位数分层回测（使用最短预测期）
        primary_h = min(self.horizons)
        fwd_primary = self._engine.make_forward_returns(price_df, horizon=primary_h)
        quantile_ret = self.layered_backtest(factor_df, fwd_primary)

        # 4. 子区间稳定性
        fwd_5 = self._engine.make_forward_returns(price_df, horizon=5)
        sub_periods = self.sub_period_stability(factor_df, fwd_5)

        report = FactorReport(
            factor_name  = factor_name,
            horizons     = self.horizons,
            stats        = stats,
            decay        = decay,
            quantile_ret = quantile_ret,
            sub_periods  = sub_periods,
        )
        # codex round-16 follow-up: when caller injected thresholds, override
        # the default-tiering result computed by FactorReport.__post_init__
        # with the yaml-driven cuts from cfg.acceptance.factor_tiers.
        if self._thresholds is not None:
            report.tier = _auto_tier(stats, thresholds=self._thresholds)
        return report

    # ── 分层回测 ──────────────────────────────────────────────────────────────

    def layered_backtest(
        self,
        factor_df:   pd.DataFrame,
        returns_df:  pd.DataFrame,
    ) -> pd.DataFrame:
        """
        按因子分位数分层，计算各层平均收益时序，并转为累积收益。

        Returns
        -------
        pd.DataFrame  index=日期，columns=['Q1','Q2',...,'QN','spread']
            spread = Q_top − Q_bottom（因子最高分位 vs 最低分位的多空收益差）
        """
        f, r = factor_df.align(returns_df, join="inner")
        results: Dict[str, pd.Series] = {f"Q{i+1}": [] for i in range(self.n_quantiles)}

        dates_with_data: list = []
        q_labels = [f"Q{i+1}" for i in range(self.n_quantiles)]

        for date in f.index:
            f_row = f.loc[date].dropna()
            r_row = r.loc[date].dropna() if date in r.index else pd.Series(dtype=float)
            common = f_row.index.intersection(r_row.index)

            if len(common) < self.n_quantiles * 2:
                continue

            f_vals = f_row[common]
            r_vals = r_row[common]

            try:
                quantiles = pd.qcut(f_vals, q=self.n_quantiles, labels=q_labels, duplicates="drop")
            except ValueError:
                continue

            dates_with_data.append(date)
            for q in q_labels:
                mask  = quantiles == q
                avg_r = r_vals[mask].mean() if mask.sum() > 0 else np.nan
                results[q].append(avg_r)

        if not dates_with_data:
            return pd.DataFrame()

        df = pd.DataFrame(results, index=dates_with_data)
        df.index = pd.DatetimeIndex(df.index)

        # 多空价差：最高分位 − 最低分位
        df["spread"] = df[q_labels[-1]] - df[q_labels[0]]

        # 转为累积收益（从 0 起算，复利）
        cum = (1 + df.fillna(0)).cumprod() - 1
        return cum

    # ── 子区间稳定性 ──────────────────────────────────────────────────────────

    def sub_period_stability(
        self,
        factor_df:   pd.DataFrame,
        returns_df:  pd.DataFrame,
    ) -> pd.DataFrame:
        """
        将时间轴均分为 n_sub_periods 段，每段独立计算 IC 汇总统计。

        Returns
        -------
        pd.DataFrame  index=0..n-1，columns=['start','end','mean_ic','ic_std','ir','n']
        """
        f, r = factor_df.align(returns_df, join="inner")
        dates = f.index
        n     = len(dates)

        if n < self.n_sub_periods * 5:
            logger.warning(
                "sub_period_stability: only %d dates, too few for %d sub-periods",
                n, self.n_sub_periods,
            )
            return pd.DataFrame()

        chunk = n // self.n_sub_periods
        rows  = []

        for i in range(self.n_sub_periods):
            sl_start = i * chunk
            sl_end   = (i + 1) * chunk if i < self.n_sub_periods - 1 else n
            sub_dates = dates[sl_start:sl_end]

            f_sub = f.loc[sub_dates]
            r_sub = r.loc[sub_dates]

            ic = _rolling_crosssection_corr_sub(f_sub, r_sub)
            valid = ic.dropna()

            if len(valid) < 2:
                rows.append({
                    "period": i + 1,
                    "start": sub_dates[0],
                    "end":   sub_dates[-1],
                    "mean_ic": np.nan, "ic_std": np.nan, "ir": np.nan, "n": len(valid),
                })
                continue

            mean_ic = float(valid.mean())
            ic_std  = float(valid.std(ddof=1))
            ir      = mean_ic / ic_std if ic_std > 0 else np.nan

            rows.append({
                "period":  i + 1,
                "start":   sub_dates[0],
                "end":     sub_dates[-1],
                "mean_ic": mean_ic,
                "ic_std":  ic_std,
                "ir":      float(ir) if not np.isnan(ir) else np.nan,
                "n":       len(valid),
            })

        return pd.DataFrame(rows).set_index("period")


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _rolling_crosssection_corr_sub(
    factor_df:  pd.DataFrame,
    returns_df: pd.DataFrame,
    min_symbols: int = 3,
) -> pd.Series:
    """子区间内的逐日截面 Spearman IC（复用 engine 内部实现）。"""
    from core.factors.factor_engine import _rolling_crosssection_corr
    return _rolling_crosssection_corr(factor_df, returns_df, method="spearman",
                                      min_symbols=min_symbols)


def _auto_tier(
    stats: Dict[int, "FactorStats"],
    thresholds: Optional[AcceptanceThresholds] = None,
) -> str:
    """
    根据最短预测期的 IR 和显著性自动评级。

    评级标准来源：``AcceptanceThresholds.factor_tiers``（默认值 0.8/0.5/0.3/0.1
    与历史 ``ValidationConfig`` 对齐；通过 ``config/acceptance.yaml`` 调整）。
    Codex round-13 §"Decision 2": factor_tiers 是独立 submodel，与 Tier D 的
    S/A/B/C/D 字母重合是巧合。

      S : IR ≥ ``thresholds.factor_tiers.s_min_ir`` 且显著
      A : IR ≥ ``thresholds.factor_tiers.a_min_ir`` 且显著
      B : IR ≥ ``thresholds.factor_tiers.b_min_ir`` 且显著
      C : IR ≥ ``thresholds.factor_tiers.c_min_ir``
      D : 其余
    """
    if not stats:
        return "D"

    cuts = (thresholds or AcceptanceThresholds()).factor_tiers

    # 取最短预测期的统计
    primary = stats[min(stats.keys())]
    ir = primary.ir

    if np.isnan(ir):
        return "D"
    if abs(ir) >= cuts.s_min_ir and primary.is_significant:
        return "S"
    if abs(ir) >= cuts.a_min_ir and primary.is_significant:
        return "A"
    if abs(ir) >= cuts.b_min_ir and primary.is_significant:
        return "B"
    if abs(ir) >= cuts.c_min_ir:
        return "C"
    return "D"
