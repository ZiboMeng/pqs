"""Tests for deferred-execution backtest kernel."""

from __future__ import annotations

import pandas as pd
import pytest

from core.backtest.deferred_execution import (
    DeferredExecutionSchedule, ExecutionScheduleEntry,
)
from core.signals.signal_state import (
    SignalState, SignalStateMachine, SignalStatus,
)


class TestSchedule:
    def test_init_validation(self):
        with pytest.raises(ValueError):
            DeferredExecutionSchedule(execution_delay_bars=-1)
        # Zero delay allowed (same-bar fill — for volume-gate same-bar)
        s = DeferredExecutionSchedule(execution_delay_bars=0)
        assert s.execution_delay_bars == 0

    def test_schedule_only_confirmed(self):
        s = DeferredExecutionSchedule(execution_delay_bars=1)
        # ARMED status cannot be scheduled
        state = SignalState(symbol="AAPL", armed_at_bar=10, ttl_bars=5)
        assert state.status == SignalStatus.ARMED
        with pytest.raises(ValueError):
            s.schedule_fill(state, target_weight=0.1)

    def test_schedule_fill_then_due_at(self):
        s = DeferredExecutionSchedule(execution_delay_bars=1)
        state = SignalState(
            symbol="AAPL", armed_at_bar=10, ttl_bars=5,
            status=SignalStatus.CONFIRMED, confirmed_at_bar=12,
        )
        s.schedule_fill(state, target_weight=0.2)
        # Scheduled for bar 13 (12 + 1 delay)
        assert s.stats()["pending"] == 1
        # Not due at bar 12
        assert s.due_at(12) == []
        # Due at bar 13
        due = s.due_at(13)
        assert len(due) == 1
        assert due[0].symbol == "AAPL"
        assert due[0].target_weight == 0.2
        # Now executed, no longer pending
        assert s.stats()["pending"] == 0
        assert s.stats()["executed"] == 1


class TestM11aSortedOrder:
    def test_due_at_returns_sorted_by_symbol(self):
        """M11a determinism: sorted iteration prevents PYTHONHASHSEED bug."""
        s = DeferredExecutionSchedule(execution_delay_bars=0)
        # Schedule fills for symbols out of alpha order
        for sym in ["ZZZZ", "AAA", "MMMM"]:
            state = SignalState(
                symbol=sym, armed_at_bar=5, ttl_bars=0,
                status=SignalStatus.CONFIRMED, confirmed_at_bar=5,
            )
            s.schedule_fill(state, target_weight=0.1)
        due = s.due_at(5)
        # Must return in alpha-sorted order regardless of insertion order
        assert [e.symbol for e in due] == ["AAA", "MMMM", "ZZZZ"]


class TestCashCarry:
    def test_armed_position_held_as_cash(self):
        s = DeferredExecutionSchedule(execution_delay_bars=3)
        state = SignalState(
            symbol="X", armed_at_bar=10, ttl_bars=10,
            status=SignalStatus.CONFIRMED, confirmed_at_bar=15,
        )
        s.schedule_fill(state, target_weight=0.5)
        # At bar 16-17: pending fill at bar 18 — X is in cash-carry
        cash = s.cash_carry_symbols_at(16)
        assert "X" in cash
        assert cash["X"] == 0.5
        # At bar 18 (fill bar): X no longer in pending after due_at
        s.due_at(18)
        cash_post = s.cash_carry_symbols_at(18)
        assert "X" not in cash_post


class TestOverdue:
    def test_overdue_detection(self):
        s = DeferredExecutionSchedule(execution_delay_bars=1)
        state = SignalState(
            symbol="X", armed_at_bar=5, ttl_bars=2,
            status=SignalStatus.CONFIRMED, confirmed_at_bar=6,
        )
        s.schedule_fill(state, target_weight=0.3)
        # Skip past bar 7 (scheduled fill), check overdue at bar 8
        overdue = s.overdue_at(8)
        assert len(overdue) == 1
        assert overdue[0].symbol == "X"
        # After overdue extraction, no longer pending
        assert s.stats()["pending"] == 0


class TestIntegrationWithStateMachine:
    def test_full_workflow_arm_confirm_schedule(self):
        """End-to-end: state machine confirms signal → scheduler queues fill."""
        machine = SignalStateMachine()
        schedule = DeferredExecutionSchedule(execution_delay_bars=1)

        # Bar 10: arm AAPL
        s = machine.arm("AAPL", bar_idx=10, ttl_bars=5)
        # Bar 11: confirmation predicate fires
        fired = machine.advance_and_confirm(11, lambda _: True)
        assert len(fired) == 1
        # Schedule the confirmed fill
        schedule.schedule_fill(fired[0], target_weight=0.25)
        # Fill due at bar 12 (11 + 1 delay)
        due = schedule.due_at(12)
        assert len(due) == 1
        assert due[0].symbol == "AAPL"
        assert due[0].target_weight == 0.25
        assert due[0].armed_at_bar == 10
        assert due[0].confirmed_at_bar == 11
