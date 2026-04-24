"""
CrossAssetRotation: 跨资产绝对+相对动量轮动策略。

核心逻辑
--------
基于 Gary Antonacci Global Equity Momentum (GEM) 框架，扩展到多资产类别：
1. 将候选资产分为"风险资产"和"防御资产"两组
2. 计算 lookback 期绝对动量（可跳过最近 skip_months 月，规避短期反转）
3. 风险资产中绝对动量为正的按相对排名取前 top_n
4. 若无风险资产通过绝对动量测试，转向最强防御资产
5. 支持 Regime 约束（CRISIS 时强制转入防御或现金）

参数搜索空间（供 StrategyMiner 使用）
-------------------------------------
  lookback_months   : 3–12
  skip_months       : 0–2   (跳过最近 N 月，0 = 不跳)
  top_n             : 1–4   (选前 N 个风险资产)
  defensive_top_n   : 1–2   (防御资产选 N 个)
  rebalance_monthly : True/False
  momentum_weighted : True/False

Universe 分组
-------------
  risk_assets      : 股票/科技/行业 ETF（SPY, QQQ, XLK, XLF, ...）
  defensive_assets : 债券+黄金（TLT, IEF, GLD）
  cash_proxy       : SHY 或不持仓（权重=0）
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)

_DAYS_PER_MONTH = 21
_DAYS_PER_YEAR  = 252

# Regime 缩放表（可通过子类覆盖）
_REGIME_SCALE = {
    "BULL":     1.00,
    "RISK_ON":  1.00,
    "NEUTRAL":  0.80,
    "CAUTIOUS": 0.50,
    "RISK_OFF": 0.20,
    "CRISIS":   0.00,   # 完全退出风险资产，全部转入防御/现金
}

# CRISIS 时防御资产比例（overrides regime scaling for defensive)
_CRISIS_DEFENSIVE_WEIGHT = 0.80


class CrossAssetRotationStrategy:
    """
    跨资产轮动策略。

    Parameters
    ----------
    risk_assets       : 风险资产列表（若 None，使用 price_df 所有列）
    defensive_assets  : 防御资产列表（TLT, IEF, GLD 等）
    lookback_months   : 动量回看窗口（月，默认 12）
    skip_months       : 跳过最近 N 个月（规避短期反转，默认 1）
    top_n             : 选取的风险资产数量（默认 2）
    defensive_top_n   : 防御资产分配数量（默认 1）
    rebalance_monthly : 是否月度再平衡（默认 True）
    momentum_weighted : 按动量大小加权（默认 False = 等权）
    """

    def __init__(
        self,
        risk_assets:        Optional[List[str]] = None,
        defensive_assets:   Optional[List[str]] = None,
        lookback_months:    int   = 12,
        skip_months:        int   = 1,
        top_n:              int   = 2,
        defensive_top_n:    int   = 1,
        rebalance_monthly:  bool  = True,
        momentum_weighted:  bool  = False,
    ) -> None:
        self._risk      = risk_assets or []
        self._defensive = defensive_assets or ["TLT", "GLD"]
        self._lookback  = lookback_months * _DAYS_PER_MONTH
        self._skip      = skip_months * _DAYS_PER_MONTH
        self._top_n     = top_n
        self._def_top_n = defensive_top_n
        self._monthly   = rebalance_monthly
        self._mw        = momentum_weighted

    def generate(
        self,
        price_df:      pd.DataFrame,
        regime_series: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """
        生成每日目标权重矩阵。

        Parameters
        ----------
        price_df      : 日收盘价，包含所有候选资产（含防御资产）
        regime_series : RegimeState 序列（可选）

        Returns
        -------
        pd.DataFrame  index=日期，columns=symbol，值=目标权重 [0,1]
        """
        all_syms = list(price_df.columns)
        risk_syms = [s for s in (self._risk or all_syms) if s in all_syms]
        def_syms  = [s for s in self._defensive if s in all_syms]

        if not risk_syms:
            logger.warning("CrossAssetRotation: no risk assets available")
            return pd.DataFrame(0.0, index=price_df.index, columns=all_syms)

        # 计算动量（跳过最近 skip 根 bar，再回看 lookback 根）
        # momentum_t = price[t-skip] / price[t-skip-lookback] - 1
        # 用 shift 实现：pct_change(lookback).shift(skip+1) 保证 T 日无 look-ahead
        momentum = price_df.pct_change(self._lookback).shift(self._skip + 1)

        if self._monthly:
            signals = self._compute_monthly(momentum, risk_syms, def_syms, all_syms, regime_series)
        else:
            signals = self._compute_daily(momentum, risk_syms, def_syms, all_syms, regime_series)

        return signals.clip(0.0, 1.0).fillna(0.0)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compute_daily(
        self,
        momentum:      pd.DataFrame,
        risk_syms:     List[str],
        def_syms:      List[str],
        all_syms:      List[str],
        regime_series: Optional[pd.Series],
    ) -> pd.DataFrame:
        rows = []
        regime_aligned = (
            regime_series.reindex(momentum.index, method="ffill").fillna("NEUTRAL")
            if regime_series is not None else None
        )
        for date, mom_row in momentum.iterrows():
            regime = str(regime_aligned.loc[date]) if regime_aligned is not None else "NEUTRAL"
            rows.append(self._select_weights(mom_row, risk_syms, def_syms, all_syms, regime))
        return pd.DataFrame(rows, index=momentum.index)

    def _compute_monthly(
        self,
        momentum:      pd.DataFrame,
        risk_syms:     List[str],
        def_syms:      List[str],
        all_syms:      List[str],
        regime_series: Optional[pd.Series],
    ) -> pd.DataFrame:
        result = pd.DataFrame(0.0, index=momentum.index, columns=all_syms)
        current: dict = {s: 0.0 for s in all_syms}
        last_month: Optional[int] = None
        regime_aligned = (
            regime_series.reindex(momentum.index, method="ffill").fillna("NEUTRAL")
            if regime_series is not None else None
        )
        for date, mom_row in momentum.iterrows():
            month = date.month * 1000 + date.year
            regime = str(regime_aligned.loc[date]) if regime_aligned is not None else "NEUTRAL"
            if month != last_month:
                current = self._select_weights(mom_row, risk_syms, def_syms, all_syms, regime)
                last_month = month
            for s in all_syms:
                result.loc[date, s] = current.get(s, 0.0)
        return result

    def _select_weights(
        self,
        mom_row:   pd.Series,
        risk_syms: List[str],
        def_syms:  List[str],
        all_syms:  List[str],
        regime:    str,
    ) -> dict:
        w = {s: 0.0 for s in all_syms}

        # CRISIS: 全部转入防御资产（不持风险资产）
        if regime == "CRISIS":
            if def_syms:
                def_mom = mom_row.reindex(def_syms).dropna()
                if not def_mom.empty:
                    best_def = def_mom.sort_values(ascending=False).index[:self._def_top_n]
                    target = _CRISIS_DEFENSIVE_WEIGHT / len(best_def)
                    for s in best_def:
                        w[s] = target
            return w

        # Regime scale for risk assets
        risk_scale = _REGIME_SCALE.get(regime, 0.80)

        # ── Risk asset selection ──────────────────────────────────────────────
        risk_mom = mom_row.reindex(risk_syms).dropna()

        # Absolute momentum filter (positive return over lookback)
        passed = risk_mom[risk_mom > 0]
        if not passed.empty:
            ranked   = passed.sort_values(ascending=False)
            selected = ranked.index[: self._top_n].tolist()
            n_sel    = len(selected)
            if self._mw:
                pos = ranked.loc[selected].clip(lower=1e-10)
                total = pos.sum()
                for s in selected:
                    w[s] = (pos[s] / total) * risk_scale
            else:
                eq = (1.0 / n_sel) * risk_scale
                for s in selected:
                    w[s] = eq

        # ── Defensive allocation for remaining budget ─────────────────────────
        risk_allocated = sum(w.values())
        defensive_budget = max(0.0, 1.0 - risk_allocated)
        if defensive_budget > 0.05 and def_syms:
            def_mom = mom_row.reindex(def_syms).dropna()
            if not def_mom.empty:
                # Always allocate to defensive when risk budget unused
                best_def = def_mom.sort_values(ascending=False).index[: self._def_top_n]
                per_def  = defensive_budget / len(best_def)
                for s in best_def:
                    w[s] = per_def

        return w
