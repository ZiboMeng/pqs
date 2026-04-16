"""
PnLTracker: 每日 P&L 跟踪与累计绩效统计。

职责
----
- 接收每日 DayResult + 权益值，追加记录
- 提供 equity_curve / daily_returns / max_drawdown / sharpe 等属性
- reset() / restore() 支持重置与重启恢复
- to_dataframe() 导出为 DataFrame，便于报告
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from core.backtest.intraday_engine import DayResult
from core.logging_setup import get_logger

logger = get_logger(__name__)


class PnLTracker:
    """
    日度 P&L 跟踪器。

    Parameters
    ----------
    initial_capital : 初始资金（USD），用于计算 total_return
    """

    def __init__(self, initial_capital: float = 100_000.0):
        self._initial  = initial_capital
        self._records: List[Dict] = []

    # ── 记录接口 ──────────────────────────────────────────────────────────────

    def record(self, day_result: DayResult, equity: float) -> None:
        """追加单日结果与对应权益。"""
        self._records.append({
            "date":         day_result.date,
            "equity":       equity,
            "net_pnl":      day_result.net_pnl,
            "n_trades":     day_result.n_trades,
            "total_cost":   day_result.total_cost,
            "forced_close": day_result.forced_close,
        })

    def restore(self, records: List[Dict]) -> None:
        """从历史快照恢复状态（重启后调用）。"""
        self._records = list(records)

    def reset(self) -> None:
        """清除所有记录，回到空状态。"""
        self._records.clear()

    # ── 状态属性 ──────────────────────────────────────────────────────────────

    @property
    def latest_equity(self) -> float:
        if not self._records:
            return self._initial
        return float(self._records[-1]["equity"])

    @property
    def equity_curve(self) -> pd.Series:
        if not self._records:
            return pd.Series(dtype=float)
        return pd.Series(
            [r["equity"] for r in self._records],
            index=pd.DatetimeIndex([r["date"] for r in self._records]),
            name="equity",
        )

    @property
    def daily_returns(self) -> pd.Series:
        eq = self.equity_curve
        if len(eq) < 2:
            return pd.Series(dtype=float)
        return eq.pct_change().dropna()

    @property
    def total_return(self) -> float:
        return self.latest_equity / self._initial - 1.0

    @property
    def max_drawdown(self) -> float:
        """历史最大回撤（≤ 0）。"""
        eq = self.equity_curve
        if eq.empty:
            return 0.0
        running_max = eq.cummax()
        dd = (eq - running_max) / running_max
        return float(dd.min())

    @property
    def running_drawdown(self) -> float:
        """当前回撤（相对于历史最高点，≤ 0）。"""
        eq = self.equity_curve
        if eq.empty:
            return 0.0
        peak    = float(eq.max())
        current = float(eq.iloc[-1])
        if peak <= 0:
            return 0.0
        return (current - peak) / peak

    @property
    def sharpe(self) -> float:
        """年化 Sharpe（需至少 20 天数据，否则返回 nan）。"""
        rets = self.daily_returns
        if len(rets) < 20:
            return float("nan")
        std = float(rets.std(ddof=1))
        if std < 1e-10:
            return float("nan")
        return float(rets.mean() / std * np.sqrt(252))

    # ── 汇总 ──────────────────────────────────────────────────────────────────

    def summary(self) -> Dict:
        """返回关键绩效指标字典。"""
        return {
            "n_days":           len(self._records),
            "latest_equity":    self.latest_equity,
            "total_return":     self.total_return,
            "max_drawdown":     self.max_drawdown,
            "running_drawdown": self.running_drawdown,
            "sharpe":           self.sharpe,
            "total_trades":     sum(r["n_trades"]   for r in self._records),
            "total_cost_usd":   sum(r["total_cost"] for r in self._records),
        }

    def to_dataframe(self) -> pd.DataFrame:
        """导出历史记录为 DataFrame（index=date）。"""
        if not self._records:
            return pd.DataFrame()
        return pd.DataFrame(self._records).set_index("date")
