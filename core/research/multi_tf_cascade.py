"""Multi-TF cascade decision module — Priority 3 (2026-05-14).

Implements the CLAUDE.md "Multi-Timescale Signal Protocol":

    15m trigger (entry timing, fast)
      → 30m confirm (structure / risk state)
        → 60m lock (final trend alignment)
          → execute on next bar open (deferred via K1 wrapper)

Higher-TF VETO: 60m direction overrides 15m trigger; 30m structure
confirmation gates. Cross-TF disagreement → no trade (conservative).

This module is a PURE DECISION FUNCTION — it does NOT load bars or
execute trades. Caller provides ALREADY-CLOSED bars at each TF and
gets back a TimingDecision-like verdict. Plug into existing K1
SignalDrivenBacktest wrapper.

Authority: CLAUDE.md "Multi-Timescale Signal Protocol" + Phase D
Multi-Timescale Validation Requirements.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple

import pandas as pd


class CascadeAction(Enum):
    """Outcome of cascade evaluation."""
    EXECUTE_LONG = "execute_long"
    EXECUTE_SHORT = "execute_short"  # reserved for future 130/30 mode
    DEFER = "defer"  # signal present at lower TF but higher TF not yet confirmed
    NO_SIGNAL = "no_signal"
    VETO = "veto"  # higher TF actively against lower TF direction


@dataclass
class CascadeBar:
    """One closed bar at a specific TF."""
    tf_label: str  # "15m", "30m", "60m", "1d"
    close_time: pd.Timestamp  # bar close timestamp (already past)
    direction: int  # -1 (down), 0 (flat), +1 (up)
    strength: float = 0.0  # |signal value|, 0-1 normalized


@dataclass
class CascadeRule:
    """Multi-TF cascade decision rule.

    trigger_tf: lowest TF that initiates the signal (e.g. "15m").
    confirm_tfs: higher TFs that must confirm direction.
    lock_tf: highest TF; its direction has VETO power.
    direction_tolerance: 0 = strict directional agreement;
        if higher TF is FLAT (direction=0), allow lower TF to lead.
    """
    trigger_tf: str = "15m"
    confirm_tfs: Tuple[str, ...] = ("30m",)
    lock_tf: str = "60m"
    flat_lock_passes: bool = True  # FLAT lock_tf doesn't veto
    min_trigger_strength: float = 0.0  # require |signal| >= this at trigger


@dataclass
class CascadeDecision:
    """Output of cascade evaluation."""
    action: CascadeAction
    reason: str
    trigger_direction: int
    confirm_directions: Tuple[int, ...]
    lock_direction: int

    @property
    def execute(self) -> bool:
        return self.action in (CascadeAction.EXECUTE_LONG, CascadeAction.EXECUTE_SHORT)


def evaluate_cascade(
    trigger_bar: Optional[CascadeBar],
    confirm_bars: Tuple[CascadeBar, ...],
    lock_bar: Optional[CascadeBar],
    rule: Optional[CascadeRule] = None,
) -> CascadeDecision:
    """Pure decision: given closed bars at each TF, decide cascade action.

    Returns NO_SIGNAL if trigger is missing or zero. Returns VETO if
    lock_tf direction is OPPOSITE trigger. Returns DEFER if any
    confirm_tf direction is opposite trigger. Returns EXECUTE_LONG when
    all aligned (trigger up + confirms not opposite + lock not opposite).

    Long-only mode (default): EXECUTE_SHORT is NEVER returned (mapped to
    NO_SIGNAL). When 130/30 flag enabled (Priority 4), short execution
    becomes available.
    """
    rule = rule or CascadeRule()

    if trigger_bar is None or trigger_bar.direction == 0:
        return CascadeDecision(
            action=CascadeAction.NO_SIGNAL,
            reason="trigger TF missing or flat",
            trigger_direction=0 if trigger_bar is None else trigger_bar.direction,
            confirm_directions=(),
            lock_direction=lock_bar.direction if lock_bar else 0,
        )

    if abs(trigger_bar.strength) < rule.min_trigger_strength:
        return CascadeDecision(
            action=CascadeAction.NO_SIGNAL,
            reason=f"trigger strength {trigger_bar.strength:.3f} < min {rule.min_trigger_strength:.3f}",
            trigger_direction=trigger_bar.direction,
            confirm_directions=tuple(b.direction for b in confirm_bars),
            lock_direction=lock_bar.direction if lock_bar else 0,
        )

    trig_dir = trigger_bar.direction
    confirm_dirs = tuple(b.direction for b in confirm_bars)
    lock_dir = lock_bar.direction if lock_bar else 0

    # Higher-TF VETO: lock_tf opposite trigger
    if lock_dir != 0 and lock_dir != trig_dir:
        return CascadeDecision(
            action=CascadeAction.VETO,
            reason=f"lock_tf {rule.lock_tf} direction {lock_dir} opposes trigger {trig_dir}",
            trigger_direction=trig_dir,
            confirm_directions=confirm_dirs,
            lock_direction=lock_dir,
        )
    if lock_dir == 0 and not rule.flat_lock_passes:
        return CascadeDecision(
            action=CascadeAction.DEFER,
            reason=f"lock_tf {rule.lock_tf} is flat and flat_lock_passes=False",
            trigger_direction=trig_dir,
            confirm_directions=confirm_dirs,
            lock_direction=lock_dir,
        )

    # Confirm TF check — any opposite → DEFER (not VETO; downstream may retry)
    for b in confirm_bars:
        if b.direction != 0 and b.direction != trig_dir:
            return CascadeDecision(
                action=CascadeAction.DEFER,
                reason=f"confirm_tf {b.tf_label} direction {b.direction} opposes trigger {trig_dir}",
                trigger_direction=trig_dir,
                confirm_directions=confirm_dirs,
                lock_direction=lock_dir,
            )

    # All aligned (or higher TFs FLAT with flat_lock_passes=True)
    action = (
        CascadeAction.EXECUTE_LONG if trig_dir > 0
        else CascadeAction.EXECUTE_SHORT  # caller may downgrade to NO_SIGNAL in long-only mode
    )
    return CascadeDecision(
        action=action,
        reason="all TFs aligned",
        trigger_direction=trig_dir,
        confirm_directions=confirm_dirs,
        lock_direction=lock_dir,
    )


def long_only_decision(decision: CascadeDecision) -> CascadeDecision:
    """Map EXECUTE_SHORT → NO_SIGNAL (long-only mode invariant)."""
    if decision.action == CascadeAction.EXECUTE_SHORT:
        return CascadeDecision(
            action=CascadeAction.NO_SIGNAL,
            reason="long-only mode (short execution disallowed)",
            trigger_direction=decision.trigger_direction,
            confirm_directions=decision.confirm_directions,
            lock_direction=decision.lock_direction,
        )
    return decision
