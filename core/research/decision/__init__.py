"""PRD-X v2 Phase X1 — DecisionPolicy / ExecutionPolicy schema layer.

Schema-only layer for the trigger-first rebalance architecture. NO
panel/bar-store/yfinance imports at this layer (sealed-2026
discipline: schema must be pure abstraction, data access is the
caller's responsibility).

Reuses existing `core.signals.signal_state.SignalStatus` 3-state
enum (ARMED/CONFIRMED/EXPIRED) — does NOT extend it. The PRD §4.1
9-state lifecycle is represented as a (SignalStatus, ActionType,
PositionState) 三元组 via `LifecycleMapper` (PRD §4.1.1 design).

Honest scope (PRD §F.2 / §F.3 C2): 6/7 existing strategies already
share `.generate()` API; 1/7 (intraday_reversal) already has the
4-method state machine. This module adds the Protocol abstraction +
GenerateStrategyAdapter to wrap the 6 .generate() strategies WITHOUT
modifying them. intraday_reversal directly satisfies DecisionPolicy
Protocol (already-blueprint).
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Protocol, Tuple, Union

import pandas as pd

from core.signals.signal_state import SignalStatus

__all__ = [
    "ActionType",
    "PositionState",
    "ActionDecision",
    "DecisionPolicy",
    "ExecutionPolicy",
    "GenerateStrategyAdapter",
    "LifecycleMapper",
]


# ── enums (PRD §4.3 + §4.1.1) ────────────────────────────────────────
class ActionType(Enum):
    """PRD §4.3: 9-action set, disjoint from SignalStatus.

    Long-only invariant (PRD §6.4): NO SHORT_*/SELL_SHORT members;
    all actions preserve weight ≥ 0 in their downstream effect.
    """
    ENTER_FULL = "enter_full"
    ENTER_PARTIAL = "enter_partial"
    ADD = "add"
    HOLD = "hold"
    TRIM = "trim"
    EXIT = "exit"
    DEFER = "defer"
    VETO = "veto"
    NO_TRADE = "no_trade"


class PositionState(Enum):
    """PRD §4.1.1: holdable position state in the lifecycle 三元组.

    Other PRD §4.1 lifecycle states (ENTERED / EXITED / TRIMMED) are
    transient transitions captured by the (status, action, position)
    triplet, not stable states the system holds.
    """
    FLAT = "flat"
    HOLD = "hold"


# ── dataclass (PRD §10.3.1 fleet contract precursor) ────────────────
@dataclass
class ActionDecision:
    """One decision step's record.

    Long-only invariant (PRD §6.4) enforced at construction:
    ``target_weight >= 0`` (no-short).
    """
    symbol: str
    date: pd.Timestamp
    status: SignalStatus
    action: ActionType
    position_state: PositionState
    target_weight: float = 0.0
    reason: str = ""

    def __post_init__(self) -> None:
        if self.target_weight < 0:
            raise ValueError(
                f"target_weight={self.target_weight} < 0 — "
                f"long-only / no-short invariant (PRD §6.4) forbids "
                f"non-negative weights at the decision layer")


# ── Protocols (PRD §3.1 Decision + Execution layers) ────────────────
class DecisionPolicy(Protocol):
    """PRD §4 state-machine API — modelled on intraday_reversal's
    proven 4-method pattern (the 1/7 blueprint per §F.2)."""

    def detect_setups(self, state: Any, ctx: Any) -> Any:
        """Evidence → setup candidates(`FLAT → ARMED_ENTRY` & similar
        ARMED state transitions). Returns SetupBatch."""
        ...

    def confirm_signals(self, state: Any, ctx: Any) -> Any:
        """`ARMED → CONFIRMED` transitions per confirmation rule
        (multi-TF alignment / persistence / TTL window)."""
        ...

    def build_target_weights(self, state: Any, ctx: Any) -> Dict[str, float]:
        """`CONFIRMED → target weight delta`. Returns
        {symbol: target_weight} mapping."""
        ...

    def step_day(self, state: Any, ctx: Any) -> Any:
        """One-day advance of the state machine; advances TTLs,
        expires stale ARMED states, processes risk-exit triggers."""
        ...


class ExecutionPolicy(Protocol):
    """PRD §6.3 4-action facade (Immediate full / Deferred / Partial
    / Staggered) via 3 methods. Reuses existing modules:
      - ``deferred_execution.DeferredExecutionSchedule``
      - ``multi_timescale.decide_timing``
      - ``cascade_overlay.apply_cascade_overlay``
    """

    def schedule_fill(self, decision: ActionDecision, ctx: Any) -> Any:
        """`CONFIRMED → fill_at_bar` (delegates to
        DeferredExecutionSchedule)."""
        ...

    def should_defer(self, decision: ActionDecision, ctx: Any) -> bool:
        """Multi-TF context → defer/proceed gate."""
        ...

    def partial_size(self, decision: ActionDecision, ctx: Any) -> float:
        """Returns the size fraction ∈ [0, 1] to actually execute
        this bar (1.0 = full, 0.5 = half, 0.0 = no-op this bar)."""
        ...


# ── GenerateStrategyAdapter (PRD §F.3 C2 solution) ──────────────────
_VALID_MODES = ("off", "active")


class GenerateStrategyAdapter:
    """Wraps any of the 6 `.generate()`-based strategies (MultiFactor /
    DualMomentum / TrendFollowing / SimpleBaseline / CrossAssetRotation
    / ConfirmationPattern) as a `DecisionPolicy`. The strategy itself
    is UNTOUCHED (composition, not inheritance).

    ``mode='off'`` (default) → identity pass-through; the adapter's
    ``build_target_weights`` returns exactly what the strategy's
    ``.generate()`` returns, byte-equal. Same bit-identical-default
    pattern as cascade_overlay R12 mode='off' / construction_tier T0 /
    XGBAlphaModel.fit(sample_weight=None) — non-default callers opt in.
    """

    def __init__(self, strategy: Any, mode: str = "off") -> None:
        if mode not in _VALID_MODES:
            raise ValueError(
                f"mode={mode!r} invalid; expected one of {_VALID_MODES}")
        self._strategy = strategy
        self._mode = mode

    def detect_setups(self, state: Any, ctx: Any) -> Any:
        # off → no decision-layer setups (legacy direct .generate()
        # path is unchanged). active mode wired in X2+.
        return [] if self._mode == "off" else _active_detect(
            self._strategy, state, ctx)

    def confirm_signals(self, state: Any, ctx: Any) -> Any:
        return [] if self._mode == "off" else _active_confirm(
            self._strategy, state, ctx)

    def build_target_weights(
        self, state: Any, ctx: Any
    ) -> Union[Dict[str, float], pd.DataFrame]:
        """Mode='off' → byte-equal identity pass-through to
        `strategy.generate(**filtered_ctx)`.

        Return type Union because real 6 .generate() strategies
        return ``pd.DataFrame`` (date × symbol weight panel) while
        intraday Decision-layer consumers may pass dict-returning
        strategies. Caller decides whether to index into the
        DataFrame for one bar or consume the panel directly.

        Implementation: inspects the wrapped ``strategy.generate``
        signature and forwards only the parameters present in ctx
        (idempotent for mismatched-signature mocks). This is the
        post-X4-M11-parity-fix contract — X1 mock-only test was
        insufficient (per feedback_audit_surfaces_not_thorough).
        """
        if not isinstance(ctx, dict):
            ctx = {}
        # filter ctx → kwargs that the strategy.generate accepts
        try:
            sig = inspect.signature(self._strategy.generate)
            params = sig.parameters
        except (TypeError, ValueError):
            # introspection failed (e.g. C-impl or dunder); fall
            # back to the legacy positional (date, ctx) call so the
            # pre-X4 mocks remain GREEN (bit-identical default).
            date = ctx.get("date")
            return self._strategy.generate(date, ctx)
        kwargs: Dict[str, Any] = {}
        for name in params:
            if name == "self":
                continue
            if name in ctx and ctx[name] is not None:
                kwargs[name] = ctx[name]
        return self._strategy.generate(**kwargs)

    def step_day(self, state: Any, ctx: Any) -> Any:
        # off → no-op (no decision-layer state to advance).
        return state


# placeholders for X2+ active-mode hooks (raise to make accidental
# use surface; not silent no-ops).
def _active_detect(strategy: Any, state: Any, ctx: Any) -> Any:
    raise NotImplementedError(
        "active-mode detect_setups wired in PRD-X X2 (rule-based "
        "trigger). Use mode='off' until then.")


def _active_confirm(strategy: Any, state: Any, ctx: Any) -> Any:
    raise NotImplementedError(
        "active-mode confirm_signals wired in PRD-X X2. "
        "Use mode='off' until then.")


# ── LifecycleMapper (PRD §4.1.1 三元组) ──────────────────────────────
_FLAT_LIFECYCLE = {"FLAT", "EXITED"}
_TRANSIENT_HOLD = {"ENTERED", "HOLD", "TRIMMED"}
_ARMED_LIFECYCLES = {"ARMED_ENTRY", "ARMED_EXIT", "ARMED_TRIM"}
_CONFIRMED_LIFECYCLES = {"CONFIRMED_ENTRY", "CONFIRMED_EXIT",
                         "CONFIRMED_TRIM"}


class LifecycleMapper:
    """PRD §4.1.1 mapping: 9-state lifecycle → (SignalStatus,
    ActionType, PositionState) triplet. Strategy must NOT extend
    SignalStatus (3-state); composite mapping preserves backward
    compat with existing intraday_reversal_runner +
    confirmation_pattern callers."""

    @staticmethod
    def from_lifecycle(
        lifecycle: str,
        action: Optional[ActionType] = None,
        position: Optional[PositionState] = None,
    ) -> Tuple[Optional[SignalStatus], Optional[ActionType],
               PositionState]:
        lc = lifecycle.strip().upper()
        if lc in _FLAT_LIFECYCLE:
            return (None, None, PositionState.FLAT)
        if lc in _TRANSIENT_HOLD:
            return (None, action, PositionState.HOLD)
        if lc in _ARMED_LIFECYCLES:
            return (SignalStatus.ARMED, action,
                    position or PositionState.FLAT)
        if lc in _CONFIRMED_LIFECYCLES:
            return (SignalStatus.CONFIRMED, action,
                    position or PositionState.HOLD)
        raise ValueError(
            f"unknown lifecycle {lifecycle!r}; valid set = "
            f"FLAT/EXITED + ENTERED/HOLD/TRIMMED + "
            f"ARMED_{{ENTRY,EXIT,TRIM}} + CONFIRMED_{{ENTRY,EXIT,TRIM}}"
        )
