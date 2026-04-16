"""Unit tests for IntradayBacktestEngine, DayResult, and _apply_confluence."""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd
import pytest

from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.cost_model import CostModel
from core.execution.execution_simulator import OrderSide
from core.backtest.backtest_engine import BacktestResult
from core.backtest.intraday_engine import (
    IntradayBacktestEngine,
    DayResult,
    _apply_confluence,
)


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


# 每天 7 根 60m K 线：9:30, 10:30, ..., 15:30
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
    n_days:     int   = 3,
    start:      str   = "2024-01-02",
    price:      float = 400.0,
    price_up:   bool  = False,
) -> pd.DataFrame:
    """生成合成日内 OHLCV DataFrame，7 bars/天，9:30–15:30（ET tz-naive）。"""
    idx:    List[pd.Timestamp] = []
    prices: List[float]        = []

    d = pd.Timestamp(start)
    day_count = 0
    while day_count < n_days:
        if d.weekday() < 5:   # Mon–Fri
            for offset in _BAR_OFFSETS:
                idx.append(d + offset)
                p = price * (1.0 + 0.001 * len(idx)) if price_up else price
                prices.append(p)
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


def _make_signals_df(
    intraday_df: pd.DataFrame,
    sym:         str   = "SPY",
    weight:      float = 0.95,
) -> pd.DataFrame:
    """生成单品种等权重信号 DataFrame。"""
    return pd.DataFrame({sym: weight}, index=intraday_df.index)


def _make_confluence_df(
    intraday_df: pd.DataFrame,
    sym:         str   = "SPY",
    score:       float = 1.0,
) -> pd.DataFrame:
    """生成单品种 confluence 评分 DataFrame。"""
    return pd.DataFrame({sym: score}, index=intraday_df.index)


def _make_engine(
    initial_capital:    float = 100_000.0,
    eod_force_close:    bool  = True,
    confluence_enabled: bool  = True,
) -> IntradayBacktestEngine:
    return IntradayBacktestEngine(
        cost_model          = _make_cost_model(),
        initial_capital     = initial_capital,
        eod_force_close     = eod_force_close,
        confluence_enabled  = confluence_enabled,
    )


# ── DayResult 数据类 ──────────────────────────────────────────────────────────

class TestDayResult:
    def test_n_trades_empty(self):
        res = DayResult(
            date=pd.Timestamp("2024-01-02"), trades=[],
            eod_positions={}, eod_cash=100_000.0,
            gross_pnl=0.0, net_pnl=0.0, forced_close=False,
        )
        assert res.n_trades == 0

    def test_n_trades_equals_len_trades(self):
        """n_trades 属性始终等于 len(trades)。"""
        from core.execution.execution_simulator import Fill, Order, OrderSide
        from core.execution.cost_model import CostBreakdown

        def _dummy_fill(sym: str) -> Fill:
            bd = CostBreakdown(
                symbol="SPY", notional_usd=1000.0,
                commission_usd=0.5, slippage_usd=1.5,
                total_cost_usd=2.0, total_bps=2.0,
            )
            return Fill(
                order=Order(symbol=sym, side=OrderSide.BUY,
                            qty_shares=1.0, signal_date=pd.Timestamp("2024-01-02")),
                executed_price=400.0, executed_qty=1.0,
                cost_breakdown=bd, fill_date=pd.Timestamp("2024-01-03"),
                cash_delta=-402.0,
            )

        trades = [_dummy_fill("SPY"), _dummy_fill("QQQ")]
        res = DayResult(
            date=pd.Timestamp("2024-01-02"), trades=trades,
            eod_positions={}, eod_cash=99_000.0,
            gross_pnl=200.0, net_pnl=198.0, forced_close=True,
        )
        assert res.n_trades == 2

    def test_forced_close_bool(self):
        res = DayResult(
            date=pd.Timestamp("2024-01-02"), trades=[],
            eod_positions={}, eod_cash=100_000.0,
            gross_pnl=0.0, net_pnl=0.0, forced_close=True,
        )
        assert res.forced_close is True

    def test_total_cost_zero_no_trades(self):
        res = DayResult(
            date=pd.Timestamp("2024-01-02"), trades=[],
            eod_positions={}, eod_cash=100_000.0,
            gross_pnl=0.0, net_pnl=0.0, forced_close=False,
        )
        assert res.total_cost == pytest.approx(0.0)


