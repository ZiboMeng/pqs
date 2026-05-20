"""Tests for ``core.research.decision.classifier_feature_extractors``
(PRD #4 P4.5 sub-step A).
"""
from __future__ import annotations

import math

import pytest

from core.research.decision.classifier_feature_extractors import (
    FEATURE_EXTRACTOR_NAMES,
    get_feature_extractor,
    rank_score_and_context_extractor,
    register_feature_extractor,
)


class TestRegistry:
    def test_default_extractor_registered(self):
        assert "rank_score_and_context" in FEATURE_EXTRACTOR_NAMES()

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown feature_extractor"):
            get_feature_extractor("does_not_exist")

    def test_register_duplicate_raises(self):
        with pytest.raises(ValueError, match="already registered"):
            register_feature_extractor(
                "rank_score_and_context", lambda ctx: None)


class TestRankScoreAndContextExtractor:
    def test_full_ctx_returns_feature_vector(self):
        ctx = {
            "stage1_rank": 0.85,
            "context_features": {"b": 0.5, "a": -1.2, "c": 2.0},
        }
        vec = rank_score_and_context_extractor(ctx)
        # sorted by name: a, b, c
        assert vec == [0.85, -1.2, 0.5, 2.0]

    def test_missing_rank_returns_none(self):
        ctx = {"context_features": {"a": 1.0}}
        assert rank_score_and_context_extractor(ctx) is None

    def test_missing_context_returns_none(self):
        ctx = {"stage1_rank": 0.5}
        assert rank_score_and_context_extractor(ctx) is None

    def test_nan_rank_returns_none(self):
        ctx = {"stage1_rank": math.nan, "context_features": {"a": 1.0}}
        assert rank_score_and_context_extractor(ctx) is None

    def test_nan_context_returns_none(self):
        ctx = {"stage1_rank": 0.5, "context_features": {"a": math.nan}}
        assert rank_score_and_context_extractor(ctx) is None

    def test_none_context_value_returns_none(self):
        ctx = {"stage1_rank": 0.5, "context_features": {"a": None}}
        assert rank_score_and_context_extractor(ctx) is None

    def test_empty_context_only_rank_vector(self):
        ctx = {"stage1_rank": 0.7, "context_features": {}}
        assert rank_score_and_context_extractor(ctx) == [0.7]

    def test_sorted_order_deterministic(self):
        ctx1 = {"stage1_rank": 0.5, "context_features": {"z": 1, "a": 2}}
        ctx2 = {"stage1_rank": 0.5, "context_features": {"a": 2, "z": 1}}
        assert (rank_score_and_context_extractor(ctx1)
                == rank_score_and_context_extractor(ctx2))
