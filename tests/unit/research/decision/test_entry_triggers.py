"""PRD-X v2 Phase X2 sub-step 5c — EntryTrigger Protocol + 3 impls (TDD).

build round. AC (PRD §5.1 + §11 X2):
  - EntryTrigger Protocol (evaluate(ctx) -> Optional[EntryEvent])
  - 3 concrete impls (PRD §5.1 A/B/C):
      FactorEntryTrigger        (factor score above entry threshold)
      EventEntryTrigger         (event-window factor positive +
                                  catalyst still valid)
      RegimeEntryTrigger        (regime state in allowed set, e.g.
                                  long-side trigger only in
                                  BULL/RISK_ON/NEUTRAL)
  - sealed-2026 discipline: pure ctx readers, zero panel imports
  - non-blanket framing: each trigger returns Optional[EntryEvent];
    fleet composition is the DecisionPolicy's job, not the trigger's.
"""
import inspect

import pandas as pd
import pytest

from core.regime.regime_detector import RegimeState
from core.research.decision.entry_triggers import (
    EntryEvent,
    EntryTrigger,
    EventEntryTrigger,
    FactorEntryTrigger,
    RegimeEntryTrigger,
)


# ── EntryEvent dataclass + Protocol ─────────────────────────────────
class TestEntryEvent:
    def test_required_fields(self):
        e = EntryEvent(symbol="SPY", date=pd.Timestamp("2025-04-01"),
                       source="factor_entry",
                       reason="factor crossover", strength=0.8)
        assert e.symbol == "SPY"
        assert e.source == "factor_entry"
        assert e.strength == 0.8

    def test_strength_clipped_to_unit_interval(self):
        # PRD §5.1: strength ∈ [0, 1] for downstream sizing
        with pytest.raises(ValueError, match=r"strength"):
            EntryEvent(symbol="X", date=pd.Timestamp("2025-04-01"),
                       source="test", reason="r", strength=1.5)
        with pytest.raises(ValueError, match=r"strength"):
            EntryEvent(symbol="X", date=pd.Timestamp("2025-04-01"),
                       source="test", reason="r", strength=-0.1)


class TestEntryTriggerProtocol:
    def test_protocol_has_evaluate(self):
        members = {m for m in dir(EntryTrigger) if not m.startswith("_")}
        assert "evaluate" in members


# ── FactorEntryTrigger ──────────────────────────────────────────────
class TestFactorEntry:
    def test_fires_when_factor_above_threshold(self):
        t = FactorEntryTrigger(entry_threshold=0.6)
        e = t.evaluate({"symbol": "SPY",
                        "date": pd.Timestamp("2025-04-01"),
                        "factor_score": 0.8})
        assert e is not None
        assert e.source == "factor_entry"
        assert "factor" in e.reason.lower()

    def test_silent_when_factor_below_threshold(self):
        t = FactorEntryTrigger(entry_threshold=0.6)
        e = t.evaluate({"symbol": "SPY",
                        "date": pd.Timestamp("2025-04-01"),
                        "factor_score": 0.3})
        assert e is None

    def test_missing_factor_silent(self):
        # graceful: factor_score absent → no trigger (NOT crash)
        t = FactorEntryTrigger(entry_threshold=0.6)
        e = t.evaluate({"symbol": "X",
                        "date": pd.Timestamp("2025-04-01")})
        assert e is None

    def test_strength_proportional_to_excess(self):
        # Higher factor score above threshold → higher strength
        t = FactorEntryTrigger(entry_threshold=0.6)
        e1 = t.evaluate({"symbol": "X",
                         "date": pd.Timestamp("2025-04-01"),
                         "factor_score": 0.7})
        e2 = t.evaluate({"symbol": "X",
                         "date": pd.Timestamp("2025-04-01"),
                         "factor_score": 0.9})
        assert e1.strength < e2.strength
        # both clipped to [0, 1]
        assert 0 <= e1.strength <= 1
        assert 0 <= e2.strength <= 1