# ── _apply_confluence ─────────────────────────────────────────────────────────

class TestApplyConfluence:
    """针对模块级工具函数 _apply_confluence 的单元测试。"""

    @staticmethod
    def _sig(w: float, sym: str = "SPY") -> pd.Series:
        return pd.Series({sym: w})

    def test_none_sig_returns_empty(self):
        assert _apply_confluence(None, None, True) == {}

    def test_enabled_false_ignores_score(self):
        """confluence_enabled=False → 低分也不过滤，权重原样返回。"""
        sig  = self._sig(0.9)
        conf = pd.Series({"SPY": 0.0})   # 极低 score
        res  = _apply_confluence(sig, conf, enabled=False)
        assert "SPY" in res
        assert res["SPY"] == pytest.approx(0.9)

    def test_score_below_threshold_blocks_trade(self):
        """score < 0.60 → 不入场（权重置 0，symbol 从结果中排除）。"""
        sig  = self._sig(0.9)
        conf = pd.Series({"SPY": 0.55})
        res  = _apply_confluence(sig, conf, enabled=True)
        assert res.get("SPY", 0.0) == pytest.approx(0.0)

    def test_score_in_half_range_halves_weight(self):
        """0.60 ≤ score < 0.80 → 权重 × 0.5。"""
        sig  = self._sig(0.8)
        conf = pd.Series({"SPY": 0.70})
        res  = _apply_confluence(sig, conf, enabled=True)
        assert res["SPY"] == pytest.approx(0.4, rel=1e-6)

    def test_score_at_lower_boundary_is_half_size(self):
        """score == 0.60 属于半仓区间（不被阻止）。"""
        sig  = self._sig(0.8)
        conf = pd.Series({"SPY": 0.60})
        res  = _apply_confluence(sig, conf, enabled=True)
        assert "SPY" in res
        assert res["SPY"] == pytest.approx(0.4)

    def test_score_full_size_unchanged(self):
        """score ≥ 0.80 → 权重不变。"""
        sig  = self._sig(0.9)
        conf = pd.Series({"SPY": 0.85})
        res  = _apply_confluence(sig, conf, enabled=True)
        assert res["SPY"] == pytest.approx(0.9)

    def test_none_conf_row_passes_through(self):
        """conf_row=None → 视同 score=1.0，全仓。"""
        sig = self._sig(0.9)
        res = _apply_confluence(sig, None, enabled=True)
        assert res["SPY"] == pytest.approx(0.9)

    def test_zero_weight_excluded(self):
        """原始 weight=0 的 symbol 不出现在结果中。"""
        sig = pd.Series({"SPY": 0.0, "QQQ": 0.5})
        res = _apply_confluence(sig, None, enabled=False)
        assert "SPY" not in res
        assert "QQQ" in res

    def test_multi_symbol_independent_filtering(self):
        """多品种时，每个 symbol 独立过滤。"""
        sig  = pd.Series({"SPY": 0.5, "QQQ": 0.5})
        conf = pd.Series({"SPY": 0.3, "QQQ": 0.9})   # SPY blocked, QQQ full
        res  = _apply_confluence(sig, conf, enabled=True)
        assert res.get("SPY", 0.0) == pytest.approx(0.0)
        assert res["QQQ"] == pytest.approx(0.5)


# ── run_single_day ────────────────────────────────────────────────────────────

