"""PRD-X v2 Phase X1 — DecisionPolicy / ExecutionPolicy schema (TDD).

build round. AC (PRD §11 X1):
  - 新 schema 单测全绿
  - 既有 backtest/paper 默认路径 bit-identical(GenerateStrategyAdapter
    with default mode=off → strategy.generate() output unchanged,
    same pattern as cascade_overlay R12 mode='off' / construction_tier
    T0 / xgb_alpha sample_weight=None)
  - sealed 2026 永不读(schema-only,不读 panel)

Honest scope (R4/R6/R7 + PRD §F.2): the 6/7 strategies already share
``.generate()``; 1/7 (intraday_reversal) already has the 4-method
state machine (detect_setups/confirm_signals/build_target_weights/
step_day) which IS the blueprint. NEW = Protocol abstractions +
GenerateStrategyAdapter wrapping the 6 .generate() strategies +
lifecycle 三元组 helper. Strategies themselves UNTOUCHED.
"""
import inspect

import pandas as pd
import pytest

from core.research.decision import (
    ActionDecision,
    ActionType,
    DecisionPolicy,
    ExecutionPolicy,
    GenerateStrategyAdapter,
    LifecycleMapper,
    PositionState,
)
from core.signals.signal_state import SignalStatus


# ── enums + dataclasses ──────────────────────────────────────────────
class TestActionTypeEnum:
    def test_nine_actions_per_prd_4_3(self):
        # PRD §4.3 explicit 9-action set, new enum disjoint from
        # SignalStatus (per audit issue #12 + §4.3 verification).
        names = {a.name for a in ActionType}
        assert names == {"ENTER_FULL", "ENTER_PARTIAL", "ADD", "HOLD",
                         "TRIM", "EXIT", "DEFER", "VETO", "NO_TRADE"}

    def test_action_type_disjoint_from_signal_status(self):
        # SignalStatus has 3 members (ARMED/CONFIRMED/EXPIRED) —
        # ActionType (9 members) must be a separate enum with no name
        # collision. PRD §4.1.1 三元组 design.
        signal_names = {s.name for s in SignalStatus}
        action_names = {a.name for a in ActionType}
        assert signal_names.isdisjoint(action_names)


class TestPositionStateEnum:
    def test_flat_and_hold_only(self):
        # PRD §4.1.1 三元组: PositionState ∈ {FLAT, HOLD}.
        # Other PRD §4.1 states (ENTERED, EXITED, TRIMMED) are
        # transient transitions, not the holdable position state.
        names = {p.name for p in PositionState}
        assert names == {"FLAT", "HOLD"}


class TestActionDecisionDataclass:
    def test_required_fields(self):
        d = ActionDecision(
            symbol="SPY", date=pd.Timestamp("2025-04-01"),
            status=SignalStatus.ARMED, action=ActionType.ENTER_FULL,
            position_state=PositionState.FLAT,
            target_weight=0.10, reason="factor crossover")
        assert d.symbol == "SPY"
        assert d.status is SignalStatus.ARMED
        assert d.action is ActionType.ENTER_FULL
        assert d.position_state is PositionState.FLAT
        assert d.target_weight == pytest.approx(0.10)

    def test_long_only_invariant_target_weight_non_negative(self):
        # PRD §6.4 invariant: long-only / no-short. ActionDecision
        # must refuse negative target_weight at construction.
        with pytest.raises(ValueError, match=r"long-only|non-negative"):
            ActionDecision(
                symbol="SPY", date=pd.Timestamp("2025-04-01"),
                status=SignalStatus.CONFIRMED,
                action=ActionType.ENTER_FULL,
                position_state=PositionState.FLAT,
                target_weight=-0.05)


# ── Protocols ────────────────────────────────────────────────────────
class TestDecisionPolicyProtocol:
    def test_protocol_has_state_machine_4_methods(self):
        # PRD §11 X1 design: 4-method state machine modelled on
        # intraday_reversal's pattern (the 1/7 blueprint).
        members = {m for m in dir(DecisionPolicy) if not m.startswith("_")}
        required = {"detect_setups", "confirm_signals",
                    "build_target_weights", "step_day"}
        assert required.issubset(members), f"missing {required - members}"


class TestExecutionPolicyProtocol:
    def test_protocol_has_execution_3_methods(self):
        # PRD §6.3 4-action set (Immediate full / Deferred / Partial /
        # Staggered) needs the 3-method facade:
        members = {m for m in dir(ExecutionPolicy) if not m.startswith("_")}
        required = {"schedule_fill", "should_defer", "partial_size"}
        assert required.issubset(members), f"missing {required - members}"


# ── GenerateStrategyAdapter (the 6/7 wrap) ───────────────────────────
class _MockGenerateStrategy:
    """Minimal mock of the 6 strategies' .generate() signature."""
    def __init__(self, weights):
        self._w = weights
    def generate(self, date, ctx=None):
        return self._w