# ── EventEntryTrigger ───────────────────────────────────────────────
class TestEventEntry:
    def test_fires_when_event_factor_positive_and_catalyst_valid(self):
        t = EventEntryTrigger(min_event_factor=0.01)
        e = t.evaluate({"symbol": "AAPL",
                        "date": pd.Timestamp("2025-04-01"),
                        "event_window_factor": 0.05,
                        "catalyst_resolved": False})
        assert e is not None
        assert "event" in e.reason.lower()

    def test_silent_when_event_factor_below_threshold(self):
        t = EventEntryTrigger(min_event_factor=0.01)
        e = t.evaluate({"symbol": "X",
                        "date": pd.Timestamp("2025-04-01"),
                        "event_window_factor": 0.005,
                        "catalyst_resolved": False})
        assert e is None

    def test_silent_when_catalyst_already_resolved(self):
        # PRD §5.1.B: catalyst resolved → no new entries (already
        # priced in)
        t = EventEntryTrigger(min_event_factor=0.01)
        e = t.evaluate({"symbol": "X",
                        "date": pd.Timestamp("2025-04-01"),
                        "event_window_factor": 0.05,
                        "catalyst_resolved": True})
        assert e is None

    def test_missing_event_factor_silent(self):
        t = EventEntryTrigger(min_event_factor=0.01)
        e = t.evaluate({"symbol": "X",
                        "date": pd.Timestamp("2025-04-01")})
        assert e is None


# ── RegimeEntryTrigger ──────────────────────────────────────────────
class TestRegimeEntry:
    def test_fires_when_regime_in_allowed_set(self):
        t = RegimeEntryTrigger(allowed_regimes={
            RegimeState.BULL, RegimeState.RISK_ON, RegimeState.NEUTRAL})
        e = t.evaluate({"symbol": "X",
                        "date": pd.Timestamp("2025-04-01"),
                        "regime": RegimeState.BULL})
        assert e is not None
        assert "regime" in e.reason.lower()

    def test_silent_when_regime_outside_allowed(self):
        t = RegimeEntryTrigger(allowed_regimes={
            RegimeState.BULL, RegimeState.RISK_ON})
        e = t.evaluate({"symbol": "X",
                        "date": pd.Timestamp("2025-04-01"),
                        "regime": RegimeState.RISK_OFF})
        assert e is None

    def test_default_allowed_set_is_long_friendly(self):
        # PRD §6.4 long-only invariant + §5.1.C: default RegimeEntry
        # only fires in long-friendly regimes (BULL/RISK_ON/NEUTRAL),
        # NOT in RISK_OFF/CAUTIOUS.
        t = RegimeEntryTrigger()
        e_bull = t.evaluate({"symbol": "X",
                             "date": pd.Timestamp("2025-04-01"),
                             "regime": RegimeState.BULL})
        e_off = t.evaluate({"symbol": "X",
                            "date": pd.Timestamp("2025-04-01"),
                            "regime": RegimeState.RISK_OFF})
        assert e_bull is not None
        assert e_off is None

    def test_missing_regime_silent(self):
        # graceful: no regime info → no trigger
        t = RegimeEntryTrigger()
        e = t.evaluate({"symbol": "X",
                        "date": pd.Timestamp("2025-04-01")})
        assert e is None


# ── schema purity ────────────────────────────────────────────────────
class TestSchemaPurity:
    def test_no_panel_imports(self):
        import core.research.decision.entry_triggers as mod
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
                    f"entry_triggers imports {name} — pure ctx-driven, "
                    f"no panel access")


class TestProtocolSatisfaction:
    def test_all_3_satisfy_entry_trigger_protocol(self):
        for cls in (FactorEntryTrigger, EventEntryTrigger,
                    RegimeEntryTrigger):
            if cls is FactorEntryTrigger:
                inst = cls(entry_threshold=0.5)
            elif cls is EventEntryTrigger:
                inst = cls()
            else:
                inst = cls()
            assert hasattr(inst, "evaluate")
            r = inst.evaluate({"symbol": "X",
                               "date": pd.Timestamp("2025-04-01")})
            assert r is None or isinstance(r, EntryEvent)


# ── §6.4 invariant cross-check ──────────────────────────────────────
class TestLongOnlyInvariant:
    def test_no_short_entry_implied_by_strength_sign(self):
        # PRD §6.4 long-only: EntryEvent.strength ∈ [0, 1] only.
        # Negative strength would imply SHORT_ENTRY — already
        # blocked by EntryEvent dataclass __post_init__.
        with pytest.raises(ValueError, match=r"strength"):
            EntryEvent(symbol="X", date=pd.Timestamp("2025-04-01"),
                       source="test", reason="r", strength=-0.5)
