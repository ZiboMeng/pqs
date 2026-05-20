"""PRD-X v2 — ML voter wiring tests.

§9.0 invariant: every voter MUST produce SignVote outputs (3-discrete);
TypeError protection in MLSidecarPolicy.vote() is the runtime gate but
the voter implementations here demonstrate the wiring works for real
sklearn-style classifiers without violating discrete-output discipline.
"""
import numpy as np
import pandas as pd
import pytest

from core.research.decision.ml_sidecar import SignVote
from core.research.decision.ml_voters import (
    binary_classifier_voter,
    classifier_voter,
    no_op_voter,
    weak_factor_filter_voter,
)


# ── no_op_voter ──────────────────────────────────────────────────────
class TestNoOpVoter:
    def test_always_no_vote(self):
        v = no_op_voter()
        for ctx in [{}, {"factor_score": 0.5}, {"symbol": "SPY"}]:
            assert v(ctx) == SignVote.NO_VOTE


# ── weak_factor_filter_voter ─────────────────────────────────────────
class TestWeakFactorFilterVoter:
    def test_factor_in_lower_band_veto(self):
        v = weak_factor_filter_voter(entry_threshold=0.7)
        # midpoint = 0.85; 0.75 ∈ (0.7, 0.85) → VETO
        assert v({"factor_score": 0.75}) == SignVote.VETO

    def test_factor_above_midpoint_no_vote(self):
        v = weak_factor_filter_voter(entry_threshold=0.7)
        # 0.95 > 0.85 → NO_VOTE
        assert v({"factor_score": 0.95}) == SignVote.NO_VOTE

    def test_factor_at_threshold_no_vote(self):
        v = weak_factor_filter_voter(entry_threshold=0.7)
        assert v({"factor_score": 0.7}) == SignVote.NO_VOTE

    def test_missing_factor_no_vote(self):
        v = weak_factor_filter_voter()
        assert v({}) == SignVote.NO_VOTE

    def test_invalid_factor_no_vote(self):
        v = weak_factor_filter_voter()
        assert v({"factor_score": "bogus"}) == SignVote.NO_VOTE


# ── classifier_voter (3-class) ────────────────────────────────────────
class _MockTriClassifier:
    """Returns whatever single label was set at construction."""
    def __init__(self, label):
        self._label = label

    def predict(self, X):
        return np.array([self._label] * len(X))


class TestClassifierVoter:
    def _fx(self, ctx):
        return [ctx.get("factor_score", 0.5), ctx.get("vol", 0.15)]

    def test_label_minus_1_maps_to_veto(self):
        clf = _MockTriClassifier(-1)
        v = classifier_voter(clf, self._fx)
        assert v({"factor_score": 0.7}) == SignVote.VETO

    def test_label_0_maps_to_no_vote(self):
        clf = _MockTriClassifier(0)
        v = classifier_voter(clf, self._fx)
        assert v({"factor_score": 0.7}) == SignVote.NO_VOTE

    def test_label_plus_1_maps_to_confirm(self):
        clf = _MockTriClassifier(1)
        v = classifier_voter(clf, self._fx)
        assert v({"factor_score": 0.7}) == SignVote.CONFIRM

    def test_invalid_label_raises(self):
        # §9.0 invariant: classifier MUST output {-1, 0, 1}
        clf = _MockTriClassifier(2)
        v = classifier_voter(clf, self._fx)
        with pytest.raises(ValueError, match=r"§9.0|class"):
            v({"factor_score": 0.7})

    def test_classifier_crash_returns_no_vote_failsafe(self):
        class _BrokenClf:
            def predict(self, X):
                raise RuntimeError("model is broken")
        v = classifier_voter(_BrokenClf(), self._fx)
        # Graceful fallback to NO_VOTE per feedback_no_blanket_failure_verdict
        assert v({"factor_score": 0.7}) == SignVote.NO_VOTE

    def test_none_features_returns_no_vote(self):
        # Feature extractor returns None → abstain
        clf = _MockTriClassifier(1)  # would return CONFIRM if asked
        v = classifier_voter(clf, lambda ctx: None)
        assert v({"factor_score": 0.7}) == SignVote.NO_VOTE

    def test_output_is_discrete_signvote_invariant(self):
        # §9.0 enforcement: output is SignVote enum, NEVER float/int
        for label in (-1, 0, 1):
            clf = _MockTriClassifier(label)
            v = classifier_voter(clf, self._fx)
            out = v({"factor_score": 0.7})
            assert isinstance(out, SignVote), (
                f"voter returned {type(out).__name__}={out}; "
                f"must be SignVote per §9.0")


# ── binary_classifier_voter (asymmetric) ──────────────────────────────
class _MockBinaryClf:
    def __init__(self, label):
        self._label = label
    def predict(self, X):
        return np.array([self._label])


class TestBinaryClassifierVoter:
    def _fx(self, ctx):
        return [ctx.get("factor_score", 0.5)]

    def test_label_0_maps_to_veto(self):
        v = binary_classifier_voter(_MockBinaryClf(0), self._fx)
        assert v({"factor_score": 0.7}) == SignVote.VETO

    def test_label_1_maps_to_no_vote(self):
        v = binary_classifier_voter(_MockBinaryClf(1), self._fx)
        assert v({"factor_score": 0.7}) == SignVote.NO_VOTE

    def test_invalid_label_raises(self):
        v = binary_classifier_voter(_MockBinaryClf(2), self._fx)
        with pytest.raises(ValueError, match=r"§9.0|categorical"):
            v({"factor_score": 0.7})

    def test_crash_returns_no_vote(self):
        class _Broken:
            def predict(self, X):
                raise IndexError("broken")
        v = binary_classifier_voter(_Broken(), self._fx)
        assert v({"factor_score": 0.7}) == SignVote.NO_VOTE


# ── Integration with MLSidecarPolicy ─────────────────────────────────
class TestVoterMLSidecarIntegration:
    def test_classifier_voter_integrates_with_sidecar(self):
        # End-to-end: real voter through MLSidecarPolicy
        from core.research.decision import (
            ActionDecision, ActionType, PositionState,
        )
        from core.research.decision.ml_sidecar import MLSidecarPolicy
        from core.signals.signal_state import SignalStatus

        clf = _MockTriClassifier(-1)  # always VETO
        voter = classifier_voter(clf, lambda ctx: [ctx.get("fs", 0.5)])
        sidecar = MLSidecarPolicy(vote_fn=voter, mode="active")
        d = ActionDecision(
            symbol="SPY", date=pd.Timestamp("2025-04-01"),
            status=SignalStatus.CONFIRMED,
            action=ActionType.ENTER_FULL,
            position_state=PositionState.FLAT,
            target_weight=0.10, reason="test")
        out = sidecar.apply(d, {"fs": 0.7})
        # VETO routes ENTER_FULL → ActionType.VETO + weight=0
        assert out.action == ActionType.VETO
        assert out.target_weight == 0.0

    def test_classifier_voter_via_sidecar_runtime_signvote_invariant(self):
        # MLSidecarPolicy.vote enforces SignVote return at runtime.
        # Our voter respects this — sidecar gets SignVote enum,
        # never raises TypeError.
        from core.research.decision.ml_sidecar import MLSidecarPolicy
        clf = _MockTriClassifier(0)
        voter = classifier_voter(clf, lambda ctx: [0.5])
        sidecar = MLSidecarPolicy(vote_fn=voter, mode="active")
        # Should not raise — voter returns SignVote.NO_VOTE
        v = sidecar.vote({"x": 1})
        assert v == SignVote.NO_VOTE
