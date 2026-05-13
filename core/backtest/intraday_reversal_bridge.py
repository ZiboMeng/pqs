"""Bridge: IntradayReversalStrategy ↔ BacktestEngine (alt-A Phase 2).

Per design memo `docs/memos/20260512-deferred_execution_bt_integration_design.md`:
this module is the SOLE plumbing between IntradayReversalStrategy's
internal SignalStateMachine + DeferredExecutionSchedule state and
BacktestEngine's daily signals_df interface.

Zero BT internal changes — bridge produces a standard signals_df that
BacktestEngine.run() consumes without any modification.

PRD `docs/prd/20260512-alt_archetype_intraday_reversal_prd.md` §11 LOCKED:
  - 53-stock cycle04+ universe
  - 5d holding cap (position aging)
  - T+1 first-60m-bar-close fill (daily-grain BT models as T+1 open)
  - 2.5bp slip per leg (cost model override)

Daily-grain semantics:
  - Day T close: setup detected via weekly_reversal_signal_5d ≤ p05
  - Day T+1: confirmation predicate evaluated (intraday volume z + early
    session return > 0)
  - Daily signals_df row at T+1 contains the confirmed weight
  - BacktestEngine.run() consumes this and fills at T+2 open
  - Effective fill = T+2 open ≈ "T+1 first-60m-bar-close" approximation
    at daily resolution

Position aging (5d hard cap per PRD §11 Q2):
  - Track entry date per filled symbol
  - At date >= entry + 5 trading days → force exit (weight back to 0)
  - This is bridge-level state (BT doesn't know about holding cap)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.signals.strategies.intraday_reversal import (
    IntradayReversalConfig, IntradayReversalStrategy,
)

logger = logging.getLogger(__name__)


@dataclass
class IntradayReversalBridgeState:
    """Tracks symbol entry dates for position-aging hard cap."""
    entry_date: Dict[str, pd.Timestamp] = field(default_factory=dict)

    def aged_out(self, sym: str, today: pd.Timestamp, hold_days: int) -> bool:
        """Returns True if sym has been held >= hold_days trading days."""
        entry = self.entry_date.get(sym)
        if entry is None:
            return False
        held = (today - entry).days
        # NB: calendar days; close enough for 5d hard cap (PRD §11 Q2).
        # If user wants exact trading-day arithmetic, swap to a NYSE
        # calendar diff helper later.
        return held >= hold_days

    def record_entry(self, sym: str, when: pd.Timestamp) -> None:
        self.entry_date[sym] = when

    def clear(self, sym: str) -> None:
        self.entry_date.pop(sym, None)


def build_intraday_reversal_signals(
    strategy: IntradayReversalStrategy,
    weekly_reversal_signal_5d: pd.DataFrame,
    vol_21d: pd.DataFrame,
    intraday_volume_60m_zscore: pd.DataFrame,
    early_session_return_pct: pd.DataFrame,
    dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Run IntradayReversalStrategy across a date range; emit BT-consumable signals_df.

    Parameters
    ----------
    strategy : IntradayReversalStrategy
        Fully-configured strategy (PRD §11 LOCKED defaults).
    weekly_reversal_signal_5d : DataFrame (dates × symbols)
        From core.factors.factor_generator. Setup detection input.
    vol_21d : DataFrame (dates × symbols)
        Setup filter (vol filter).
    intraday_volume_60m_zscore : DataFrame (dates × symbols)
        Per-day 60m volume z-score at open. Phase 2 simplification:
        single value per (date, sym) representing "T+1 morning 60m
        volume vs 20d avg". Future: full 60m grid.
    early_session_return_pct : DataFrame (dates × symbols)
        Per-day early-session return. Phase 2 simplification: single
        value per (date, sym) representing "T+1 first-60m return".
    dates : DatetimeIndex
        Date range to iterate.

    Returns
    -------
    signals_df : DataFrame (dates × symbols)
        Target weights consumable by BacktestEngine.run(). Row at date T
        means: BT should hold these weights at close of T (will fill at
        T+1 open per BT semantics).

    Side effects: strategy.machine + strategy.schedule are advanced.
    Bridge keeps `state` (entry_date map) for position-aging logic.
    """
    state = IntradayReversalBridgeState()
    hold_cap = strategy.config.holding_period_max_days

    # Initialize all-zero signals_df
    all_syms = sorted(set(weekly_reversal_signal_5d.columns)
                      | set(vol_21d.columns))
    signals = pd.DataFrame(0.0, index=dates, columns=all_syms)

    # Track active positions = those held + not yet aged out
    active_weights: Dict[str, float] = {}

    for bar_idx, today in enumerate(dates):
        # Step 1: position aging — drop symbols past hold cap
        aged = [s for s in list(active_weights.keys())
                if state.aged_out(s, today, hold_cap)]
        for s in aged:
            active_weights.pop(s, None)
            state.clear(s)

        # Step 2: strategy step → produces today's NEW confirmed weights
        try:
            new_weights = strategy.step_day(
                bar_idx=bar_idx,
                weekly_reversal_signal_5d=weekly_reversal_signal_5d,
                vol_21d=vol_21d,
                intraday_volume_60m_zscore=(
                    intraday_volume_60m_zscore.loc[today]
                    if today in intraday_volume_60m_zscore.index else pd.Series(dtype=float)
                ),
                early_session_return_pct=(
                    early_session_return_pct.loc[today]
                    if today in early_session_return_pct.index else pd.Series(dtype=float)
                ),
                as_of_date=today,
            )
        except (KeyError, ValueError) as e:
            logger.debug("step_day failed at %s: %s", today, e)
            new_weights = {}

        # Step 3: merge new confirmed into active book + record entry date
        for sym, w in new_weights.items():
            if sym not in active_weights:
                state.record_entry(sym, today)
            active_weights[sym] = w

        # Step 4: emit row — re-normalize so total weight ≤ 1.0
        # (per PRD §3 sizing: equal-weight top-N, NOT leverage)
        total = sum(active_weights.values())
        if total > 1.0:
            scale = 1.0 / total
            row = {s: w * scale for s, w in active_weights.items()}
        else:
            row = dict(active_weights)
        for sym, w in row.items():
            if sym in signals.columns:
                signals.at[today, sym] = w

    return signals


def estimate_alt_a_turnover(signals: pd.DataFrame) -> float:
    """Quick estimate of annualized turnover from signals_df.

    Useful for cost-sensitivity check pre-fire (PRD §11 Q4 / §9
    cost_sensitivity_2x check).

    Returns
    -------
    float : ratio (e.g. 100.0 = 100x annualized turnover)
    """
    if signals.empty or len(signals) < 2:
        return 0.0
    # Day-to-day absolute weight change (one-sided turnover)
    diffs = signals.diff().abs().sum(axis=1).fillna(0)
    avg_daily_turn = float(diffs.mean())
    annualized = avg_daily_turn * 252
    return annualized
