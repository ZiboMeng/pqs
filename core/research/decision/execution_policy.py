"""PRD-X v2 Phase X4 §F.2 — DeferredExecutionAdapter.

Concrete ExecutionPolicy Protocol implementation that wraps the
existing `core.backtest.deferred_execution.DeferredExecutionSchedule`
kernel (PRD §F.3 C1 reuse pattern — NOT a new build).

**P1-1 fix (2026-05-20, post-auditor)**: prior version's
schedule_fill() returned only an audit dict, never invoking the
underlying kernel. Auditor F1 correctly flagged this as facade-only
"X4 schema + adapter shell" not real integration. Updated impl
constructs a SignalState (CONFIRMED) from the ActionDecision +
ctx-supplied bar indices, then calls `schedule.schedule_fill(state,
target_weight)` to actually register the pending fill in the
kernel queue. ctx must supply `bar_idx` (current); `armed_at_bar`
defaults to `bar_idx - 1` if not provided.

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
from core.signals.signal_state import SignalState, SignalStatus

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
    ) -> Optional[ExecutionScheduleEntry]:
        """Schedule a fill for a CONFIRMED ActionDecision.

        P1-1 (post-auditor): actually invokes the underlying
        DeferredExecutionSchedule.schedule_fill() kernel — no longer
        an audit-only facade. Returns the ExecutionScheduleEntry that
        the kernel registered (or None for off-mode / non-fill
        actions).

        Requires `ctx['bar_idx']` (current bar index). `ctx['armed_at_bar']`
        optional (defaults to bar_idx - 1). `ctx['ttl_bars']` optional
        (defaults to 5, matches SignalStateMachine convention).
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
        ctx = ctx if isinstance(ctx, dict) else {}
        bar_idx = ctx.get("bar_idx")
        if bar_idx is None:
            raise ValueError(
                "DeferredExecutionAdapter.schedule_fill active mode "
                "requires ctx['bar_idx'] (current bar index for the "
                "underlying DeferredExecutionSchedule kernel)")
        bar_idx = int(bar_idx)
        armed_at_bar = int(ctx.get("armed_at_bar", bar_idx - 1))
        ttl_bars = int(ctx.get("ttl_bars", 5))
        # Construct a CONFIRMED SignalState — the kernel's
        # schedule_fill contract requires status=CONFIRMED.
        state = SignalState(
            symbol=decision.symbol,
            armed_at_bar=armed_at_bar,
            ttl_bars=ttl_bars,
            status=SignalStatus.CONFIRMED,
            confirmed_at_bar=bar_idx,
            setup_metadata={
                "action": decision.action.value,
                "reason": decision.reason,
                "decision_date": str(decision.date),
            },
        )
        # Drive the kernel — this is the real X4 integration that
        # auditor F1 flagged missing.
        return self._schedule.schedule_fill(
            signal_state=state,
            target_weight=decision.target_weight,
        )

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