class TestRunSingleDay:
    def test_returns_day_result(self):
        bars = _make_intraday_df(n_days=1)
        sigs = _make_signals_df(bars)
        engine = _make_engine()
        res = engine.run_single_day(
            date      = pd.Timestamp("2024-01-02"),
            day_bars  = bars,
            day_sigs  = sigs,
            day_conf  = None,
            positions = {},
            cash      = 100_000.0,
        )
        assert isinstance(res, DayResult)

    def test_empty_bars_returns_early(self):
        engine = _make_engine()
        res = engine.run_single_day(
            date=pd.Timestamp("2024-01-02"),
            day_bars=pd.DataFrame(), day_sigs=pd.DataFrame(),
            day_conf=None, positions={}, cash=100_000.0,
        )
        assert res.n_trades == 0
        assert res.eod_cash == pytest.approx(100_000.0)
        assert res.forced_close is False

    def test_eod_forced_close_clears_positions(self):
        """eod_force_close=True + 最后 K 线为 15:30 → 持仓清零。"""
        bars   = _make_intraday_df(n_days=1)
        sigs   = _make_signals_df(bars, weight=0.95)
        engine = _make_engine(eod_force_close=True)
        res = engine.run_single_day(
            date=pd.Timestamp("2024-01-02"),
            day_bars=bars, day_sigs=sigs, day_conf=None,
            positions={}, cash=100_000.0,
        )
        assert res.forced_close is True
        # EOD 强制平仓后，剩余持仓应为空（或全部为 0）
        remaining = sum(v for v in res.eod_positions.values())
        assert remaining == pytest.approx(0.0, abs=1e-4)

    def test_eod_close_disabled_preserves_positions(self):
        """eod_force_close=False → 不强制平仓，forced_close=False。"""
        bars   = _make_intraday_df(n_days=1)
        sigs   = _make_signals_df(bars, weight=0.95)
        engine = _make_engine(eod_force_close=False)
        res = engine.run_single_day(
            date=pd.Timestamp("2024-01-02"),
            day_bars=bars, day_sigs=sigs, day_conf=None,
            positions={}, cash=100_000.0,
        )
        assert res.forced_close is False

    def test_zero_signals_no_buy_trades(self):
        """全零信号 → 不产生任何买入委托。"""
        bars   = _make_intraday_df(n_days=1)
        sigs   = _make_signals_df(bars, weight=0.0)
        engine = _make_engine()
        res = engine.run_single_day(
            date=pd.Timestamp("2024-01-02"),
            day_bars=bars, day_sigs=sigs, day_conf=None,
            positions={}, cash=100_000.0,
        )
        buys = [f for f in res.trades if f.side == OrderSide.BUY]
        assert len(buys) == 0

    def test_low_confluence_blocks_buys(self):
        """Confluence score < 0.60 → 没有买入成交。"""
        bars   = _make_intraday_df(n_days=1)
        sigs   = _make_signals_df(bars, weight=0.95)
        conf   = _make_confluence_df(bars, score=0.50)   # 低于阈值
        engine = _make_engine(confluence_enabled=True)
        res = engine.run_single_day(
            date=pd.Timestamp("2024-01-02"),
            day_bars=bars, day_sigs=sigs, day_conf=conf,
            positions={}, cash=100_000.0,
        )
        buys = [f for f in res.trades if f.side == OrderSide.BUY]
        assert len(buys) == 0

    def test_high_confluence_allows_buys(self):
        """Confluence score ≥ 0.80 → 产生至少一笔买入。"""
        bars   = _make_intraday_df(n_days=1)
        sigs   = _make_signals_df(bars, weight=0.95)
        conf   = _make_confluence_df(bars, score=0.90)
        engine = _make_engine(confluence_enabled=True)
        res = engine.run_single_day(
            date=pd.Timestamp("2024-01-02"),
            day_bars=bars, day_sigs=sigs, day_conf=conf,
            positions={}, cash=100_000.0,
        )
        buys = [f for f in res.trades if f.side == OrderSide.BUY]
        assert len(buys) > 0

    def test_cash_not_deeply_negative(self):
        """成交后现金账户不应大幅负值（允许小额浮动）。"""
        bars   = _make_intraday_df(n_days=1)
        sigs   = _make_signals_df(bars, weight=0.95)
        engine = _make_engine()
        res = engine.run_single_day(
            date=pd.Timestamp("2024-01-02"),
            day_bars=bars, day_sigs=sigs, day_conf=None,
            positions={}, cash=100_000.0,
        )
        assert res.eod_cash > -1_000.0

    def test_n_trades_equals_len_trades(self):
        """n_trades 属性 == len(trades)，始终成立。"""
        bars   = _make_intraday_df(n_days=1)
        sigs   = _make_signals_df(bars, weight=0.95)
        engine = _make_engine()
        res = engine.run_single_day(
            date=pd.Timestamp("2024-01-02"),
            day_bars=bars, day_sigs=sigs, day_conf=None,
            positions={}, cash=100_000.0,
        )
        assert res.n_trades == len(res.trades)

    def test_total_cost_non_negative(self):
        """所有成交的总成本 ≥ 0。"""
        bars   = _make_intraday_df(n_days=1)
        sigs   = _make_signals_df(bars, weight=0.95)
        engine = _make_engine()
        res = engine.run_single_day(
            date=pd.Timestamp("2024-01-02"),
            day_bars=bars, day_sigs=sigs, day_conf=None,
            positions={}, cash=100_000.0,
        )
        assert res.total_cost >= 0.0

    def test_date_preserved_in_result(self):
        """DayResult.date 应与输入 date 一致。"""
        bars   = _make_intraday_df(n_days=1)
        sigs   = _make_signals_df(bars, weight=0.95)
        engine = _make_engine()
        date   = pd.Timestamp("2024-01-02")
        res    = engine.run_single_day(
            date=date, day_bars=bars, day_sigs=sigs,
            day_conf=None, positions={}, cash=100_000.0,
        )
        assert res.date == date

    def test_confluence_disabled_ignores_low_score(self):
        """confluence_enabled=False → 即使 score=0，信号也正常成交。"""
        bars   = _make_intraday_df(n_days=1)
        sigs   = _make_signals_df(bars, weight=0.95)
        conf   = _make_confluence_df(bars, score=0.0)   # 极低 score
        engine = _make_engine(confluence_enabled=False)
        res = engine.run_single_day(
            date=pd.Timestamp("2024-01-02"),
            day_bars=bars, day_sigs=sigs, day_conf=conf,
            positions={}, cash=100_000.0,
        )
        buys = [f for f in res.trades if f.side == OrderSide.BUY]
        assert len(buys) > 0


