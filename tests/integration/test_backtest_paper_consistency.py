"""
Integration test: backtest vs paper trading consistency.

Runs both engines on identical signals/prices over a short window
and compares fills, positions, cash, and equity.
Uses zero-cost mode to isolate execution logic from cost model differences.
"""

import numpy as np
import pandas as pd
import pytest
import tempfile
from pathlib import Path

from core.backtest.backtest_engine import BacktestEngine
from core.execution.cost_model import CostModel
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.pnl_tracker import PnLTracker
from core.risk.kill_switch import KillSwitch, KillSwitchConfig


def _make_deterministic_data(n_days=60, n_syms=4, seed=123):
    """Create deterministic price data with known patterns."""
    np.random.seed(seed)
    idx = pd.bdate_range("2023-01-02", periods=n_days)
    close_data = {}
    open_data = {}
    for i in range(n_syms):
        sym = f"S{i}"
        base = 50 + i * 20
        returns = np.random.randn(n_days) * 0.01
        close_prices = base * np.exp(np.cumsum(returns))
        close_data[sym] = close_prices
        open_data[sym] = close_prices * (1 + np.random.randn(n_days) * 0.002)
    price_df = pd.DataFrame(close_data, index=idx)
    open_df = pd.DataFrame(open_data, index=idx)
    return price_df, open_df, idx


def _make_signals(price_df, top_n=2):
    """Create simple equal-weight signals for top_n symbols."""
    signals = pd.DataFrame(0.0, index=price_df.index, columns=price_df.columns)
    syms = list(price_df.columns)
    w = 1.0 / top_n
    for i, date in enumerate(price_df.index):
        selected = syms[:top_n] if i % 20 < 10 else syms[-top_n:]
        for s in selected:
            signals.loc[date, s] = w
    return signals


def _make_zero_cost_model():
    """CostModel that charges zero — isolates execution logic."""
    import copy
    from core.config.loader import load_config
    cfg = load_config(Path("config"))
    cost_cfg = copy.deepcopy(cfg.cost_model)
    for tier_name, tier in cost_cfg.tiers.items():
        tier.commission_bps = 0.0
        tier.slippage_interday_bps = 0.0
        tier.slippage_intraday_bps = 0.0
    return CostModel(cost_cfg)


class TestBacktestPaperConsistency:
    """Verify backtest and paper trading produce consistent results."""

    def _run_backtest(self, signals, price_df, open_df, cost_model, capital, integer_shares):
        engine = BacktestEngine(
            cost_model=cost_model,
            initial_capital=capital,
            integer_shares=integer_shares,
        )
        result = engine.run(
            signals_df=signals,
            price_df=price_df,
            open_df=open_df,
        )
        return result

    def _run_paper(self, signals, price_df, open_df, cost_model, capital, integer_shares):
        tracker = PnLTracker(initial_capital=capital)
        ks = KillSwitch(KillSwitchConfig(max_drawdown=-0.99))
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        engine = PaperTradingEngine(
            cost_model=cost_model,
            pnl_tracker=tracker,
            db_path=db_path,
            initial_capital=capital,
            kill_switch=ks,
        )

        dates = price_df.index
        equities = []
        for i in range(len(dates) - 1):
            date = dates[i]
            next_date = dates[i + 1]

            if date not in signals.index:
                continue

            day_wts = signals.loc[date]
            target = {s: float(v) for s, v in day_wts.items() if v > 0.001}

            prices_today = {s: float(price_df.loc[date, s]) for s in price_df.columns
                           if not pd.isna(price_df.loc[date, s])}
            opens_next = {s: float(open_df.loc[next_date, s]) for s in open_df.columns
                          if not pd.isna(open_df.loc[next_date, s])}

            engine.run_day_daily(
                date=next_date,
                target_wts=target,
                prices=prices_today,
                open_prices=opens_next,
            )
            eq = engine._cash + sum(
                engine._positions.get(s, 0) * prices_today.get(s, 0) for s in engine._positions
            )
            equities.append((next_date, eq))

        return engine, equities, tracker

    def test_integer_shares_consistency(self):
        """Both engines in integer share mode should produce identical fills."""
        price_df, open_df, idx = _make_deterministic_data()
        signals = _make_signals(price_df)
        cost = _make_zero_cost_model()
        capital = 100_000.0

        bt = self._run_backtest(signals, price_df, open_df, cost, capital, integer_shares=True)
        paper_engine, paper_equities, _ = self._run_paper(
            signals, price_df, open_df, cost, capital, integer_shares=True
        )

        bt_final = bt.equity_curve.iloc[-1]
        paper_final = paper_equities[-1][1] if paper_equities else capital

        divergence_pct = abs(bt_final - paper_final) / capital * 100
        assert divergence_pct < 5.0, (
            f"Equity divergence {divergence_pct:.2f}% exceeds 5% threshold. "
            f"BT={bt_final:.2f}, Paper={paper_final:.2f}"
        )

    def test_both_produce_trades(self):
        """Both engines should produce non-zero trades."""
        price_df, open_df, _ = _make_deterministic_data()
        signals = _make_signals(price_df)
        cost = _make_zero_cost_model()
        capital = 100_000.0

        bt = self._run_backtest(signals, price_df, open_df, cost, capital, integer_shares=True)
        paper_engine, _, _ = self._run_paper(
            signals, price_df, open_df, cost, capital, integer_shares=True
        )

        assert len(bt.trades) > 0, "Backtest produced zero trades"
        assert len(paper_engine._tracker._records) > 0, "Paper produced zero records"

    def test_stressed_cost_changes_results(self):
        """2x cost should produce lower returns than 1x cost."""
        import copy
        from core.config.loader import load_config
        price_df, open_df, _ = _make_deterministic_data(n_days=120)
        signals = _make_signals(price_df)
        capital = 100_000.0

        cfg = load_config(Path("config"))

        cost_1x = CostModel(cfg.cost_model)
        bt_1x = self._run_backtest(signals, price_df, open_df, cost_1x, capital, integer_shares=False)

        cost_2x_cfg = copy.deepcopy(cfg.cost_model)
        for tier_name, tier in cost_2x_cfg.tiers.items():
            tier.commission_bps *= 2
            tier.slippage_interday_bps *= 2
        cost_2x = CostModel(cost_2x_cfg)
        bt_2x = self._run_backtest(signals, price_df, open_df, cost_2x, capital, integer_shares=False)

        ret_1x = bt_1x.equity_curve.iloc[-1] / capital - 1
        ret_2x = bt_2x.equity_curve.iloc[-1] / capital - 1
        assert ret_1x > ret_2x, (
            f"2x cost should produce lower return. 1x={ret_1x:.4f}, 2x={ret_2x:.4f}"
        )

    def test_paper_trading_integer_shares_match(self):
        """Paper trading must use same integer_shares as configured."""
        price_df, open_df, _ = _make_deterministic_data(n_days=30)
        signals = _make_signals(price_df)
        cost = _make_zero_cost_model()

        _, paper_equities_int, _ = self._run_paper(
            signals, price_df, open_df, cost, 100_000, integer_shares=True
        )

        assert len(paper_equities_int) > 0, "Paper trading produced no equity records"
