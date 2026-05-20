"""PRD-X v2 Phase X5 — MLSidecarPolicy (sign-vote / include-veto) TDD.

AC (PRD §11 X5 + §9.0 post-audit-fix constraint):
  - SignVote enum with 3 discrete values: VETO / NO_VOTE / CONFIRM
  - MLSidecarPolicy wraps a vote function (model_output → SignVote)
  - **§9.0 invariant: output MUST be discrete (categorical/sign),
    NEVER continuous magnitude as size weight** — verified by tests
  - VETO routes ActionDecision to DEFER/VETO action (NOT a negative
    weight; long-only invariant preserved)
  - CONFIRM is a no-op pass-through (sidecar adds no continuous
    magnitude; only adds a discrete gate)
  - NO_VOTE is a no-op pass-through
  - bit-identical default mode='off' — all votes return NO_VOTE
    (cascade_overlay R12 / construction_tier T0 precedent)
  - Schema-purity: no panel/yfinance/bar_store imports

The MLSidecarPolicy is an OVERLAY on rule-based decisions; it
filters/vetoes but does NOT generate magnitudes. The size comes
from rule-based policy (FactorEntryTrigger.strength etc), NOT
from ML scores. Per `feedback_audit_per_round_methodology` and
post-fix REVISION memo, ML continuous magnitude was FORCED across
3 model classes to a universal poison IC; this is the post-fix
discipline.
"""
import inspect

import pandas as pd
import pytest

from core.research.decision import (
    ActionDecision, ActionType, PositionState,
)
from core.research.decision.ml_sidecar import (
    MLSidecarPolicy,
    SignVote,
)
from core.signals.signal_state import SignalStatus


def _mk_decision(action=ActionType.ENTER_FULL, weight=0.10, symbol="SPY"):
    return ActionDecision(
        symbol=symbol, date=pd.Timestamp("2025-04-01"),
        status=SignalStatus.CONFIRMED, action=action,
        position_state=PositionState.FLAT,
        target_weight=weight, reason="test")


# ── SignVote enum ──────────────────────────────────────────────────
class TestSignVoteEnum:
    def test_three_discrete_values(self):
        names = {v.name for v in SignVote}
        assert names == {"VETO", "NO_VOTE", "CONFIRM"}

    def test_no_continuous_magnitude_member(self):
        # §9.0 post-fix invariant: no continuous magnitude
        # representation should exist alongside SignVote
        for v in SignVote:
            # values are discrete tokens, not floats
            assert isinstance(v.value, (str, int))


# ── Construction + mode validation ──────────────────────────────────
class TestConstruction:
    def test_default_mode_off(self):
        p = MLSidecarPolicy(vote_fn=lambda ctx: SignVote.CONFIRM)
        assert p.mode == "off"

    def test_active_mode_accepted(self):
        p = MLSidecarPolicy(vote_fn=lambda ctx: SignVote.VETO,
                            mode="active")
        assert p.mode == "active"

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValueError, match=r"mode"):
            MLSidecarPolicy(vote_fn=lambda ctx: SignVote.CONFIRM,
                            mode="bogus")


# ── mode='off' bit-identical: all votes = NO_VOTE ───────────────────
class TestModeOffBitIdentical:
    def test_off_returns_no_vote_regardless_of_vote_fn(self):
        p = MLSidecarPolicy(
            vote_fn=lambda ctx: SignVote.VETO,  # would VETO
            mode="off")
        # off mode → all votes NO_VOTE
        v = p.vote(ctx={"symbol": "SPY",
                         "date": pd.Timestamp("2025-04-01")})
        assert v == SignVote.NO_VOTE

    def test_off_apply_decision_unchanged(self):
        # apply() should leave the decision exactly as-is
        p = MLSidecarPolicy(
            vote_fn=lambda ctx: SignVote.VETO, mode="off")
        d = _mk_decision()
        out = p.apply(d, ctx={"symbol": "SPY",
                               "date": pd.Timestamp("2025-04-01")})
        assert out.action == d.action
        assert out.target_weight == d.target_weight


