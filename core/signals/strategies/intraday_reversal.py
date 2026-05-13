"""Intraday reversal strategy (alt-archetype A Phase 1 skeleton).

PRD: `docs/prd/20260512-alt_archetype_intraday_reversal_prd.md`
Lineage: `alt-archetype-intraday-reversal-2026-05-12`

Phase 1 SKELETON ONLY (this file):
  - Strategy class + config dataclass
  - Setup detection logic (weekly reversal + overnight gap filter)
  - Confirmation predicate (intraday volume + early-session direction)
  - Returns target weights at daily rebalance frequency

Phase 2 (1 week eng, DEFERRED):
  - deferred-execution × BacktestEngine integration (Family Q signal-conf
    MVP shares this plumbing)
  - 60m bar fill-timing (T+1 first-60m-bar-close per PRD §11 open question)

Phase 3 (DEFERRED):
  - Track A acceptance pack on validation years 2018/19/21/23/25
  - Anti-sibling NAV correlation vs RCMv1 / Cand-2 / Trial 9 v2 /
    cycle #09 nominee (if exists)

Per PRD §11 open directional questions, the following are PLACEHOLDER
defaults pending user explicit-go:
  - universe scope: 53-stock cycle04+ (broader than top-30 liquid)
  - holding period: 5d hard cap
  - entry timing: first-60m-bar-close (T+1 10:30 ET)
  - cost model: 2.5bp slip + commission

Integration depends on:
  - `core/signals/signal_state.SignalStateMachine` (state machine, exists)
  - `core/factors/signal_confirmation_factors.compute_signal_confirmation_factors`
    (5 multi-bar factors, exists)
  - `core/backtest/deferred_execution.DeferredExecutionSchedule` (kernel,
    exists; BacktestEngine integration deferred)

This file imports the above so import-time errors signal infra rot.
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
from core.backtest.deferred_execution import (
    DeferredExecutionSchedule, ExecutionScheduleEntry,
)

logger = logging.getLogger(__name__)


@dataclass
class IntradayReversalConfig:
    """Hyperparameters for intraday reversal strategy.

    All defaults match PRD §3 placeholder values; user explicit-go on §11
    open directional questions can override.
    """
    # Universe scope (PRD §11 Q1)
    universe_top_n_dollar_volume: Optional[int] = None  # None = use full universe

    # Setup detection (PRD §3)
    # weekly_reversal_signal_5d ≤ 5th percentile = setup armed
    setup_quantile_threshold: float = 0.05
    # vol_21d minimum percentile (filter microcap-like behavior)
    vol_filter_min_pct: float = 0.30

    # Confirmation (intraday volume + early-session direction)
    volume_surge_at_open_60m_min: float = 1.5  # vs 20d avg
    confirmation_ttl_bars: int = 1  # next bar (T+1 first-60m-close)

    # Sizing
    top_n: int = 5
    equal_weight: bool = True

    # Holding (PRD §11 Q2)
    holding_period_max_days: int = 5
    stop_loss_sigma: float = 0.5  # opposite-direction move triggers exit

    # Execution (PRD §11 Q3 + Q4)
    execution_delay_bars: int = 1  # T+1 first-60m-bar-close fill
    cost_slip_bps_per_leg: float = 2.5
    cost_commission_bps_per_trade: float = 0.5


class IntradayReversalStrategy:
    """Setup-then-confirm intraday reversal strategy.

    Phase 1 SKELETON: produces daily target weights based on T-day setup
    detection + T+1 morning confirmation. Phase 2 will wire this through
    DeferredExecutionSchedule + BacktestEngine.

    Per PRD §3, this is a DAILY-rebalance strategy with intraday execution
    timing — NOT a daily-only top-N selector (that's cycle04-08's pattern
    and produces sibling). The intraday confirmation is what breaks the
    sibling geometry.

    Phase 1 returns target weights ONLY for confirmed signals; cash carry
    (armed-but-not-confirmed positions) is handled by DeferredExecutionSchedule
    in Phase 2.

    Usage (Phase 1):
        strat = IntradayReversalStrategy()
        signals = strat.detect_setups(price_df, volume_df, T_date)
        confirmed = strat.confirm_signals(signals, intraday_volume_60m, T_plus_1)
        weights = strat.build_target_weights(confirmed)

    Usage (Phase 2, when integration ships):
        # BacktestEngine.run(strategy=IntradayReversalStrategy(...)) with
        # deferred-execution schedule wiring.
    """

    def __init__(self, config: Optional[IntradayReversalConfig] = None):
        self.config = config or IntradayReversalConfig()
        self.machine = SignalStateMachine()
        self.schedule = DeferredExecutionSchedule(
            execution_delay_bars=self.config.execution_delay_bars,
        )

    def detect_setups(
        self,
        weekly_reversal_signal_5d: pd.DataFrame,
        vol_21d: pd.DataFrame,
        as_of_date: pd.Timestamp,
    ) -> List[str]:
        """Identify symbols whose weekly_reversal_signal_5d is in bottom
        quantile (= candidate reversal setup) AND vol_21d above filter.

        Returns list of symbols (subset of weekly_reversal_signal_5d columns).
        """
        if as_of_date not in weekly_reversal_signal_5d.index:
            return []
        wr_row = weekly_reversal_signal_5d.loc[as_of_date].dropna()
        vol_row = vol_21d.loc[as_of_date].dropna() if as_of_date in vol_21d.index else pd.Series(dtype=float)

        if wr_row.empty:
            return []

        # Setup quantile threshold on weekly_reversal_signal_5d
        setup_threshold = wr_row.quantile(self.config.setup_quantile_threshold)
        setup_candidates = wr_row[wr_row <= setup_threshold].index.tolist()

        # Filter by vol_21d minimum percentile
        if not vol_row.empty and self.config.vol_filter_min_pct > 0:
            vol_threshold = vol_row.quantile(self.config.vol_filter_min_pct)
            setup_candidates = [
                s for s in setup_candidates
                if s in vol_row.index and vol_row[s] >= vol_threshold
            ]

        return setup_candidates

    def confirm_signals(
        self,
        armed_symbols: List[str],
        intraday_volume_60m_zscore: pd.Series,
        early_session_return_pct: pd.Series,
    ) -> List[str]:
        """Apply confirmation predicate to armed setups.

        Confirmation requires:
          - intraday volume z-score at open 60m > volume_surge_at_open_60m_min
          - early-session return direction CONSISTENT with reversal direction
            (i.e., positive return — confirming bounce off setup low)

        Returns subset of armed_symbols that pass confirmation.
        """
        confirmed = []
        for sym in armed_symbols:
            vol_z = intraday_volume_60m_zscore.get(sym)
            ret = early_session_return_pct.get(sym)
            if vol_z is None or pd.isna(vol_z):
                continue
            if ret is None or pd.isna(ret):
                continue
            if (
                vol_z >= self.config.volume_surge_at_open_60m_min
                and ret > 0.0
            ):
                confirmed.append(sym)
        return confirmed

    def build_target_weights(
        self,
        confirmed_symbols: List[str],
    ) -> Dict[str, float]:
        """Equal-weight top-N over confirmed reversal candidates.

        Returns dict[symbol → target weight]. Empty if no confirmed.
        """
        if not confirmed_symbols:
            return {}
        # Top-N truncation; sort alphabetically for M11a determinism
        chosen = sorted(confirmed_symbols)[: self.config.top_n]
        if self.config.equal_weight and chosen:
            w = 1.0 / len(chosen)
            return {sym: w for sym in chosen}
        return {sym: 1.0 / len(chosen) for sym in chosen}

    def step_day(
        self,
        bar_idx: int,
        weekly_reversal_signal_5d: pd.DataFrame,
        vol_21d: pd.DataFrame,
        intraday_volume_60m_zscore: pd.Series,
        early_session_return_pct: pd.Series,
        as_of_date: pd.Timestamp,
    ) -> Dict[str, float]:
        """One-bar step: detect setups, arm state machine, confirm,
        schedule fills via DeferredExecutionSchedule.

        Returns final target weights (deferred fills excluded; cash carry
        handled by self.schedule).

        Phase 1: this returns DRY-RUN target weights without invoking
        BacktestEngine. Phase 2 will wire this method through the engine's
        rebalance loop.
        """
        # Step 1: detect setups (ARM)
        setups = self.detect_setups(weekly_reversal_signal_5d, vol_21d, as_of_date)
        for sym in setups:
            self.machine.arm(
                symbol=sym, bar_idx=bar_idx,
                ttl_bars=self.config.confirmation_ttl_bars,
            )

        # Step 2: advance + apply confirmation predicate
        confirmed_subset = self.confirm_signals(
            setups, intraday_volume_60m_zscore, early_session_return_pct,
        )
        # Mark confirmation in state machine. The returned `fired` list
        # contains SignalState objects that transitioned to CONFIRMED at
        # this bar — use them directly (no get() lookup needed).
        confirmation_predicate = lambda state: state.symbol in confirmed_subset
        confirmed_states = self.machine.advance_and_confirm(
            bar_idx, confirmation_predicate,
        )

        # Step 3: schedule fills (deferred-execution)
        confirmed_by_sym = {s.symbol: s for s in confirmed_states}
        weights = self.build_target_weights(list(confirmed_by_sym.keys()))
        for sym, w in weights.items():
            state = confirmed_by_sym.get(sym)
            if state is not None:
                self.schedule.schedule_fill(state, target_weight=w)

        return weights

    def get_pending_cash_carry(self, bar_idx: int) -> Dict[str, float]:
        """Symbols armed-but-not-yet-filled — their target weight is held
        as cash until DeferredExecutionSchedule.due_at(bar_idx) fires."""
        return self.schedule.cash_carry_symbols_at(bar_idx)
