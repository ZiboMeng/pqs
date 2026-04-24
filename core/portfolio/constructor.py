"""
PortfolioConstructor: 仓位构建器（风险平价 + Regime 感知）。

设计目标
--------
Q3-C：风险平价（Volatility Targeting）— 动态调整权重，避免上涨期错过收益、
      下跌期暴露风险。比固定等权更灵活，回撤控制更好。
Q5-B：Regime 感知 — 消费 RegimeDetector 输出，按当前市场环境约束最大敞口。

核心流程
--------
  raw_weights（来自信号策略）
      ↓
  vol_scaling（波动率平价：各标的按历史 vol 倒数加权）
      ↓
  regime_cap（按 regime 约束最大单标的权重和总敞口）
      ↓
  hard_cap（max_single_position 绝对上限）
      ↓
  归一化（权重之和 ≤ 1，允许持现金）
      ↓
  final_weights

风险平价逻辑
-----------
  vol_i = rolling std(returns_i, vol_window)  ×  sqrt(252)   # 年化波动率
  raw_vol_weight_i = 1 / vol_i
  normalized = raw_vol_weight_i / sum(raw_vol_weight_i)       # 使权重和=1

然后与信号权重（原始选股方向）结合：
  combined_i = signal_i × vol_weight_i   # 仅对被选中的标的做 vol 平价

这样：
  - 信号选哪些标的：由策略决定
  - 选中的标的各自分多少：由波动率平价决定
  - 总敞口上限：由 regime 决定

使用示例
--------
    constructor = PortfolioConstructor(vol_window=60, target_vol=0.15)
    weights     = constructor.build(
        raw_signals  = strategy.generate(price_df),
        price_df     = price_df,
        regime_series = detector.classify_series(spy, vix),
        regime_config = cfg.regime,
    )
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)

# 波动率兜底（防止 0 除法）
_MIN_VOL = 1e-6
# 默认最大单标的权重（若无 regime 配置时使用）
_DEFAULT_MAX_SINGLE = 0.35
# 默认目标年化波动率
_DEFAULT_TARGET_VOL = 0.25


class PortfolioConstructor:
    """
    风险平价 + Regime 感知的仓位构建器。

    Parameters
    ----------
    vol_window      : 计算历史波动率的滚动窗口（交易日，默认 60）
    target_vol      : 目标年化波动率（默认 0.15 = 15%）；用于整体敞口缩放
    use_vol_parity  : True（默认）→ 对选中标的做波动率平价；
                      False → 维持原始信号权重比例（等权或策略给的权重）
    max_single_pos  : 单标的权重硬上限（由 regime 约束进一步收紧）
    min_history     : 计算 vol 需要的最小历史 bar 数；不足时退回等权
    """

    def __init__(
        self,
        vol_window:     int   = 60,
        target_vol:     float = _DEFAULT_TARGET_VOL,
        use_vol_parity: bool  = True,
        max_single_pos: float = _DEFAULT_MAX_SINGLE,
        min_history:    int   = 30,
    ) -> None:
        self._vol_window    = vol_window
        self._target_vol    = target_vol
        self._use_vol_parity = use_vol_parity
        self._max_single    = max_single_pos
        self._min_history   = min_history

    # ── 主接口 ────────────────────────────────────────────────────────────────

    def build(
        self,
        raw_signals:    pd.DataFrame,
        price_df:       pd.DataFrame,
        regime_series:  Optional[pd.Series] = None,
        regime_config=  None,     # RegimeConfig（可选，用于读取 position_constraints）
    ) -> pd.DataFrame:
        """
        从原始信号权重构建最终目标权重矩阵。

        Parameters
        ----------
        raw_signals    : 策略输出的目标权重，index=日期，columns=symbol，值∈[0,1]
        price_df       : 日收盘价（用于计算历史 vol）
        regime_series  : RegimeState 字符串序列（可选）；用于动态调整总敞口上限
        regime_config  : RegimeConfig 对象（可选）；用于读取每个 regime 的持仓约束

        Returns
        -------
        pd.DataFrame  index=日期，columns=symbol，值=最终目标权重 [0, 1]
        """
        common = raw_signals.index.intersection(price_df.index)
        if common.empty:
            logger.warning("PortfolioConstructor.build: signals 与 price_df 无共同日期")
            return raw_signals.copy()

        signals = raw_signals.loc[common]
        prices  = price_df.reindex(columns=signals.columns).loc[common]
        returns = prices.pct_change()

        # Step 1: 波动率平价（对被信号选中的标的）
        if self._use_vol_parity:
            weights = self._vol_parity_weights(signals, returns)
        else:
            # 直接归一化原始权重
            row_sum = signals.sum(axis=1).replace(0, np.nan)
            weights = signals.divide(row_sum, axis=0).fillna(0.0)

        # Step 2: 波动率目标缩放（控制总组合风险敞口）
        weights = self._apply_vol_target(weights, returns)

        # Step 3: Regime 约束
        if regime_series is not None:
            weights = self._apply_regime_caps(weights, regime_series, regime_config)

        # Step 4: 单标的硬上限
        weights = weights.clip(upper=self._effective_max_single(regime_series, regime_config))

        # Step 5: 最终归一化（权重和 ≤ 1，超出则按比例缩放）
        weights = self._normalize(weights)

        return weights.fillna(0.0)

    # ── Step 1: 波动率平价 ────────────────────────────────────────────────────

    def _vol_parity_weights(
        self, signals: pd.DataFrame, returns: pd.DataFrame
    ) -> pd.DataFrame:
        """
        对信号选中的标的，按历史 vol 倒数分配权重。

        未被信号选中的标的（signal=0）权重保持为 0。
        """
        # 滚动年化波动率
        rolling_vol = (
            returns.rolling(self._vol_window, min_periods=self._min_history)
            .std()
            .multiply(np.sqrt(252))
            .shift(1)  # 使用 T-1 的 vol，避免当日 look-ahead
        )

        result = pd.DataFrame(0.0, index=signals.index, columns=signals.columns)

        for date in signals.index:
            sig_row  = signals.loc[date]
            vol_row  = rolling_vol.loc[date] if date in rolling_vol.index else pd.Series(dtype=float)

            selected = sig_row[sig_row > 0].index.tolist()
            if not selected:
                continue

            vols = vol_row.reindex(selected)
            # 如果任何 vol 为 NaN 或 0（历史不足），退回等权
            if vols.isna().any() or (vols < _MIN_VOL).any():
                w = 1.0 / len(selected)
                for s in selected:
                    result.loc[date, s] = w
            else:
                inv_vol = 1.0 / vols.clip(lower=_MIN_VOL)
                total   = inv_vol.sum()
                for s in selected:
                    result.loc[date, s] = inv_vol[s] / total

        return result

    # ── Step 2: 波动率目标缩放 ────────────────────────────────────────────────

    def _apply_vol_target(
        self, weights: pd.DataFrame, returns: pd.DataFrame
    ) -> pd.DataFrame:
        """
        按 target_vol 对整体权重缩放：

        portfolio_vol = sqrt(weights @ cov_matrix @ weights.T)
        scale = target_vol / portfolio_vol  （上限为 1，不做杠杆）

        简化版本（忽略相关性）：
          portfolio_vol_approx = sqrt(sum((w_i × vol_i)^2))
        这是对角协方差矩阵近似，适合 ETF 组合（相关性较强但简化误差可接受）。
        """
        rolling_vol = (
            returns.rolling(self._vol_window, min_periods=self._min_history)
            .std()
            .multiply(np.sqrt(252))
            .shift(1)
        )

        result = weights.copy()

        for date in weights.index:
            w    = weights.loc[date]
            vols = rolling_vol.loc[date] if date in rolling_vol.index else pd.Series(dtype=float)

            active = w[w > 0]
            if active.empty:
                continue

            active_vols = vols.reindex(active.index).fillna(0.20)  # 无数据时假设 20% vol
            port_vol    = float(np.sqrt(((active * active_vols) ** 2).sum()))

            if port_vol < _MIN_VOL:
                continue

            scale = min(1.0, self._target_vol / port_vol)
            result.loc[date] = w * scale

        return result

    # ── Step 3: Regime 约束 ──────────────────────────────────────────────────

    def _apply_regime_caps(
        self,
        weights:       pd.DataFrame,
        regime_series: pd.Series,
        regime_config  = None,
    ) -> pd.DataFrame:
        """
        按当前 regime 约束最大总敞口：

        从 RegimeConfig.position_constraints[regime].target_cash_pct_min 计算
        允许的最大投资敞口 = 1 - target_cash_pct_min。

        若无 regime_config，使用默认映射。
        """
        _default_max_exposure = {
            "BULL":     1.00,
            "RISK_ON":  0.95,
            "NEUTRAL":  0.85,
            "CAUTIOUS": 0.70,
            "RISK_OFF": 0.50,
            "CRISIS":   0.20,
        }

        aligned = regime_series.reindex(weights.index, method="ffill").fillna("NEUTRAL")
        result  = weights.copy()

        for date in weights.index:
            regime = str(aligned.loc[date])

            # 读取最大敞口
            if regime_config is not None:
                try:
                    constr       = regime_config.position_constraints[regime]
                    max_exposure = 1.0 - constr.target_cash_pct_min
                except (KeyError, AttributeError):
                    max_exposure = _default_max_exposure.get(regime, 0.85)
            else:
                max_exposure = _default_max_exposure.get(regime, 0.85)

            # 当前总敞口
            total = float(weights.loc[date].sum())
            if total > max_exposure and total > 0:
                scale = max_exposure / total
                result.loc[date] = weights.loc[date] * scale

        return result

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    def _normalize(self, weights: pd.DataFrame) -> pd.DataFrame:
        """权重和 > 1 时等比缩小，保证不超过 100% 投资度。"""
        row_sum = weights.sum(axis=1)
        scale   = row_sum.where(row_sum <= 1.0, 1.0 / row_sum.replace(0, 1.0))
        return weights.multiply(scale, axis=0)

    def _effective_max_single(
        self,
        regime_series: Optional[pd.Series],
        regime_config  = None,
    ) -> float:
        """
        返回单标的权重硬上限（简化版：用序列最后一个 regime 决定）。
        正式版中，apply_regime_caps 已逐行处理，这里只是最后的安全网。
        """
        if regime_series is not None and len(regime_series) > 0:
            last_regime = str(regime_series.iloc[-1])
            if regime_config is not None:
                try:
                    return regime_config.position_constraints[last_regime].max_single_position
                except (KeyError, AttributeError):
                    pass
        return self._max_single
