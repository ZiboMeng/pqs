"""PRD-X v2 Phase X2 sub-step 5b — ExitTrigger protocol + 4 impls (TDD).

build round. AC (PRD §5.2 + §11 X2):
  - ExitTrigger Protocol (evaluate(ctx) -> Optional[ExitEvent])
  - 4 concrete impls (PRD §5.2 A/B/C):
      ThesisDecayTrigger        (factor score 跌破 exit threshold)
      FactorExitTrigger         (sibling-overlap up, edge gone)
      EventInvalidationTrigger  (event-window factor 转负 / catalyst
                                  resolved)
      RiskExitTrigger           (subscribe core/risk/* modules)
  - non-blanket framing: each trigger returns Optional[ExitEvent] +
    reason string (FailureSignal-style record-and-route).
  - sealed-2026 discipline: triggers read ctx only, no panel.
"""
import inspect

import pandas as pd
import pytest

from core.research.decision.exit_triggers import (
    EventInvalidationTrigger,
    ExitEvent,
    ExitTrigger,
    FactorExitTrigger,
    RiskExitTrigger,
    ThesisDecayTrigger,
)


# ── ExitEvent dataclass + Protocol ───────────────────────────────────
class TestExitEvent:
    def test_required_fields(self):
        e = ExitEvent(symbol="SPY", date=pd.Timestamp("2025-04-01"),
                      source="thesis_decay", reason="factor < threshold")
        assert e.symbol == "SPY" and e.source == "thesis_decay"


class TestExitTriggerProtocol:
    def test_protocol_has_evaluate(self):
        members = {m for m in dir(ExitTrigger) if not m.startswith("_")}
        assert "evaluate" in members


# ── ThesisDecayTrigger (factor score 跌破 exit threshold) ───────────
class TestThesisDecay:
    def test_fires_when_factor_below_threshold(self):
        t = ThesisDecayTrigger(exit_threshold=0.5)
        e = t.evaluate({"symbol": "SPY", "date": pd.Timestamp("2025-04-01"),
                        "factor_score": 0.3})
        assert e is not None
        assert e.source == "thesis_decay"
        assert "factor" in e.reason.lower()

    def test_silent_when_factor_above_threshold(self):
        t = ThesisDecayTrigger(exit_threshold=0.5)
        e = t.evaluate({"symbol": "SPY", "date": pd.Timestamp("2025-04-01"),
                        "factor_score": 0.8})
        assert e is None

    def test_missing_factor_silent(self):
        # graceful: factor_score absent → no trigger (not a crash)
        t = ThesisDecayTrigger(exit_threshold=0.5)
        e = t.evaluate({"symbol": "X", "date": pd.Timestamp("2025-04-01")})
        assert e is None


# ── FactorExitTrigger (sibling-overlap up, expected_excess < cost) ──
class TestFactorExit:
    def test_fires_when_sibling_overlap_high(self):
        t = FactorExitTrigger(sibling_overlap_threshold=0.7,
                              min_expected_excess=0.0)
        e = t.evaluate({"symbol": "X", "date": pd.Timestamp("2025-04-01"),
                        "sibling_overlap": 0.85,
                        "expected_excess": 0.05})
        assert e is not None
        assert "sibling" in e.reason.lower()

    def test_fires_when_expected_excess_below_cost_buffer(self):
        t = FactorExitTrigger(sibling_overlap_threshold=0.99,
                              min_expected_excess=0.02)
        e = t.evaluate({"symbol": "X", "date": pd.Timestamp("2025-04-01"),
                        "sibling_overlap": 0.5,
                        "expected_excess": 0.005})
        assert e is not None
        assert "expected" in e.reason.lower() or "excess" in e.reason.lower()

    def test_silent_when_both_ok(self):
        t = FactorExitTrigger(sibling_overlap_threshold=0.7,
                              min_expected_excess=0.0)
        e = t.evaluate({"symbol": "X", "date": pd.Timestamp("2025-04-01"),
                        "sibling_overlap": 0.4,
                        "expected_excess": 0.05})
        assert e is None


