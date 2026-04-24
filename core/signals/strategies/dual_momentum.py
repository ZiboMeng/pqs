"""
DualMomentumStrategy: Gary Antonacci 经典双重动量策略。

核心逻辑
--------
1. 绝对动量（Absolute Momentum / Time-series Momentum）
   - 对每个候选标的：若其 lookback_months 月收益率 > 无风险利率（近似为短债 ETF 或 0%）
     → 该标的"通过绝对动量测试"，否则用现金代替

2. 相对动量（Relative Momentum / Cross-sectional Momentum）
   - 在通过绝对动量测试的标的中，按 lookback_months 月收益率排名
   - 选取前 top_n 名作为投资标的

3. 最终信号
   - 被选中的标的：按 equal weight 或 momentum-weighted 分配权重
   - 未被选中的标的：权重为 0（持现金）
   - 若所有标的均未通过绝对动量测试 → 全部持现金

经典参数
--------
- lookback_months = 12（约 252 个交易日）
- top_n = 1（Antonacci 原版：只选 1 个最强动量）
- 但本系统默认 top_n = 3（分散风险），lookback_months = 12

适配 ETF 种子池
---------------
典型用法：
  universe = ["SPY", "QQQ", "GLD", "TLT", "IWM"]
  strategy = DualMomentumStrategy(universe=universe, top_n=3)
  signals  = strategy.generate(price_df)

防过拟合设计
-----------
- lookback_months 为唯一主参数（不要因子加权、不要多周期平均）
- 单一决策规则：排名 + 绝对动量过滤
- 信号每月重新平衡（每日产出，但实际换仓频率低）

参考文献
--------
Antonacci, G. (2012). Risk Premia Harvesting Through Dual Momentum.
Portfolio Management Consultants.
"""

from __future__ import annotations

from typing import List, Optional

import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)

# 交易日常数
_DAYS_PER_MONTH  = 21
_DAYS_PER_YEAR   = 252


