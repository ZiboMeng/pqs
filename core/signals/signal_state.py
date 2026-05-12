"""Signal state machine for setup-then-trigger confirmation patterns.

PRD-driven 2026-05-12 per:
- docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md §4.1

State machine: ARMED → (CONFIRMED | EXPIRED).
  ARMED at bar T (setup pattern detected).
  Each subsequent bar T+1, T+2, ..., increment age.
  If confirmation pattern is met within TTL → CONFIRMED → fire entry signal.
  If age exceeds ttl_bars → EXPIRED → discard (no entry).

This module provides the pure-Python state machine — backtest /
mining wiring lives in core/backtest/backtest_engine.py extension.

Leakage rule (R3 audit requirement): at bar T+k decision time, only
data ≤ T+k may be inspected. Tests in
tests/unit/signals/test_signal_state.py enforce this invariant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class SignalStatus(Enum):
    ARMED = "armed"          # setup detected, awaiting confirmation
    CONFIRMED = "confirmed"  # fired → enter position
    EXPIRED = "expired"      # ttl exceeded without confirmation


@dataclass
class SignalState:
    """Single (symbol, setup_bar) signal in flight."""
    symbol: str
    armed_at_bar: int       # integer bar index when armed
    ttl_bars: int           # max bars to wait for confirmation (0 = same-bar)
    status: SignalStatus = SignalStatus.ARMED
    confirmed_at_bar: Optional[int] = None
    setup_metadata: Dict = field(default_factory=dict)

    @property
    def age(self) -> int:
        """Bars elapsed since arming. Caller must track current bar.

        For age calculation, see `SignalStateMachine.advance_bar`.
        """
        return self.armed_at_bar  # overridden in machine

    def is_active(self) -> bool:
        return self.status == SignalStatus.ARMED

    def is_terminal(self) -> bool:
        return self.status in (SignalStatus.CONFIRMED, SignalStatus.EXPIRED)


class SignalStateMachine:
    """Manages a collection of in-flight SignalStates across bars.

    Workflow:
      machine = SignalStateMachine()
      for bar_idx, bar in enumerate(bars):
          # 1. Arm new signals where setup is detected
          for sym in setups_detected(bar):
              machine.arm(sym, bar_idx, ttl_bars=5, setup_metadata={...})

          # 2. Advance & check confirmations
          fired = machine.advance_and_confirm(
              bar_idx,
              confirmation_check=lambda state: confirm_predicate(state, bar),
          )
          # `fired` is a list of states transitioned to CONFIRMED at this bar
          # `expired` states are auto-pruned by machine internally
    """

    def __init__(self):
        self._active: List[SignalState] = []
        self._terminal: List[SignalState] = []

    def arm(
        self,
        symbol: str,
        bar_idx: int,
        ttl_bars: int,
        setup_metadata: Optional[Dict] = None,
    ) -> SignalState:
        """Add a new ARMED signal for (symbol, bar_idx). Returns the state."""
        s = SignalState(
            symbol=symbol,
            armed_at_bar=bar_idx,
            ttl_bars=ttl_bars,
            setup_metadata=setup_metadata or {},
        )
        self._active.append(s)
        return s

    def advance_and_confirm(
        self,
        current_bar: int,
        confirmation_check,
    ) -> List[SignalState]:
        """For each active signal at `current_bar`:
          - If confirmation_check(state) → status=CONFIRMED, fire.
          - Elif current_bar - armed_at_bar >= ttl_bars → EXPIRED.
          - Else: continue armed.

        `confirmation_check(state)` is a user-supplied callable receiving
        the SignalState and returning bool. The callable MUST only inspect
        data ≤ current_bar (caller's responsibility — no automatic
        leakage prevention here).

        Returns the list of states transitioned to CONFIRMED at this bar.
        """
        fired: List[SignalState] = []
        still_active: List[SignalState] = []
        for s in self._active:
            age = current_bar - s.armed_at_bar
            if age < 0:
                # Should never happen but guard
                still_active.append(s)
                continue
            # Confirmation check first (allows same-bar confirmation if ttl == 0)
            if confirmation_check(s):
                s.status = SignalStatus.CONFIRMED
                s.confirmed_at_bar = current_bar
                fired.append(s)
                self._terminal.append(s)
                continue
            # If age exceeds ttl → expire
            if age >= s.ttl_bars:
                s.status = SignalStatus.EXPIRED
                self._terminal.append(s)
                continue
            still_active.append(s)
        self._active = still_active
        return fired

    def active_signals(self) -> List[SignalState]:
        return list(self._active)

    def terminal_history(self) -> List[SignalState]:
        return list(self._terminal)

    def stats(self) -> Dict[str, int]:
        n_armed = len(self._active)
        n_confirmed = sum(1 for s in self._terminal if s.status == SignalStatus.CONFIRMED)
        n_expired = sum(1 for s in self._terminal if s.status == SignalStatus.EXPIRED)
        return {"armed": n_armed, "confirmed": n_confirmed, "expired": n_expired}
