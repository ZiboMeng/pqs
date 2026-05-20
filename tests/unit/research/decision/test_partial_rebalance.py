"""PRD-X v2 Phase X3 — PartialRebalancePolicy (delta-to-trade) TDD.

AC (PRD §6.3 + §5.3.1):
  - Per-symbol delta-to-trade computation: target - current
  - NoTradeBandCalculator gates: |delta| < band → HOLD / NO_TRADE
  - 4-action routing precision:
      delta > enter_band + current=0           → ENTER_FULL or ENTER_PARTIAL
      delta > add_band   + current>0           → ADD
      delta < -trim_band + current>0           → TRIM
      target≤0 + |delta|>exit_band             → EXIT
  - mode='off' default bit-identical (R12/T0 precedent):
      returns target weights as-is, no delta gating
  - §6.4 long-only invariant:
      target_weight < 0 rejected at construction (ActionDecision)
      EXIT to weight=0 only, never negative
"""
import pandas as pd
import pytest

from core.regime.regime_detector import RegimeState
from core.research.decision import (
    ActionDecision, ActionType, PositionState,
)
from core.research.decision.no_trade_band import NoTradeBandCalculator
from core.research.decision.partial_rebalance import (
    PartialRebalancePolicy,
)
from core.signals.signal_state import SignalStatus


def _band(base=0.02):
    return NoTradeBandCalculator(base_band=base)


# ── construction + mode validation ──────────────────────────────────
class TestConstruction:
    def test_default_mode_off(self):
        p = PartialRebalancePolicy(no_trade_band=_band())
        assert p.mode == "off"

    def test_active_mode_accepted(self):
        p = PartialRebalancePolicy(no_trade_band=_band(), mode="active")
        assert p.mode == "active"

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValueError, match=r"mode"):
            PartialRebalancePolicy(no_trade_band=_band(), mode="bogus")


# ── mode='off' bit-identical pass-through ──────────────────────────
class TestModeOffBitIdentical:
    def test_off_returns_target_unchanged(self):
        p = PartialRebalancePolicy(no_trade_band=_band(), mode="off")
        target = {"SPY": 0.5, "QQQ": 0.3}
        current = {"SPY": 0.4, "QQQ": 0.3}
        out = p.compute_actions(
            target_weights=target,
            current_weights=current,
            ctx={"date": pd.Timestamp("2025-04-01"),
                 "regime": RegimeState.NEUTRAL,
                 "realized_vol": 0.15})
        # mode='off' → minimal pass-through: emit ENTER_FULL for each
        # non-zero target, current ignored (legacy path bit-identical)
        weight_map = {d.symbol: d.target_weight for d in out}
        assert weight_map == target


