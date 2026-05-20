"""PRD-X v2 Phase X2 §5 — RuleBasedDecisionPolicy.

Concrete DecisionPolicy Protocol implementation that composes the
3 R5 building blocks into a complete state-machine:

  Entry side: EntryTrigger list (composition = OR firing)
  Exit side:  ExitTrigger list  (composition = OR firing)
  Sizing:     base_position_size * trigger.strength

State machine (per-symbol):

  FLAT
    │
    │ EntryTrigger fires → SetupRecord(status=ARMED)
    ▼
  ARMED  (persistence < confirm_min_bars)
    │
    │ persistence >= confirm_min_bars → status=CONFIRMED
    ▼
  CONFIRMED → build_target_weights emits target weight > 0
    │
    │ ExitTrigger fires OR ARMED setup ages past TTL
    ▼
  EXITED → target weight = 0

bit-identical-default discipline: mode='off' → all 4 Protocol methods
return empty/no-op (legacy path untouched, same precedent as
cascade_overlay R12 / construction_tier T0 / sample_weight=None).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from core.research.decision.entry_triggers import (
    EntryEvent, EntryTrigger,
)
from core.research.decision.exit_triggers import (
    ExitEvent, ExitTrigger,
)
from core.signals.signal_state import SignalStatus

__all__ = ["SetupRecord", "RuleBasedDecisionPolicy"]


_VALID_MODES = ("off", "active")


# ── SetupRecord (per-symbol state) ───────────────────────────────────
@dataclass
class SetupRecord:
    """One symbol's setup-state record in the rule-based state machine.

    Fields:
      symbol         — which symbol
      date           — current ctx date (most recent detect)
      status         — SignalStatus.ARMED → CONFIRMED via persistence
      source         — which trigger fired ('factor_entry' / etc.)
      strength       — ∈ [0, 1]; from EntryEvent.strength
      armed_date     — original date when status first became ARMED
      armed_bar      — bar/checkpoint counter value when first ARMED
                       (used by TTL; bar-anchored not day-anchored;
                       fixed P1-3 from `.days` semantic mismatch)
      persistence    — count of distinct bars the signal has been
                       re-detected (used for confirm_min_bars gate)
      exit_reason    — populated if an ExitTrigger fired
    """
    symbol: str
    date: pd.Timestamp
    status: SignalStatus
    source: str
    strength: float
    armed_date: pd.Timestamp
    armed_bar: int = 0
    persistence: int = 1
    exit_reason: str = ""


# ── RuleBasedDecisionPolicy ──────────────────────────────────────────
class RuleBasedDecisionPolicy:
    """Composes EntryTrigger + ExitTrigger lists into a DecisionPolicy.

    Parameters
    ----------
    entry_triggers : list[EntryTrigger]
    exit_triggers  : list[ExitTrigger]
    mode           : 'off' (default, bit-identical no-op) or 'active'
    confirm_min_bars : int — bars of persistence needed before ARMED
                        → CONFIRMED transition (default 1 = same-day
                        confirm; raise to 2-3 for stronger filters)
    base_position_size : float — base target weight per CONFIRMED
                        symbol (multiplied by strength); default 0.1.
                        §6.4 long-only invariant: must be ≥ 0.
    ttl_bars       : int — max bars (checkpoint ticks) in ARMED
                        state before expiry. **bar-anchored not
                        day-anchored** (P1-3 fix per auditor): each
                        step_day call advances a bar counter by 1;
                        a setup ARMED at bar N expires when current
                        bar > N + ttl_bars. Cadence-agnostic
                        (works for daily / weekly / monthly /
                        intraday — driver controls the step_day
                        cadence). Default 5.
    """

    def __init__(
        self,
        entry_triggers: List[EntryTrigger],
        exit_triggers: List[ExitTrigger],
        mode: str = "off",
        confirm_min_bars: int = 1,
        base_position_size: float = 0.1,
        ttl_bars: int = 5,
    ) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(
                f"mode={mode!r} invalid; expected one of {_VALID_MODES}")
        if base_position_size < 0:
            raise ValueError(
                f"base_position_size={base_position_size} < 0 — "
                f"long-only invariant (PRD §6.4)")
        self._entry_triggers = list(entry_triggers)
        self._exit_triggers = list(exit_triggers)
        self._mode = mode
        self._confirm_min_bars = int(confirm_min_bars)
        self._base = float(base_position_size)
        self._ttl_bars = int(ttl_bars)
        # internal state: per-symbol tracker
        self._tracker: Dict[str, SetupRecord] = {}
        self._exited: Dict[str, str] = {}  # symbol → exit reason
        # P1-3 bar counter (cadence-agnostic TTL anchor); advanced
        # by step_day when ctx['date'] differs from last_bar_date.
        # Avoids over-counting when driver calls step_day per-symbol.
        # armed_bar snapshot stored at detect time.
        self._bar_counter: int = 0
        self._last_bar_date: Optional[pd.Timestamp] = None

    @property
    def mode(self) -> str:
        return self._mode

    # ── Protocol method 1: detect_setups ────────────────────────────
    def detect_setups(self, state: Any, ctx: Dict[str, Any]
                       ) -> List[SetupRecord]:
        if self._mode == "off":
            return []
        if not isinstance(ctx, dict):
            return []
        symbol = ctx.get("symbol", "")
        date = ctx.get("date", pd.Timestamp.now())
        # if symbol is currently exited, do not re-arm in same ctx
        # (caller must reset _exited if re-entry desired)
        if symbol in self._exited:
            return []
        # fire all entry triggers; first firing wins (OR composition)
        fired: Optional[EntryEvent] = None
        for trig in self._entry_triggers:
            ev = trig.evaluate(ctx)
            if ev is not None:
                fired = ev
                break
        if fired is None:
            return []
        # update tracker
        existing = self._tracker.get(symbol)
        if existing is None:
            rec = SetupRecord(
                symbol=symbol, date=date,
                status=SignalStatus.ARMED, source=fired.source,
                strength=fired.strength, armed_date=date,
                armed_bar=self._bar_counter,
                persistence=1)
            self._tracker[symbol] = rec
            return [rec]
        # existing setup: refresh + increment persistence if new date
        if existing.date != date:
            existing.date = date
            existing.persistence += 1
        existing.strength = max(existing.strength, fired.strength)
        return [existing]

    # ── Protocol method 2: confirm_signals ──────────────────────────
    def confirm_signals(self, state: Any, ctx: Dict[str, Any]
                         ) -> List[SetupRecord]:
        if self._mode == "off":
            return []
        out: List[SetupRecord] = []
        for sym, rec in self._tracker.items():
            if (rec.status is SignalStatus.ARMED and
                    rec.persistence >= self._confirm_min_bars):
                rec.status = SignalStatus.CONFIRMED
            out.append(rec)
        return out

    # ── Protocol method 3: build_target_weights ─────────────────────
    def build_target_weights(self, state: Any, ctx: Dict[str, Any]
                              ) -> Dict[str, float]:
        if self._mode == "off":
            return {}
        weights: Dict[str, float] = {}
        for sym, rec in self._tracker.items():
            if sym in self._exited:
                weights[sym] = 0.0
                continue
            if rec.status is SignalStatus.CONFIRMED:
                w = self._base * max(0.0, min(1.0, rec.strength))
                # §6.4 long-only invariant: weight >= 0 guaranteed
                weights[sym] = max(0.0, w)
            else:
                # ARMED → no target weight yet (deferred)
                pass
        return weights

    # ── Protocol method 4: step_day ─────────────────────────────────
    def step_day(self, state: Any, ctx: Dict[str, Any]) -> Any:
        if self._mode == "off":
            return None
        if not isinstance(ctx, dict):
            ctx = {}
        symbol = ctx.get("symbol", "")
        # 1) run exit triggers on this symbol if it has a CONFIRMED setup
        rec = self._tracker.get(symbol)
        if rec is not None and rec.status is SignalStatus.CONFIRMED:
            for trig in self._exit_triggers:
                ev = trig.evaluate(ctx)
                if ev is not None:
                    rec.status = SignalStatus.EXPIRED
                    rec.exit_reason = ev.reason
                    self._exited[symbol] = ev.reason
                    break
        # 2) advance bar counter on date change (P1-3 bar-anchored
        #    TTL); per-symbol calls within the same bar don't
        #    multi-count
        date = ctx.get("date")
        if date is not None and date != self._last_bar_date:
            self._bar_counter += 1
            self._last_bar_date = date
        # 3) expire ARMED setups past TTL (bar-count, not days)
        for sym, r in list(self._tracker.items()):
            if r.status is SignalStatus.ARMED:
                bars_armed = self._bar_counter - r.armed_bar
                if bars_armed > self._ttl_bars:
                    r.status = SignalStatus.EXPIRED
                    r.exit_reason = (
                        f"TTL expired ({bars_armed} > "
                        f"{self._ttl_bars} bars)")
        return self._tracker
