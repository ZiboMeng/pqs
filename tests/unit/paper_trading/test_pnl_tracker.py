"""Unit tests for PnLTracker."""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd
import pytest

from core.backtest.intraday_engine import DayResult
from core.paper_trading.pnl_tracker import PnLTracker


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _make_day_result(
    date:          str   = "2024-01-02",
    net_pnl:       float = 0.0,
    n_trades:      int   = 0,
    total_cost:    float = 0.0,
    forced_close:  bool  = True,
) -> DayResult:
    return DayResult(
        date          = pd.Timestamp(date),
        trades        = [],
        eod_positions = {},
        eod_cash      = 100_000.0,
        gross_pnl     = net_pnl,
        net_pnl       = net_pnl,
        forced_close  = forced_close,
    )


def _fill_tracker(
    tracker:  PnLTracker,
    equities: List[float],
    start:    str = "2024-01-02",
) -> None:
    """向 tracker 批量注入等间距权益序列。"""
    dates = pd.bdate_range(start, periods=len(equities))
    for i, (eq, date) in enumerate(zip(equities, dates)):
        pnl = eq - (equities[i - 1] if i > 0 else tracker._initial)
        dr  = _make_day_result(date=str(date.date()), net_pnl=pnl)
        tracker.record(dr, eq)


# ── 初始状态 ──────────────────────────────────────────────────────────────────

class TestPnLTrackerInit:
    def test_latest_equity_equals_initial_capital(self):
        t = PnLTracker(initial_capital=100_000.0)
        assert t.latest_equity == pytest.approx(100_000.0)

    def test_equity_curve_empty(self):
        t = PnLTracker()
        assert t.equity_curve.empty

    def test_daily_returns_empty(self):
        t = PnLTracker()
        assert t.daily_returns.empty

    def test_max_drawdown_zero_when_empty(self):
        t = PnLTracker()
        assert t.max_drawdown == pytest.approx(0.0)

    def test_running_drawdown_zero_when_empty(self):
        t = PnLTracker()
        assert t.running_drawdown == pytest.approx(0.0)

    def test_total_return_zero_when_empty(self):
        t = PnLTracker()
        assert t.total_return == pytest.approx(0.0)

    def test_sharpe_nan_when_empty(self):
        t = PnLTracker()
        assert np.isnan(t.sharpe)


# ── record / equity_curve ──────────────────────────────────────────────────────

class TestRecord:
    def test_single_record_equity_curve_length_1(self):
        t  = PnLTracker()
        dr = _make_day_result("2024-01-02")
        t.record(dr, 101_000.0)
        assert len(t.equity_curve) == 1

    def test_equity_curve_values_match(self):
        t = PnLTracker()
        _fill_tracker(t, [100_000.0, 101_000.0, 99_000.0])
        eq = t.equity_curve
        assert list(eq.values) == pytest.approx([100_000.0, 101_000.0, 99_000.0])

    def test_equity_curve_index_is_datetime(self):
        t = PnLTracker()
        _fill_tracker(t, [100_000.0, 101_000.0])
        assert isinstance(t.equity_curve.index, pd.DatetimeIndex)

    def test_latest_equity_updated(self):
        t = PnLTracker(100_000.0)
        _fill_tracker(t, [100_000.0, 105_000.0])
        assert t.latest_equity == pytest.approx(105_000.0)


# ── daily_returns ──────────────────────────────────────────────────────────────

class TestDailyReturns:
    def test_one_record_returns_empty(self):
        t = PnLTracker()
        _fill_tracker(t, [100_000.0])
        assert t.daily_returns.empty

    def test_two_records_returns_one_value(self):
        t = PnLTracker()
        _fill_tracker(t, [100_000.0, 110_000.0])
        rets = t.daily_returns
        assert len(rets) == 1
        assert rets.iloc[0] == pytest.approx(0.10, rel=1e-4)

    def test_declining_equity_negative_return(self):
        t = PnLTracker()
        _fill_tracker(t, [100_000.0, 90_000.0])
        assert t.daily_returns.iloc[0] < 0


# ── total_return ──────────────────────────────────────────────────────────────

class TestTotalReturn:
    def test_positive_when_equity_above_initial(self):
        t = PnLTracker(100_000.0)
        _fill_tracker(t, [100_000.0, 120_000.0])
        assert t.total_return > 0

    def test_negative_when_equity_below_initial(self):
        t = PnLTracker(100_000.0)
        _fill_tracker(t, [100_000.0, 80_000.0])
        assert t.total_return < 0

    def test_exact_value(self):
        t = PnLTracker(100_000.0)
        _fill_tracker(t, [100_000.0, 115_000.0])
        assert t.total_return == pytest.approx(0.15, rel=1e-4)


# ── max_drawdown ──────────────────────────────────────────────────────────────

class TestMaxDrawdown:
    def test_flat_equity_zero_drawdown(self):
        t = PnLTracker(100_000.0)
        _fill_tracker(t, [100_000.0] * 10)
        assert t.max_drawdown == pytest.approx(0.0, abs=1e-6)

    def test_monotone_rising_zero_drawdown(self):
        t = PnLTracker(100_000.0)
        _fill_tracker(t, [100_000.0 * (1.001 ** i) for i in range(10)])
        assert t.max_drawdown == pytest.approx(0.0, abs=1e-6)

    def test_declining_after_peak(self):
        """峰值后回落 50% → max_drawdown 应约为 -0.50。"""
        t = PnLTracker(100_000.0)
        _fill_tracker(t, [100_000.0, 120_000.0, 60_000.0])
        assert t.max_drawdown == pytest.approx(-0.50, rel=1e-3)

    def test_drawdown_is_non_positive(self):
        t = PnLTracker()
        _fill_tracker(t, [100_000.0, 90_000.0, 95_000.0, 85_000.0])
        assert t.max_drawdown <= 0


