"""PRD-X v2 — ML voter wiring per §9.0 sign-vote / include-veto.

Provides concrete `vote_fn` factories that wrap scikit-learn-style
classifiers into the SignVote-returning contract enforced by
`MLSidecarPolicy.vote()` at runtime.

**§9.0 INVARIANT**: every voter in this module produces discrete
SignVote outputs (VETO / NO_VOTE / CONFIRM). Continuous magnitude
predictions are NEVER routed as size weights — that's the post-fix
constraint surfaced by 3-model-class magnitude-IC poisoning.

Wiring is architectural — the classifier passed in must be trained
externally (with proper temporal-split discipline per
`feedback_temporal_split_discipline`) and produce class labels
in {-1, 0, 1} or {0, 1}. Training pipelines + persisted models live
in alpha-engineering scope (distinct track from this loop).

Voter kinds:

  no_op_voter
      Always returns NO_VOTE. The bit-identical default; matches
      MLSidecarPolicy(mode='off') behavior.

  weak_factor_filter_voter
      Heuristic — VETO when factor_score is in the noisy lower
      half of entry-eligible band [threshold, midpoint]. R10/R14
      acceptance experiments used this.

  classifier_voter
      Real ML wiring: wraps a sklearn-like classifier with
      `.predict(X) -> array-like of class labels`. Maps:
        -1 → VETO        (model says don't enter)
         0 → NO_VOTE     (model abstains)
        +1 → CONFIRM     (model endorses entry)
      Feature extractor function maps `ctx` to a 2D feature array
      (`[[x1, x2, ...]]`). Empty/missing features → NO_VOTE
      (graceful fallback, NOT a crash).

  binary_classifier_voter
      Binary {0, 1} classifier — 0 → VETO, 1 → NO_VOTE
      (asymmetric: model can BLOCK entries but never CONFIRM via
      this kind; CONFIRM requires the 3-class form above).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import numpy as np

from core.research.decision.ml_sidecar import SignVote

__all__ = [
    "no_op_voter",
    "weak_factor_filter_voter",
    "classifier_voter",
    "binary_classifier_voter",
]


# ── no_op ─────────────────────────────────────────────────────────────
def no_op_voter() -> Callable[[Dict[str, Any]], SignVote]:
    """Bit-identical default: always NO_VOTE pass-through."""
    def voter(ctx: Dict[str, Any]) -> SignVote:
        return SignVote.NO_VOTE
    return voter


# ── heuristic ─────────────────────────────────────────────────────────
def weak_factor_filter_voter(
    entry_threshold: float = 0.7,
) -> Callable[[Dict[str, Any]], SignVote]:
    """VETO when factor_score is in the noisy lower half of the
    entry-eligible band [entry_threshold, midpoint]."""
    midpoint = (entry_threshold + 1.0) / 2.0

    def voter(ctx: Dict[str, Any]) -> SignVote:
        fs = ctx.get("factor_score")
        if fs is None:
            return SignVote.NO_VOTE
        try:
            f = float(fs)
        except (TypeError, ValueError):
            return SignVote.NO_VOTE
        if entry_threshold < f < midpoint:
            return SignVote.VETO
        return SignVote.NO_VOTE
    return voter


# ── ML classifier (3-class: -1/0/+1) ─────────────────────────────────
def classifier_voter(
    classifier: Any,
    feature_extractor: Callable[[Dict[str, Any]], Optional[list]],
) -> Callable[[Dict[str, Any]], SignVote]:
    """Wrap a trained sklearn-style classifier into a SignVote voter.

    Parameters
    ----------
    classifier : object
        Must expose `.predict(X)` returning array-like of class
        labels. Labels MUST be in {-1, 0, 1}. Any other label
        raises ValueError at runtime (defensive — protects against
        misconfigured models or label-encoding bugs).
    feature_extractor : Callable[[ctx], list | None]
        Maps the per-decision ctx dict to a flat 1D feature vector
        (will be wrapped to 2D for `predict`). Return None to abstain
        on this ctx (e.g. missing features) — voter returns
        NO_VOTE without invoking classifier.

    Mapping:
      -1 → VETO,  0 → NO_VOTE,  +1 → CONFIRM

    Exception safety: classifier crash → NO_VOTE (graceful, logged
    via __debug__ assertion path only — in production paths the
    caller should wrap with proper logging). Per
    `feedback_no_blanket_failure_verdict`, NO_VOTE is the correct
    failsafe (don't pretend to predict, don't VETO either).

    §9.0 invariant: this voter NEVER returns a magnitude or
    continuous value. Classifier output is mapped to SignVote
    enum (3-discrete). Tests in test_ml_voters.py enforce this.
    """
    _LABEL_MAP = {-1: SignVote.VETO, 0: SignVote.NO_VOTE,
                  1: SignVote.CONFIRM}

    def voter(ctx: Dict[str, Any]) -> SignVote:
        feats = feature_extractor(ctx)
        if feats is None:
            return SignVote.NO_VOTE
        try:
            X = np.asarray(feats, dtype=float).reshape(1, -1)
            pred = classifier.predict(X)
        except Exception:
            # Graceful: a bad ctx or classifier crash → abstain.
            # This is by-design failsafe — don't enable a position
            # AND don't veto a position when the model is broken.
            return SignVote.NO_VOTE
        label = int(np.asarray(pred).flatten()[0])
        if label not in _LABEL_MAP:
            raise ValueError(
                f"classifier returned label {label} ∉ {{-1, 0, 1}}; "
                f"§9.0 invariant requires 3-class output (VETO / "
                f"NO_VOTE / CONFIRM)")
        return _LABEL_MAP[label]
    return voter


# ── binary classifier (asymmetric VETO-only) ────────────────────────
def binary_classifier_voter(
    classifier: Any,
    feature_extractor: Callable[[Dict[str, Any]], Optional[list]],
) -> Callable[[Dict[str, Any]], SignVote]:
    """Binary classifier {0, 1} → SignVote{VETO, NO_VOTE}.

    0 → VETO (model says block);  1 → NO_VOTE (model abstains).

    Use this when training data only supports binary labels
    (e.g. "this entry was a winner: 1 / loser: 0"). The asymmetry
    is by-design — a binary model can BLOCK entries but can't
    actively CONFIRM (CONFIRM in PRD-X is "model endorses, override
    rule-based default", which needs 3-class signal).
    """
    def voter(ctx: Dict[str, Any]) -> SignVote:
        feats = feature_extractor(ctx)
        if feats is None:
            return SignVote.NO_VOTE
        try:
            X = np.asarray(feats, dtype=float).reshape(1, -1)
            pred = classifier.predict(X)
        except Exception:
            return SignVote.NO_VOTE
        label = int(np.asarray(pred).flatten()[0])
        if label == 0:
            return SignVote.VETO
        if label == 1:
            return SignVote.NO_VOTE
        raise ValueError(
            f"binary_classifier_voter got label {label} ∉ {{0, 1}}; "
            f"§9.0 invariant requires categorical output")
    return voter
