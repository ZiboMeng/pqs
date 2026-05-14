"""SignalDrivenBacktest — wrapper over BacktestEngine for signal-driven execution.

PRD: docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md §4.1
Design: docs/audit/20260513-k1_deferred_exec_design.md

This module is the K1 deliverable: a higher-level wrapper that drives the
existing pure-Python kernel (`SignalStateMachine` + `DeferredExecutionSchedule`)
against actual price data, builds a weight panel from confirmed fills + exit
signals, and delegates to `BacktestEngine.run` for NAV computation.

Architectural choice (K1.1 design audit §1-§2): we do NOT modify
`BacktestEngine.run` itself — this preserves M11a/M11b parity bit-for-bit
for all existing cycle04-10 backtests. Signal-driven semantics are
expressed as a (date × symbol) weight panel that the existing engine
consumes through its standard `signals_df` argument.

K1.2 STATUS (this file): STUB. All methods raise NotImplementedError.
30 RED tests in tests/unit/backtest/test_signal_driven_runner.py
will fail with NotImplementedError until K1.3 lands the real impl.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

import pandas as pd

from core.backtest.backtest_engine import BacktestEngine, BacktestResult
from core.execution.cost_model import CostModel
from core.backtest.deferred_execution import DeferredExecutionSchedule
from core.signals.signal_state import (
    SignalState, SignalStateMachine, SignalStatus,
)


# Callable signatures
ConfirmationPredicate = Callable[[SignalState, int, Dict], bool]
PositionSizingRule = Callable[[SignalState, int, Dict], float]


class SignalDrivenBacktest:
    """Drive BacktestEngine via entry/exit signal predicates.

    K1.3 implementation TODO. Stub raises NotImplementedError.
    """

    def __init__(
        self,
        entry_signals: pd.DataFrame,
        exit_signals: pd.DataFrame,
        price_df: pd.DataFrame,
        ttl_bars: int = 0,
        top_n: int = 10,
        confirmation_predicate: Optional[ConfirmationPredicate] = None,
        position_sizing_rule: Optional[PositionSizingRule] = None,
        cost_model: Optional[CostModel] = None,
        initial_capital: float = 100_000.0,
        execution_delay_bars: int = 1,
        max_single_weight: Optional[float] = None,
        cluster_cap: Optional[float] = None,
    ):
        # ---- Validation (eagerly raise per K1.1 §2 contract) ----
        if not entry_signals.index.equals(exit_signals.index):
            raise ValueError(
                "entry_signals and exit_signals must have identical indices"
            )
        if ttl_bars < 0:
            raise ValueError("ttl_bars must be >= 0")

        # ---- Store params ----
        self.entry_signals = entry_signals
        self.exit_signals = exit_signals
        self.price_df = price_df
        self.ttl_bars = ttl_bars
        self.top_n = top_n
        self.confirmation_predicate = confirmation_predicate
        self.position_sizing_rule = position_sizing_rule
        # Cost model: if None, defer construction (K1.3 builds default at run() time)
        self.cost_model = cost_model
        self.initial_capital = initial_capital
        self.execution_delay_bars = execution_delay_bars
        self.max_single_weight = max_single_weight
        self.cluster_cap = cluster_cap

        # ---- Internal state (populated during run()) ----
        self._machine = SignalStateMachine()
        self._schedule = DeferredExecutionSchedule(
            execution_delay_bars=execution_delay_bars
        )
        self._weight_panel: Optional[pd.DataFrame] = None
        self._result: Optional[BacktestResult] = None

    # ── Public API ───────────────────────────────────────────────────────

    def run(self) -> BacktestResult:
        """Drive the signal state machine through bars and produce a BacktestResult.

        K1.3 will implement. K1.2 stub raises so tests fail RED.
        """
        raise NotImplementedError(
            "K1.3 implementation pending — see docs/audit/20260513-k1_deferred_exec_design.md §8"
        )

    def signal_history(self) -> List[SignalState]:
        """Return all signals processed so far (active + terminal).

        Combined view of `machine.active_signals() + machine.terminal_history()`.
        K1.3 may override; default delegates to underlying machine.
        """
        return (
            list(self._machine.active_signals())
            + list(self._machine.terminal_history())
        )

    def weight_panel(self) -> pd.DataFrame:
        """Return the (date × symbol) weight panel produced by run().

        Raises if run() has not been called.
        """
        if self._weight_panel is None:
            raise RuntimeError("run() must be called before weight_panel()")
        return self._weight_panel
