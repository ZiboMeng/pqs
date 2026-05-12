"""Tests for setup-then-trigger signal state machine.

PRD 2026-05-12 (Signal-confirmation MVP Phase 1).
"""

from __future__ import annotations

import pytest

from core.signals.signal_state import (
    SignalState,
    SignalStateMachine,
    SignalStatus,
)


class TestArmAndExpire:
    def test_arm_creates_armed_state(self):
        m = SignalStateMachine()
        s = m.arm("AAPL", bar_idx=10, ttl_bars=5)
        assert s.status == SignalStatus.ARMED
        assert s.armed_at_bar == 10
        assert len(m.active_signals()) == 1

    def test_advance_no_confirmation_expires_at_ttl(self):
        m = SignalStateMachine()
        m.arm("AAPL", bar_idx=10, ttl_bars=3)
        # No confirmation across bars 10..13
        for bar in [10, 11, 12]:
            fired = m.advance_and_confirm(bar, confirmation_check=lambda s: False)
            assert fired == []
            assert len(m.active_signals()) == 1  # still armed
        # At bar 13, age=3 ≥ ttl=3 → expire
        fired = m.advance_and_confirm(13, confirmation_check=lambda s: False)
        assert fired == []
        assert len(m.active_signals()) == 0
        terminal = m.terminal_history()
        assert len(terminal) == 1
        assert terminal[0].status == SignalStatus.EXPIRED


class TestConfirmFiring:
    def test_same_bar_confirmation_ttl_zero(self):
        """ttl_bars=0 → same-bar gate (§3.1). Confirmation at arm bar fires."""
        m = SignalStateMachine()
        m.arm("AAPL", bar_idx=10, ttl_bars=0)
        fired = m.advance_and_confirm(10, confirmation_check=lambda s: True)
        assert len(fired) == 1
        assert fired[0].status == SignalStatus.CONFIRMED
        assert fired[0].confirmed_at_bar == 10
        assert len(m.active_signals()) == 0

    def test_confirmation_within_ttl_fires(self):
        m = SignalStateMachine()
        m.arm("AAPL", bar_idx=10, ttl_bars=5)
        # Confirm at bar 12 (age=2 < ttl=5)
        m.advance_and_confirm(10, confirmation_check=lambda s: False)
        m.advance_and_confirm(11, confirmation_check=lambda s: False)
        fired = m.advance_and_confirm(12, confirmation_check=lambda s: True)
        assert len(fired) == 1
        assert fired[0].confirmed_at_bar == 12

    def test_confirmation_after_ttl_does_not_fire(self):
        """Confirmation must beat ttl. Late confirmation → state already expired."""
        m = SignalStateMachine()
        m.arm("AAPL", bar_idx=10, ttl_bars=2)
        m.advance_and_confirm(10, confirmation_check=lambda s: False)
        m.advance_and_confirm(11, confirmation_check=lambda s: False)
        # At bar 12, age=2 ≥ ttl=2 → expire FIRST (confirmation_check called
        # but we'll test with check=False so it goes to expired path)
        m.advance_and_confirm(12, confirmation_check=lambda s: False)
        # Bar 13: already expired; advance_and_confirm should not re-fire
        fired = m.advance_and_confirm(13, confirmation_check=lambda s: True)
        assert fired == []  # no active signals to fire


class TestMultiSymbolIndependence:
    def test_multiple_symbols_independent(self):
        m = SignalStateMachine()
        m.arm("AAPL", bar_idx=10, ttl_bars=3)
        m.arm("MSFT", bar_idx=10, ttl_bars=3)
        # Only AAPL confirms at bar 11
        fired = m.advance_and_confirm(
            11, confirmation_check=lambda s: s.symbol == "AAPL",
        )
        assert len(fired) == 1
        assert fired[0].symbol == "AAPL"
        # MSFT still armed
        active = m.active_signals()
        assert len(active) == 1
        assert active[0].symbol == "MSFT"


class TestMetadataPreserved:
    def test_setup_metadata_carries_through(self):
        m = SignalStateMachine()
        m.arm("AAPL", bar_idx=10, ttl_bars=5, setup_metadata={"breakout_high": 150.0})
        fired = m.advance_and_confirm(11, confirmation_check=lambda s: True)
        assert fired[0].setup_metadata["breakout_high"] == 150.0


class TestStats:
    def test_stats_track_three_states(self):
        m = SignalStateMachine()
        # Arm 3 signals
        m.arm("A", 10, ttl_bars=2)
        m.arm("B", 10, ttl_bars=2)
        m.arm("C", 10, ttl_bars=2)
        # A confirms at bar 11
        m.advance_and_confirm(11, confirmation_check=lambda s: s.symbol == "A")
        # B & C expire at bar 12
        m.advance_and_confirm(12, confirmation_check=lambda s: False)
        stats = m.stats()
        assert stats == {"armed": 0, "confirmed": 1, "expired": 2}


class TestLeakagePrevention:
    """The state machine itself does NOT prevent caller-side leakage —
    that's the caller's responsibility. But: state must NEVER access
    information from bars > current_bar.

    These tests verify the machine doesn't have hidden lookahead via
    its own internal state (e.g., reading future TTL conditions).
    """

    def test_machine_state_only_advances_through_advance_calls(self):
        """No 'time travel' via state inspection — armed_at_bar is set
        at arm time and never modified."""
        m = SignalStateMachine()
        s = m.arm("X", bar_idx=5, ttl_bars=10)
        original_armed_at = s.armed_at_bar
        # Advance many bars without confirming
        for b in range(5, 14):
            m.advance_and_confirm(b, confirmation_check=lambda x: False)
        # State's armed_at_bar is immutable
        assert s.armed_at_bar == original_armed_at
