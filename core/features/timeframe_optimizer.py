"""
TimeframeOptimizer: 动态时间帧权重优化器。

目标
----
用数据驱动替代硬编码的时间帧权重（60m=0.45, 30m=0.40, 15m=0.15），
让每个时间帧的权重正比于其对短期收益的实际预测贡献（IR 贡献）。

工作原理
--------
1. Calibrate 阶段（离线研究，使用历史数据）：
   - 对每个时间帧，计算其 directional signal 与 next-bar 收益的 Spearman 相关（IC）
   - 用 rolling window 平滑 IC 时序，取均值/std 得到 IR
   - 权重 = softmax(max(IR_i, 0)) → 只对正 IR 的时间帧分配权重
   - 支持分 regime 校准（BULL / CRISIS 下不同权重）

2. Runtime 阶段：
   - 加载已校准的权重（JSON 文件）
   - FeaturePipeline 实例化时调用 optimizer.get_weights(regime) 获取权重

3. 再校准：
   - 建议每月重新校准一次（由 run_mining.py 或 cron 触发）
   - 若数据不足或 IR 全为负，退回 uniform 权重

使用方法
--------
    # 校准
    optimizer = TimeframeOptimizer()
    optimizer.calibrate(
        intraday_data={"60m": df_60m, "30m": df_30m, "15m": df_15m},
        next_bar_returns=returns_60m_shifted,
        regime_series=regime_s,
    )
    optimizer.save("data/timeframe_weights.json")

    # 运行时
    optimizer = TimeframeOptimizer.load("data/timeframe_weights.json")
    weights = optimizer.get_weights(regime="BULL")
    pipeline = FeaturePipeline(confluence_weights=weights)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from core.logging_setup import get_logger

logger = get_logger(__name__)

# Fallback if calibration fails or data is insufficient
_UNIFORM_FALLBACK = {"60m": 0.45, "30m": 0.40, "15m": 0.15}

# Minimum periods required for reliable IR estimate
_MIN_PERIODS = 60


class TimeframeOptimizer:
    """
    动态时间帧权重优化器。

    Parameters
    ----------
    ir_window     : 用于平滑 IC 序列的滚动窗口（bars）
    regime_aware  : 是否按 regime 分别校准权重
    """

    def __init__(
        self,
        ir_window:    int  = 60,
        regime_aware: bool = True,
    ) -> None:
        self._ir_window    = ir_window
        self._regime_aware = regime_aware
        # weights dict: regime → {freq: weight}
        # "global" key holds regime-agnostic weights
        self._weights: Dict[str, Dict[str, float]] = {}

    # ── Calibration ───────────────────────────────────────────────────────────

    def calibrate(
        self,
        intraday_data:    Dict[str, pd.DataFrame],
        next_bar_returns: pd.Series,
        regime_series:    Optional[pd.Series] = None,
    ) -> None:
        """
        从历史日内数据中估计每个时间帧的预测 IR，推导最优权重。

        Parameters
        ----------
        intraday_data     : {freq: OHLCV DataFrame} — 各时间帧的历史数据
        next_bar_returns  : 以主时间帧（60m）为基础的下一根 bar 实际收益
                            index 与 60m DataFrame 对齐
        regime_series     : 可选，日度 RegimeState 序列（用于分 regime 校准）
        """
        freqs = list(intraday_data.keys())
        if not freqs:
            logger.warning("TimeframeOptimizer.calibrate: empty intraday_data")
            self._weights["global"] = _UNIFORM_FALLBACK.copy()
            return

        # Compute directional signal for each freq
        signals: Dict[str, pd.Series] = {}
        for freq, df in intraday_data.items():
            sig = self._extract_signal(df)
            if sig is not None and not sig.empty:
                signals[freq] = sig

        if not signals:
            logger.warning("TimeframeOptimizer: could not extract signals — using uniform weights")
            self._weights["global"] = _UNIFORM_FALLBACK.copy()
            return

        # Align all signals to next_bar_returns index
        aligned_ret = next_bar_returns.dropna()
        common_idx  = aligned_ret.index
        for freq in list(signals.keys()):
            sig = signals[freq].reindex(common_idx, method="ffill").fillna(0.0)
            signals[freq] = sig

        # Global calibration
        self._weights["global"] = self._compute_weights(signals, aligned_ret)

        # Regime-conditional calibration
        if self._regime_aware and regime_series is not None:
            regimes = ["BULL", "RISK_ON", "NEUTRAL", "CAUTIOUS", "RISK_OFF", "CRISIS"]
            aligned_regime = regime_series.reindex(common_idx, method="ffill").fillna("NEUTRAL")
            for r in regimes:
                mask  = aligned_regime == r
                n_obs = int(mask.sum())
                if n_obs < _MIN_PERIODS:
                    logger.debug("TimeframeOptimizer: not enough %s obs (%d) — skipping", r, n_obs)
                    continue
                r_ret  = aligned_ret[mask]
                r_sigs = {f: signals[f][mask] for f in signals}
                self._weights[r] = self._compute_weights(r_sigs, r_ret)

        logger.info(
            "TimeframeOptimizer calibrated: global=%s",
            {k: f"{v:.3f}" for k, v in self._weights.get("global", {}).items()},
        )

    # ── Runtime ───────────────────────────────────────────────────────────────

    def get_weights(self, regime: Optional[str] = None) -> Dict[str, float]:
        """
        返回指定 regime 的时间帧权重（若无则返回 global 权重）。

        未校准时返回 _UNIFORM_FALLBACK。
        """
        if regime and regime in self._weights:
            return dict(self._weights[regime])
        return dict(self._weights.get("global", _UNIFORM_FALLBACK))

    def save(self, path: str | Path) -> None:
        """持久化权重到 JSON 文件。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._weights, indent=2))
        logger.info("TimeframeOptimizer saved to %s", p)

    @classmethod
    def load(cls, path: str | Path) -> "TimeframeOptimizer":
        """从 JSON 文件加载权重。"""
        p = Path(path)
        if not p.exists():
            logger.warning("TimeframeOptimizer: %s not found — returning default", p)
            opt = cls()
            opt._weights["global"] = _UNIFORM_FALLBACK.copy()
            return opt
        data = json.loads(p.read_text())
        opt  = cls()
        opt._weights = data
        logger.info("TimeframeOptimizer loaded from %s", p)
        return opt

    # ── Internal ──────────────────────────────────────────────────────────────

    def _compute_weights(
        self,
        signals:  Dict[str, pd.Series],
        returns:  pd.Series,
    ) -> Dict[str, float]:
        """
        给定各时间帧信号和实际收益，计算权重。

        IR = mean(IC) / std(IC)，IC = Spearman corr(signal, return)
        权重 = softmax(max(IR, 0))；若全部 IR ≤ 0，退回均匀权重。
        """
        irs: Dict[str, float] = {}
        for freq, sig in signals.items():
            common = sig.index.intersection(returns.index)
            if len(common) < _MIN_PERIODS:
                irs[freq] = 0.0
                continue
            s  = sig.loc[common].values
            r  = returns.loc[common].values
            # Rolling Spearman IC (window = ir_window)
            ic_vals = self._rolling_spearman_ic(s, r, self._ir_window)
            valid   = ic_vals[~np.isnan(ic_vals)]
            if len(valid) < 10:
                irs[freq] = 0.0
            else:
                std = valid.std()
                irs[freq] = float(valid.mean() / std) if std > 1e-10 else 0.0

        pos_irs = {f: max(v, 0.0) for f, v in irs.items()}
        total   = sum(pos_irs.values())

        if total < 1e-10:
            # All IRS non-positive — fall back to uniform over available freqs
            n = len(signals)
            return {f: 1.0 / n for f in signals}

        # Softmax-style normalization (already linear since we clipped negatives)
        return {f: v / total for f, v in pos_irs.items()}

    @staticmethod
    def _extract_signal(df: pd.DataFrame) -> Optional[pd.Series]:
        """
        从 OHLCV DataFrame 提取简单方向信号 ∈ [-1, +1]。

        使用 (close - open) / open 作为 bar 方向信号代理；
        正值 = 收涨，负值 = 收跌。
        """
        if df is None or df.empty:
            return None
        if "close" not in df.columns or "open" not in df.columns:
            if "close" in df.columns:
                sig = df["close"].pct_change().clip(-0.05, 0.05) / 0.05
                return sig.rename("signal")
            return None
        sig = (df["close"] - df["open"]) / df["open"].replace(0, np.nan)
        return sig.clip(-0.05, 0.05).rename("signal")

    @staticmethod
    def _rolling_spearman_ic(
        signal:  np.ndarray,
        returns: np.ndarray,
        window:  int,
    ) -> np.ndarray:
        """按滚动窗口计算逐点 Spearman IC。"""
        n      = len(signal)
        result = np.full(n, np.nan)
        for i in range(window, n):
            s = signal[i - window : i]
            r = returns[i - window : i]
            mask = ~(np.isnan(s) | np.isnan(r))
            if mask.sum() < 10:
                continue
            corr, _ = scipy_stats.spearmanr(s[mask], r[mask])
            result[i] = corr
        return result
