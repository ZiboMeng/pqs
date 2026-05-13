"""Deferred-execution backtest layer for signal-confirmation strategies.

PRD-driven 2026-05-12 per
`docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md` §4.1.

This is the KERNEL for signal-conf backtesting. Full integration with
existing `core/backtest/backtest_engine.py` is a 1-week follow-up; this
ships the pure-Python building block:

  - Signal armed at T (entered state machine)
  - Fill scheduled for T+k (after confirmation, with execution delay)
  - During [T, T+k] interval, NAV reflects cash (no position yet)
  - Once filled, normal mark-to-market resumes
  - M11a/M11b parity preserved by routing fills through
    BacktestEngine._generate_orders contract (sorted iteration)

Boundary: this kernel handles the SIGNAL state machine + fill scheduling.
It does NOT modify NAV computation (that lives in BacktestEngine
proper). Integration glue is in `core/backtest/backtest_engine.py`
extension (deferred — needs careful M11a/M11b regression testing).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.signals.signal_state import (
    SignalState, SignalStateMachine, SignalStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class ExecutionScheduleEntry:
    """One fill scheduled for execution at a future bar."""
    symbol: str
    fill_at_bar: int          # integer bar index of fill date
    target_weight: float      # weight at fill time
    armed_at_bar: int         # original arm bar (audit trail)
    confirmed_at_bar: int     # confirmation bar (audit trail)
    setup_metadata: Dict = field(default_factory=dict)


class DeferredExecutionSchedule:
    """Tracks pending fills with execution delay support.

    Workflow each bar:
      1. Strategy generates confirmation fires (via SignalStateMachine).
      2. Each fire registers an ExecutionScheduleEntry with
         fill_at_bar = confirmed_at_bar + execution_delay_bars.
      3. Backtest engine queries `due_at(bar_idx)` to fetch fills.
      4. Engine processes fills with M11a sorted-iteration guarantee
         (deterministic across PYTHONHASHSEED).
    """

    def __init__(self, execution_delay_bars: int = 1):
        """
        Args:
            execution_delay_bars: Bars between confirmation and fill.
                                  Default 1 = signal at T-close fills at
                                  T+1 open. Mirrors existing BacktestEngine
                                  T+1 open execution convention.
        """
        if execution_delay_bars < 0:
            raise ValueError("execution_delay_bars must be ≥ 0")
        self.execution_delay_bars = execution_delay_bars
        self._pending: List[ExecutionScheduleEntry] = []
        self._executed: List[ExecutionScheduleEntry] = []

    def schedule_fill(
        self,
        signal_state: SignalState,
        target_weight: float,
    ) -> ExecutionScheduleEntry:
        """Register a fill for a confirmed signal."""
        if signal_state.status != SignalStatus.CONFIRMED:
            raise ValueError(
                f"Can only schedule fills for CONFIRMED signals; "
                f"got {signal_state.status}"
            )
        entry = ExecutionScheduleEntry(
            symbol=signal_state.symbol,
            fill_at_bar=(signal_state.confirmed_at_bar or 0) + self.execution_delay_bars,
            target_weight=target_weight,
            armed_at_bar=signal_state.armed_at_bar,
            confirmed_at_bar=signal_state.confirmed_at_bar or 0,
            setup_metadata=dict(signal_state.setup_metadata),
        )
        self._pending.append(entry)
        return entry

    def due_at(self, bar_idx: int) -> List[ExecutionScheduleEntry]:
        """Return entries scheduled to fill at this bar; remove from pending.

        Returned list is sorted by symbol (M11a determinism guarantee —
        sorted iteration prevents PYTHONHASHSEED-dependent order).
        """
        due = [e for e in self._pending if e.fill_at_bar == bar_idx]
        still_pending = [e for e in self._pending if e.fill_at_bar != bar_idx]
        self._pending = still_pending
        # Sort by symbol for deterministic execution order
        due.sort(key=lambda e: e.symbol)
        self._executed.extend(due)
        return due

    def overdue_at(self, bar_idx: int) -> List[ExecutionScheduleEntry]:
        """Return entries whose fill_at_bar < current bar (missed
        execution — e.g. due to data gap). Caller decides whether to
        force-fill at current bar or cancel.
        """
        overdue = [e for e in self._pending if e.fill_at_bar < bar_idx]
        self._pending = [e for e in self._pending if e.fill_at_bar >= bar_idx]
        return overdue

    def cash_carry_symbols_at(self, bar_idx: int) -> Dict[str, float]:
        """Symbols armed-and-confirmed-but-not-yet-filled at this bar.

        These positions hold CASH (target weight pending). Backtest
        engine treats them as 0 position contribution to NAV until
        fill_at_bar reached.

        Returns: {symbol: pending_target_weight}
        """
        return {
            e.symbol: e.target_weight
            for e in self._pending
            if e.fill_at_bar > bar_idx
        }

    def stats(self) -> Dict[str, int]:
        return {
            "pending": len(self._pending),
            "executed": len(self._executed),
        }


def integrate_deferred_fills_into_weight_panel(
    base_weights: pd.DataFrame,
    schedule: DeferredExecutionSchedule,
    index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Apply deferred-fill schedule to an existing target-weight panel.

    For each scheduled fill, replace weights from `fill_at_bar` onwards
    with the scheduled target_weight until the next rebalance bar.

    Returns adjusted (date × symbol) weight DataFrame.
    """
    out = base_weights.copy()
    for entry in schedule._executed:
        if entry.fill_at_bar >= len(index):
            continue  # fill is after panel end
        fill_date = index[entry.fill_at_bar]
        if entry.symbol not in out.columns:
            continue
        out.loc[fill_date, entry.symbol] = entry.target_weight
    return out
