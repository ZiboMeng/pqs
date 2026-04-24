"""Unit tests for PaperTradingEngine."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd
import pytest

from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.cost_model import CostModel
from core.backtest.intraday_engine import DayResult
from core.paper_trading.pnl_tracker import PnLTracker
from core.paper_trading.paper_trading_engine import PaperTradingEngine


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _make_cost_model() -> CostModel:
    cfg = CostModelConfig(
        tiers={
            "default": CostTierConfig(
                symbols=[],
                commission_bps=0.5,
                slippage_interday_bps=3.0,
                slippage_intraday_bps=5.0,
            )
        }
    )
    return CostModel(cfg)


_BAR_OFFSETS: List[pd.Timedelta] = [
    pd.Timedelta(hours=9,  minutes=30),
    pd.Timedelta(hours=10, minutes=30),
    pd.Timedelta(hours=11, minutes=30),
    pd.Timedelta(hours=12, minutes=30),
    pd.Timedelta(hours=13, minutes=30),
    pd.Timedelta(hours=14, minutes=30),
    pd.Timedelta(hours=15, minutes=30),
]


def _make_intraday_df(
    n_days:   int   = 1,
    start:    str   = "2024-01-02",
    price:    float = 400.0,
) -> pd.DataFrame:
    """生成 n_days 天的合成 60m OHLCV 数据。"""
    idx:    List[pd.Timestamp] = []
    prices: List[float]        = []
    d = pd.Timestamp(start)
    day_count = 0
    while day_count < n_days:
        if d.weekday() < 5:
            for offset in _BAR_OFFSETS:
                idx.append(d + offset)
                prices.append(price)
            day_count += 1
        d += pd.Timedelta(days=1)
    n = len(idx)
    return pd.DataFrame(
        {
            "open":   prices,
            "high":   [p * 1.001 for p in prices],
            "low":    [p * 0.999 for p in prices],
            "close":  prices,
            "volume": [1_000_000] * n,
        },
        index=pd.DatetimeIndex(idx),
    )


def _make_signals_df(intraday_df: pd.DataFrame, sym: str = "SPY",
                     weight: float = 0.95) -> pd.DataFrame:
    return pd.DataFrame({sym: weight}, index=intraday_df.index)


def _make_engine(
    tmp_path: Path,
    initial_capital:    float = 100_000.0,
    eod_force_close:    bool  = True,
    confluence_enabled: bool  = True,
) -> PaperTradingEngine:
    return PaperTradingEngine(
        cost_model          = _make_cost_model(),
        pnl_tracker         = PnLTracker(initial_capital),
        db_path             = tmp_path / "paper_trading.db",
        initial_capital     = initial_capital,
        eod_force_close     = eod_force_close,
        confluence_enabled  = confluence_enabled,
    )


# ── 初始状态 ──────────────────────────────────────────────────────────────────

class TestInitialState:
    def test_positions_empty(self, tmp_path):
        engine = _make_engine(tmp_path)
        assert engine.get_positions() == {}

    def test_cash_equals_initial_capital(self, tmp_path):
        engine = _make_engine(tmp_path, initial_capital=200_000.0)
        assert engine.get_cash() == pytest.approx(200_000.0)

    def test_equity_equals_initial_capital(self, tmp_path):
        engine = _make_engine(tmp_path, initial_capital=100_000.0)
        assert engine.get_equity() == pytest.approx(100_000.0)


# ── run_day ───────────────────────────────────────────────────────────────────

class TestRunDay:
    def test_returns_day_result(self, tmp_path):
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars)
        result = engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        assert isinstance(result, DayResult)

    def test_pnl_tracker_updated(self, tmp_path):
        """run_day 后，PnLTracker 应有 1 条记录。"""
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        assert len(engine._tracker.equity_curve) == 1

    def test_cash_changes_after_trades(self, tmp_path):
        """有非零信号时，run_day 后现金账户有变化（买入消耗现金，EOD卖出归还）。"""
        engine = _make_engine(tmp_path, initial_capital=100_000.0)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars, weight=0.95)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        # EOD 强制清仓后现金应接近初始资金（扣去成本后略少）
        assert engine.get_cash() < 100_000.0 + 1.0   # 不超过初始 + 浮动

    def test_eod_positions_empty_after_forced_close(self, tmp_path):
        """eod_force_close=True → run_day 后持仓应为空。"""
        engine = _make_engine(tmp_path, eod_force_close=True)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars, weight=0.95)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        remaining = sum(engine.get_positions().values())
        assert remaining == pytest.approx(0.0, abs=1e-4)

    def test_zero_signals_equity_near_capital(self, tmp_path):
        """全零信号 → 权益接近初始资金。"""
        engine = _make_engine(tmp_path, initial_capital=100_000.0)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars, weight=0.0)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        assert abs(engine.get_equity() - 100_000.0) < 1.0

    def test_multiple_days_tracked(self, tmp_path):
        """连续运行 3 天 → PnLTracker 有 3 条记录。"""
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df(n_days=3)
        dates  = sorted(set(bars.index.date))
        for d in dates:
            d_ts   = pd.Timestamp(d)
            mask   = bars.index.date == d
            d_bars = bars.loc[mask]
            d_sigs = _make_signals_df(d_bars, weight=0.95)
            engine.run_day(d_ts, d_bars, d_sigs)
        assert len(engine._tracker.equity_curve) == 3


# ── SQLite 持久化 ─────────────────────────────────────────────────────────────

class TestPersistence:
    def test_state_saved_to_db(self, tmp_path):
        """run_day 后，SQLite 中应有 pt_history 记录。"""
        import sqlite3
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)

        db_path = tmp_path / "paper_trading.db"
        conn    = sqlite3.connect(db_path)
        count   = conn.execute("SELECT COUNT(*) FROM pt_history").fetchone()[0]
        conn.close()
        assert count == 1

    def test_cash_restored_after_restart(self, tmp_path):
        """
        运行一天后创建新引擎（同 DB 路径）→ 现金应与旧引擎一致。
        """
        engine1 = _make_engine(tmp_path)
        bars    = _make_intraday_df()
        sigs    = _make_signals_df(bars)
        engine1.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        cash_after = engine1.get_cash()

        # 重新加载
        engine2 = PaperTradingEngine(
            cost_model       = _make_cost_model(),
            pnl_tracker      = PnLTracker(100_000.0),
            db_path          = tmp_path / "paper_trading.db",
            initial_capital  = 100_000.0,
        )
        assert engine2.get_cash() == pytest.approx(cash_after, rel=1e-6)

    def test_history_restored_after_restart(self, tmp_path):
        """重启后，PnLTracker 应从 DB 恢复历史记录。"""
        engine1 = _make_engine(tmp_path)
        bars    = _make_intraday_df()
        sigs    = _make_signals_df(bars)
        engine1.run_day(pd.Timestamp("2024-01-02"), bars, sigs)

        engine2 = PaperTradingEngine(
            cost_model       = _make_cost_model(),
            pnl_tracker      = PnLTracker(100_000.0),
            db_path          = tmp_path / "paper_trading.db",
            initial_capital  = 100_000.0,
        )
        assert len(engine2._tracker.equity_curve) == 1

    def test_load_history_returns_dataframe(self, tmp_path):
        """load_history() 应返回 DataFrame，行数等于运行天数。"""
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df(n_days=2)
        dates  = sorted(set(bars.index.date))
        for d in dates:
            d_ts   = pd.Timestamp(d)
            mask   = bars.index.date == d
            d_bars = bars.loc[mask]
            d_sigs = _make_signals_df(d_bars)
            engine.run_day(d_ts, d_bars, d_sigs)
        hist = engine.load_history()
        assert isinstance(hist, pd.DataFrame)
        assert len(hist) == 2


# ── reset ────────────────────────────────────────────────────────────────────

class TestReset:
    def test_reset_clears_positions(self, tmp_path):
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        engine.reset()
        assert engine.get_positions() == {}

    def test_reset_restores_capital(self, tmp_path):
        engine = _make_engine(tmp_path, initial_capital=100_000.0)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        engine.reset()
        assert engine.get_cash() == pytest.approx(100_000.0)

    def test_reset_clears_tracker(self, tmp_path):
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        engine.reset()
        assert engine._tracker.equity_curve.empty

    def test_reset_clears_db(self, tmp_path):
        import sqlite3
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        engine.reset()

        db_path = tmp_path / "paper_trading.db"
        conn    = sqlite3.connect(db_path)
        count   = conn.execute("SELECT COUNT(*) FROM pt_history").fetchone()[0]
        conn.close()
        assert count == 0


# ── EOD 对账 ──────────────────────────────────────────────────────────────────

class TestReconcile:
    def test_returns_dict_with_expected_keys(self, tmp_path):
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars)
        result = engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        rec    = engine.reconcile(pd.Timestamp("2024-01-02"), result)
        for key in ["ok", "warnings", "n_trades", "equity", "drawdown", "date"]:
            assert key in rec, f"缺少 key: {key}"

    def test_ok_true_for_normal_day(self, tmp_path):
        """正常交易日（无大回撤、无异常 P&L）→ ok=True。"""
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars, weight=0.0)   # 零信号，P&L ≈ 0
        result = engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        rec    = engine.reconcile(pd.Timestamp("2024-01-02"), result)
        assert rec["ok"] is True

    def test_warns_on_residual_positions_after_forced_close(self, tmp_path):
        """forced_close=True 但有残余持仓 → 应产生警告。"""
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars, weight=0.0)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)   # 初始化 tracker

        fake_result = DayResult(
            date=pd.Timestamp("2024-01-02"),
            trades=[], eod_positions={"SPY": 50.0},   # 残余持仓！
            eod_cash=99_000.0, gross_pnl=0.0, net_pnl=0.0, forced_close=True,
        )
        rec = engine.reconcile(pd.Timestamp("2024-01-02"), fake_result)
        assert rec["ok"] is False
        assert len(rec["warnings"]) > 0

    def test_warns_on_large_pnl(self, tmp_path):
        """单日 P&L 超过权益 5% → 产生警告。"""
        engine = _make_engine(tmp_path, initial_capital=100_000.0)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars, weight=0.0)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)

        # 构造一个 P&L = 10000（= 10% 的权益）的假结果
        big_pnl_result = DayResult(
            date=pd.Timestamp("2024-01-02"),
            trades=[], eod_positions={}, eod_cash=100_000.0,
            gross_pnl=10_000.0, net_pnl=10_000.0, forced_close=True,
        )
        rec = engine.reconcile(pd.Timestamp("2024-01-02"), big_pnl_result)
        assert rec["ok"] is False
        assert any("P&L" in w for w in rec["warnings"])

    def test_warnings_is_list(self, tmp_path):
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars)
        result = engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        rec    = engine.reconcile(pd.Timestamp("2024-01-02"), result)
        assert isinstance(rec["warnings"], list)


# ── Kill Switch ───────────────────────────────────────────────────────────────

class TestKillSwitch:
    def test_not_triggered_normally(self, tmp_path):
        """正常交易（无大回撤）→ kill switch 不触发。"""
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars, weight=0.0)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        assert engine.is_kill_switch_triggered is False

    def test_triggered_by_large_drawdown(self, tmp_path):
        """运行时注入 > 20% 回撤 → kill switch 应触发。"""
        engine = _make_engine(tmp_path, initial_capital=100_000.0)
        # 手动注入 tracker 记录：峰值 100k → 当前 75k（-25% 回撤）
        from core.backtest.intraday_engine import DayResult
        engine._tracker.record(
            DayResult(date=pd.Timestamp("2024-01-02"), trades=[],
                      eod_positions={}, eod_cash=100_000.0,
                      gross_pnl=0.0, net_pnl=0.0, forced_close=True),
            equity=100_000.0,
        )
        engine._tracker.record(
            DayResult(date=pd.Timestamp("2024-01-03"), trades=[],
                      eod_positions={}, eod_cash=75_000.0,
                      gross_pnl=-25_000.0, net_pnl=-25_000.0, forced_close=True),
            equity=75_000.0,
        )
        assert engine.is_kill_switch_triggered is True

    def test_triggered_by_loss_streak(self, tmp_path):
        """连续 5 日亏损 → kill switch 应触发（需 6 条记录才能产生 5 个日收益率）。"""
        engine = _make_engine(tmp_path, initial_capital=100_000.0)
        eq    = 100_000.0
        dates = pd.bdate_range("2024-01-02", periods=6)
        for d in dates:
            eq -= 100.0   # 每天微亏
            engine._tracker.record(
                DayResult(date=d, trades=[], eod_positions={},
                          eod_cash=eq, gross_pnl=-100.0, net_pnl=-100.0,
                          forced_close=True),
                equity=eq,
            )
        assert engine.is_kill_switch_triggered is True

    def test_not_triggered_by_single_loss(self, tmp_path):
        """单日亏损不触发 kill switch。"""
        engine = _make_engine(tmp_path, initial_capital=100_000.0)
        engine._tracker.record(
            DayResult(date=pd.Timestamp("2024-01-02"), trades=[],
                      eod_positions={}, eod_cash=99_000.0,
                      gross_pnl=-1000.0, net_pnl=-1000.0, forced_close=True),
            equity=99_000.0,
        )
        assert engine.is_kill_switch_triggered is False


# ── get_pnl_summary ───────────────────────────────────────────────────────────

class TestGetPnlSummary:
    def test_returns_dict(self, tmp_path):
        engine = _make_engine(tmp_path)
        assert isinstance(engine.get_pnl_summary(), dict)

    def test_summary_updated_after_run(self, tmp_path):
        engine = _make_engine(tmp_path)
        bars   = _make_intraday_df()
        sigs   = _make_signals_df(bars)
        engine.run_day(pd.Timestamp("2024-01-02"), bars, sigs)
        summary = engine.get_pnl_summary()
        assert summary["n_days"] == 1
