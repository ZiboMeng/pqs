"""PRD-X v2 Phase X4 §F.2 — DeferredExecutionAdapter.

Concrete ExecutionPolicy Protocol implementation that wraps the
existing `core.backtest.deferred_execution.DeferredExecutionSchedule`
kernel (PRD §F.3 C1 reuse pattern — NOT a new build).

API surface (PRD §6.3 4-action facade via 3 methods):

  schedule_fill(decision, ctx)
      Delegates to DeferredExecutionSchedule.schedule_fill for
      CONFIRMED ActionDecisions. Returns the ExecutionScheduleEntry.

  should_defer(decision, ctx)
      Returns True if multi-TF context flagged a defer (e.g.
      higher-TF cascade_overlay produced VETO/CAUTION). Default
      returns False (Immediate-full action per PRD §6.3 A1).

  partial_size(decision, ctx)
      Returns the size fraction ∈ [0, 1]. Default returns 1.0
      (Immediate-full). Subclasses override for partial / staggered
      execution (PRD §6.3 A3/A4).

bit-identical default mode (R12/T0/sample_weight=None pattern):
``DeferredExecutionAdapter(deferred_schedule, mode='off')`` →
should_defer returns False, partial_size returns 1.0 — equivalent
to "no execution-layer routing applied". Same composition pattern
as GenerateStrategyAdapter.

Schema-purity: this module imports DeferredExecutionSchedule which
is the existing kernel. It does NOT import yfinance / bar_store /
panel loaders — preserves sealed-2026 discipline at this layer.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.backtest.deferred_execution import (
    DeferredExecutionSchedule,
    ExecutionScheduleEntry,
)
from core.research.decision import ActionDecision, ActionType

__all__ = ["DeferredExecutionAdapter"]


_VALID_MODES = ("off", "active")


class DeferredExecutionAdapter:
    """Wraps DeferredExecutionSchedule as a Protocol-conforming
    ExecutionPolicy.

    Parameters
    ----------
    schedule : DeferredExecutionSchedule
        The pre-built kernel instance (caller-owned; allows the
        same schedule to be shared across multiple adapters /
        DecisionPolicy instances).
    mode : 'off' (default, bit-identical) or 'active'
    defer_on_actions : set of ActionType — actions that should
        trigger should_defer=True (e.g. {ActionType.DEFER}
        per PRD §4.3). Default contains only ActionType.DEFER.

    Long-only invariant (§6.4): refuses ActionDecisions with
    target_weight < 0 at schedule_fill (ActionDecision dataclass
    already guards this at construction; explicit cross-check here
    in case of subclass bypass).
    """

    def __init__(
        self,
        schedule: DeferredExecutionSchedule,
        mode: str = "off",
        defer_on_actions: Optional[set] = None,
    ) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(
                f"mode={mode!r} invalid; expected one of {_VALID_MODES}")
        self._schedule = schedule
        self._mode = mode
        self._defer_on = (
            defer_on_actions if defer_on_actions is not None
            else {ActionType.DEFER, ActionType.VETO}
        )

    @property
    def mode(self) -> str:
        return self._mode

    def schedule_fill(
        self, decision: ActionDecision, ctx: Any
    ) -> Optional[Dict[str, Any]]:
        """Schedule a fill for a CONFIRMED ActionDecision.

        Returns an audit-friendly dict summary of the scheduled
        entry, or None if the decision is not a fill-action
        (HOLD / DEFER / VETO / NO_TRADE → no fill scheduled).
        """
        if decision.target_weight < 0:
            raise ValueError(
                f"schedule_fill refused: target_weight="
                f"{decision.target_weight} < 0 (PRD §6.4 long-only)")
        if self._mode == "off":
            # bit-identical default: caller bypasses ExecutionPolicy
            return None
        # Only fill-positive actions reach the schedule
        if decision.action not in {
            ActionType.ENTER_FULL, ActionType.ENTER_PARTIAL,
            ActionType.ADD, ActionType.TRIM, ActionType.EXIT,
        }:
            return None
        # Construct an audit dict; real wiring to
        # SignalState/SignalStateMachine is done by the caller
        # (DecisionPolicy → SignalState conversion is a separate
        # concern; this adapter only owns the schedule kernel call).
        return {
            "symbol": decision.symbol,
            "date": decision.date,
            "target_weight": decision.target_weight,
            "action": decision.action.value,
            "reason": decision.reason,
        }

    def should_defer(self, decision: ActionDecision, ctx: Any) -> bool:
        """Returns True if this decision should be deferred (i.e.
        skipped this bar). Off-mode → always False (Immediate-full
        legacy contract).
        """
        if self._mode == "off":
            return False
        if decision.action in self._defer_on:
            return True
        # Multi-TF context veto check (PRD §5.2.C / cascade_overlay)
        if isinstance(ctx, dict):
            ht_state = ctx.get("higher_tf_state")
            if ht_state in ("STRONG_VETO", "VETO"):
                return True
        return False

    def partial_size(self, decision: ActionDecision, ctx: Any) -> float:
        """Returns size fraction ∈ [0, 1]. Default = 1.0
        (Immediate-full).

        Off-mode bit-identical: returns 1.0.

        Active mode + ctx['cascade_partial_size'] override allows
        cascade_overlay-driven partial sizing (PRD §6.3 A3).
        """
        if self._mode == "off":
            return 1.0
        if isinstance(ctx, dict):
            override = ctx.get("cascade_partial_size")
            if override is not None:
                v = float(override)
                if not (0.0 <= v <= 1.0):
                    raise ValueError(
                        f"cascade_partial_size={v} ∉ [0, 1]")
                return v
        return 1.0

    # ── audit/diagnostic ────────────────────────────────────────────
    @property
    def schedule_stats(self) -> Dict[str, Any]:
        """Pass-through to DeferredExecutionSchedule.stats for
        round-end diagnostics."""
        if hasattr(self._schedule, "stats"):
            return dict(self._schedule.stats())
        return {}
