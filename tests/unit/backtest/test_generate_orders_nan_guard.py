"""Regression test: NaN weight guard in BacktestEngine._generate_orders.

Smoke mining run (2026-04-20) revealed 13/20 trials failing with
"cannot convert float NaN to integer" inside _generate_orders when
integer_shares=True (post-P0.5). Root cause: a NaN target weight
propagated through delta_w → delta_usd → qty, and int(NaN) raised
inside the integer-shares branch.

This test guards against regression: _generate_orders must silently
skip any symbol with a non-finite weight instead of crashing.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestEngine
from core.config.loader import load_config
from core.execution.cost_model import CostModel


def _engine(integer_shares=True):
    cfg = load_config(Path("config"))
    return BacktestEngine(
        cost_model=CostModel(cfg.cost_model),
        initial_capital=10_000,
        integer_shares=integer_shares,
    )


class TestNaNWeightGuard:
    def test_nan_tgt_weight_does_not_crash(self):
        """A NaN in tgt_weights must be skipped, not raise."""
        eng = _engine(integer_shares=True)
        cur_weights = {"AAPL": 0.0}
        tgt_weights = {"AAPL": float("nan"), "MSFT": 0.5}
        open_row = pd.Series({"AAPL": 100.0, "MSFT": 200.0})
        price_row = pd.Series({"AAPL": 100.0, "MSFT": 200.0})
        orders = eng._generate_orders(
            cur_weights=cur_weights, tgt_weights=tgt_weights,
            portfolio_val=10_000.0, price_row=price_row,
            open_row=open_row, signal_date=pd.Timestamp("2024-01-02"),
        )
        # AAPL skipped (NaN); MSFT generates a BUY
        syms = {o.symbol for o in orders}
        assert "AAPL" not in syms
        assert "MSFT" in syms

    def test_nan_cur_weight_does_not_crash(self):
        eng = _engine(integer_shares=True)
        cur_weights = {"AAPL": float("nan")}
        tgt_weights = {"AAPL": 0.5}
        open_row = pd.Series({"AAPL": 100.0})
        price_row = pd.Series({"AAPL": 100.0})
        orders = eng._generate_orders(
            cur_weights=cur_weights, tgt_weights=tgt_weights,
            portfolio_val=10_000.0, price_row=price_row,
            open_row=open_row, signal_date=pd.Timestamp("2024-01-02"),
        )
        assert not any(o.symbol == "AAPL" for o in orders)

    def test_fractional_mode_also_guarded(self):
        """Same guard should apply even when integer_shares=False
        (divison by NaN gives NaN qty anyway)."""
        eng = _engine(integer_shares=False)
        tgt_weights = {"AAPL": float("nan")}
        open_row = pd.Series({"AAPL": 100.0})
        orders = eng._generate_orders(
            cur_weights={}, tgt_weights=tgt_weights,
            portfolio_val=10_000.0, price_row=open_row,
            open_row=open_row, signal_date=pd.Timestamp("2024-01-02"),
        )
        assert orders == []

    def test_full_run_with_nan_signals_doesnt_crash(self):
        """End-to-end: a weights DataFrame with occasional NaN rows
        must not raise during integer_shares backtest."""
        idx = pd.bdate_range("2024-01-02", periods=10)
        prices = pd.DataFrame({"A": 100.0, "B": 200.0}, index=idx)
        opens = prices.copy()
        # Insert NaN into signals on days 3-5
        signals = pd.DataFrame(0.5, index=idx, columns=["A", "B"])
        signals.loc[signals.index[3:6], "A"] = np.nan
        eng = _engine(integer_shares=True)
        result = eng.run(signals_df=signals, price_df=prices, open_df=opens)
        # The run should complete with a non-empty equity curve
        assert not result.equity_curve.empty
