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
from typing import Callable, Dict, List, Optional

import pandas as pd

import numpy as np

from core.execution.cost_model import CostModel
from core.execution.execution_simulator import ExecutionSimulator, Order, OrderSide, Fill
from core.backtest.backtest_engine import BacktestEngine as _DailyEngine
from core.backtest.intraday_engine import IntradayBacktestEngine, DayResult, BarUpdate
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
        integer_shares:     bool               = True,
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
        self._integer_shares  = integer_shares

        # 运行时状态
        self._positions: Dict[str, float] = {}
        self._cash:      float             = initial_capital
        # Stale-bars tracker persists across successive run_day_intraday
        # invocations so that a multi-day halt accumulates correctly
        # toward the intraday ghost-cleanup threshold (closeout 2026-04-20).
        self._intraday_stale_counts: Dict[str, int] = {}

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

    def run_day_daily(
        self,
        date:        pd.Timestamp,
        target_wts:  Dict[str, float],
        prices:      Dict[str, float],
        open_prices: Dict[str, float],
        vix:         float = 15.0,
    ) -> DayResult:
        """
        Daily-mode execution using BacktestEngine's order generation logic.
        Ensures paper trading and backtest use identical rebalance semantics.
        """
        price_row = pd.Series(prices)
        open_row = pd.Series(open_prices)

        portfolio_value = self._cash + sum(
            self._positions.get(s, 0) * prices.get(s, 0) for s in self._positions
        )

        cur_weights: Dict[str, float] = {}
        if portfolio_value > 0:
            for sym, qty in self._positions.items():
                p = prices.get(sym, 0)
                if p > 0:
                    cur_weights[sym] = (qty * p) / portfolio_value

        daily_engine = _DailyEngine(
            cost_model=self._engine._cost,
            initial_capital=self._initial_capital,
            integer_shares=self._integer_shares,
        )
        orders = daily_engine._generate_orders(
            cur_weights=cur_weights,
            tgt_weights=target_wts,
            portfolio_val=portfolio_value,
            price_row=price_row,
            open_row=open_row,
            signal_date=date,
        )

        fills = daily_engine._sim.simulate_fills(
            orders=orders,
            open_prices=open_prices,
            vix=vix,
            cash=self._cash,
        )

        for fill in fills:
            prev_qty = self._positions.get(fill.symbol, 0.0)
            if fill.side == OrderSide.BUY:
                self._positions[fill.symbol] = prev_qty + fill.executed_qty
            else:
                self._positions[fill.symbol] = max(prev_qty - fill.executed_qty, 0.0)
            self._cash += fill.cash_delta

        self._positions = {s: q for s, q in self._positions.items() if q > 1e-6}

        equity = self._cash + sum(
            self._positions.get(s, 0) * prices.get(s, 0) for s in self._positions
        )
        net_pnl = equity - portfolio_value

        result = DayResult(
            date=date, trades=fills,
            eod_positions=dict(self._positions), eod_cash=self._cash,
            gross_pnl=net_pnl, net_pnl=net_pnl, forced_close=False,
        )

        self._tracker.record(result, equity)
        self._save_state(date, result, equity)

        logger.info(
            "[%s] daily: equity=%.2f  pnl=%.2f  trades=%d",
            date.date(), equity, net_pnl, len(fills),
        )
        return result

    def run_day_intraday(
        self,
        run_id:         str,
        date:           pd.Timestamp,
        day_bars:       Dict[str, pd.DataFrame],
        target_wts:     Dict[str, float],
        vix:            float = 15.0,
        target_wts_fn:  Optional[Callable[[pd.Timestamp, Dict[str, float], float], Dict[str, float]]] = None,
        timing_provider: Optional[Callable[[pd.Timestamp, Dict[str, float], float], Dict[str, float]]] = None,
        resume_from_checkpoint: bool = True,
    ) -> DayResult:
        """Bar-by-bar intraday execution for paper (live or replay).

        Flow per bar:
          1. skip_bar_fn: if a fill already exists for this bar (same run_id),
             skip → idempotent re-run
          2. Generate orders at bar T close using current positions + cash
          3. Simulate fills at bar T+1 open
          4. Persist orders/fills/positions/equity for the bar via
             save_intraday_bar + checkpoint
          5. Update in-memory positions/cash/tracker

        Parameters
        ----------
        target_wts       : static target weights (used if no provider
                           passed). Daily MFS output goes here.
        target_wts_fn    : generic per-bar target callback (preexisting).
        timing_provider  : multi-TF timing layer closure (from
                           `core.intraday.multi_timescale.
                           make_timing_target_provider`). When provided,
                           it becomes the per-bar target function —
                           applies decide_timing() to the daily targets
                           at each bar. Mutually exclusive with
                           target_wts_fn (if both passed, timing_provider
                           wins and a warning is logged).

        Shared by live and replay; the ONLY difference is the bar source
        (today's partial day vs a historical day's bars).
        """
        if timing_provider is not None and target_wts_fn is not None:
            logger.warning(
                "run_day_intraday received both target_wts_fn and "
                "timing_provider; timing_provider takes precedence."
            )
        effective_target_fn = timing_provider or target_wts_fn
        if not day_bars:
            return DayResult(date=date, trades=[], eod_positions=dict(self._positions),
                             eod_cash=self._cash, gross_pnl=0.0, net_pnl=0.0,
                             forced_close=False)

        cp_last_bar_ts: Optional[pd.Timestamp] = None
        # Short-circuit key: do ALL symbols' bars end at or before the
        # checkpoint's last_bar_ts? Checking only the reference symbol's
        # last bar broke if day_bars grew across calls (e.g. new bar
        # arrives between live re-runs) or if the reference symbol
        # changed due to dict-iteration order. Using max() across all
        # symbols is stable.
        day_last_bar_ts = max(
            df.index[-1] for df in day_bars.values() if len(df) > 0
        )
        if resume_from_checkpoint:
            cp = self.load_bar_checkpoint(run_id)
            if cp is not None:
                # Round 3 (Topic C, 2026-04-20): always restore
                # stale_counts when the checkpoint exists, regardless
                # of date. Rationale: stale_counts is a cumulative
                # counter for "consecutive halt bars" that spans days.
                # If the previous process died on day N with a 3-day
                # halt counter for sym X, day N+1's fresh engine
                # must keep that counter, otherwise a halted symbol
                # gets its stale counter reset every day on resume
                # and ghost cleanup never fires.
                persisted_stale = cp.get("stale_counts") or {}
                if persisted_stale:
                    self._intraday_stale_counts = {
                        s: int(n) for s, n in persisted_stale.items()
                    }
                    logger.info(
                        "[%s] restored stale_counts from checkpoint: %s",
                        date.date(), self._intraday_stale_counts,
                    )
            if cp is not None and cp["date"] == date:
                self._positions = {s: float(q) for s, q in cp["positions"].items()}
                self._cash = float(cp["cash"])
                cp_last_bar_ts = cp["last_bar_ts"]
                logger.info(
                    "[%s] resumed run_id=%s from bar_ts=%s (cash=%.2f, %d positions)",
                    date.date(), run_id, cp_last_bar_ts, self._cash,
                    len(self._positions),
                )
                # Short-circuit only when EVERY symbol's last bar is
                # already at or before the checkpoint — guarantees there
                # is no new bar to process regardless of which symbol we
                # pick as reference. If any symbol has new bars past
                # cp_last_bar_ts, we resume normally and process them.
                all_bars_covered = all(
                    df.index[-1] <= cp_last_bar_ts
                    for df in day_bars.values() if len(df) > 0
                )
                if all_bars_covered and cp_last_bar_ts >= day_last_bar_ts:
                    logger.info(
                        "[%s] day already fully processed; skipping",
                        date.date(),
                    )
                    return DayResult(
                        date=date, trades=[],
                        eod_positions=dict(self._positions),
                        eod_cash=self._cash,
                        gross_pnl=0.0, net_pnl=0.0, forced_close=False,
                    )

        def _skip(bar_ts: pd.Timestamp) -> bool:
            # Skip bars already processed — either seen by checkpoint or
            # have persisted fills.
            if cp_last_bar_ts is not None and bar_ts <= cp_last_bar_ts:
                return True
            return self.has_fill_for_bar(run_id, bar_ts)

        # Track fills emitted through the per-bar hook so any remaining
        # fills (e.g. EOD force-close, which happens OUTSIDE the per-bar
        # loop in run_multi_day) can be persisted separately below.
        bar_fill_ids: set[int] = set()

        def _on_bar(upd: BarUpdate) -> None:
            # Update in-memory state from the runtime's per-bar snapshot.
            self._positions = dict(upd.positions)
            self._cash = upd.cash
            for f in upd.fills:
                bar_fill_ids.add(id(f))
            self.save_intraday_bar(
                run_id=run_id, date=upd.date, bar_ts=upd.bar_ts,
                orders=upd.orders, fills=upd.fills,
                positions=upd.positions, cash=upd.cash, equity=upd.equity,
            )
            self.save_bar_checkpoint(
                run_id=run_id, date=upd.date, bar_ts=upd.bar_ts,
                positions=upd.positions, cash=upd.cash,
            )

        result = self._engine.run_multi_day(
            date=date, day_bars=day_bars,
            target_wts=target_wts,
            positions=self._positions.copy(),
            cash=self._cash,
            vix=vix,
            target_wts_fn=effective_target_fn,
            on_bar_complete=_on_bar,
            skip_bar_fn=_skip,
            stale_counts=self._intraday_stale_counts,
        )

        self._positions = result.eod_positions
        self._cash = result.eod_cash

        # Day-level equity record (for pnl_tracker + pt_history)
        port_val = 0.0
        for sym, qty in self._positions.items():
            if sym in day_bars and len(day_bars[sym]) > 0:
                port_val += qty * float(day_bars[sym]["close"].iloc[-1])
        equity = self._cash + port_val

        # Persist any fills not emitted by the per-bar hook (i.e. EOD
        # force-close fills that happen after the bar loop in
        # run_multi_day). Bucket them onto the last bar timestamp and
        # guard with has_fill_for_bar to keep re-runs idempotent.
        residual_fills = [f for f in result.trades if id(f) not in bar_fill_ids]
        if residual_fills:
            ref_sym = next(iter(day_bars))
            last_bar_ts = day_bars[ref_sym].index[-1]
            if not self.has_fill_for_bar(run_id, last_bar_ts):
                self.save_intraday_bar(
                    run_id=run_id, date=date, bar_ts=last_bar_ts,
                    orders=[], fills=residual_fills,
                    positions=self._positions, cash=self._cash, equity=equity,
                    is_eod=True,  # P1.8: flag EOD residuals for attribution
                )
                # Final checkpoint reflects post-EOD state so a re-run
                # doesn't re-trigger EOD force-close.
                self.save_bar_checkpoint(
                    run_id=run_id, date=date, bar_ts=last_bar_ts,
                    positions=self._positions, cash=self._cash,
                )
        self._tracker.record(result, equity)
        self._save_state(date, result, equity)

        logger.info(
            "[%s] intraday: equity=%.2f  pnl=%.2f  trades=%d",
            date.date(), equity, result.net_pnl, result.n_trades,
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

    @property
    def kill_switch(self) -> KillSwitch:
        return self._kill_switch

    def get_equity_curve(self) -> pd.Series:
        """Return equity curve from PnLTracker."""
        return self._tracker.equity_series

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
        # Intraday bar-level persistence tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS intraday_orders (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id       TEXT    NOT NULL,
                date         TEXT    NOT NULL,
                bar_ts       TEXT    NOT NULL,
                symbol       TEXT    NOT NULL,
                side         TEXT    NOT NULL,
                qty          REAL    NOT NULL,
                signal_source TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS intraday_fills (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id       TEXT    NOT NULL,
                date         TEXT    NOT NULL,
                bar_ts       TEXT    NOT NULL,
                symbol       TEXT    NOT NULL,
                side         TEXT    NOT NULL,
                qty          REAL    NOT NULL,
                price        REAL    NOT NULL,
                slippage_usd REAL    NOT NULL DEFAULT 0,
                commission_usd REAL  NOT NULL DEFAULT 0,
                cash_delta   REAL    NOT NULL,
                is_eod       INTEGER NOT NULL DEFAULT 0
            )
        """)
        # P1.8 (2026-04-20): migration for DBs created before is_eod
        # column existed. ALTER will no-op when the column already
        # exists; failure silenced because older SQLite reports an
        # error we treat as "already migrated."
        try:
            conn.execute(
                "ALTER TABLE intraday_fills ADD COLUMN is_eod INTEGER "
                "NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # column exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS intraday_positions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id       TEXT    NOT NULL,
                date         TEXT    NOT NULL,
                bar_ts       TEXT    NOT NULL,
                symbol       TEXT    NOT NULL,
                qty          REAL    NOT NULL,
                avg_cost     REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS intraday_equity (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id       TEXT    NOT NULL,
                date         TEXT    NOT NULL,
                bar_ts       TEXT    NOT NULL,
                equity       REAL    NOT NULL,
                cash         REAL    NOT NULL,
                portfolio_value REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bar_checkpoints (
                run_id       TEXT    PRIMARY KEY,
                date         TEXT    NOT NULL,
                last_bar_ts  TEXT    NOT NULL,
                state_json   TEXT    NOT NULL,
                updated_at   TEXT    NOT NULL
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

    # ── Intraday persistence ─────────────────────────────────────────────────

    def save_intraday_bar(
        self,
        run_id:    str,
        date:      pd.Timestamp,
        bar_ts:    pd.Timestamp,
        orders:    List[Order],
        fills:     List[Fill],
        positions: Dict[str, float],
        cash:      float,
        equity:    float,
        is_eod:    bool = False,
    ) -> None:
        """Persist one bar's orders, fills, positions, and equity snapshot.

        is_eod (P1.8, 2026-04-20): when True, fills for this call are
        flagged as EOD residual (force-close). Downstream attribution
        can filter these out so "bar N fills" aren't conflated with
        end-of-day flatten trades parked on the last bar_ts.
        """
        conn = sqlite3.connect(self._db_path)
        date_str = str(date.date())
        bar_str = str(bar_ts)
        is_eod_int = 1 if is_eod else 0

        for o in orders:
            conn.execute(
                "INSERT INTO intraday_orders (run_id, date, bar_ts, symbol, side, qty, signal_source) "
                "VALUES (?,?,?,?,?,?,?)",
                (run_id, date_str, bar_str, o.symbol, o.side.value if hasattr(o.side, 'value') else str(o.side),
                 o.qty_shares, None),
            )

        for f in fills:
            conn.execute(
                "INSERT INTO intraday_fills (run_id, date, bar_ts, symbol, side, qty, price, "
                "slippage_usd, commission_usd, cash_delta, is_eod) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, date_str, bar_str, f.order.symbol,
                 f.order.side.value if hasattr(f.order.side, 'value') else str(f.order.side),
                 f.executed_qty, f.executed_price,
                 f.cost_breakdown.slippage_usd, f.cost_breakdown.commission_usd, f.cash_delta,
                 is_eod_int),
            )

        for sym, qty in positions.items():
            if qty > 1e-6:
                conn.execute(
                    "INSERT INTO intraday_positions (run_id, date, bar_ts, symbol, qty, avg_cost) "
                    "VALUES (?,?,?,?,?,?)",
                    (run_id, date_str, bar_str, sym, qty, None),
                )

        port_val = equity - cash
        conn.execute(
            "INSERT INTO intraday_equity (run_id, date, bar_ts, equity, cash, portfolio_value) "
            "VALUES (?,?,?,?,?,?)",
            (run_id, date_str, bar_str, equity, cash, port_val),
        )

        conn.commit()
        conn.close()

    def save_bar_checkpoint(
        self,
        run_id:   str,
        date:     pd.Timestamp,
        bar_ts:   pd.Timestamp,
        positions: Dict[str, float],
        cash:     float,
    ) -> None:
        """Save checkpoint for restart recovery.

        Round 3 (Topic C, 2026-04-20): state_json now also includes
        `stale_counts` = self._intraday_stale_counts so that
        multi-day halt counters survive process restarts. Without
        this, a halted-for-3-days symbol resets counter to 0 each
        day on resume and never triggers ghost cleanup.
        """
        state = json.dumps({
            "positions":    positions,
            "cash":         cash,
            "stale_counts": dict(self._intraday_stale_counts),
        })
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT OR REPLACE INTO bar_checkpoints (run_id, date, last_bar_ts, state_json, updated_at) "
            "VALUES (?,?,?,?,?)",
            (run_id, str(date.date()), str(bar_ts), state, str(pd.Timestamp.now())),
        )
        conn.commit()
        conn.close()

    def load_bar_checkpoint(self, run_id: str) -> Optional[Dict]:
        """Load latest checkpoint for a run_id. Returns None if not found.

        Return dict now includes `stale_counts` (default {}) for
        back-compat with older checkpoints that pre-date Round 3's
        stale-count persistence.
        """
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT date, last_bar_ts, state_json FROM bar_checkpoints WHERE run_id=?",
            (run_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        state = json.loads(row[2])
        return {
            "date":         pd.Timestamp(row[0]),
            "last_bar_ts":  pd.Timestamp(row[1]),
            "positions":    state["positions"],
            "cash":         state["cash"],
            "stale_counts": state.get("stale_counts", {}),
        }

    def has_fill_for_bar(self, run_id: str, bar_ts: pd.Timestamp) -> bool:
        """Check if fills already exist for this bar (idempotency guard)."""
        conn = sqlite3.connect(self._db_path)
        n = conn.execute(
            "SELECT COUNT(*) FROM intraday_fills WHERE run_id=? AND bar_ts=?",
            (run_id, str(bar_ts)),
        ).fetchone()[0]
        conn.close()
        return n > 0