# ── delta-to-trade routing in active mode ──────────────────────────
class TestDeltaToTradeRouting:
    def _ctx(self):
        return {"date": pd.Timestamp("2025-04-01"),
                "regime": RegimeState.NEUTRAL,
                "realized_vol": 0.15}

    def test_enter_full_when_current_zero_and_delta_large(self):
        # base_band=0.02 × NEUTRAL × vol-anchor = 0.02; enter_band_mult=1.0 = 0.02
        p = PartialRebalancePolicy(no_trade_band=_band(0.02),
                                    mode="active")
        out = p.compute_actions(
            target_weights={"SPY": 0.10},
            current_weights={"SPY": 0.0},
            ctx=self._ctx())
        d = next(d for d in out if d.symbol == "SPY")
        assert d.action == ActionType.ENTER_FULL
        assert d.target_weight == pytest.approx(0.10)

    def test_add_when_existing_position_and_positive_delta(self):
        p = PartialRebalancePolicy(no_trade_band=_band(0.02),
                                    mode="active")
        out = p.compute_actions(
            target_weights={"SPY": 0.15},
            current_weights={"SPY": 0.10},
            ctx=self._ctx())
        d = next(d for d in out if d.symbol == "SPY")
        assert d.action == ActionType.ADD
        assert d.target_weight == pytest.approx(0.15)

    def test_trim_when_existing_position_and_negative_delta(self):
        p = PartialRebalancePolicy(no_trade_band=_band(0.02),
                                    mode="active")
        out = p.compute_actions(
            target_weights={"SPY": 0.05},
            current_weights={"SPY": 0.15},
            ctx=self._ctx())
        d = next(d for d in out if d.symbol == "SPY")
        assert d.action == ActionType.TRIM
        assert d.target_weight == pytest.approx(0.05)

    def test_exit_when_target_zero(self):
        p = PartialRebalancePolicy(no_trade_band=_band(0.02),
                                    mode="active")
        out = p.compute_actions(
            target_weights={"SPY": 0.0},
            current_weights={"SPY": 0.10},
            ctx=self._ctx())
        d = next(d for d in out if d.symbol == "SPY")
        assert d.action == ActionType.EXIT
        assert d.target_weight == 0.0

    def test_exit_when_target_missing(self):
        # symbol absent from target → treat as exit
        p = PartialRebalancePolicy(no_trade_band=_band(0.02),
                                    mode="active")
        out = p.compute_actions(
            target_weights={"QQQ": 0.1},
            current_weights={"SPY": 0.10},
            ctx=self._ctx())
        spy_d = next(d for d in out if d.symbol == "SPY")
        assert spy_d.action == ActionType.EXIT


# ── NoTradeBand gating: |delta| < band → HOLD/NO_TRADE ──────────────
class TestNoTradeBandGating:
    def _ctx(self, vol=0.15):
        return {"date": pd.Timestamp("2025-04-01"),
                "regime": RegimeState.NEUTRAL,
                "realized_vol": vol}

    def test_small_delta_within_band_holds(self):
        # base_band=0.05; |delta|=0.01 < add_band=0.05*0.5=0.025
        p = PartialRebalancePolicy(no_trade_band=_band(0.05),
                                    mode="active")
        out = p.compute_actions(
            target_weights={"SPY": 0.11},
            current_weights={"SPY": 0.10},
            ctx=self._ctx())
        d = next(d for d in out if d.symbol == "SPY")
        assert d.action == ActionType.HOLD
        # target_weight stays at CURRENT (no trade)
        assert d.target_weight == pytest.approx(0.10)

    def test_no_trade_when_both_zero(self):
        p = PartialRebalancePolicy(no_trade_band=_band(),
                                    mode="active")
        out = p.compute_actions(
            target_weights={"SPY": 0.0},
            current_weights={"SPY": 0.0},
            ctx=self._ctx())
        d = next(d for d in out if d.symbol == "SPY")
        assert d.action == ActionType.NO_TRADE

    def test_high_vol_widens_band_gates_more(self):
        # Same delta=0.03, but high vol → wider band → may HOLD
        p_lo = PartialRebalancePolicy(no_trade_band=_band(0.02),
                                       mode="active")
        p_hi = PartialRebalancePolicy(no_trade_band=_band(0.02),
                                       mode="active")
        # low vol
        out_lo = p_lo.compute_actions(
            target_weights={"SPY": 0.13},
            current_weights={"SPY": 0.10},
            ctx=self._ctx(vol=0.05))
        # high vol (3x anchor → 3x band)
        out_hi = p_hi.compute_actions(
            target_weights={"SPY": 0.13},
            current_weights={"SPY": 0.10},
            ctx=self._ctx(vol=0.60))
        d_lo = next(d for d in out_lo if d.symbol == "SPY")
        d_hi = next(d for d in out_hi if d.symbol == "SPY")
        # Low vol: delta=0.03 > add_band ~0.005 → ADD
        # High vol: delta=0.03 < add_band ~0.04 → HOLD
        assert d_lo.action == ActionType.ADD
        assert d_hi.action == ActionType.HOLD


