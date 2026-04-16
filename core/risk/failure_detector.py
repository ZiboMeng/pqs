"""
FailureDetector: 策略运行时失效检测。

检测项
------
1. max_drawdown       — 当前回撤超过阈值（severity=critical）
2. loss_streak        — 连续亏损天数达到阈值（severity=warn）
3. rolling_sharpe     — 近期滚动 Sharpe 低于阈值（severity=warn）
4. vol_spike          — 近期已实现波动率相对基准期骤升（severity=warn）

每项检测返回 FailureSignal，方便下游 KillSwitch 聚合决策。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)


# ── FailureSignal ─────────────────────────────────────────────────────────────

@dataclass
class FailureSignal:
    """
    单项失效检测结果。

    Attributes
    ----------
    rule_name   : 规则名称
    triggered   : 是否触发
    value       : 检测到的实际值
    threshold   : 判断阈值
    description : 人类可读描述
    severity    : "warn"（警告）| "critical"（严重，应立即止损）
    """
    rule_name:   str
    triggered:   bool
    value:       float
    threshold:   float
    description: str
    severity:    str = "warn"

    def __str__(self) -> str:
        tag = "⚠️ TRIGGERED" if self.triggered else "✅ OK"
        return (
            f"[{tag}] {self.rule_name}: "
            f"value={self.value:.4f}, threshold={self.threshold:.4f} "
            f"[{self.severity}]"
        )


# ── FailureDetector ───────────────────────────────────────────────────────────

class FailureDetector:
    """
    策略运行时失效检测器。

    Parameters
    ----------
    max_drawdown       : 回撤阈值（负值，默认 -0.20）
    loss_streak        : 连续亏损天数阈值（默认 5 天）
    rolling_sharpe_thr : 滚动 Sharpe 最低值（默认 -0.5）
    rolling_sharpe_win : 滚动 Sharpe 窗口（默认 60 天）
    vol_spike_mult     : 波动率骤升倍数阈值（默认 2.0）
    vol_spike_win      : 近期波动率窗口（默认 20 天）
    vol_baseline_win   : 基准期波动率窗口（默认 252 天）
    """

    def __init__(
        self,
        max_drawdown:       float = -0.20,
        loss_streak:        int   = 5,
        rolling_sharpe_thr: float = -0.5,
        rolling_sharpe_win: int   = 60,
        vol_spike_mult:     float = 2.0,
        vol_spike_win:      int   = 20,
        vol_baseline_win:   int   = 252,
    ) -> None:
        self.max_drawdown       = max_drawdown
        self.loss_streak        = loss_streak
        self.rolling_sharpe_thr = rolling_sharpe_thr
        self.rolling_sharpe_win = rolling_sharpe_win
        self.vol_spike_mult     = vol_spike_mult
        self.vol_spike_win      = vol_spike_win
        self.vol_baseline_win   = vol_baseline_win

    # ── 单项检测 ──────────────────────────────────────────────────────────────

    def check_drawdown(self, equity: pd.Series) -> FailureSignal:
        """当前回撤是否超过 max_drawdown 阈值（severity=critical）。"""
        if len(equity) < 2:
            return FailureSignal(
                rule_name="max_drawdown", triggered=False,
                value=0.0, threshold=self.max_drawdown,
                description="数据不足", severity="critical",
            )
        running_max = equity.cummax()
        dd = float(((equity - running_max) / running_max).iloc[-1])
        return FailureSignal(
            rule_name   = "max_drawdown",
            triggered   = dd < self.max_drawdown,
            value       = dd,
            threshold   = self.max_drawdown,
            description = f"当前回撤 {dd:.2%}（阈值 {self.max_drawdown:.2%}）",
            severity    = "critical",
        )

    def check_loss_streak(self, equity: pd.Series) -> FailureSignal:
        """最近是否连续亏损达到 loss_streak 天。"""
        if len(equity) < self.loss_streak + 1:
            return FailureSignal(
                rule_name="loss_streak", triggered=False,
                value=0.0, threshold=float(self.loss_streak),
                description="数据不足", severity="warn",
            )
        rets   = equity.pct_change().dropna()
        tail   = rets.tail(self.loss_streak)
        streak = int((tail < 0).sum())
        return FailureSignal(
            rule_name   = "loss_streak",
            triggered   = streak >= self.loss_streak,
            value       = float(streak),
            threshold   = float(self.loss_streak),
            description = f"最近 {self.loss_streak} 日有 {streak} 日亏损",
            severity    = "warn",
        )

    def check_rolling_sharpe(self, equity: pd.Series) -> FailureSignal:
        """近 rolling_sharpe_win 日的 Sharpe 是否低于阈值。"""
        w = self.rolling_sharpe_win
        if len(equity) < w + 1:
            return FailureSignal(
                rule_name="rolling_sharpe", triggered=False,
                value=float("nan"), threshold=self.rolling_sharpe_thr,
                description="数据不足", severity="warn",
            )
        rets   = equity.pct_change().dropna().tail(w)
        std    = float(rets.std(ddof=1))
        sharpe = (
            float(rets.mean() / std * np.sqrt(252))
            if std > 1e-10
            else float("nan")
        )
        triggered = (not np.isnan(sharpe)) and (sharpe < self.rolling_sharpe_thr)
        return FailureSignal(
            rule_name   = "rolling_sharpe",
            triggered   = triggered,
            value       = sharpe,
            threshold   = self.rolling_sharpe_thr,
            description = f"近 {w} 日滚动 Sharpe = {sharpe:.3f}（阈值 {self.rolling_sharpe_thr:.1f}）",
            severity    = "warn",
        )

    def check_vol_spike(self, equity: pd.Series) -> FailureSignal:
        """近期已实现波动率是否相对基准期骤升超过 vol_spike_mult 倍。"""
        min_len = self.vol_spike_win + self.vol_baseline_win
        if len(equity) < min_len:
            return FailureSignal(
                rule_name="vol_spike", triggered=False,
                value=float("nan"), threshold=self.vol_spike_mult,
                description="数据不足", severity="warn",
            )
        rets         = equity.pct_change().dropna()
        recent_std   = float(rets.tail(self.vol_spike_win).std(ddof=1)) * np.sqrt(252)
        baseline_std = float(
            rets.tail(self.vol_baseline_win).iloc[: -self.vol_spike_win].std(ddof=1)
        ) * np.sqrt(252)
        ratio     = recent_std / baseline_std if baseline_std > 1e-10 else float("nan")
        triggered = bool((not np.isnan(ratio)) and (ratio > self.vol_spike_mult))
        return FailureSignal(
            rule_name   = "vol_spike",
            triggered   = triggered,
            value       = ratio if not np.isnan(ratio) else 0.0,
            threshold   = self.vol_spike_mult,
            description = (
                f"近 {self.vol_spike_win} 日 vol 骤升 {ratio:.2f}x"
                f"（阈值 {self.vol_spike_mult:.1f}x）"
            ),
            severity    = "warn",
        )

    # ── 聚合接口 ──────────────────────────────────────────────────────────────

    def check_all(self, equity: pd.Series) -> List[FailureSignal]:
        """运行全部检测项，返回 FailureSignal 列表。"""
        return [
            self.check_drawdown(equity),
            self.check_loss_streak(equity),
            self.check_rolling_sharpe(equity),
            self.check_vol_spike(equity),
        ]

    def any_triggered(self, equity: pd.Series) -> bool:
        """是否有任意一项触发（含 warn 和 critical）。"""
        return any(s.triggered for s in self.check_all(equity))

    def critical_triggered(self, equity: pd.Series) -> bool:
        """是否有 severity=critical 的项触发（当前仅 max_drawdown 为 critical）。"""
        return any(
            s.triggered and s.severity == "critical"
            for s in self.check_all(equity)
        )
