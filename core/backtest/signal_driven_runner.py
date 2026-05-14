"""SignalDrivenBacktest — wrapper over BacktestEngine for signal-driven execution.

PRD: docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md §4.1
Design: docs/audit/20260513-k1_deferred_exec_design.md

K1 deliverable: a higher-level wrapper that drives the existing pure-Python
kernel (`SignalStateMachine` + `DeferredExecutionSchedule`) against actual
price data, builds a weight panel from confirmed fills + exit signals, and
delegates to `BacktestEngine.run` for NAV computation.

Architectural choice (K1.1 design audit §1-§2): we do NOT modify
`BacktestEngine.run` itself — this preserves M11a/M11b parity bit-for-bit
for all existing cycle04-10 backtests. Signal-driven semantics are
expressed as a (date × symbol) weight panel that the existing engine
consumes through its standard `signals_df` argument.

Lifecycle per bar:
  1. ARM: scan entry_signals[bar] → add ARMED SignalState to machine
  2. CONFIRM: advance_and_confirm via confirmation_predicate
     (or default: ttl=0 auto-confirm same-bar, ttl>0 wait for explicit True)
  3. SCHEDULE: for each new CONFIRMED state, compute target_weight via
     position_sizing_rule (or default equal-weight 1/top_n) → schedule fill
     for bar + execution_delay_bars
  4. FILL: schedule.due_at(bar) → apply target_weights to live_positions
     (subject to top_n + max_single_weight constraints)
  5. EXIT: scan exit_signals[bar] → schedule exit for next bar (executed
     via pending_exits dict, mirrors T+1 fill convention)
  6. PROCESS EXITS: pending_exits.pop(bar) → remove from live_positions
  7. RECORD: weight_panel.loc[date] = live_positions

After all bars processed, call BacktestEngine.run(signals_df=weight_panel,
price_df=price_df, ...) for actual NAV computation.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestEngine, BacktestResult
from core.execution.cost_model import CostModel
from core.config.schemas.cost_model import CostModelConfig
from core.backtest.deferred_execution import DeferredExecutionSchedule
from core.signals.signal_state import (
    SignalState, SignalStateMachine, SignalStatus,
)


# Callable signatures
# - confirmation_predicate(state, bar_idx, ctx) -> bool
# - position_sizing_rule(state, bar_idx, ctx) -> float (target weight)
ConfirmationPredicate = Callable[[SignalState, int, Dict], bool]
PositionSizingRule = Callable[[SignalState, int, Dict], float]


def _default_cost_model() -> CostModel:
    """Zero-cost default (single 'default' tier with all bps = 0)."""
    from core.config.schemas.cost_model import CostTierConfig
    config = CostModelConfig(
        tiers={
            "default": CostTierConfig(
                symbols=[],
                commission_bps=0.0,
                slippage_interday_bps=0.0,
                slippage_intraday_bps=0.0,
            )
        }
    )
    return CostModel(config)


class SignalDrivenBacktest:
    """Drive BacktestEngine via entry/exit signal predicates.

    See module docstring for algorithm; see K1.1 design memo §3 for state machine spec.
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
        open_df: Optional[pd.DataFrame] = None,
    ):
        # ---- Validation (eagerly raise per K1.1 §2 contract) ----
        if not entry_signals.index.equals(exit_signals.index):
            raise ValueError(
                "entry_signals and exit_signals must have identical indices"
            )
        if ttl_bars < 0:
            raise ValueError("ttl_bars must be >= 0")
        if top_n <= 0:
            raise ValueError("top_n must be >= 1")

        # ---- Store params ----
        self.entry_signals = entry_signals.astype(bool)
        self.exit_signals = exit_signals.astype(bool)
        self.price_df = price_df
        self.ttl_bars = ttl_bars
        self.top_n = top_n
        self.confirmation_predicate = confirmation_predicate
        self.position_sizing_rule = position_sizing_rule
        self.cost_model = cost_model
        self.initial_capital = initial_capital
        self.execution_delay_bars = execution_delay_bars
        self.max_single_weight = max_single_weight
        self.cluster_cap = cluster_cap
        self.open_df = open_df

        # ---- Internal state (populated during run()) ----
        self._machine = SignalStateMachine()
        self._schedule = DeferredExecutionSchedule(
            execution_delay_bars=execution_delay_bars
        )
        # pending_exits: {bar_idx_when_exit_executes: [list of syms to exit]}
        self._pending_exits: Dict[int, List[str]] = {}
        self._weight_panel: Optional[pd.DataFrame] = None
        self._result: Optional[BacktestResult] = None
        # live_positions during run loop: {sym: weight}
        self._live_positions: Dict[str, float] = {}

    # ── Internal helpers ─────────────────────────────────────────────────

    def _default_predicate(self, state: SignalState, bar_idx: int) -> bool:
        """Default confirmation logic.

        If user predicate provided → delegate. Else:
          - ttl_bars == 0 → auto-confirm same-bar (volume-gate §3.1 pattern)
          - ttl_bars > 0 → never auto-confirm (signal will EXPIRE per state machine)
        """
        if self.confirmation_predicate is not None:
            ctx = self._build_ctx(bar_idx)
            return bool(self.confirmation_predicate(state, bar_idx, ctx))
        # No user predicate
        if self.ttl_bars == 0 and state.armed_at_bar == bar_idx:
            return True
        return False

    def _build_ctx(self, bar_idx: int) -> Dict:
        """Build the ctx dict passed to user predicates.

        ctx exposes data ONLY up to bar_idx inclusive (leakage discipline R3).
        """
        return {
            "price_df_so_far": self.price_df.iloc[: bar_idx + 1],
            "bar_idx": bar_idx,
        }

    def _compute_target_weight(self, state: SignalState, bar_idx: int) -> float:
        """Compute target weight at fill scheduling time."""
        if self.position_sizing_rule is not None:
            ctx = self._build_ctx(bar_idx)
            return float(self.position_sizing_rule(state, bar_idx, ctx))
        # Default equal-weight
        w = 1.0 / self.top_n
        if self.max_single_weight is not None:
            w = min(w, self.max_single_weight)
        return w

    def _apply_caps(self, raw_positions: Dict[str, float]) -> Dict[str, float]:
        """Enforce top_n + max_single_weight on the live_positions dict.

        - Drop to top_n positions (lower-priority dropped — for ties, alphabetic).
        - Clip each weight to max_single_weight if set.
        - M11a determinism: sorted iteration.
        """
        if not raw_positions:
            return {}

        # Apply max_single_weight clip
        if self.max_single_weight is not None:
            clipped = {
                s: min(w, self.max_single_weight)
                for s, w in raw_positions.items()
            }
        else:
            clipped = dict(raw_positions)

        # Drop to top_n: stable sort by (-weight, sym) for M11a determinism
        if len(clipped) <= self.top_n:
            return dict(sorted(clipped.items()))
        sorted_items = sorted(clipped.items(), key=lambda kv: (-kv[1], kv[0]))
        kept = dict(sorted_items[: self.top_n])
        return dict(sorted(kept.items()))

    # ── Main loop ────────────────────────────────────────────────────────

    def run(self) -> BacktestResult:
        """Drive the signal state machine through bars and produce a BacktestResult.

        Returns the BacktestResult from underlying BacktestEngine.run().
        """
        # ---- Setup ----
        dates = self.entry_signals.index
        symbols = sorted(set(self.entry_signals.columns) | set(self.price_df.columns))

        # Weight panel: (date × symbol) all zeros initially
        weight_panel = pd.DataFrame(0.0, index=dates, columns=symbols)

        # ---- Per-bar loop ----
        for bar_idx, date in enumerate(dates):
            # Step 1: ARM new signals from entry_signals[date]
            if date in self.entry_signals.index:
                row = self.entry_signals.loc[date]
                # Sorted iteration for M11a determinism
                for sym in sorted(row.index):
                    if bool(row.get(sym, False)):
                        self._machine.arm(sym, bar_idx=bar_idx, ttl_bars=self.ttl_bars)

            # Step 2: CONFIRM — advance state machine
            fired = self._machine.advance_and_confirm(
                bar_idx,
                lambda state, _bi=bar_idx: self._default_predicate(state, _bi),
            )

            # Step 3: SCHEDULE fills for newly confirmed signals (sorted by sym for M11a)
            for state in sorted(fired, key=lambda s: s.symbol):
                tgt_w = self._compute_target_weight(state, bar_idx)
                # Skip if fill would land after last bar
                fill_at = bar_idx + self.execution_delay_bars
                if fill_at >= len(dates):
                    continue
                self._schedule.schedule_fill(state, target_weight=tgt_w)

            # Step 4: FILL — apply due fills (entries land here)
            due = self._schedule.due_at(bar_idx)
            if due:
                # Pending new positions to merge with current live_positions
                # then re-apply caps
                proposed = dict(self._live_positions)
                for entry in due:
                    proposed[entry.symbol] = entry.target_weight
                self._live_positions = self._apply_caps(proposed)

            # Step 5: Schedule EXITS for next bar (T+1 convention)
            if date in self.exit_signals.index:
                row = self.exit_signals.loc[date]
                exit_bar = bar_idx + 1
                for sym in sorted(row.index):
                    if bool(row.get(sym, False)) and sym in self._live_positions:
                        self._pending_exits.setdefault(exit_bar, []).append(sym)

            # Step 6: PROCESS EXITS due this bar
            for sym in sorted(self._pending_exits.pop(bar_idx, [])):
                self._live_positions.pop(sym, None)

            # Step 7: RECORD weights for this bar (after all updates)
            for sym, w in self._live_positions.items():
                if sym in weight_panel.columns:
                    weight_panel.loc[date, sym] = w

        # ---- Cache panel + delegate to BacktestEngine ----
        self._weight_panel = weight_panel

        # Build BacktestEngine with provided or default cost model
        cost = self.cost_model or _default_cost_model()
        engine = BacktestEngine(
            cost_model=cost,
            initial_capital=self.initial_capital,
        )
        # signals_df = weight_panel; price_df + open_df pass through
        # Subset price_df to the same column union for safety
        price_aligned = self.price_df.reindex(columns=symbols, fill_value=np.nan)
        open_aligned = (
            self.open_df.reindex(columns=symbols, fill_value=np.nan)
            if self.open_df is not None
            else None
        )
        result = engine.run(
            signals_df=weight_panel,
            price_df=price_aligned,
            open_df=open_aligned,
        )
        self._result = result
        return result

    # ── Public accessors ─────────────────────────────────────────────────

    def signal_history(self) -> List[SignalState]:
        """Return all signals processed (active + terminal)."""
        return (
            list(self._machine.active_signals())
            + list(self._machine.terminal_history())
        )

    def weight_panel(self) -> pd.DataFrame:
        """Return the (date × symbol) weight panel produced by run()."""
        if self._weight_panel is None:
            raise RuntimeError("run() must be called before weight_panel()")
        return self._weight_panel
