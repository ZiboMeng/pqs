"""PRD #4 P4.5 — feature extractors for trained classifier_voter.

Mapping `ctx → feature vector` so a saved ``binary_classifier_voter``
artifact can be wired via yaml. Each extractor is named; the name goes
into ``production_strategy.yaml::decision_stack.ml_sidecar.voter_params.
feature_extractor``.

§9.0: extractors only PASS DATA THROUGH. No magnitude scaling or
ML-side decisions made here — that's the classifier's job (which
itself must return discrete labels per §9.0).

Returning ``None`` from an extractor means "abstain on this ctx" —
the voter then returns NO_VOTE without invoking the classifier.

PRD: docs/prd/20260520-prd_rank_first_ml_pipeline.md §P4.5
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

__all__ = [
    "FeatureExtractor",
    "register_feature_extractor",
    "get_feature_extractor",
    "FEATURE_EXTRACTOR_NAMES",
    "rank_score_and_context_extractor",
]


FeatureExtractor = Callable[[Dict[str, Any]], Optional[List[float]]]

_REGISTRY: Dict[str, FeatureExtractor] = {}


def register_feature_extractor(
    name: str, fn: FeatureExtractor,
) -> FeatureExtractor:
    """Register a feature extractor under a name (usable from yaml)."""
    if name in _REGISTRY:
        raise ValueError(
            f"feature_extractor {name!r} already registered; choose a "
            f"distinct name or unregister first")
    _REGISTRY[name] = fn
    return fn


def get_feature_extractor(name: str) -> FeatureExtractor:
    """Resolve a registered extractor by name; raises if unknown."""
    if name not in _REGISTRY:
        raise ValueError(
            f"unknown feature_extractor={name!r}; valid: "
            f"{sorted(_REGISTRY.keys())}")
    return _REGISTRY[name]


def FEATURE_EXTRACTOR_NAMES() -> List[str]:
    """Snapshot of registered extractor names."""
    return sorted(_REGISTRY.keys())


# ── Default extractor: rank_score_and_context ────────────────────────
def rank_score_and_context_extractor(
    ctx: Dict[str, Any],
) -> Optional[List[float]]:
    """Match the feature vector built by
    ``dev/scripts/ml/train_sign_classifier.py::_build_xy_for_stage2``:

        [stage1_rank, *sorted(context_features)]

    ctx must contain:
      - 'stage1_rank' (float): cross-sectional rank ∈ [0, 1]
      - 'context_features' (dict[str, float]): standardized context
        features (per-bar cross-sectional z-scored upstream)

    Returns None (abstain) if either key missing or any value is NaN /
    None — voter then NO_VOTE per §9.0 failsafe.
    """
    rank = ctx.get("stage1_rank")
    ctx_feats = ctx.get("context_features")
    if rank is None or ctx_feats is None:
        return None
    try:
        rank_f = float(rank)
    except (TypeError, ValueError):
        return None
    if rank_f != rank_f:  # NaN check (NaN != NaN)
        return None
    vec: List[float] = [rank_f]
    for name in sorted(ctx_feats.keys()):
        v = ctx_feats[name]
        if v is None:
            return None
        try:
            v_f = float(v)
        except (TypeError, ValueError):
            return None
        if v_f != v_f:  # NaN
            return None
        vec.append(v_f)
    return vec


# Register defaults at module load
register_feature_extractor(
    "rank_score_and_context", rank_score_and_context_extractor)