# ── §6.4 long-only invariant guards ────────────────────────────────
class TestLongOnlyInvariant:
    def _ctx(self):
        return {"date": pd.Timestamp("2025-04-01"),
                "regime": RegimeState.NEUTRAL,
                "realized_vol": 0.15}

    def test_negative_target_weight_refused(self):
        # ActionDecision dataclass guards negative weight; the policy
        # should never produce a negative target
        p = PartialRebalancePolicy(no_trade_band=_band(),
                                    mode="active")
        with pytest.raises(ValueError, match=r"long-only|non-negative"):
            p.compute_actions(
                target_weights={"SPY": -0.1},
                current_weights={"SPY": 0.0},
                ctx=self._ctx())

    def test_exit_to_zero_never_negative(self):
        # EXIT always goes to weight=0, never below
        p = PartialRebalancePolicy(no_trade_band=_band(),
                                    mode="active")
        out = p.compute_actions(
            target_weights={"SPY": 0.0},
            current_weights={"SPY": 0.10},
            ctx=self._ctx())
        d = next(d for d in out if d.symbol == "SPY")
        assert d.target_weight == 0.0
        assert d.action == ActionType.EXIT


# ── ENTER_PARTIAL routing (PRD §6.3 A3 — small target = partial) ────
class TestEnterPartial:
    def _ctx(self):
        return {"date": pd.Timestamp("2025-04-01"),
                "regime": RegimeState.NEUTRAL,
                "realized_vol": 0.15}

    def test_small_target_size_enter_partial(self):
        # When current=0 and target is small (below partial_threshold),
        # route to ENTER_PARTIAL not ENTER_FULL.
        p = PartialRebalancePolicy(no_trade_band=_band(0.01),
                                    mode="active",
                                    partial_full_threshold=0.05)
        # target=0.03 < threshold=0.05 → ENTER_PARTIAL
        out = p.compute_actions(
            target_weights={"SPY": 0.03},
            current_weights={"SPY": 0.0},
            ctx=self._ctx())
        d = next(d for d in out if d.symbol == "SPY")
        assert d.action == ActionType.ENTER_PARTIAL

    def test_large_target_size_enter_full(self):
        p = PartialRebalancePolicy(no_trade_band=_band(0.01),
                                    mode="active",
                                    partial_full_threshold=0.05)
        # target=0.10 > threshold=0.05 → ENTER_FULL
        out = p.compute_actions(
            target_weights={"SPY": 0.10},
            current_weights={"SPY": 0.0},
            ctx=self._ctx())
        d = next(d for d in out if d.symbol == "SPY")
        assert d.action == ActionType.ENTER_FULL


# ── multi-symbol delta routing ─────────────────────────────────────
class TestMultiSymbol:
    def test_three_symbols_three_actions(self):
        p = PartialRebalancePolicy(no_trade_band=_band(0.02),
                                    mode="active")
        ctx = {"date": pd.Timestamp("2025-04-01"),
               "regime": RegimeState.NEUTRAL,
               "realized_vol": 0.15}
        out = p.compute_actions(
            target_weights={"SPY": 0.10, "QQQ": 0.05, "GLD": 0.0},
            current_weights={"SPY": 0.0, "QQQ": 0.10, "GLD": 0.10},
            ctx=ctx)
        actions = {d.symbol: d.action for d in out}
        # SPY: 0→0.10, current=0 → ENTER_FULL
        # QQQ: 0.10→0.05, current=0.10 → TRIM
        # GLD: 0.10→0, target=0 → EXIT
        assert actions["SPY"] == ActionType.ENTER_FULL
        assert actions["QQQ"] == ActionType.TRIM
        assert actions["GLD"] == ActionType.EXIT


# ── schema purity ──────────────────────────────────────────────────
class TestSchemaPurity:
    def test_no_panel_imports(self):
        import ast
        import inspect
        import core.research.decision.partial_rebalance as mod
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
                    f"partial_rebalance imports {name} — pure delta "
                    f"calc, no panel access")