# ── active mode: VETO routes to defer/veto ──────────────────────────
class TestActiveVeto:
    def test_veto_routes_to_veto_action(self):
        p = MLSidecarPolicy(
            vote_fn=lambda ctx: SignVote.VETO, mode="active")
        d = _mk_decision(action=ActionType.ENTER_FULL, weight=0.10)
        out = p.apply(d, ctx={"symbol": "SPY",
                               "date": pd.Timestamp("2025-04-01")})
        # VETO → ActionType.VETO; weight = 0 (long-only)
        assert out.action == ActionType.VETO
        assert out.target_weight == 0.0

    def test_veto_does_not_introduce_negative_weight(self):
        # §6.4 long-only — VETO never goes short
        p = MLSidecarPolicy(
            vote_fn=lambda ctx: SignVote.VETO, mode="active")
        d = _mk_decision(action=ActionType.ENTER_FULL, weight=0.10)
        out = p.apply(d, ctx={})
        assert out.target_weight >= 0.0


# ── CONFIRM = no-op pass-through ────────────────────────────────────
class TestActiveConfirm:
    def test_confirm_passes_through_unchanged(self):
        p = MLSidecarPolicy(
            vote_fn=lambda ctx: SignVote.CONFIRM, mode="active")
        d = _mk_decision(action=ActionType.ENTER_FULL, weight=0.07)
        out = p.apply(d, ctx={})
        assert out.action == d.action
        assert out.target_weight == d.target_weight

    def test_confirm_does_not_modify_size(self):
        # §9.0 critical: ML CONFIRM must NOT scale the weight
        # (no continuous magnitude as size). Weight is preserved.
        p = MLSidecarPolicy(
            vote_fn=lambda ctx: SignVote.CONFIRM, mode="active")
        d = _mk_decision(action=ActionType.ADD, weight=0.05)
        out = p.apply(d, ctx={})
        assert out.target_weight == 0.05


# ── NO_VOTE = no-op pass-through ────────────────────────────────────
class TestActiveNoVote:
    def test_no_vote_passes_through(self):
        p = MLSidecarPolicy(
            vote_fn=lambda ctx: SignVote.NO_VOTE, mode="active")
        d = _mk_decision(action=ActionType.ENTER_FULL, weight=0.10)
        out = p.apply(d, ctx={})
        assert out.action == d.action
        assert out.target_weight == d.target_weight


# ── §9.0 invariant: vote_fn must return SignVote, not float ─────────
class TestSign90Invariant:
    def test_vote_fn_returning_float_rejected(self):
        # §9.0 post-fix: ML output MUST be sign-vote, NOT continuous
        # magnitude. If the vote_fn returns a float (model raw score),
        # the policy must reject it.
        p = MLSidecarPolicy(
            vote_fn=lambda ctx: 0.85,  # raw model score (float)
            mode="active")
        with pytest.raises(TypeError, match=r"SignVote"):
            p.vote(ctx={"symbol": "SPY",
                         "date": pd.Timestamp("2025-04-01")})

    def test_vote_fn_returning_int_rejected(self):
        p = MLSidecarPolicy(vote_fn=lambda ctx: 1, mode="active")
        with pytest.raises(TypeError, match=r"SignVote"):
            p.vote(ctx={"symbol": "X",
                         "date": pd.Timestamp("2025-04-01")})

    def test_vote_fn_returning_string_rejected(self):
        p = MLSidecarPolicy(vote_fn=lambda ctx: "veto", mode="active")
        with pytest.raises(TypeError, match=r"SignVote"):
            p.vote(ctx={"symbol": "X",
                         "date": pd.Timestamp("2025-04-01")})


# ── exit action invariant: VETO on EXIT is a no-op ─────────────────
class TestActionTypeInteraction:
    def test_veto_on_hold_keeps_hold(self):
        # If decision is already HOLD, ML VETO doesn't escalate
        p = MLSidecarPolicy(
            vote_fn=lambda ctx: SignVote.VETO, mode="active")
        d = _mk_decision(action=ActionType.HOLD, weight=0.05)
        out = p.apply(d, ctx={})
        # HOLD stays HOLD (ML can't force exit; only blocks new entries)
        assert out.action in (ActionType.HOLD, ActionType.VETO)

    def test_veto_on_exit_passes_through(self):
        # EXIT is risk-driven, ML can't block exits
        p = MLSidecarPolicy(
            vote_fn=lambda ctx: SignVote.VETO, mode="active")
        d = _mk_decision(action=ActionType.EXIT, weight=0.0)
        out = p.apply(d, ctx={})
        assert out.action == ActionType.EXIT


# ── schema purity ──────────────────────────────────────────────────
class TestSchemaPurity:
    def test_no_panel_imports(self):
        import ast
        import core.research.decision.ml_sidecar as mod
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
                    f"ml_sidecar imports {name} — pure overlay, "
                    f"no panel access")
