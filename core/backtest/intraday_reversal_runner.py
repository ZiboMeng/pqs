"""IntradayReversalRunner — bridge IntradayReversalStrategy → SignalDrivenBacktest.

T1a.2 deliverable. Converts the existing daily-rebalance
`IntradayReversalStrategy` (Phase 1 skeleton at
`core/signals/strategies/intraday_reversal.py`) into entry/exit signal
DataFrames + confirmation predicate consumed by the K1 wrapper
`SignalDrivenBacktest`.

Architectural rationale:
- IntradayReversalStrategy already has `detect_setups()` (weekly
  reversal + vol filter) and `confirm_signals()` (intraday volume +
  early-session direction) APIs but lacks BacktestEngine integration
- K1 SignalDrivenBacktest expects entry_signals + exit_signals
  DataFrames + an optional confirmation_predicate(state, bar_idx, ctx)
- This module bridges the two by precomputing entry signals from
  detect_setups + wiring the confirmation logic through the predicate

Cadence convention:
- Setup detected at bar T (entry_signal[T, sym] = True)
- ARMED at T, ttl_bars=1 → confirmation eligible at T (age 0) or T+1 (age 1)
- User predicate forces confirmation ONLY at T+1 (age 1, post-setup
  intraday data is the relevant signal; T's intraday is the setup
  evening itself)
- If confirmed at T+1: fill at T+2 (execution_delay_bars=1)
- Exit approximation: T+2+max_holding_days marks exit signal for sym
  (no-op if position never opened, e.g., setup didn't confirm)

Phase 2 scope (this file):
- Synthetic-data testable (no 60m bar dependency)
- Real 60m factor compute path is Phase 3 (T1a.3, separate module)
- Track A acceptance + NAV correlation gate are Phase 3 (T1a.5+)
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestResult
from core.backtest.signal_driven_runner import SignalDrivenBacktest
from core.execution.cost_model import CostModel
from core.signals.signal_state import SignalState
from core.signals.strategies.intraday_reversal import (
    IntradayReversalStrategy, IntradayReversalConfig,
)


class IntradayReversalRunner:
    """Bridge IntradayReversalStrategy through SignalDrivenBacktest.

    Inputs:
      - strategy: IntradayReversalStrategy with config (or default config)
      - Factor panels (date × symbol):
        - weekly_reversal_signal_5d (setup feature; LOWER = better reversal candidate)
        - vol_21d (volatility filter; HIGHER percentile = adequate liquidity)
        - intraday_volume_60m_zscore (confirmation feature 1)
        - early_session_return_pct (confirmation feature 2)
      - price_df: (date × symbol) close prices for NAV computation

    Workflow:
      1. _build_entry_signals(): scan each date; call strategy.detect_setups
         → entry_signals[T, sym] = True iff sym in setups at T
      2. _build_exit_signals(): for each setup date T, mark exit at
         T + ttl + execution_delay + max_holding_days as approximation
         (no-op if position never opened per K1.2 test_12)
      3. _make_confirmation_predicate(): user callable that returns True iff
         (bar_idx - armed_at_bar == ttl_bars) AND intraday conditions met
      4. Pass to SignalDrivenBacktest.run()
    """

    def __init__(
        self,
        strategy: IntradayReversalStrategy,
        weekly_reversal_signal_5d: pd.DataFrame,
        vol_21d: pd.DataFrame,
        intraday_volume_60m_zscore: pd.DataFrame,
        early_session_return_pct: pd.DataFrame,
        price_df: pd.DataFrame,
        initial_capital: float = 100_000.0,
        cost_model: Optional[CostModel] = None,
    ):
        # ---- Validation ----
        # All factor panels must share the same date index
        idx = weekly_reversal_signal_5d.index
        for name, df in [
            ("vol_21d", vol_21d),
            ("intraday_volume_60m_zscore", intraday_volume_60m_zscore),
            ("early_session_return_pct", early_session_return_pct),
            ("price_df", price_df),
        ]:
            if not df.index.equals(idx):
                raise ValueError(
                    f"{name}.index must equal weekly_reversal_signal_5d.index"
                )

        self.strategy = strategy
        self.weekly_reversal_signal_5d = weekly_reversal_signal_5d
        self.vol_21d = vol_21d
        self.intraday_volume_60m_zscore = intraday_volume_60m_zscore
        self.early_session_return_pct = early_session_return_pct
        self.price_df = price_df
        self.initial_capital = initial_capital
        self.cost_model = cost_model
        self.dates = idx
        # Setup symbols per date (precomputed via detect_setups)
        self._setups_by_date: Dict[pd.Timestamp, list] = {}

    # ── Build phase ──────────────────────────────────────────────────────

    def _build_entry_signals(self) -> pd.DataFrame:
        """For each date, call strategy.detect_setups → entry_signals[T, sym]."""
        symbols = sorted(self.weekly_reversal_signal_5d.columns)
        entry = pd.DataFrame(False, index=self.dates, columns=symbols, dtype=bool)
        for d in self.dates:
            setups = self.strategy.detect_setups(
                self.weekly_reversal_signal_5d,
                self.vol_21d,
                d,
            )
            self._setups_by_date[d] = setups
            for sym in setups:
                if sym in entry.columns:
                    entry.loc[d, sym] = True
        return entry

    def _build_exit_signals(self) -> pd.DataFrame:
        """Approximate max-holding-days exit: for each setup at T, mark exit
        at T + ttl + execution_delay + max_holding_days.

        Per K1.2 test_12, exit_signal for a sym with no position is a no-op,
        so this safely handles setups that never confirmed (no fill).
        """
        symbols = sorted(self.weekly_reversal_signal_5d.columns)
        exit_ = pd.DataFrame(False, index=self.dates, columns=symbols, dtype=bool)
        cfg = self.strategy.config
        ttl = cfg.confirmation_ttl_bars
        delay = cfg.execution_delay_bars
        hold = cfg.holding_period_max_days
        # Total offset from setup date to exit signal date
        offset = ttl + delay + hold
        n = len(self.dates)
        for setup_idx, d in enumerate(self.dates):
            setups = self._setups_by_date.get(d, [])
            exit_idx = setup_idx + offset
            if exit_idx >= n:
                continue
            exit_date = self.dates[exit_idx]
            for sym in setups:
                if sym in exit_.columns:
                    exit_.loc[exit_date, sym] = True
        return exit_

    def _make_confirmation_predicate(self) -> Callable:
        """Return a confirmation_predicate(state, bar_idx, ctx) -> bool.

        Logic: only check at age == ttl_bars; require both volume surge AND
        early-session positive return per strategy.confirm_signals semantics.
        """
        cfg = self.strategy.config
        ttl = cfg.confirmation_ttl_bars
        vol_thresh = cfg.volume_surge_at_open_60m_min
        intraday_vol = self.intraday_volume_60m_zscore
        early_ret = self.early_session_return_pct
        dates = self.dates

        def predicate(state: SignalState, bar_idx: int, ctx: dict) -> bool:
            age = bar_idx - state.armed_at_bar
            if age != ttl:
                # Only check at the configured confirmation lag
                return False
            if bar_idx >= len(dates):
                return False
            d = dates[bar_idx]
            try:
                v = intraday_vol.loc[d, state.symbol]
                r = early_ret.loc[d, state.symbol]
            except (KeyError, IndexError):
                return False
            if pd.isna(v) or pd.isna(r):
                return False
            return bool(v >= vol_thresh and r > 0.0)

        return predicate

    # ── Run ──────────────────────────────────────────────────────────────

    def run(self) -> BacktestResult:
        """Drive IntradayReversalStrategy through SignalDrivenBacktest."""
        entry_signals = self._build_entry_signals()
        exit_signals = self._build_exit_signals()
        cfg = self.strategy.config

        bt = SignalDrivenBacktest(
            entry_signals=entry_signals,
            exit_signals=exit_signals,
            price_df=self.price_df,
            ttl_bars=cfg.confirmation_ttl_bars,
            top_n=cfg.top_n,
            confirmation_predicate=self._make_confirmation_predicate(),
            position_sizing_rule=None,  # equal-weight 1/top_n default
            cost_model=self.cost_model,
            initial_capital=self.initial_capital,
            execution_delay_bars=cfg.execution_delay_bars,
            max_single_weight=None,  # no cap beyond top_n
        )
        result = bt.run()
        self._signal_driven_bt = bt
        return result

    def weight_panel(self) -> pd.DataFrame:
        """Convenience accessor — delegates to wrapped SignalDrivenBacktest."""
        return self._signal_driven_bt.weight_panel()

    def signal_history(self):
        """All signal states processed (active + terminal)."""
        return self._signal_driven_bt.signal_history()

    def setups_by_date(self) -> Dict[pd.Timestamp, list]:
        """Diagnostic: which symbols were setup-detected at each date."""
        return dict(self._setups_by_date)