# ── EventInvalidationTrigger ────────────────────────────────────────
class TestEventInvalidation:
    def test_fires_when_event_factor_turns_negative(self):
        t = EventInvalidationTrigger(min_event_factor=0.0)
        e = t.evaluate({"symbol": "X", "date": pd.Timestamp("2025-04-01"),
                        "event_window_factor": -0.05})
        assert e is not None
        assert "event" in e.reason.lower()

    def test_fires_when_catalyst_resolved(self):
        t = EventInvalidationTrigger()
        e = t.evaluate({"symbol": "X", "date": pd.Timestamp("2025-04-01"),
                        "event_window_factor": 0.02,
                        "catalyst_resolved": True})
        assert e is not None
        assert "catalyst" in e.reason.lower() or "resolved" in e.reason.lower()

    def test_silent_when_event_positive_and_unresolved(self):
        t = EventInvalidationTrigger(min_event_factor=0.0)
        e = t.evaluate({"symbol": "X", "date": pd.Timestamp("2025-04-01"),
                        "event_window_factor": 0.02,
                        "catalyst_resolved": False})
        assert e is None


# ── RiskExitTrigger (subscribe core/risk/*) ─────────────────────────
class _FakeKillSwitch:
    def __init__(self, triggered=False, reason=""):
        self._tr = triggered
        self._rs = reason
    def is_triggered(self):
        return self._tr


class TestRiskExitSubscription:
    def test_fires_when_kill_switch_triggered(self):
        ks = _FakeKillSwitch(triggered=True, reason="MaxDD 22%")
        t = RiskExitTrigger(kill_switch=ks)
        e = t.evaluate({"symbol": "X", "date": pd.Timestamp("2025-04-01")})
        assert e is not None
        assert e.source == "risk_exit"
        assert "kill" in e.reason.lower() or "risk" in e.reason.lower()

    def test_silent_when_kill_switch_inactive(self):
        ks = _FakeKillSwitch(triggered=False)
        t = RiskExitTrigger(kill_switch=ks)
        e = t.evaluate({"symbol": "X", "date": pd.Timestamp("2025-04-01")})
        assert e is None

    def test_fires_on_failure_signal(self):
        # FailureDetector pattern: ctx may carry a list of
        # FailureSignal objects from check_all()
        from dataclasses import dataclass
        @dataclass
        class _Sig:
            kind: str = "drawdown"
            triggered: bool = True
            value: float = 0.25
        t = RiskExitTrigger()
        e = t.evaluate({"symbol": "X", "date": pd.Timestamp("2025-04-01"),
                        "failure_signals": [_Sig()]})
        assert e is not None
        assert "drawdown" in e.reason.lower() or "failure" in e.reason.lower()

    def test_fires_on_higher_tf_strong_veto(self):
        # PRD §5.2.C: higher-TF context 从 confirm 变为 strong veto
        t = RiskExitTrigger()
        e = t.evaluate({"symbol": "X", "date": pd.Timestamp("2025-04-01"),
                        "higher_tf_state": "STRONG_VETO"})
        assert e is not None
        assert "veto" in e.reason.lower() or "tf" in e.reason.lower()

    def test_silent_when_no_risk_signal(self):
        t = RiskExitTrigger()
        e = t.evaluate({"symbol": "X", "date": pd.Timestamp("2025-04-01")})
        assert e is None


# ── invariants + schema purity ──────────────────────────────────────
class TestSchemaPurity:
    def test_no_panel_imports(self):
        import core.research.decision.exit_triggers as mod
        import ast
        tree = ast.parse(inspect.getsource(mod))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                for n in node.names:
                    imported.add(n.name)
        for forbidden in ("core.data", "yfinance",
                          "core.data.bar_store"):
            for name in imported:
                assert not name.startswith(forbidden), (
                    f"exit_triggers imports {name} — pure ctx-driven, "
                    f"no panel access")


class TestProtocolSatisfaction:
    def test_all_4_satisfy_exit_trigger_protocol(self):
        # all 4 concrete impls must satisfy ExitTrigger.evaluate API
        for cls in (ThesisDecayTrigger, FactorExitTrigger,
                    EventInvalidationTrigger, RiskExitTrigger):
            # construct with minimal kwargs
            if cls is ThesisDecayTrigger:
                inst = cls(exit_threshold=0.5)
            elif cls is FactorExitTrigger:
                inst = cls()
            elif cls is EventInvalidationTrigger:
                inst = cls()
            else:
                inst = cls()
            assert hasattr(inst, "evaluate")
            # evaluate(ctx) returns Optional[ExitEvent]
            r = inst.evaluate({"symbol": "X",
                               "date": pd.Timestamp("2025-04-01")})
            assert r is None or isinstance(r, ExitEvent)
