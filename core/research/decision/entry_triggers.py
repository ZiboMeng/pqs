"""PRD-X v2 Phase X2 §5.1 — EntryTrigger Protocol + 3 concrete impls.

Mirror structure of exit_triggers.py: ctx-driven, record-and-route,
schema-pure (no panel imports). PRD §5.1 three families:

  FactorEntryTrigger
      Long-side factor score crosses entry threshold (e.g. momentum
      / value composite > 0.6).

  EventEntryTrigger
      Event-window factor positive (catalyst-driven entry, e.g.
      post-earnings drift) AND catalyst not yet resolved.

  RegimeEntryTrigger
      Regime state in allowed set (default: BULL/RISK_ON/NEUTRAL).
      §6.4 long-only invariant: RISK_OFF / CAUTIOUS not in default
      allowed set → no long entry in defensive regimes.

The Decision-layer composes these (logical AND for confluence, or
OR for any-source firing) — the trigger itself records "this
condition holds" and exits.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, Set

import pandas as pd

from core.regime.regime_detector import RegimeState

__all__ = [
    "EntryEvent",
    "EntryTrigger",
    "FactorEntryTrigger",
    "EventEntryTrigger",
    "RegimeEntryTrigger",
]


# ── EntryEvent dataclass + Protocol ──────────────────────────────────
@dataclass
class EntryEvent:
    """One entry-trigger firing record.

    Fields:
      symbol   — affected symbol
      date     — event timestamp (bar-close)
      source   — which trigger fired (factor_entry / event_entry /
                 regime_entry)
      reason   — human-readable diagnostic
      strength — ∈ [0, 1]; downstream Decision-layer uses for sizing
                 input (NOT a continuous-magnitude size weight — see
                 §9.0 post-audit-fix constraint; this is a normalized
                 confidence, not a magnitude IC predictor).

    Long-only invariant (PRD §6.4): strength is non-negative.
    Negative strength would imply SHORT_ENTRY — blocked at
    construction.
    """
    symbol: str
    date: pd.Timestamp
    source: str
    reason: str
    strength: float = 1.0

    def __post_init__(self) -> None:
        if not (0.0 <= float(self.strength) <= 1.0):
            raise ValueError(
                f"strength={self.strength} ∉ [0, 1] — long-only "
                f"invariant (PRD §6.4) + normalized-confidence "
                f"convention (PRD §5.1)")


class EntryTrigger(Protocol):
    """PRD §5.1 trigger API. `evaluate(ctx) -> Optional[EntryEvent]`."""

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[EntryEvent]:
        ...


# ── trigger 1: FactorEntryTrigger ────────────────────────────────────
class FactorEntryTrigger:
    """Fires when factor_score in ctx exceeds entry_threshold.

    Strength = clipped normalized excess over threshold:
        s = min(1.0, (factor_score - threshold) / (1 - threshold))

    So at the threshold s=0; at factor_score=1 s=1.

    Graceful: missing factor_score → None (no trigger, not crash).
    """

    def __init__(self, entry_threshold: float) -> None:
        if not (0.0 <= entry_threshold < 1.0):
            raise ValueError(
                f"entry_threshold={entry_threshold} ∉ [0, 1) — "
                f"threshold must leave room for excess > 0")
        self._th = float(entry_threshold)

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[EntryEvent]:
        ctx = ctx or {}
        factor_score = ctx.get("factor_score")
        if factor_score is None:
            return None
        fs = float(factor_score)
        if fs <= self._th:
            return None
        # normalized excess for sizing input
        excess = max(0.0, min(1.0, (fs - self._th) / (1.0 - self._th)))
        return EntryEvent(
            symbol=ctx.get("symbol", ""),
            date=ctx.get("date", pd.Timestamp.now()),
            source="factor_entry",
            reason=(f"factor_score={fs:.4f} > entry_threshold="
                    f"{self._th:.4f}"),
            strength=excess,
        )


# ── trigger 2: EventEntryTrigger ─────────────────────────────────────
class EventEntryTrigger:
    """Fires when event_window_factor > min_event_factor AND
    catalyst_resolved is falsy.

    PRD §5.1.B: catalyst already resolved → already priced in;
    no new entries.
    """

    def __init__(self, min_event_factor: float = 0.0) -> None:
        self._ev_th = float(min_event_factor)

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[EntryEvent]:
        ctx = ctx or {}
        ev_factor = ctx.get("event_window_factor")
        if ev_factor is None:
            return None
        if float(ev_factor) <= self._ev_th:
            return None
        if ctx.get("catalyst_resolved"):
            return None
        # strength scaled by event-factor magnitude (clip to [0, 1])
        s = max(0.0, min(1.0, float(ev_factor)))
        return EntryEvent(
            symbol=ctx.get("symbol", ""),
            date=ctx.get("date", pd.Timestamp.now()),
            source="event_entry",
            reason=(f"event_window_factor={float(ev_factor):.4f} > "
                    f"min={self._ev_th:.4f} + catalyst still valid"),
            strength=s,
        )


# ── trigger 3: RegimeEntryTrigger ────────────────────────────────────
_DEFAULT_LONG_FRIENDLY: Set[RegimeState] = {
    RegimeState.BULL,
    RegimeState.RISK_ON,
    RegimeState.NEUTRAL,
}


class RegimeEntryTrigger:
    """Fires when the regime is in the allowed set.

    Default allowed = {BULL, RISK_ON, NEUTRAL} (long-friendly per
    §6.4 long-only invariant). RISK_OFF / CAUTIOUS not in default
    allowed → no long entry in defensive regimes.

    Pattern: pair this with FactorEntryTrigger / EventEntryTrigger
    via Decision-layer AND-composition (regime gate + signal).
    """

    def __init__(
        self,
        allowed_regimes: Optional[Set[RegimeState]] = None,
        strength: float = 1.0,
    ) -> None:
        self._allowed = (allowed_regimes if allowed_regimes is not None
                         else set(_DEFAULT_LONG_FRIENDLY))
        if not (0.0 <= strength <= 1.0):
            raise ValueError(
                f"strength={strength} ∉ [0, 1]")
        self._strength = float(strength)

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[EntryEvent]:
        ctx = ctx or {}
        regime = ctx.get("regime")
        if regime is None:
            return None
        if regime not in self._allowed:
            return None
        return EntryEvent(
            symbol=ctx.get("symbol", ""),
            date=ctx.get("date", pd.Timestamp.now()),
            source="regime_entry",
            reason=(f"regime={getattr(regime, 'name', str(regime))} "
                    f"in allowed set ({len(self._allowed)} regimes)"),
            strength=self._strength,
        )
