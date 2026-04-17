"""Tests for IntradayBacktestEngine multi-asset support (run_multi_day)."""

import numpy as np
import pandas as pd
import pytest

from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.cost_model import CostModel
from core.backtest.intraday_engine import IntradayBacktestEngine


def _make_zero_cost():
    cfg = CostModelConfig(tiers={
        "default": CostTierConfig(symbols=[], commission_bps=0, slippage_interday_bps=0, slippage_intraday_bps=0)
    })
    return CostModel(cfg)


def _make_multi_asset_bars(n_bars=7, n_syms=3, seed=42):
    """Create Dict[symbol → 60m OHLCV DataFrame] for one trading day."""
    np.random.seed(seed)
    idx = pd.date_range("2025-01-02 09:30", periods=n_bars, freq="60min")
    bars = {}
    for i in range(n_syms):
        sym = f"SYM{i}"
        base = 100 + i * 20
        close = base + np.cumsum(np.random.randn(n_bars) * 0.5)
        bars[sym] = pd.DataFrame({
            "open": close * (1 + np.random.randn(n_bars) * 0.002),
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.random.uniform(1e5, 5e5, n_bars),
        }, index=idx)
    return bars


class TestRunMultiDay:
    def test_basic_execution(self):
        engine = IntradayBacktestEngine(cost_model=_make_zero_cost(), initial_capital=100000)
        bars = _make_multi_asset_bars()
        target = {"SYM0": 0.3, "SYM1": 0.3, "SYM2": 0.3}
        result = engine.run_multi_day(
            date=pd.Timestamp("2025-01-02"),
            day_bars=bars,
            target_wts=target,
            positions={},
            cash=100000,
        )
        assert result.n_trades > 0, "Should produce trades"
        assert result.eod_cash > 0

    def test_eod_close_clears_positions(self):
        engine = IntradayBacktestEngine(cost_model=_make_zero_cost(), eod_force_close=True)
        bars = _make_multi_asset_bars()
        result = engine.run_multi_day(
            date=pd.Timestamp("2025-01-02"),
            day_bars=bars,
            target_wts={"SYM0": 0.5, "SYM1": 0.5},
            positions={},
            cash=100000,
        )
        assert len(result.eod_positions) == 0, "EOD close should clear all positions"

    def test_multi_asset_portfolio_value(self):
        bars = _make_multi_asset_bars()
        shares = {"SYM0": 10, "SYM1": 5}
        val = IntradayBacktestEngine._multi_portfolio_value(shares, bars, 0)
        expected = 10 * bars["SYM0"]["close"].iloc[0] + 5 * bars["SYM1"]["close"].iloc[0]
        assert abs(val - expected) < 0.01

    def test_empty_bars_returns_no_trades(self):
        engine = IntradayBacktestEngine(cost_model=_make_zero_cost())
        result = engine.run_multi_day(
            date=pd.Timestamp("2025-01-02"),
            day_bars={},
            target_wts={"SYM0": 0.5},
            positions={},
            cash=100000,
        )
        assert result.n_trades == 0

    def test_existing_positions_carried(self):
        engine = IntradayBacktestEngine(cost_model=_make_zero_cost(), eod_force_close=False)
        bars = _make_multi_asset_bars()
        result = engine.run_multi_day(
            date=pd.Timestamp("2025-01-02"),
            day_bars=bars,
            target_wts={"SYM0": 0.5},
            positions={"SYM0": 100},
            cash=50000,
        )
        assert result.eod_cash > 0

    def test_missing_symbol_in_bars_skipped(self):
        engine = IntradayBacktestEngine(cost_model=_make_zero_cost())
        bars = _make_multi_asset_bars(n_syms=2)  # only SYM0, SYM1
        result = engine.run_multi_day(
            date=pd.Timestamp("2025-01-02"),
            day_bars=bars,
            target_wts={"SYM0": 0.3, "SYM1": 0.3, "MISSING": 0.3},
            positions={},
            cash=100000,
        )
        assert result.n_trades > 0  # should still trade available symbols