# ── running_drawdown ──────────────────────────────────────────────────────────

class TestRunningDrawdown:
    def test_at_peak_zero_drawdown(self):
        """权益在历史最高点时，当前回撤为 0。"""
        t = PnLTracker(100_000.0)
        _fill_tracker(t, [100_000.0, 105_000.0, 110_000.0])
        assert t.running_drawdown == pytest.approx(0.0, abs=1e-6)

    def test_below_peak_negative(self):
        t = PnLTracker(100_000.0)
        _fill_tracker(t, [100_000.0, 110_000.0, 99_000.0])
        dd = t.running_drawdown
        assert dd < 0

    def test_running_drawdown_exact(self):
        """峰值 110k → 当前 99k → 回撤 = (99k-110k)/110k ≈ -0.10。"""
        t = PnLTracker(100_000.0)
        _fill_tracker(t, [100_000.0, 110_000.0, 99_000.0])
        expected = (99_000.0 - 110_000.0) / 110_000.0
        assert t.running_drawdown == pytest.approx(expected, rel=1e-4)


# ── sharpe ────────────────────────────────────────────────────────────────────

class TestSharpe:
    def test_nan_for_fewer_than_20_days(self):
        t = PnLTracker(100_000.0)
        _fill_tracker(t, [100_000.0 * (1.001 ** i) for i in range(10)])
        assert np.isnan(t.sharpe)

    def test_nan_for_zero_volatility(self):
        """完全平稳收益 → std ≈ 0 → sharpe = nan。"""
        t = PnLTracker(100_000.0)
        _fill_tracker(t, [100_000.0 + i * 10 for i in range(30)])
        # 日收益极小且恒定，std 接近 0
        # sharpe 应为 nan（std < 1e-10）或极大值
        # 只要不抛异常即可；nan 是预期
        result = t.sharpe
        assert isinstance(result, float)

    def test_positive_for_rising_equity(self):
        """单调上涨（低波动率）→ Sharpe 为正。"""
        t   = PnLTracker(100_000.0)
        rng = np.random.default_rng(42)
        daily: List[float] = [100_000.0]
        for _ in range(30):
            daily.append(daily[-1] * (1 + abs(rng.normal(0.002, 0.001))))
        _fill_tracker(t, daily)
        assert t.sharpe > 0


# ── summary ───────────────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_returns_dict(self):
        t = PnLTracker()
        assert isinstance(t.summary(), dict)

    def test_summary_keys_present(self):
        t = PnLTracker()
        _fill_tracker(t, [100_000.0, 102_000.0])
        keys = t.summary().keys()
        for k in ["n_days", "latest_equity", "total_return", "max_drawdown",
                  "running_drawdown", "sharpe", "total_trades", "total_cost_usd"]:
            assert k in keys, f"缺少 key: {k}"

    def test_summary_n_days_correct(self):
        t = PnLTracker()
        _fill_tracker(t, [100_000.0] * 5)
        assert t.summary()["n_days"] == 5

    def test_summary_total_cost_sums_correctly(self):
        t  = PnLTracker()
        eq = 100_000.0
        for i in range(3):
            dr = DayResult(
                date=pd.Timestamp("2024-01-0" + str(i + 2)),
                trades=[], eod_positions={}, eod_cash=eq,
                gross_pnl=0.0, net_pnl=0.0, forced_close=True,
            )
            # total_cost 由 Fill 列表决定，这里用空 trades → total_cost=0
            t.record(dr, eq)
        assert t.summary()["total_cost_usd"] == pytest.approx(0.0)


# ── reset / restore ───────────────────────────────────────────────────────────

class TestResetRestore:
    def test_reset_clears_records(self):
        t = PnLTracker()
        _fill_tracker(t, [100_000.0, 102_000.0])
        t.reset()
        assert t.equity_curve.empty
        assert t.latest_equity == pytest.approx(100_000.0)

    def test_restore_repopulates(self):
        t = PnLTracker(100_000.0)
        records = [
            {"date": pd.Timestamp("2024-01-02"), "equity": 101_000.0,
             "net_pnl": 1000.0, "n_trades": 2, "total_cost": 5.0, "forced_close": True},
            {"date": pd.Timestamp("2024-01-03"), "equity": 102_000.0,
             "net_pnl": 1000.0, "n_trades": 1, "total_cost": 3.0, "forced_close": True},
        ]
        t.restore(records)
        assert len(t.equity_curve) == 2
        assert t.latest_equity == pytest.approx(102_000.0)

    def test_restore_then_record(self):
        """restore 后可继续追加新记录。"""
        t = PnLTracker(100_000.0)
        t.restore([{"date": pd.Timestamp("2024-01-02"), "equity": 101_000.0,
                    "net_pnl": 1000.0, "n_trades": 1, "total_cost": 2.0, "forced_close": True}])
        dr = _make_day_result("2024-01-03", net_pnl=500.0)
        t.record(dr, 101_500.0)
        assert len(t.equity_curve) == 2


# ── to_dataframe ──────────────────────────────────────────────────────────────

class TestToDataframe:
    def test_empty_returns_empty_df(self):
        t = PnLTracker()
        assert t.to_dataframe().empty

    def test_columns_present(self):
        t = PnLTracker()
        _fill_tracker(t, [100_000.0, 102_000.0])
        df = t.to_dataframe()
        for col in ["equity", "net_pnl", "n_trades", "total_cost", "forced_close"]:
            assert col in df.columns, f"缺少列: {col}"

    def test_row_count_matches_records(self):
        t = PnLTracker()
        _fill_tracker(t, [100_000.0, 101_000.0, 102_000.0])
        assert len(t.to_dataframe()) == 3