# ── IntradayBacktestEngine.run ────────────────────────────────────────────────

class TestIntradayEngineRun:
    def test_returns_backtest_result(self):
        bars   = _make_intraday_df(n_days=3)
        sigs   = _make_signals_df(bars)
        engine = _make_engine()
        result = engine.run(bars, sigs)
        assert isinstance(result, BacktestResult)

    def test_equity_curve_length_equals_n_days(self):
        """权益曲线每个交易日一个数据点。"""
        n_days = 5
        bars   = _make_intraday_df(n_days=n_days)
        sigs   = _make_signals_df(bars)
        engine = _make_engine()
        result = engine.run(bars, sigs)
        assert len(result.equity_curve) == n_days

    def test_equity_curve_all_positive(self):
        bars   = _make_intraday_df(n_days=3)
        sigs   = _make_signals_df(bars)
        engine = _make_engine()
        result = engine.run(bars, sigs)
        assert (result.equity_curve > 0).all()

    def test_empty_intraday_df_returns_empty_result(self):
        engine = _make_engine()
        result = engine.run(pd.DataFrame(), pd.DataFrame())
        assert result.equity_curve.empty

    def test_empty_signals_returns_empty_result(self):
        bars   = _make_intraday_df(n_days=3)
        engine = _make_engine()
        result = engine.run(bars, pd.DataFrame())
        assert result.equity_curve.empty

    def test_zero_signals_equity_near_initial_capital(self):
        """全零信号（不持仓）→ 权益曲线应接近初始资金（现金不动）。"""
        bars   = _make_intraday_df(n_days=3)
        sigs   = _make_signals_df(bars, weight=0.0)
        engine = _make_engine(initial_capital=100_000.0)
        result = engine.run(bars, sigs)
        assert (result.equity_curve - 100_000.0).abs().max() < 1.0

    def test_trades_recorded_with_nonzero_signals(self):
        """有非零信号 → 应记录至少一笔成交。"""
        bars   = _make_intraday_df(n_days=3)
        sigs   = _make_signals_df(bars, weight=0.95)
        engine = _make_engine()
        result = engine.run(bars, sigs)
        assert len(result.trades) > 0

    def test_metrics_dict_returned(self):
        """result.metrics 应为 dict（可以为空，但必须是 dict）。"""
        bars   = _make_intraday_df(n_days=5)
        sigs   = _make_signals_df(bars)
        engine = _make_engine()
        result = engine.run(bars, sigs)
        assert isinstance(result.metrics, dict)

    def test_low_confluence_reduces_trades_vs_high(self):
        """低 confluence score → 成交笔数应 ≤ 高 score 的情况。"""
        bars    = _make_intraday_df(n_days=3)
        sigs    = _make_signals_df(bars, weight=0.95)
        conf_lo = _make_confluence_df(bars, score=0.50)   # 全部屏蔽
        conf_hi = _make_confluence_df(bars, score=0.90)   # 全部允许

        eng_lo = _make_engine(confluence_enabled=True)
        eng_hi = _make_engine(confluence_enabled=True)

        res_lo = eng_lo.run(bars, sigs, conf_lo)
        res_hi = eng_hi.run(bars, sigs, conf_hi)

        # 低 score 时买入更少（允许等于，因为 EOD sell 仍可能发生）
        buys_lo = sum(1 for f in res_lo.trades if f.side == OrderSide.BUY)
        buys_hi = sum(1 for f in res_hi.trades if f.side == OrderSide.BUY)
        assert buys_lo <= buys_hi

    def test_vix_series_accepted_without_error(self):
        """vix_series 正常传入时，不抛出异常。"""
        bars  = _make_intraday_df(n_days=3)
        sigs  = _make_signals_df(bars)
        dates = sorted(set(bars.index.date))
        vix   = pd.Series(
            25.0,
            index=pd.DatetimeIndex([pd.Timestamp(d) for d in dates]),
        )
        engine = _make_engine()
        result = engine.run(bars, sigs, vix_series=vix)
        assert isinstance(result, BacktestResult)

    def test_confluence_disabled_more_trades_than_blocked(self):
        """confluence_enabled=False → 买入数 ≥ 被 score 屏蔽时。"""
        bars    = _make_intraday_df(n_days=3)
        sigs    = _make_signals_df(bars, weight=0.95)
        conf    = _make_confluence_df(bars, score=0.0)   # 若启用则全屏蔽

        eng_on  = _make_engine(confluence_enabled=True)
        eng_off = _make_engine(confluence_enabled=False)

        res_on  = eng_on.run(bars, sigs, conf)
        res_off = eng_off.run(bars, sigs, conf)

        buys_on  = sum(1 for f in res_on.trades  if f.side == OrderSide.BUY)
        buys_off = sum(1 for f in res_off.trades if f.side == OrderSide.BUY)
        assert buys_off >= buys_on

    def test_rising_price_equity_positive(self):
        """价格单调上涨 + 满仓信号 → 权益全程正值。"""
        bars   = _make_intraday_df(n_days=10, price_up=True)
        sigs   = _make_signals_df(bars, weight=0.95)
        engine = _make_engine(initial_capital=100_000.0)
        result = engine.run(bars, sigs)
        assert not result.equity_curve.empty
        assert (result.equity_curve > 0).all()

    def test_equity_index_is_datetime(self):
        """equity_curve.index 应为 DatetimeIndex。"""
        bars   = _make_intraday_df(n_days=3)
        sigs   = _make_signals_df(bars)
        engine = _make_engine()
        result = engine.run(bars, sigs)
        assert isinstance(result.equity_curve.index, pd.DatetimeIndex)

    def test_confluence_df_same_index_accepted(self):
        """confluence_df 与 intraday_df 同 index → 正常运行。"""
        bars   = _make_intraday_df(n_days=3)
        sigs   = _make_signals_df(bars)
        conf   = _make_confluence_df(bars, score=0.85)
        engine = _make_engine()
        result = engine.run(bars, sigs, conf)
        assert isinstance(result, BacktestResult)
        assert len(result.equity_curve) == 3
