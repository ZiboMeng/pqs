"""Focused tests for apply_kill_switch_to_target() helper in scripts/run_paper.py.

Covers the guarantee that both replay and live flows route target-weight
adjustments through the same kill-switch gate:

  - NORMAL    → target unchanged
  - DEGRADED  → every weight multiplied by position_multiplier
  - SUSPENDED → target becomes empty dict (force liquidation to cash)
  - engine without kill_switch (e.g. a minimal test stub) → no-op
"""
from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

# Load run_paper.py as a module (it's a script, not a package entry).
_RUN_PAPER_PATH = Path(__file__).resolve().parents[3] / "scripts" / "run_paper.py"


@pytest.fixture(scope="module")
def run_paper_mod():
    spec = importlib.util.spec_from_file_location("_run_paper_under_test", _RUN_PAPER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _StubTracker:
    def __init__(self, records):
        self._records = records


class _StubKS:
    """Minimal KillSwitch stub — only emulates what the helper needs."""

    def __init__(self, state, multiplier, triggered=True, rules=("test_rule",)):
        self._state = state
        self._multiplier = multiplier
        self._triggered = triggered
        self._rules = list(rules)

    def evaluate(self, equity_series):
        # imitate KillSwitchResult shape; only fields the helper reads
        r = types.SimpleNamespace(
            state=self._state,
            position_multiplier=self._multiplier,
            active_rules=self._rules,
            triggered=self._triggered,
        )
        return r


class _StubEngine:
    def __init__(self, kill_switch=None, equity_records=None, initial=10_000.0):
        self.kill_switch = kill_switch
        self._initial_capital = initial
        self._tracker = _StubTracker(equity_records or [])


class TestApplyKillSwitch:
    def test_normal_state_target_unchanged(self, run_paper_mod):
        eng = _StubEngine(kill_switch=_StubKS("NORMAL", 1.0, triggered=False))
        target = {"SPY": 0.5, "QQQ": 0.5}
        new_target, result = run_paper_mod.apply_kill_switch_to_target(eng, target)
        assert new_target == target
        assert result.state == "NORMAL"

    def test_degraded_scales_by_multiplier(self, run_paper_mod):
        eng = _StubEngine(kill_switch=_StubKS("DEGRADED", 0.5))
        target = {"SPY": 0.6, "QQQ": 0.4}
        new_target, result = run_paper_mod.apply_kill_switch_to_target(eng, target)
        assert result.state == "DEGRADED"
        assert new_target == {"SPY": 0.3, "QQQ": 0.2}

    def test_degraded_with_different_multiplier(self, run_paper_mod):
        eng = _StubEngine(kill_switch=_StubKS("DEGRADED", 0.25))
        target = {"AAPL": 0.8, "MSFT": 0.2}
        new_target, result = run_paper_mod.apply_kill_switch_to_target(eng, target)
        assert result.state == "DEGRADED"
        assert new_target == {"AAPL": 0.2, "MSFT": 0.05}

    def test_suspended_forces_empty_target(self, run_paper_mod):
        eng = _StubEngine(kill_switch=_StubKS("SUSPENDED", 0.0))
        target = {"SPY": 1.0}
        new_target, result = run_paper_mod.apply_kill_switch_to_target(eng, target)
        assert new_target == {}
        assert result.state == "SUSPENDED"

    def test_no_kill_switch_returns_unchanged(self, run_paper_mod):
        eng = _StubEngine(kill_switch=None)
        target = {"SPY": 1.0}
        new_target, result = run_paper_mod.apply_kill_switch_to_target(eng, target)
        assert new_target == target
        assert result is None

    def test_equity_series_uses_tracker_records(self, run_paper_mod):
        """When the tracker has records, they should form the equity series."""
        captured = {}

        class _Spy(_StubKS):
            def evaluate(self, equity_series):
                captured["series"] = list(equity_series)
                return types.SimpleNamespace(
                    state="NORMAL", position_multiplier=1.0,
                    active_rules=[], triggered=False,
                )

        records = [{"equity": 10_000}, {"equity": 10_500}, {"equity": 10_200}]
        eng = _StubEngine(kill_switch=_Spy("NORMAL", 1.0), equity_records=records)
        run_paper_mod.apply_kill_switch_to_target(eng, {"SPY": 1.0})
        assert captured["series"] == [10_000, 10_500, 10_200]

    def test_equity_series_falls_back_to_initial(self, run_paper_mod):
        """No tracker records → use [initial_capital]."""
        captured = {}

        class _Spy(_StubKS):
            def evaluate(self, equity_series):
                captured["series"] = list(equity_series)
                return types.SimpleNamespace(
                    state="NORMAL", position_multiplier=1.0,
                    active_rules=[], triggered=False,
                )

        eng = _StubEngine(kill_switch=_Spy("NORMAL", 1.0), equity_records=[], initial=25_000.0)
        run_paper_mod.apply_kill_switch_to_target(eng, {})
        assert captured["series"] == [25_000.0]

    def test_degraded_preserves_zero_weights(self, run_paper_mod):
        eng = _StubEngine(kill_switch=_StubKS("DEGRADED", 0.5))
        target = {"SPY": 0.4, "TLT": 0.0}  # zero should stay zero (0.5×0=0)
        new_target, _ = run_paper_mod.apply_kill_switch_to_target(eng, target)
        assert new_target == {"SPY": 0.2, "TLT": 0.0}
