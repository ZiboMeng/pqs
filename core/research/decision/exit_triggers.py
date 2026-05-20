"""PRD-X v2 Phase X2 §5.2 — ExitTrigger Protocol + 4 concrete impls.

Subscribes to existing risk-module APIs (KillSwitch, FailureDetector,
sr_stops, BaseDetector) at the ctx layer — pure consumers, no panel
imports (schema-purity per X1 / no_trade_band precedent).

The 4 trigger families (PRD §5.2.A/B/C):

  ThesisDecayTrigger
      Long-side thesis (factor score) decayed below exit threshold.
      Used by both core_alpha and event-driven candidates.

  FactorExitTrigger
      Sibling-overlap up + expected_excess shrank below cost buffer
      (sibling convergence root-causes per Diversifier Role; see
      `feedback_audit_per_round_methodology` + PRD §10.3.1 fleet
      contract).

  EventInvalidationTrigger
      Event-window factor turned negative OR catalyst already
      resolved (PEAD-style exit). Pure event-driven.

  RiskExitTrigger
      Subscribes to core/risk/* (KillSwitch + FailureDetector
      signals via ctx) and core/intraday multi-TF state (higher_tf
      STRONG_VETO from cascade_overlay). PRD §5.2.C risk-managed
      exit + §6.4 invariant guard (MaxDD ≤ 25% 2008-style is the
      driving constraint).

All 4 follow the **record-and-route** pattern (per
`feedback_no_blanket_failure_verdict`): trigger fires when its
specific condition holds; otherwise returns None (NOT a global
verdict). Reason string carries the specific cause for downstream
audit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

import pandas as pd

__all__ = [
    "ExitEvent",
    "ExitTrigger",
    "ThesisDecayTrigger",
    "FactorExitTrigger",
    "EventInvalidationTrigger",
    "RiskExitTrigger",
]


# ── ExitEvent dataclass + Protocol ────────────────────────────────────
@dataclass
class ExitEvent:
    """One exit-trigger firing record (record-and-route pattern).

    Fields:
      symbol  — affected position
      date    — event timestamp (bar-close convention per §multi-TF)
      source  — which trigger fired (thesis_decay / factor_exit /
                event_invalidation / risk_exit)
      reason  — human-readable diagnostic; downstream audit reads this
                for root-cause attribution.
    """
    symbol: str
    date: pd.Timestamp
    source: str
    reason: str


class ExitTrigger(Protocol):
    """PRD §5.2 trigger API. `evaluate(ctx) -> Optional[ExitEvent]`
    pattern: returns None when the trigger does NOT fire; returns an
    ExitEvent when it does. Multiple triggers compose via union (any
    firing → exit signal at decision layer).
    """

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[ExitEvent]:
        ...


# ── trigger 1: ThesisDecayTrigger ────────────────────────────────────
class ThesisDecayTrigger:
    """Fires when the long-side factor score has decayed below the
    exit threshold (e.g. momentum factor < 0.5 → thesis decayed).

    Graceful: if ``factor_score`` absent from ctx, returns None
    (NOT a crash — the trigger has nothing to evaluate).
    """

    def __init__(self, exit_threshold: float) -> None:
        self._th = float(exit_threshold)

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[ExitEvent]:
        ctx = ctx or {}
        factor_score = ctx.get("factor_score")
        if factor_score is None:
            return None
        if float(factor_score) < self._th:
            return ExitEvent(
                symbol=ctx.get("symbol", ""),
                date=ctx.get("date", pd.Timestamp.now()),
                source="thesis_decay",
                reason=(f"factor_score={factor_score:.4f} < "
                        f"exit_threshold={self._th:.4f}"),
            )
        return None


# ── trigger 2: FactorExitTrigger ─────────────────────────────────────
class FactorExitTrigger:
    """Fires when:
      (a) sibling_overlap > threshold (factor edge converged with
          active core, low diversification value), OR
      (b) expected_excess < min_expected_excess (edge shrank below
          cost buffer; PRD §5.2.B).

    Either condition independently fires the trigger.
    """

    def __init__(
        self,
        sibling_overlap_threshold: float = 0.7,
        min_expected_excess: float = 0.0,
    ) -> None:
        self._so_th = float(sibling_overlap_threshold)
        self._ex_th = float(min_expected_excess)

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[ExitEvent]:
        ctx = ctx or {}
        sibling_overlap = ctx.get("sibling_overlap")
        if sibling_overlap is not None and (
            float(sibling_overlap) > self._so_th
        ):
            return ExitEvent(
                symbol=ctx.get("symbol", ""),
                date=ctx.get("date", pd.Timestamp.now()),
                source="factor_exit",
                reason=(f"sibling_overlap={float(sibling_overlap):.3f} "
                        f"> threshold={self._so_th:.3f}"),
            )
        expected_excess = ctx.get("expected_excess")
        if expected_excess is not None and (
            float(expected_excess) < self._ex_th
        ):
            return ExitEvent(
                symbol=ctx.get("symbol", ""),
                date=ctx.get("date", pd.Timestamp.now()),
                source="factor_exit",
                reason=(f"expected_excess={float(expected_excess):.4f} "
                        f"< min={self._ex_th:.4f} (below cost buffer)"),
            )
        return None


# ── trigger 3: EventInvalidationTrigger ──────────────────────────────
class EventInvalidationTrigger:
    """Fires when the event-window factor turns negative OR the
    catalyst has already resolved. PEAD-style.

    Two independent firing conditions:
      (a) event_window_factor < min_event_factor (factor flipped sign)
      (b) catalyst_resolved is True (event passed, no remaining edge)
    """

    def __init__(self, min_event_factor: float = 0.0) -> None:
        self._ev_th = float(min_event_factor)

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[ExitEvent]:
        ctx = ctx or {}
        ev_factor = ctx.get("event_window_factor")
        if ev_factor is not None and float(ev_factor) < self._ev_th:
            return ExitEvent(
                symbol=ctx.get("symbol", ""),
                date=ctx.get("date", pd.Timestamp.now()),
                source="event_invalidation",
                reason=(f"event_window_factor={float(ev_factor):.4f} "
                        f"< min={self._ev_th:.4f} (factor turned "
                        f"negative)"),
            )
        if ctx.get("catalyst_resolved"):
            return ExitEvent(
                symbol=ctx.get("symbol", ""),
                date=ctx.get("date", pd.Timestamp.now()),
                source="event_invalidation",
                reason="catalyst_resolved → event edge exhausted",
            )
        return None


# ── trigger 4: RiskExitTrigger (subscribes core/risk/*) ──────────────
class RiskExitTrigger:
    """Subscribes to core/risk/* modules at the ctx layer:
      - kill_switch (constructor kwarg; KillSwitch instance with
        .is_triggered())
      - ctx['failure_signals'] (list of FailureSignal objects from
        FailureDetector.check_all(); fires on any .triggered=True)
      - ctx['higher_tf_state'] == 'STRONG_VETO' (cascade_overlay /
        multi-TF veto; PRD §5.2.C)

    Pure consumer: NO direct imports of core/risk/* (caller-owned
    instances pass via constructor / ctx). Keeps schema-purity
    invariant intact and allows test mocking.
    """

    def __init__(self, kill_switch: Any = None) -> None:
        self._ks = kill_switch

    def evaluate(self, ctx: Dict[str, Any]) -> Optional[ExitEvent]:
        ctx = ctx or {}
        # (1) KillSwitch (system-wide circuit breaker)
        if self._ks is not None:
            try:
                triggered = bool(self._ks.is_triggered())
            except Exception:  # pragma: no cover — defensive
                triggered = False
            if triggered:
                return ExitEvent(
                    symbol=ctx.get("symbol", ""),
                    date=ctx.get("date", pd.Timestamp.now()),
                    source="risk_exit",
                    reason="kill_switch.is_triggered() == True "
                           "(risk circuit-breaker fired)",
                )
        # (2) FailureDetector signals (drawdown/streak/sharpe/vol_spike)
        signals = ctx.get("failure_signals") or []
        for sig in signals:
            tr = getattr(sig, "triggered", False)
            kind = getattr(sig, "kind", "failure")
            if tr:
                return ExitEvent(
                    symbol=ctx.get("symbol", ""),
                    date=ctx.get("date", pd.Timestamp.now()),
                    source="risk_exit",
                    reason=f"failure_signal kind={kind} triggered",
                )
        # (3) Higher-TF context STRONG_VETO (PRD §5.2.C)
        if ctx.get("higher_tf_state") == "STRONG_VETO":
            return ExitEvent(
                symbol=ctx.get("symbol", ""),
                date=ctx.get("date", pd.Timestamp.now()),
                source="risk_exit",
                reason="higher_tf STRONG_VETO (multi-TF context "
                       "flipped from confirm to veto)",
            )
        return None
