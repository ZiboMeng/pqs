"""
KillSwitch: 策略熔断开关。

在 FailureDetector 基础上补充：
  - VIX 绝对值阈值（市场极端恐慌）
  - 持仓集中度阈值（单标的过度集中）

任意一项规则触发 → KillSwitchResult.triggered = True。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from core.risk.failure_detector import FailureDetector, FailureSignal
from core.logging_setup import get_logger

logger = get_logger(__name__)


# ── 配置 ──────────────────────────────────────────────────────────────────────

@dataclass
class KillSwitchConfig:
    """
    KillSwitch 阈值配置。

    Attributes
    ----------
    max_drawdown        : 回撤熔断阈值（默认 -20%）
    loss_streak         : 连续亏损天数（默认 5 天）
    rolling_sharpe_thr  : 滚动 Sharpe 最低值（默认 -0.5）
    rolling_sharpe_win  : 滚动 Sharpe 窗口（默认 60 天）
    vol_spike_mult      : 波动率骤升倍数（默认 3.0）
    vix_threshold       : VIX 熔断阈值（默认 40.0）
    max_position_conc   : 单标的最大权重（默认 0.80）
    """
    max_drawdown:       float = -0.20
    loss_streak:        int   = 5
    rolling_sharpe_thr: float = -0.5
    rolling_sharpe_win: int   = 60
    vol_spike_mult:     float = 3.0
    vix_threshold:      float = 40.0
    max_position_conc:  float = 0.80


# ── 结果 ──────────────────────────────────────────────────────────────────────

@dataclass
class KillSwitchResult:
    """
    KillSwitch.evaluate() 输出。

    Attributes
    ----------
    triggered    : 是否熔断
    active_rules : 触发的规则名列表
    signals      : 全部 FailureSignal（含未触发项）
    """
    triggered:    bool
    active_rules: List[str]          = field(default_factory=list)
    signals:      List[FailureSignal] = field(default_factory=list)

    def __str__(self) -> str:
        if self.triggered:
            return f"🚨 KILL SWITCH TRIGGERED: {', '.join(self.active_rules)}"
        return "✅ 运行正常（未触发熔断）"


# ── KillSwitch ────────────────────────────────────────────────────────────────

class KillSwitch:
    """
    策略熔断开关。

    Parameters
    ----------
    config : KillSwitchConfig（可选，默认使用标准阈值）
    """

    def __init__(self, config: Optional[KillSwitchConfig] = None) -> None:
        self._cfg = config or KillSwitchConfig()
        self._detector = FailureDetector(
            max_drawdown       = self._cfg.max_drawdown,
            loss_streak        = self._cfg.loss_streak,
            rolling_sharpe_thr = self._cfg.rolling_sharpe_thr,
            rolling_sharpe_win = self._cfg.rolling_sharpe_win,
            vol_spike_mult     = self._cfg.vol_spike_mult,
        )

    # ── 主接口 ────────────────────────────────────────────────────────────────

    def evaluate(
        self,
        equity_curve: pd.Series,
        vix:          Optional[float]            = None,
        weights:      Optional[Dict[str, float]] = None,
    ) -> KillSwitchResult:
        """
        评估所有熔断规则，返回 KillSwitchResult。

        Parameters
        ----------
        equity_curve : 权益曲线（pd.Series）
        vix          : 当日 VIX 值（可选）
        weights      : 当前持仓权重 {symbol: weight}（可选，用于集中度检测）
        """
        signals: List[FailureSignal] = self._detector.check_all(equity_curve)

        # ── VIX 阈值检测 ──────────────────────────────────────────────────────
        if vix is not None:
            triggered = float(vix) >= self._cfg.vix_threshold
            signals.append(FailureSignal(
                rule_name   = "vix_spike",
                triggered   = triggered,
                value       = float(vix),
                threshold   = self._cfg.vix_threshold,
                description = f"VIX = {vix:.1f}（阈值 {self._cfg.vix_threshold:.0f}）",
                severity    = "warn",
            ))

        # ── 持仓集中度检测 ────────────────────────────────────────────────────
        if weights:
            max_w      = max(weights.values(), default=0.0)
            triggered  = max_w > self._cfg.max_position_conc
            max_sym    = max(weights, key=weights.__getitem__)
            signals.append(FailureSignal(
                rule_name   = "position_concentration",
                triggered   = triggered,
                value       = float(max_w),
                threshold   = self._cfg.max_position_conc,
                description = (
                    f"最大持仓 {max_sym} = {max_w:.2%}"
                    f"（阈值 {self._cfg.max_position_conc:.2%}）"
                ),
                severity    = "warn",
            ))

        active    = [s.rule_name for s in signals if s.triggered]
        triggered = len(active) > 0

        if triggered:
            logger.warning("KillSwitch triggered: %s", active)

        return KillSwitchResult(
            triggered    = triggered,
            active_rules = active,
            signals      = signals,
        )

    def is_triggered(
        self,
        equity_curve: pd.Series,
        vix:          Optional[float]            = None,
        weights:      Optional[Dict[str, float]] = None,
    ) -> bool:
        """快捷接口：直接返回 bool。"""
        return self.evaluate(equity_curve, vix, weights).triggered