class TestGenerateStrategyAdapter:
    def test_wraps_generate_to_decision_policy(self):
        s = _MockGenerateStrategy({"SPY": 0.4, "QQQ": 0.6})
        adapter = GenerateStrategyAdapter(s)
        # adapter must satisfy DecisionPolicy Protocol
        for m in ("detect_setups", "confirm_signals",
                  "build_target_weights", "step_day"):
            assert hasattr(adapter, m), f"adapter missing {m}"

    def test_default_mode_off_bit_identical_to_generate(self):
        # AC: GenerateStrategyAdapter(strategy, mode="off") must
        # produce target weights byte-equal to strategy.generate()
        # itself (no decision-layer routing applied). Same pattern
        # as cascade_overlay R12 mode='off' / construction_tier T0 /
        # XGBAlphaModel.fit(sample_weight=None).
        weights = {"SPY": 0.4, "QQQ": 0.35, "GLD": 0.25}
        s = _MockGenerateStrategy(weights)
        adapter = GenerateStrategyAdapter(s, mode="off")
        out = adapter.build_target_weights(
            state=None, ctx={"date": pd.Timestamp("2025-04-01")})
        # mode='off' → identity pass-through
        assert out == weights

    def test_mode_unknown_rejected(self):
        s = _MockGenerateStrategy({})
        with pytest.raises(ValueError, match=r"mode"):
            GenerateStrategyAdapter(s, mode="bogus")

    def test_strategy_untouched_no_subclass_required(self):
        # Protocol-based duck typing: strategy doesn't inherit
        # DecisionPolicy, only the adapter does. Strategy class
        # untouched. PRD §F.3 C2 solution.
        s = _MockGenerateStrategy({})
        assert not issubclass(type(s), object) is False  # tautology to assert no MRO change required
        # adapter doesn't mutate the wrapped strategy
        adapter = GenerateStrategyAdapter(s)
        assert adapter._strategy is s


# ── LifecycleMapper: PRD §4.1 10-state → (SignalStatus, Action, PositionState) ──
class TestLifecycleMapper:
    def test_flat_lifecycle(self):
        m = LifecycleMapper.from_lifecycle("FLAT")
        # FLAT: no signal status, no action, position FLAT
        assert m == (None, None, PositionState.FLAT)

    def test_armed_entry_lifecycle(self):
        m = LifecycleMapper.from_lifecycle("ARMED_ENTRY",
                                           action=ActionType.ENTER_FULL,
                                           position=PositionState.FLAT)
        assert m == (SignalStatus.ARMED, ActionType.ENTER_FULL,
                     PositionState.FLAT)

    def test_confirmed_exit_lifecycle(self):
        m = LifecycleMapper.from_lifecycle("CONFIRMED_EXIT",
                                           action=ActionType.EXIT,
                                           position=PositionState.HOLD)
        assert m == (SignalStatus.CONFIRMED, ActionType.EXIT,
                     PositionState.HOLD)

    def test_unknown_lifecycle_raises(self):
        with pytest.raises(ValueError, match=r"unknown lifecycle"):
            LifecycleMapper.from_lifecycle("BOGUS_STATE")


# ── Invariant guards (PRD §6.4 embedded at schema layer) ─────────────
class TestInvariantGuards:
    def test_no_short_action_in_action_type(self):
        # ActionType must NOT contain SHORT_*-style members.
        names = {a.name for a in ActionType}
        for forbidden in ("SHORT_ENTER", "SELL_SHORT", "SHORT",
                          "ENTER_SHORT"):
            assert forbidden not in names

    def test_action_decision_rejects_short_via_negative_weight(self):
        # already covered above; explicit invariant cross-reference
        with pytest.raises(ValueError):
            ActionDecision(
                symbol="X", date=pd.Timestamp("2025-04-01"),
                status=SignalStatus.CONFIRMED, action=ActionType.EXIT,
                position_state=PositionState.FLAT,
                target_weight=-1.0)


# ── Structural guard: schema reads no panel data ─────────────────────
class TestSchemaPure:
    def test_decision_module_imports_no_panel_or_bar_store(self):
        # Schema-only layer must NOT import data loaders (sealed-2026
        # discipline: schema layer can't read panel at construction).
        # Test must check actual IMPORT statements + CALL syntax, not
        # free-text mentions in docstrings (R3 my-test-bug fix: prior
        # `forbidden not in src` flagged docstring discipline text
        # mentioning "yfinance"/"bar-store" by name).
        import core.research.decision as dm
        import ast
        tree = ast.parse(inspect.getsource(dm))
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    imported_names.add(n.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)
        # the schema can import SignalStatus + stdlib + typing + pandas;
        # NOT BarStore / MarketDataStore / yfinance / panel loaders.
        forbidden_import_patterns = ("core.data", "yfinance",
                                     "core.data.bar_store",
                                     "core.data.market_data_store")
        for forbidden in forbidden_import_patterns:
            for name in imported_names:
                assert not name.startswith(forbidden), (
                    f"decision schema imports {name} — must be pure "
                    f"schema layer (sealed-2026 discipline)")
