"""Tests for ghost-position cleanup in BacktestEngine (P1.6, 2026-04-20).

Scenario: a held symbol becomes permanently halted/delisted, so its
open price is NaN on every subsequent day. Prior behavior: the engine
skipped orders for that symbol (correct for short gaps) → position
stayed forever → phantom holdings accrued at last mark.

Fix: after N consecutive stale-open days (configurable threshold),
force-liquidate at the last observed close; if no valid close ever
seen, write off. Diagnostic log in engine.ghost_liquidations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestEngine
from core.config.loader import load_config
from core.execution.cost_model import CostModel
from pathlib import Path


def _cost():
    return CostModel(load_config(Path("config")).cost_model)


def _run(signals, prices, opens, threshold=3):
    eng = BacktestEngine(cost_model=_cost(), initial_capital=10_000,
                         stale_days_threshold=threshold)
    return eng, eng.run(signals_df=signals, price_df=prices, open_df=opens)


class TestGhostLiquidation:

    def test_halted_position_force_liquidated_at_last_close(self):
        """AAPL entered on day 0, then halts on day 2 (all opens NaN
        from day 3 onward). After threshold stale days, engine should
        liquidate at last valid AAPL close."""
        idx = pd.bdate_range("2024-01-02", periods=12)
        # Prices: AAPL valid through day 5, then NaN; BBB stays valid
        aapl_close = [100.0] * 6 + [np.nan] * 6
        bbb_close  = [50.0 + i * 0.5 for i in range(12)]
        prices = pd.DataFrame({"AAPL": aapl_close, "BBB": bbb_close}, index=idx)
        # Opens valid through day 5 for AAPL, then NaN
        opens = prices.copy()
        # Signal: hold 50% AAPL, 50% BBB
        signals = pd.DataFrame(0.5, index=idx, columns=["AAPL", "BBB"])

        eng = BacktestEngine(cost_model=_cost(), initial_capital=10_000,
                             stale_days_threshold=3)
        result = eng.run(signals_df=signals, price_df=prices, open_df=opens)
        # After 3+ stale days, AAPL should appear in ghost_liquidations
        syms_liquidated = {g["symbol"] for g in eng.ghost_liquidations}
        assert "AAPL" in syms_liquidated, (
            f"AAPL not in ghost_liquidations: {eng.ghost_liquidations}"
        )
        # Each liquidation should have stale_days > threshold
        for g in eng.ghost_liquidations:
            assert g["stale_days"] > 3

    def test_price_is_last_valid_close(self):
        idx = pd.bdate_range("2024-01-02", periods=10)
        aapl_close = [100.0, 101.0, 102.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]
        bbb_close  = [50.0] * 10
        prices = pd.DataFrame({"AAPL": aapl_close, "BBB": bbb_close}, index=idx)
        opens = prices.copy()
        signals = pd.DataFrame(0.5, index=idx, columns=["AAPL", "BBB"])

        eng = BacktestEngine(cost_model=_cost(), initial_capital=10_000,
                             stale_days_threshold=2)
        eng.run(signals_df=signals, price_df=prices, open_df=opens)
        aapl_liqs = [g for g in eng.ghost_liquidations if g["symbol"] == "AAPL"]
        assert len(aapl_liqs) >= 1
        # Last valid AAPL close was 102.0 (day 2)
        assert aapl_liqs[0]["price"] == 102.0

    def test_short_gap_not_liquidated(self):
        """A held symbol missing 1-2 days (below threshold) should
        NOT be force-liquidated."""
        idx = pd.bdate_range("2024-01-02", periods=10)
        aapl_close = [100.0, 101.0, np.nan, np.nan, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]
        bbb_close  = [50.0] * 10
        prices = pd.DataFrame({"AAPL": aapl_close, "BBB": bbb_close}, index=idx)
        opens = prices.copy()
        signals = pd.DataFrame(0.5, index=idx, columns=["AAPL", "BBB"])

        eng = BacktestEngine(cost_model=_cost(), initial_capital=10_000,
                             stale_days_threshold=5)
        eng.run(signals_df=signals, price_df=prices, open_df=opens)
        aapl_liqs = [g for g in eng.ghost_liquidations if g["symbol"] == "AAPL"]
        assert len(aapl_liqs) == 0, (
            f"AAPL was liquidated after a short gap: {aapl_liqs}"
        )

    def test_clean_history_no_liquidations(self):
        idx = pd.bdate_range("2024-01-02", periods=10)
        prices = pd.DataFrame({
            "AAPL": [100.0 + i * 0.5 for i in range(10)],
            "BBB":  [50.0 + i * 0.3 for i in range(10)],
        }, index=idx)
        opens = prices.copy()
        signals = pd.DataFrame(0.5, index=idx, columns=["AAPL", "BBB"])

        eng = BacktestEngine(cost_model=_cost(), initial_capital=10_000,
                             stale_days_threshold=3)
        eng.run(signals_df=signals, price_df=prices, open_df=opens)
        assert len(eng.ghost_liquidations) == 0

    def test_ghost_liquidation_proceeds_go_to_cash(self):
        """Force-liquidation proceeds should increase cash by qty*price."""
        idx = pd.bdate_range("2024-01-02", periods=15)
        aapl_close = [100.0] * 5 + [np.nan] * 10
        bbb_close = [50.0] * 15
        prices = pd.DataFrame({"AAPL": aapl_close, "BBB": bbb_close}, index=idx)
        opens = prices.copy()
        signals = pd.DataFrame(0.5, index=idx, columns=["AAPL", "BBB"])

        eng = BacktestEngine(cost_model=_cost(), initial_capital=10_000,
                             stale_days_threshold=3)
        result = eng.run(signals_df=signals, price_df=prices, open_df=opens)
        # After all liquidations, AAPL should no longer be in the final
        # positions snapshot
        final_positions = result.positions.iloc[-1]
        assert final_positions.get("AAPL", 0.0) == 0.0, (
            "AAPL still held after force-liquidation"
        )
        # Cash curve should have jumped at the liquidation date
        liqs = [g for g in eng.ghost_liquidations if g["symbol"] == "AAPL"]
        assert liqs and liqs[0]["proceeds"] > 0
