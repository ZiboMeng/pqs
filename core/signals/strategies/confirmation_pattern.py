"""ConfirmationPatternStrategy — setup-then-trigger / TTL-gated entries.

PRD-driven 2026-05-12 per
`docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md`.

Mechanism:
  1. SETUP detection: at each bar, scan universe for a pattern that
     "arms" a signal (e.g. breakout above 20d high, volume gate,
     consolidation finish).
  2. ARMED state: signal sits in queue with TTL = N bars. State
     tracked via `core.signals.signal_state.SignalStateMachine`.
  3. CONFIRMATION check: at subsequent bars, evaluate predicate; if
     met within TTL → fire entry (target weight); if TTL expires →
     discard.
  4. Position: equal-weight top-K confirmed signals at each bar.

This is the MVP (§3.1 same-bar AND-gate + §3.2 multi-bar TTL).
Multi-phase patterns (§3.3) are out of scope.

Deferred-execution backtest extension lives in
`core/backtest/backtest_engine.py` (not in this file) — see PRD §4.1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from core.signals.signal_state import (
    SignalStateMachine, SignalStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class ConfirmationPatternConfig:
    """Hyperparameters for confirmation pattern strategy.

    Matches the `ConfirmationPatternSpace.sample()` schema in PRD §4.2."""
    arm_type: str = "breakout_high_n"
    setup_lookback_days: int = 20
    confirmation_ttl_bars: int = 5
    confirmation_threshold_pct: float = 1.0
    volume_multiplier: float = 1.5
    top_n: int = 5
    rebalance_monthly: bool = False


# ── Setup detectors ──

def _detect_breakout_high(
    price_at_t: pd.Series,
    rolling_max: pd.Series,
) -> pd.Series:
    """Boolean per-symbol: close > prior N-day max → setup armed.

    `rolling_max` = max(close, N) shifted by 1 (no same-bar lookahead).
    """
    return price_at_t > rolling_max


def _detect_volume_gate_same_bar(
    price_change_pct: pd.Series,
    volume_ratio_at_t: pd.Series,
    threshold_pct: float,
    vol_mult: float,
) -> pd.Series:
    """Boolean: today's return > threshold AND volume > avg × mult.

    For arm_type='volume_gate_same_bar', this returns the signal directly
    (no state machine; ttl_bars semantically 0 — same bar fires)."""
    return (price_change_pct > threshold_pct / 100.0) & (
        volume_ratio_at_t > vol_mult
    )


# ── Confirmation predicates ──

def _confirmation_close_above_setup(
    state, current_close: pd.Series, threshold_pct: float,
) -> bool:
    """For breakout setup: current close > setup price by threshold_pct."""
    setup_price = state.setup_metadata.get("setup_price")
    if setup_price is None:
        return False
    current = current_close.get(state.symbol)
    if current is None or pd.isna(current):
        return False
    return current >= setup_price * (1 + threshold_pct / 100.0)


# ── Strategy class ──


class ConfirmationPatternStrategy:
    """Setup-then-trigger strategy with TTL window.

    Per PRD MVP §3.1 (same-bar gate) and §3.2 (multi-bar TTL).
    """

    def __init__(self, config: Optional[ConfirmationPatternConfig] = None):
        self.config = config or ConfirmationPatternConfig()

    def generate(
        self,
        price_df: pd.DataFrame,
        volume_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Return (date × symbol) target weight DataFrame, range [0, 1].

        Each row sums to ≤ 1 (cash residual when fewer than top_n
        active signals).
        """
        cfg = self.config
        N = cfg.setup_lookback_days
        weights = pd.DataFrame(0.0, index=price_df.index, columns=price_df.columns)

        # Pre-compute rolling max (shifted by 1 to prevent same-bar lookahead)
        rolling_max = price_df.rolling(N).max().shift(1)
        # Volume avg (for volume gate)
        if volume_df is not None:
            vol_avg = volume_df.rolling(N).mean().shift(1)
            vol_ratio = volume_df / vol_avg.replace(0, np.nan)
        else:
            vol_ratio = None

        machine = SignalStateMachine()

        for bar_idx, ts in enumerate(price_df.index):
            close_at_t = price_df.iloc[bar_idx]
            # ── 1. Arm new signals at this bar (setup detection) ──
            if cfg.arm_type == "breakout_high_n":
                rmax_t = rolling_max.iloc[bar_idx]
                triggered = (close_at_t > rmax_t).fillna(False)
                for sym, fired in triggered.items():
                    if fired:
                        machine.arm(
                            symbol=sym, bar_idx=bar_idx,
                            ttl_bars=cfg.confirmation_ttl_bars,
                            setup_metadata={
                                "setup_price": float(close_at_t[sym]),
                                "setup_bar": ts,
                            },
                        )
            elif cfg.arm_type == "volume_gate_same_bar":
                if vol_ratio is None or bar_idx == 0:
                    continue
                prev_close = price_df.iloc[bar_idx - 1]
                ret = (close_at_t - prev_close) / prev_close.replace(0, np.nan)
                gated = _detect_volume_gate_same_bar(
                    ret, vol_ratio.iloc[bar_idx],
                    cfg.confirmation_threshold_pct, cfg.volume_multiplier,
                ).fillna(False)
                # Same-bar fire: arm + confirm same bar
                for sym, fired in gated.items():
                    if fired:
                        s = machine.arm(
                            symbol=sym, bar_idx=bar_idx,
                            ttl_bars=0,
                            setup_metadata={"setup_price": float(close_at_t[sym])},
                        )

            # ── 2. Advance & confirm signals ──
            # For volume_gate_same_bar (ttl=0), the volume + return
            # gate IS the confirmation — same-bar fire. For breakout
            # (ttl>0), wait for close to push setup_price × threshold.
            if cfg.arm_type == "volume_gate_same_bar":
                confirmation_predicate = lambda state: True
            else:
                confirmation_predicate = (
                    lambda state: _confirmation_close_above_setup(
                        state, close_at_t,
                        cfg.confirmation_threshold_pct,
                    )
                )
            fired = machine.advance_and_confirm(
                bar_idx,
                confirmation_check=confirmation_predicate,
            )
            # ── 3. Set weights: top_n equal-weight on confirmed signals ──
            # Strategy collects confirmed signals over recent K bars; for
            # MVP each bar's weight is just the current-bar fires (no
            # cumulative position book). Real backtest layer extends to
            # multi-bar holding.
            if fired:
                # Equal-weight, capped at top_n
                fired_syms = [s.symbol for s in fired[:cfg.top_n]]
                w = 1.0 / max(len(fired_syms), 1)
                for sym in fired_syms:
                    if sym in weights.columns:
                        weights.loc[ts, sym] = w

        return weights
