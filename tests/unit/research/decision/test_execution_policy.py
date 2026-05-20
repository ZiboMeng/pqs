"""PRD-X v2 Phase X4 §F.2 — DeferredExecutionAdapter (TDD).

AC:
  - Wraps existing DeferredExecutionSchedule (PRD §F.3 C1 reuse)
  - Satisfies ExecutionPolicy Protocol (schedule_fill / should_defer
    / partial_size)
  - mode='off' bit-identical (R12/T0 pattern): should_defer=False,
    partial_size=1.0
  - PRD §6.4 long-only invariant guard: refuses target_weight < 0
  - cascade_overlay multi-TF veto integration via ctx
"""
import pandas as pd
import pytest

from core.backtest.deferred_execution import DeferredExecutionSchedule
from core.research.decision import (
    ActionDecision, ActionType, ExecutionPolicy, PositionState,
)
from core.research.decision.execution_policy import (
    DeferredExecutionAdapter,
)
from core.signals.signal_state import SignalStatus


def _mk_decision(action=ActionType.ENTER_FULL, weight=0.1, symbol="SPY"):
    return ActionDecision(
        symbol=symbol, date=pd.Timestamp("2025-04-01"),
        status=SignalStatus.CONFIRMED, action=action,
        position_state=PositionState.FLAT,
        target_weight=weight, reason="test")


class TestConstruction:
    def test_default_mode_off(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched)
        assert a.mode == "off"

    def test_active_mode_accepted(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="active")
        assert a.mode == "active"

    def test_unknown_mode_rejected(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        with pytest.raises(ValueError, match=r"mode"):
            DeferredExecutionAdapter(sched, mode="bogus")


class TestProtocolSatisfaction:
    def test_satisfies_execution_policy(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched)
        for m in ("schedule_fill", "should_defer", "partial_size"):
            assert hasattr(a, m)


class TestModeOffBitIdentical:
    def test_off_should_defer_false(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="off")
        d = _mk_decision()
        assert a.should_defer(d, {}) is False

    def test_off_partial_size_one(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="off")
        d = _mk_decision()
        assert a.partial_size(d, {}) == 1.0

    def test_off_schedule_fill_none(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="off")
        d = _mk_decision()
        assert a.schedule_fill(d, {}) is None


class TestActiveScheduleFill:
    def test_enter_full_scheduled(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="active")
        d = _mk_decision(action=ActionType.ENTER_FULL, weight=0.05)
        res = a.schedule_fill(d, {})
        assert res is not None
        assert res["symbol"] == "SPY"
        assert res["target_weight"] == 0.05
        assert res["action"] == "enter_full"

    def test_hold_action_no_fill(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="active")
        d = _mk_decision(action=ActionType.HOLD, weight=0.0)
        res = a.schedule_fill(d, {})
        assert res is None

    def test_veto_action_no_fill(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="active")
        d = _mk_decision(action=ActionType.VETO, weight=0.0)
        res = a.schedule_fill(d, {})
        assert res is None


class TestActiveShouldDefer:
    def test_defer_action_triggers_defer(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="active")
        d = _mk_decision(action=ActionType.DEFER, weight=0.0)
        assert a.should_defer(d, {}) is True

    def test_strong_veto_ctx_triggers_defer(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="active")
        d = _mk_decision(action=ActionType.ENTER_FULL, weight=0.1)
        assert a.should_defer(d, {"higher_tf_state": "STRONG_VETO"}) is True

    def test_enter_full_no_veto_no_defer(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="active")
        d = _mk_decision(action=ActionType.ENTER_FULL, weight=0.1)
        assert a.should_defer(d, {}) is False


class TestActivePartialSize:
    def test_default_full_size(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="active")
        d = _mk_decision()
        assert a.partial_size(d, {}) == 1.0

    def test_cascade_partial_override(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="active")
        d = _mk_decision()
        assert a.partial_size(d, {"cascade_partial_size": 0.5}) == 0.5

    def test_cascade_partial_out_of_range_rejected(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="active")
        d = _mk_decision()
        with pytest.raises(ValueError, match=r"cascade_partial_size"):
            a.partial_size(d, {"cascade_partial_size": 1.5})


class TestLongOnlyInvariant:
    def test_negative_weight_refused_at_construction(self):
        # ActionDecision dataclass guards target_weight < 0 already
        with pytest.raises(ValueError, match=r"long-only|non-negative"):
            _mk_decision(action=ActionType.ENTER_FULL, weight=-0.05)

    def test_schedule_fill_explicit_invariant_cross_check(self):
        sched = DeferredExecutionSchedule(execution_delay_bars=1)
        a = DeferredExecutionAdapter(sched, mode="active")
        # Construct via __new__ to bypass dataclass guard (simulating
        # subclass bypass). Verify adapter still rejects.
        d = ActionDecision.__new__(ActionDecision)
        object.__setattr__(d, "symbol", "X")
        object.__setattr__(d, "date", pd.Timestamp("2025-04-01"))
        object.__setattr__(d, "status", SignalStatus.CONFIRMED)
        object.__setattr__(d, "action", ActionType.ENTER_FULL)
        object.__setattr__(d, "position_state", PositionState.FLAT)
        object.__setattr__(d, "target_weight", -0.1)
        object.__setattr__(d, "reason", "bypass attempt")
        with pytest.raises(ValueError, match=r"long-only"):
            a.schedule_fill(d, {})
