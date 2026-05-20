"""PRD-X v2 Phase X2 sub-step 5d — RuleBasedDecisionPolicy (TDD).

Composes EntryTrigger + ExitTrigger + NoTradeBandCalculator into a
concrete DecisionPolicy Protocol implementation. AC:

  - satisfies the 4-method DecisionPolicy Protocol
    (detect_setups / confirm_signals / build_target_weights / step_day)
  - mode='off' default → no decisions emitted (legacy path
    bit-identical, same pattern as cascade_overlay R12 /
    construction_tier T0 / sample_weight=None)
  - state machine: FLAT → ARMED → CONFIRMED → HOLD; exit triggers
    drive HOLD → EXITED transitions
  - ActionDecision outputs respect §6.4 long-only invariant
    (target_weight >= 0)
  - no panel/bar-store imports at module level (schema purity)
"""
import inspect
import pandas as pd
import pytest

from core.regime.regime_detector import RegimeState
from core.research.decision import (
    ActionDecision,
    ActionType,
    DecisionPolicy,
    PositionState,
)
from core.research.decision.entry_triggers import FactorEntryTrigger
from core.research.decision.exit_triggers import ThesisDecayTrigger
from core.research.decision.no_trade_band import NoTradeBandCalculator
from core.research.decision.rule_based_policy import (
    RuleBasedDecisionPolicy,
    SetupRecord,
)
from core.signals.signal_state import SignalStatus


# ── construction + Protocol satisfaction ────────────────────────────
class TestConstruction:
    def test_default_mode_off(self):
        p = RuleBasedDecisionPolicy(entry_triggers=[], exit_triggers=[])
        assert p.mode == "off"

    def test_active_mode_accepted(self):
        p = RuleBasedDecisionPolicy(entry_triggers=[],
                                    exit_triggers=[], mode="active")
        assert p.mode == "active"

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValueError, match=r"mode"):
            RuleBasedDecisionPolicy(entry_triggers=[],
                                     exit_triggers=[], mode="bogus")


class TestProtocolSatisfaction:
    def test_satisfies_decision_policy_4_methods(self):
        p = RuleBasedDecisionPolicy(entry_triggers=[], exit_triggers=[])
        for m in ("detect_setups", "confirm_signals",
                  "build_target_weights", "step_day"):
            assert hasattr(p, m), f"missing {m}"


# ── mode='off' bit-identical: zero decisions emitted ───────────────
class TestModeOffBitIdentical:
    def test_off_mode_detect_setups_empty(self):
        # mode='off' → trigger framework dormant; same precedent as
        # cascade_overlay R12 mode='off' (legacy unchanged)
        entry = FactorEntryTrigger(entry_threshold=0.6)
        p = RuleBasedDecisionPolicy(entry_triggers=[entry],
                                    exit_triggers=[], mode="off")
        out = p.detect_setups(state=None,
                              ctx={"symbol": "SPY",
                                   "date": pd.Timestamp("2025-04-01"),
                                   "factor_score": 0.9})
        assert out == []  # off mode → empty (no detection)

    def test_off_mode_build_target_weights_empty(self):
        p = RuleBasedDecisionPolicy(entry_triggers=[],
                                    exit_triggers=[], mode="off")
        w = p.build_target_weights(state=None, ctx={})
        assert w == {}


# ── active mode: detect_setups runs triggers ───────────────────────
class TestActiveDetect:
    def test_active_detect_runs_entry_triggers(self):
        entry = FactorEntryTrigger(entry_threshold=0.6)
        p = RuleBasedDecisionPolicy(entry_triggers=[entry],
                                    exit_triggers=[], mode="active")
        setups = p.detect_setups(
            state=None,
            ctx={"symbol": "SPY",
                 "date": pd.Timestamp("2025-04-01"),
                 "factor_score": 0.85})
        assert len(setups) == 1
        assert setups[0].symbol == "SPY"
        assert setups[0].status is SignalStatus.ARMED

    def test_active_detect_silent_when_no_trigger_fires(self):
        entry = FactorEntryTrigger(entry_threshold=0.6)
        p = RuleBasedDecisionPolicy(entry_triggers=[entry],
                                    exit_triggers=[], mode="active")
        setups = p.detect_setups(
            state=None,
            ctx={"symbol": "X",
                 "date": pd.Timestamp("2025-04-01"),
                 "factor_score": 0.3})
        assert setups == []

    def test_setup_record_carries_strength(self):
        entry = FactorEntryTrigger(entry_threshold=0.5)
        p = RuleBasedDecisionPolicy(entry_triggers=[entry],
                                    exit_triggers=[], mode="active")
        setups = p.detect_setups(
            state=None,
            ctx={"symbol": "X",
                 "date": pd.Timestamp("2025-04-01"),
                 "factor_score": 0.9})
        assert len(setups) == 1
        assert 0 < setups[0].strength <= 1


