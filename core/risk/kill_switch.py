"""
KillSwitch: 三档策略熔断开关。

档位（由轻到重）
--------------
  NORMAL   → 正常运行，仓位 100%
  DEGRADED → 回撤 > 承诺的 70%，仓位缩至 50%
  SUSPENDED → 回撤 > 承诺的 100%，清仓冻结
  (恢复)   → 连续 N 天所有诊断绿灯 → DEGRADED → 再 N 天 → NORMAL

额外检测：
  - VIX 绝对值阈值（市场极端恐慌）
  - 持仓集中度阈值（单标的过度集中）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from core.risk.failure_detector import FailureDetector, FailureSignal
from core.logging_setup import get_logger

logger = get_logger(__name__)


# ── 配置 ──────────────────────────────────────────────────────────────────────

class KillSwitchState:
    NORMAL    = "NORMAL"
    DEGRADED  = "DEGRADED"
    SUSPENDED = "SUSPENDED"


@dataclass
class KillSwitchConfig:
    """
    KillSwitch 阈值配置。

    Three-tier thresholds:
      degrade_dd_ratio  : drawdown > promised × this → DEGRADED (position ×50%)
      suspend_dd_ratio  : drawdown > promised × this → SUSPENDED (clear all)
      recover_green_days: consecutive green days to auto-recover one tier
    """
    max_drawdown:       float = -0.20
    loss_streak:        int   = 5
    rolling_sharpe_thr: float = -0.5
    rolling_sharpe_win: int   = 60
    vol_spike_mult:     float = 3.0
    vix_threshold:      float = 40.0
    max_position_conc:  float = 0.80
    degrade_dd_ratio:   float = 0.70
    suspend_dd_ratio:   float = 1.00
    recover_green_days: int   = 10
    degraded_position_mult: float = 0.50


# ── 结果 ──────────────────────────────────────────────────────────────────────

@dataclass
class KillSwitchResult:
    """
    KillSwitch.evaluate() 输出。

    Attributes
    ----------
    triggered    : 是否有任意规则触发
    state        : 当前状态 (NORMAL / DEGRADED / SUSPENDED)
    position_multiplier : 仓位乘数 (1.0 / 0.5 / 0.0)
    active_rules : 触发的规则名列表
    signals      : 全部 FailureSignal（含未触发项）
    green_streak : 连续绿灯天数
    """
    triggered:           bool
    state:               str   = KillSwitchState.NORMAL
    position_multiplier: float = 1.0
    active_rules:        List[str]          = field(default_factory=list)
    signals:             List[FailureSignal] = field(default_factory=list)
    green_streak:        int   = 0

    def __str__(self) -> str:
        if self.state == KillSwitchState.SUSPENDED:
            return f"SUSPENDED (position=0%): {', '.join(self.active_rules)}"
        if self.state == KillSwitchState.DEGRADED:
            return f"DEGRADED (position=50%): {', '.join(self.active_rules)}"
        return f"NORMAL (position=100%, green_streak={self.green_streak})"


# ── KillSwitch ────────────────────────────────────────────────────────────────

class KillSwitch:
    """
    三档策略熔断开关（NORMAL / DEGRADED / SUSPENDED）。

    State machine:
      NORMAL → DEGRADED: drawdown > promised × degrade_dd_ratio
      DEGRADED → SUSPENDED: drawdown > promised × suspend_dd_ratio
      SUSPENDED → DEGRADED: recover_green_days consecutive green days
      DEGRADED → NORMAL: another recover_green_days consecutive green days
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
        self._state: str = KillSwitchState.NORMAL
        self._green_streak: int = 0
        self._degrade_dd = self._cfg.max_drawdown * self._cfg.degrade_dd_ratio
        self._suspend_dd = self._cfg.max_drawdown * self._cfg.suspend_dd_ratio

    @property
    def state(self) -> str:
        return self._state

    @property
    def position_multiplier(self) -> float:
        if self._state == KillSwitchState.SUSPENDED:
            return 0.0
        if self._state == KillSwitchState.DEGRADED:
            return self._cfg.degraded_position_mult
        return 1.0

    # ── 主接口 ────────────────────────────────────────────────────────────────

    def evaluate(
        self,
        equity_curve: pd.Series,
        vix:          Optional[float]            = None,
        weights:      Optional[Dict[str, float]] = None,
    ) -> KillSwitchResult:
        signals: List[FailureSignal] = self._detector.check_all(equity_curve)

        if vix is not None:
            triggered = float(vix) >= self._cfg.vix_threshold
            signals.append(FailureSignal(
                rule_name="vix_spike", triggered=triggered,
                value=float(vix), threshold=self._cfg.vix_threshold,
                description=f"VIX = {vix:.1f} (threshold {self._cfg.vix_threshold:.0f})",
                severity="warn",
            ))

        if weights:
            max_w = max(weights.values(), default=0.0)
            triggered = max_w > self._cfg.max_position_conc
            max_sym = max(weights, key=weights.__getitem__) if weights else ""
            signals.append(FailureSignal(
                rule_name="position_concentration", triggered=triggered,
                value=float(max_w), threshold=self._cfg.max_position_conc,
                description=f"Max position {max_sym} = {max_w:.2%}",
                severity="warn",
            ))

        active = [s.rule_name for s in signals if s.triggered]
        any_triggered = len(active) > 0

        current_dd = self._get_current_dd(equity_curve)
        self._update_state(current_dd, any_triggered)

        if self._state != KillSwitchState.NORMAL:
            logger.warning("KillSwitch state=%s, active=%s", self._state, active)

        return KillSwitchResult(
            triggered=any_triggered or self._state != KillSwitchState.NORMAL,
            state=self._state,
            position_multiplier=self.position_multiplier,
            active_rules=active,
            signals=signals,
            green_streak=self._green_streak,
        )

    def is_triggered(
        self,
        equity_curve: pd.Series,
        vix:          Optional[float]            = None,
        weights:      Optional[Dict[str, float]] = None,
    ) -> bool:
        return self.evaluate(equity_curve, vix, weights).triggered

    def reset(self) -> None:
        self._state = KillSwitchState.NORMAL
        self._green_streak = 0

    # ── Internal ─────────────────────────────────────────────────────────────

    def _get_current_dd(self, equity: pd.Series) -> float:
        if len(equity) < 2:
            return 0.0
        running_max = equity.cummax()
        return float(((equity - running_max) / running_max).iloc[-1])

    def _update_state(self, current_dd: float, any_triggered: bool) -> None:
        if current_dd <= self._suspend_dd:
            self._state = KillSwitchState.SUSPENDED
            self._green_streak = 0
            return

        if current_dd <= self._degrade_dd:
            if self._state == KillSwitchState.NORMAL:
                self._state = KillSwitchState.DEGRADED
                self._green_streak = 0
            return

        if any_triggered:
            self._green_streak = 0
            return

        self._green_streak += 1

        if self._state == KillSwitchState.SUSPENDED:
            if self._green_streak >= self._cfg.recover_green_days:
                self._state = KillSwitchState.DEGRADED
                self._green_streak = 0
                logger.info("KillSwitch: SUSPENDED → DEGRADED (recovery)")
        elif self._state == KillSwitchState.DEGRADED:
            if self._green_streak >= self._cfg.recover_green_days:
                self._state = KillSwitchState.NORMAL
                self._green_streak = 0
                logger.info("KillSwitch: DEGRADED → NORMAL (recovery)")
