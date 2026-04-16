"""
TrendFollowingStrategy: SPY EMA 趋势跟踪策略（参考基线）。

逻辑
----
对组合中的每个标的：
  - 若标的价格 > 其 slow_ema（默认 200-EMA）→ 目标权重 = 平等分配（或自定义权重）
  - 若标的价格 ≤ slow_ema → 目标权重 = 0（持现金）

同时提供多重过滤器（均可从配置关闭）：
  1. 快速 EMA 确认（price > fast_ema，默认 50-EMA）
  2. 全局 regime 过滤（若当前 regime ≤ RISK_OFF，降低敞口）
  3. 趋势动量确认（slow_ema 本身是否上升）

设计目的
--------
- 作为最简单可运行的 baseline 策略
- 验证端到端回测管线正确性
- 不以超越 SPY 为目标；只要行为可预期、逻辑清晰即可

用法
----
    strategy = TrendFollowingStrategy(fast_ema=50, slow_ema=200)
    signals_df = strategy.generate(price_df)
    # signals_df: index=日期, columns=symbol, value=目标权重 [0,1]
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)


class TrendFollowingStrategy:
    """
    基于 EMA 趋势跟踪的日线信号策略。

    Parameters
    ----------
    symbols       : 参与交易的 symbol 列表（若为 None，使用 price_df 的所有列）
    fast_ema      : 快速 EMA 窗口（默认 50），用于趋势确认过滤
    slow_ema      : 慢速 EMA 窗口（默认 200），用于趋势主判断
    use_fast_confirm : 是否要求价格同时高于 fast_ema 才给信号（默认 True）
    use_trend_direction : 是否要求 slow_ema 本身斜率为正（防止 EMA 下降时仍持仓）
    equal_weight  : 所有在趋势上方的标的是否等权分配（默认 True）
    """

    def __init__(
        self,
        symbols:              Optional[List[str]] = None,
        fast_ema:             int  = 50,
        slow_ema:             int  = 200,
        use_fast_confirm:     bool = True,
        use_trend_direction:  bool = False,
        equal_weight:         bool = True,
    ) -> None:
        self._symbols             = symbols
        self._fast_w              = fast_ema
        self._slow_w              = slow_ema
        self._use_fast            = use_fast_confirm
        self._use_trend_dir       = use_trend_direction
        self._equal_weight        = equal_weight

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
        price_df       : 日收盘价 DataFrame，index=日期，columns=symbol
        regime_series  : 可选，RegimeState 字符串序列（如 "BULL"/"CRISIS"）；
                         若提供，在 CRISIS / RISK_OFF 环境下自动降低敞口

        Returns
        -------
        pd.DataFrame  index=日期，columns=symbol，值=目标权重 [0, 1]
        """
        syms   = self._symbols or list(price_df.columns)
        prices = price_df[syms].copy()

        # 计算 EMA
        fast_ema = prices.ewm(span=self._fast_w, adjust=False).mean()
        slow_ema = prices.ewm(span=self._slow_w, adjust=False).mean()

        # 主趋势信号：price > slow_ema
        above_slow = prices > slow_ema

        # 可选过滤 1：price > fast_ema
        if self._use_fast:
            above_slow = above_slow & (prices > fast_ema)

        # 可选过滤 2：slow_ema 斜率为正（用 diff 近似）
        if self._use_trend_dir:
            slow_rising = slow_ema.diff() > 0
            above_slow  = above_slow & slow_rising

        # 计算原始权重（在趋势上方的标的等权）
        if self._equal_weight:
            # 每行：等权分配给满足条件的 symbol
            n_active   = above_slow.sum(axis=1).replace(0, np.nan)
            raw_weights = above_slow.divide(n_active, axis=0).fillna(0.0)
        else:
            # 不做等权：直接返回 0/1 mask（调用方按需缩放）
            raw_weights = above_slow.astype(float)

        # 可选：regime 缩放
        if regime_series is not None:
            scale = self._regime_scale(regime_series, raw_weights.index)
            raw_weights = raw_weights.multiply(scale, axis=0)

        return raw_weights.clip(lower=0.0, upper=1.0)

    # ── 内部 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _regime_scale(regime_series: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
        """
        根据 regime 返回权重缩放系数（0 ~ 1）：
          BULL / RISK_ON  → 1.0（全敞口）
          NEUTRAL         → 0.75
          CAUTIOUS        → 0.50
          RISK_OFF        → 0.25
          CRISIS          → 0.0（全现金）
        """
        _map = {
            "BULL":     1.00,
            "RISK_ON":  1.00,
            "NEUTRAL":  0.75,
            "CAUTIOUS": 0.50,
            "RISK_OFF": 0.25,
            "CRISIS":   0.00,
        }
        aligned = regime_series.reindex(idx, method="ffill").fillna("NEUTRAL")
        return aligned.map(lambda r: _map.get(r, 0.75))