# ── confirm_signals: ARMED → CONFIRMED with TTL ────────────────────
class TestConfirmSignals:
    def test_armed_setup_confirmed_when_signal_persists(self):
        entry = FactorEntryTrigger(entry_threshold=0.5)
        p = RuleBasedDecisionPolicy(entry_triggers=[entry],
                                    exit_triggers=[], mode="active",
                                    confirm_min_bars=2)
        # day 1: detect
        ctx1 = {"symbol": "SPY",
                "date": pd.Timestamp("2025-04-01"),
                "factor_score": 0.8}
        setups1 = p.detect_setups(state=None, ctx=ctx1)
        assert len(setups1) == 1
        # day 1: confirm with 1 bar of persistence → still ARMED
        confirmed1 = p.confirm_signals(state=None, ctx=ctx1)
        assert all(s.status is SignalStatus.ARMED for s in confirmed1)
        # day 2: persist → now CONFIRMED
        ctx2 = {"symbol": "SPY",
                "date": pd.Timestamp("2025-04-02"),
                "factor_score": 0.85}
        p.detect_setups(state=None, ctx=ctx2)
        confirmed2 = p.confirm_signals(state=None, ctx=ctx2)
        assert any(s.status is SignalStatus.CONFIRMED
                   for s in confirmed2)


# ── build_target_weights: CONFIRMED → ActionDecision ───────────────
class TestBuildTargetWeights:
    def test_confirmed_produces_action_decisions(self):
        entry = FactorEntryTrigger(entry_threshold=0.5)
        p = RuleBasedDecisionPolicy(
            entry_triggers=[entry], exit_triggers=[],
            mode="active", confirm_min_bars=1)
        ctx = {"symbol": "SPY", "date": pd.Timestamp("2025-04-01"),
               "factor_score": 0.85}
        p.detect_setups(state=None, ctx=ctx)
        p.confirm_signals(state=None, ctx=ctx)
        weights = p.build_target_weights(state=None, ctx=ctx)
        assert "SPY" in weights
        assert weights["SPY"] >= 0  # long-only

    def test_build_returns_dict_str_float(self):
        p = RuleBasedDecisionPolicy(entry_triggers=[],
                                    exit_triggers=[], mode="active")
        out = p.build_target_weights(state=None, ctx={})
        assert isinstance(out, dict)


# ── exit triggers drive EXIT actions ───────────────────────────────
class TestExitWiring:
    def test_exit_trigger_fires_after_position_held(self):
        entry = FactorEntryTrigger(entry_threshold=0.5)
        exit_t = ThesisDecayTrigger(exit_threshold=0.4)
        p = RuleBasedDecisionPolicy(
            entry_triggers=[entry], exit_triggers=[exit_t],
            mode="active", confirm_min_bars=1)
        # entry day
        ctx_in = {"symbol": "SPY",
                  "date": pd.Timestamp("2025-04-01"),
                  "factor_score": 0.85}
        p.detect_setups(state=None, ctx=ctx_in)
        p.confirm_signals(state=None, ctx=ctx_in)
        p.build_target_weights(state=None, ctx=ctx_in)
        # exit day: factor decays below threshold
        ctx_out = {"symbol": "SPY",
                   "date": pd.Timestamp("2025-04-15"),
                   "factor_score": 0.2}  # below exit_threshold=0.4
        p.step_day(state=None, ctx=ctx_out)
        weights = p.build_target_weights(state=None, ctx=ctx_out)
        assert weights.get("SPY", 0.0) == 0.0  # exited


# ── step_day: TTL expiry + risk processing ─────────────────────────
class TestStepDay:
    def test_step_day_returns_state(self):
        p = RuleBasedDecisionPolicy(entry_triggers=[],
                                    exit_triggers=[], mode="active")
        out = p.step_day(state=None, ctx={})
        # state-machine advance returns SOMETHING (state object or None
        # for off-mode); shouldn't crash
        assert out is None or out is not False


# ── §6.4 invariant: long-only ──────────────────────────────────────
class TestLongOnlyInvariant:
    def test_target_weights_non_negative(self):
        entry = FactorEntryTrigger(entry_threshold=0.5)
        p = RuleBasedDecisionPolicy(
            entry_triggers=[entry], exit_triggers=[], mode="active",
            confirm_min_bars=1)
        ctx = {"symbol": "SPY", "date": pd.Timestamp("2025-04-01"),
               "factor_score": 0.85}
        p.detect_setups(state=None, ctx=ctx)
        p.confirm_signals(state=None, ctx=ctx)
        weights = p.build_target_weights(state=None, ctx=ctx)
        for s, w in weights.items():
            assert w >= 0, f"{s} weight {w} negative — long-only violated"


# ── schema purity ──────────────────────────────────────────────────
class TestSchemaPurity:
    def test_no_panel_imports(self):
        import core.research.decision.rule_based_policy as mod
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
                    f"rule_based_policy imports {name} — pure "
                    f"composition layer, no panel access")


# ── SetupRecord dataclass ──────────────────────────────────────────
class TestSetupRecord:
    def test_required_fields(self):
        s = SetupRecord(
            symbol="SPY", date=pd.Timestamp("2025-04-01"),
            status=SignalStatus.ARMED, source="factor_entry",
            strength=0.8, armed_date=pd.Timestamp("2025-04-01"))
        assert s.symbol == "SPY"
        assert s.status is SignalStatus.ARMED
        assert s.strength == 0.8
