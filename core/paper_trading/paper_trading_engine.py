"""
PaperTradingEngine: 内部模拟盘引擎（不对接真实 Broker）。

设计原则
--------
- 复用 IntradayBacktestEngine.run_single_day()，确保回测与模拟盘行为完全一致
- 状态持久化到 SQLite（重启后可从上次位置恢复）
- EOD 对账：检查残余持仓、异常 P&L、大回撤
- kill_switch 通过注入 KillSwitch 对象实现（所有阈值均来自配置，无硬编码）

数据表
------
  pt_state   : 当前持仓 & 现金（单行，每日覆盖）
  pt_history : 历史每日权益、P&L、交易笔数（只追加）
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from core.execution.cost_model import CostModel
from core.backtest.intraday_engine import IntradayBacktestEngine, DayResult
from core.paper_trading.pnl_tracker import PnLTracker
from core.risk.kill_switch import KillSwitch, KillSwitchConfig
from core.logging_setup import get_logger

logger = get_logger(__name__)

# ── EOD 对账阈值（仅用于警告，不触发 kill switch）────────────────────────────
_WARN_DAILY_PNL_RATIO    = 0.05   # 单日 P&L / 权益 > 5% → 警告
_WARN_DRAWDOWN_THRESHOLD = -0.15  # 当前回撤 < -15% → 警告

# ── Replay 模式 Bias 警告文本 ────────────────────────────────────────────────
_REPLAY_BIAS_WARNING = (
    "⚠️  [REPLAY MODE] 此运行为历史回放，存在以下偏差风险：\n"
    "  1. 策略/参数基于完整历史数据选择（前视偏差）\n"
    "  2. 回放结果不代表真实 OOS 绩效\n"
    "  3. 仅用于测试执行一致性和发现系统性 bug\n"
    "  所有 replay 记录在数据库中标注 is_replay=1"
)


class PaperTradingEngine:
    """
    内部模拟盘引擎。

    Parameters
    ----------
    cost_model          : CostModel 实例（与 BacktestEngine 共享）
    pnl_tracker         : PnLTracker 实例
    db_path             : SQLite 数据库路径（自动创建父目录）
    initial_capital     : 初始资金（USD）
    eod_force_close     : 是否 EOD 强制清仓（默认 True）
    confluence_enabled  : 是否启用 confluence 过滤（默认 True）
    kill_switch         : KillSwitch 实例；若为 None，使用默认配置（-20% 回撤 / 5 连亏）
    """

    def __init__(
        self,
        cost_model:         CostModel,
        pnl_tracker:        PnLTracker,
        db_path:            str | Path,
        initial_capital:    float              = 100_000.0,
        eod_force_close:    bool               = True,
        confluence_enabled: bool               = True,
        kill_switch:        Optional[KillSwitch] = None,
        replay_mode:        bool               = False,
    ):
        self._engine = IntradayBacktestEngine(
            cost_model         = cost_model,
            initial_capital    = initial_capital,
            eod_force_close    = eod_force_close,
            confluence_enabled = confluence_enabled,
        )
        self._tracker         = pnl_tracker
        self._db_path         = Path(db_path)
        self._initial_capital = initial_capital
        self._kill_switch     = kill_switch or KillSwitch(KillSwitchConfig())
        self._replay_mode     = replay_mode

        # 运行时状态
        self._positions: Dict[str, float] = {}
        self._cash:      float             = initial_capital

        if replay_mode:
            logger.warning(_REPLAY_BIAS_WARNING)

        # 初始化数据库并加载历史状态
        self._init_db()
        self._load_state()

    # ── 主接口 ────────────────────────────────────────────────────────────────

    def run_day(
        self,
        date:     pd.Timestamp,
        day_bars: pd.DataFrame,
        day_sigs: pd.DataFrame,
        day_conf: Optional[pd.DataFrame] = None,
        vix:      float                   = 15.0,
    ) -> DayResult:
        """
        执行单日模拟盘交易。

        流程：
          1. 调用 run_single_day()（与回测完全共用）
          2. 更新内存状态（持仓 / 现金）
          3. 计算当日 EOD 权益
          4. 记录到 PnLTracker
          5. 持久化到 SQLite
          6. 返回 DayResult

        Parameters
        ----------
        date     : 交易日期（pd.Timestamp）
        day_bars : 当日 60m OHLCV DataFrame（ET tz-naive）
        day_sigs : 当日目标权重信号
        day_conf : 当日 confluence 评分（可选，None=不过滤）
        vix      : 当日 VIX 值（默认 15.0）
        """
        result = self._engine.run_single_day(
            date      = date,
            day_bars  = day_bars,
            day_sigs  = day_sigs,
            day_conf  = day_conf,
            positions = self._positions.copy(),
            cash      = self._cash,
            vix       = vix,
        )

        # 更新内存状态
        self._positions = result.eod_positions
        self._cash      = result.eod_cash

        # 当日 EOD 权益 = 现金 + 持仓市值（EOD 清仓后持仓为空，仅现金）
        equity = self._cash + self._position_value(day_bars)

        # 记录到 PnLTracker
        self._tracker.record(result, equity)

        # 持久化
        self._save_state(date, result, equity)

        logger.info(
            "[%s] equity=%.2f  net_pnl=%.2f  trades=%d  forced_close=%s",
            date.date(), equity, result.net_pnl, result.n_trades, result.forced_close,
        )
        return result

    # ── 状态查询 ──────────────────────────────────────────────────────────────

    def get_positions(self) -> Dict[str, float]:
        """返回当前持仓副本。"""
        return dict(self._positions)

    def get_cash(self) -> float:
        """返回当前现金余额。"""
        return self._cash

    def get_equity(self) -> float:
        """返回 PnLTracker 记录的最新权益。"""
        return self._tracker.latest_equity

    def get_pnl_summary(self) -> Dict:
        """返回 PnLTracker.summary() 字典。"""
        return self._tracker.summary()

    def load_history(self) -> pd.DataFrame:
        """从 SQLite 加载完整每日历史记录（index=date）。"""
        conn = sqlite3.connect(self._db_path)
        try:
            df = pd.read_sql_query(
                "SELECT * FROM pt_history ORDER BY date",
                conn,
                index_col="date",
            )
        finally:
            conn.close()
        if not df.empty:
            df.index = pd.DatetimeIndex(df.index)
        return df

    # ── EOD 对账 ──────────────────────────────────────────────────────────────

    def reconcile(self, date: pd.Timestamp, day_result: DayResult) -> Dict:
        """
        EOD 对账：对当日结果进行异常检测。

        检查项：
          1. EOD 强制平仓后是否有残余持仓
          2. 单日 P&L 是否超过权益的 ±5%
          3. 当前回撤是否超过 -15%（warning 阈值，低于 kill switch 触发线）

        Returns
        -------
        dict: {ok, warnings, n_trades, equity, drawdown, date}
        """
        warnings: List[str] = []

        # 检查 EOD 强制平仓后残余持仓
        if day_result.forced_close:
            remaining = sum(day_result.eod_positions.values())
            if remaining > 1e-4:
                warnings.append(f"EOD 后仍有残余持仓: {remaining:.4f} 股")

        # 检查单日 P&L 比例
        eq = self._tracker.latest_equity
        if eq > 0 and abs(day_result.net_pnl / eq) > _WARN_DAILY_PNL_RATIO:
            pct = day_result.net_pnl / eq
            warnings.append(f"单日 P&L 异常: {pct:.1%}")

        # 检查当前回撤（warning 阈值）
        dd = self._tracker.running_drawdown
        if dd < _WARN_DRAWDOWN_THRESHOLD:
            warnings.append(f"当前回撤超过警戒阈值: {dd:.1%}")

        if warnings:
            logger.warning("[%s] EOD 对账警告: %s", date.date(), "; ".join(warnings))
        else:
            logger.info("[%s] EOD 对账通过", date.date())

        return {
            "ok":       len(warnings) == 0,
            "warnings": warnings,
            "n_trades": day_result.n_trades,
            "equity":   eq,
            "drawdown": dd,
            "date":     date,
        }

    # ── Kill Switch ───────────────────────────────────────────────────────────

    @property
    def is_kill_switch_triggered(self) -> bool:
        """
        使用注入的 KillSwitch 对象判断是否触发（所有阈值来自配置）。

        当权益曲线数据不足时，返回 False（不触发）。
        """
        eq = self._tracker.equity_curve
        if len(eq) < 2:
            return False
        triggered = self._kill_switch.is_triggered(eq)
        if triggered:
            logger.warning("Kill switch triggered by KillSwitch evaluation")
        return triggered

    # ── 重置 ──────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """重置到初始状态，清除所有持仓、PnLTracker 记录与 DB 数据。"""
        self._positions = {}
        self._cash      = self._initial_capital
        self._tracker.reset()
        self._clear_db()
        logger.info("PaperTradingEngine reset. initial_capital=%.2f", self._initial_capital)

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    def _position_value(self, day_bars: pd.DataFrame) -> float:
        """用当日最后一根 K 线的 close 价格估算持仓市值。"""
        if not self._positions or day_bars.empty:
            return 0.0
        last_close = (
            float(day_bars["close"].iloc[-1])
            if "close" in day_bars.columns
            else 0.0
        )
        return sum(qty * last_close for qty in self._positions.values())

    # ── SQLite 持久化 ─────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """初始化数据库 schema（幂等）。"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pt_state (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                cash           REAL    NOT NULL,
                positions_json TEXT    NOT NULL,
                updated_at     TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pt_history (
                date         TEXT    PRIMARY KEY,
                equity       REAL    NOT NULL,
                net_pnl      REAL    NOT NULL,
                n_trades     INTEGER NOT NULL,
                total_cost   REAL    NOT NULL,
                forced_close INTEGER NOT NULL,
                is_replay    INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def _load_state(self) -> None:
        """
        从 DB 加载最新状态：
          - pt_state  → 恢复 _cash / _positions
          - pt_history → 恢复 PnLTracker 历史记录
        """
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT cash, positions_json FROM pt_state ORDER BY id DESC LIMIT 1"
            ).fetchone()
            hist_rows = conn.execute(
                "SELECT date, equity, net_pnl, n_trades, total_cost, forced_close "
                "FROM pt_history ORDER BY date"
            ).fetchall()
        finally:
            conn.close()

        if row:
            self._cash      = float(row[0])
            self._positions = json.loads(row[1])

        if hist_rows:
            records = [
                {
                    "date":         pd.Timestamp(r[0]),
                    "equity":       float(r[1]),
                    "net_pnl":      float(r[2]),
                    "n_trades":     int(r[3]),
                    "total_cost":   float(r[4]),
                    "forced_close": bool(r[5]),
                }
                for r in hist_rows
            ]
            self._tracker.restore(records)

    def _save_state(
        self,
        date:   pd.Timestamp,
        result: DayResult,
        equity: float,
    ) -> None:
        """持久化当日状态到 SQLite。"""
        conn = sqlite3.connect(self._db_path)
        # pt_state 只保留一行（最新状态）
        conn.execute("DELETE FROM pt_state")
        conn.execute(
            "INSERT INTO pt_state (cash, positions_json, updated_at) VALUES (?, ?, ?)",
            (self._cash, json.dumps(self._positions), str(date.date())),
        )
        # pt_history 按日期主键 upsert
        conn.execute(
            "INSERT OR REPLACE INTO pt_history "
            "(date, equity, net_pnl, n_trades, total_cost, forced_close, is_replay) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(date.date()),
                equity,
                result.net_pnl,
                result.n_trades,
                result.total_cost,
                int(result.forced_close),
                int(self._replay_mode),
            ),
        )
        conn.commit()
        conn.close()

    def _clear_db(self) -> None:
        """清空数据库所有记录。"""
        conn = sqlite3.connect(self._db_path)
        conn.execute("DELETE FROM pt_state")
        conn.execute("DELETE FROM pt_history")
        conn.commit()
        conn.close()