class DualMomentumStrategy:
    """
    双重动量策略（绝对动量 + 相对动量）。

    Parameters
    ----------
    universe          : 候选标的列表（若为 None，使用 price_df 所有列）
    lookback_months   : 动量回看窗口（月数，默认 12）
    top_n             : 选取前 N 名（默认 3；设为 1 则复原 Antonacci 原版）
    abs_momentum_rate : 绝对动量比较基准（年化，默认 0.0）
                        设为 0 相当于"只要正收益就入选"
    rebalance_monthly : True → 每月第一个交易日才更新信号（其余日持仓不变）
                        False → 每日均重新计算（更快响应，但换手率高）
    momentum_weighted : True → 按动量大小加权；False → 等权
    """

    def __init__(
        self,
        universe:          Optional[List[str]] = None,
        lookback_months:   int   = 12,
        top_n:             int   = 3,
        abs_momentum_rate: float = 0.0,
        rebalance_monthly: bool  = True,
        momentum_weighted: bool  = False,
    ) -> None:
        self._universe         = universe
        self._lookback         = lookback_months * _DAYS_PER_MONTH
        self._top_n            = top_n
        self._abs_threshold    = (1 + abs_momentum_rate) ** (1 / 12) - 1  # 月化
        self._rebalance_monthly = rebalance_monthly
        self._momentum_weighted = momentum_weighted

    # ── 主接口 ────────────────────────────────────────────────────────────────

    def generate(
        self,
        price_df:      pd.DataFrame,
        regime_series: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """
        生成每日目标权重矩阵。

        Parameters
        ----------
        price_df       : 日收盘价，index=日期（DatetimeIndex），columns=symbol
        regime_series  : 可选，RegimeState 字符串序列；
                         在 CRISIS 时强制降低敞口（保护资本）

        Returns
        -------
        pd.DataFrame  index=日期，columns=symbol，值=目标权重 [0, 1]
        注意：末尾 lookback 根 bar 内 momentum 无效，权重全为 0。
        """
        syms   = self._universe or list(price_df.columns)
        prices = price_df[syms].copy()
        n      = len(prices)

        if n <= self._lookback:
            logger.warning(
                "DualMomentumStrategy: 数据长度 %d ≤ lookback %d，全部返回 0 权重",
                n, self._lookback,
            )
            return pd.DataFrame(0.0, index=prices.index, columns=syms)

        # 计算 lookback 期收益率（无 look-ahead：T 日用 T-lookback 到 T-1 的数据）
        momentum = prices.pct_change(self._lookback).shift(1)  # shift(1) 避免 T 日收盘 look-ahead

        # 按月份或每日决策
        if self._rebalance_monthly:
            signals = self._compute_monthly(momentum, syms)
        else:
            signals = self._compute_daily(momentum, syms)

        # Regime 缩放
        if regime_series is not None:
            scale = _regime_scale(regime_series, signals.index)
            signals = signals.multiply(scale, axis=0)

        return signals.clip(lower=0.0, upper=1.0).fillna(0.0)

    # ── 动量计算 ──────────────────────────────────────────────────────────────

    def _compute_daily(self, momentum: pd.DataFrame, syms: List[str]) -> pd.DataFrame:
        """每日重算：行情变化立即反映。"""
        rows = []
        for date, row in momentum.iterrows():
            rows.append(self._select_weights(row, syms))
        return pd.DataFrame(rows, index=momentum.index)

    def _compute_monthly(self, momentum: pd.DataFrame, syms: List[str]) -> pd.DataFrame:
        """每月第一个交易日更新，其余日沿用上次权重（降低换手率）。"""
        result = pd.DataFrame(0.0, index=momentum.index, columns=syms)
        current_weights: dict = {s: 0.0 for s in syms}
        last_month: Optional[int] = None

        for date, row in momentum.iterrows():
            month = date.month * 1000 + date.year  # 唯一月份 key
            if month != last_month:
                current_weights = self._select_weights(row, syms)
                last_month = month
            for s in syms:
                result.loc[date, s] = current_weights.get(s, 0.0)

        return result

    def _select_weights(
        self, momentum_row: pd.Series, syms: List[str]
    ) -> dict:
        """
        给定某一时点的 momentum 值，返回 {symbol: weight} 字典。

        步骤：
        1. 过滤 NaN
        2. 绝对动量过滤（> 阈值才保留）
        3. 相对排名取前 top_n
        4. 按 equal_weight 或 momentum_weight 分配
        """
        valid = momentum_row.dropna()
        if valid.empty:
            return {s: 0.0 for s in syms}

        # 绝对动量过滤
        passed_abs = valid[valid > self._abs_threshold]
        if passed_abs.empty:
            return {s: 0.0 for s in syms}  # 全持现金

        # 相对动量排名（降序），取前 top_n
        ranked = passed_abs.sort_values(ascending=False)
        selected = ranked.iloc[: self._top_n]

        if selected.empty:
            return {s: 0.0 for s in syms}

        # 权重分配
        if self._momentum_weighted:
            # 按动量值正比分配（全为正，已经通过绝对动量过滤）
            pos_vals = selected.clip(lower=1e-10)
            total    = pos_vals.sum()
            weights  = (pos_vals / total).to_dict()
        else:
            # 等权
            w = 1.0 / len(selected)
            weights = {s: w for s in selected.index}

        return {s: weights.get(s, 0.0) for s in syms}


# ── 辅助 ──────────────────────────────────────────────────────────────────────

def _regime_scale(regime_series: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    """
    Regime → 权重缩放系数。

    CRISIS 时全部现金；RISK_OFF 时保留 25%；其他维持。
    """
    _map = {
        "BULL":     1.00,
        "RISK_ON":  1.00,
        "NEUTRAL":  1.00,
        "CAUTIOUS": 0.75,
        "RISK_OFF": 0.25,
        "CRISIS":   0.00,
    }
    aligned = regime_series.reindex(idx, method="ffill").fillna("NEUTRAL")
    return aligned.map(lambda r: _map.get(r, 1.0))
