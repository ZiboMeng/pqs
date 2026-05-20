"""PRD-X v2 Phase X5 — MLSidecarPolicy (sign-vote / include-veto only).

§9.0 post-audit-fix HARD constraint: ML outputs MUST be discrete
sign-vote / include-veto / classifier, NEVER continuous magnitude
as size weight. Post-fix A/B experiments across 3 model classes
(XGB / LightGBM / linear) forced a universal magnitude-IC poison —
the conclusion was that ML-as-sizer is structurally toxic in this
research scope.

This MLSidecarPolicy enforces §9.0 by design:
  - vote_fn must return a SignVote enum value (VETO / NO_VOTE /
    CONFIRM); non-enum returns raise TypeError
  - The sidecar overlays a rule-based decision: VETO blocks a
    pending entry by routing to ActionType.VETO with weight=0;
    NO_VOTE and CONFIRM are no-op pass-throughs (no continuous
    scaling, ever)
  - bit-identical default mode='off' returns NO_VOTE for every
    ctx — sidecar dormant, legacy decision path untouched (same
    cascade_overlay R12 / construction_tier T0 precedent)

The ML model itself is opaque to this policy; the user wires
`vote_fn(ctx) -> SignVote` however they want (threshold a raw
score, classifier prediction, ensemble vote, etc) — but the
sidecar contract refuses anything other than SignVote at runtime.

Schema-purity: zero panel/yfinance/bar_store imports (sidecar is a
pure ctx → categorical overlay; the model and feature pipeline
live outside this module).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict

import pandas as pd

from core.research.decision import (
    ActionDecision, ActionType, PositionState,
)
from core.signals.signal_state import SignalStatus

__all__ = ["SignVote", "MLSidecarPolicy"]


_VALID_MODES = ("off", "active")


# ── SignVote enum (PRD §9.0 discrete-only invariant) ─────────────────
class SignVote(Enum):
    """Discrete ML sidecar output. §9.0 post-fix constraint requires
    ML outputs be categorical, NEVER continuous magnitude.

    VETO     — block the entry/add (defer or skip)
    NO_VOTE  — no opinion (pass-through, default)
    CONFIRM  — confirm rule-based decision (pass-through, NOT scaling)
    """
    VETO = "veto"
    NO_VOTE = "no_vote"
    CONFIRM = "confirm"


class MLSidecarPolicy:
    """Overlay an ML sign-vote on top of a rule-based ActionDecision.

    Parameters
    ----------
    vote_fn : Callable[[Dict[str, Any]], SignVote]
        Function mapping ctx → SignVote. Must return a SignVote
        instance; any other return type raises TypeError at runtime
        per §9.0 post-fix invariant.
    mode : 'off' (default, bit-identical) or 'active'
    """

    def __init__(
        self,
        vote_fn: Callable[[Dict[str, Any]], SignVote],
        mode: str = "off",
    ) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(
                f"mode={mode!r} invalid; expected one of {_VALID_MODES}")
        self._vote_fn = vote_fn
        self._mode = mode

    @property
    def mode(self) -> str:
        return self._mode

    def vote(self, ctx: Dict[str, Any]) -> SignVote:
        """Return the ML vote for this ctx.

        - mode='off' → always NO_VOTE (bit-identical pass-through)
        - mode='active' → calls vote_fn(ctx); enforces SignVote
          return type per §9.0 (TypeError otherwise)
        """
        if self._mode == "off":
            return SignVote.NO_VOTE
        v = self._vote_fn(ctx)
        if not isinstance(v, SignVote):
            raise TypeError(
                f"vote_fn returned {type(v).__name__}={v!r}; "
                f"§9.0 post-audit-fix invariant requires SignVote "
                f"(discrete sign-vote, NOT continuous magnitude as "
                f"size weight)")
        return v

    def apply(
        self, decision: ActionDecision, ctx: Dict[str, Any]
    ) -> ActionDecision:
        """Apply the ML sidecar vote to a rule-based ActionDecision.

        Returns a new ActionDecision (the input is not mutated):
          - VETO + entry-like action → ActionType.VETO, weight=0
          - VETO + non-entry (HOLD/EXIT/TRIM) → unchanged (ML
              can't force or block defensive actions)
          - CONFIRM / NO_VOTE → unchanged (pure pass-through, NO
              size scaling per §9.0)
        """
        if self._mode == "off":
            return decision
        v = self.vote(ctx)
        if v in (SignVote.NO_VOTE, SignVote.CONFIRM):
            # pure pass-through; NO size scaling (§9.0)
            return decision
        # v == VETO
        # Only veto entry-like actions; HOLD / EXIT / TRIM / NO_TRADE
        # are defensive and ML can't block them (risk modules own
        # those exits per §5.2.C; ML is opinion-overlay, not risk)
        entry_actions = {ActionType.ENTER_FULL, ActionType.ENTER_PARTIAL,
                         ActionType.ADD}
        if decision.action not in entry_actions:
            return decision
        # Route to VETO with weight 0 (§6.4 long-only: no negative
        # weight ever; VETO means "do nothing", not "go short")
        return ActionDecision(
            symbol=decision.symbol,
            date=decision.date,
            status=decision.status,
            action=ActionType.VETO,
            position_state=PositionState.FLAT,
            target_weight=0.0,
            reason=f"ML VETO (was {decision.action.value})")
