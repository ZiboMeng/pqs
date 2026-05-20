"""Tests for ``core.research.ml.context_features`` (PRD #4 P4.3).

Coverage:
- All bundle names registered in BUNDLE_NAMES
- Every factor in every bundle is in RESEARCH_FACTORS (drift detection)
- Bundles do not overlap (union semantics for `all_context`)
- extract_feature_bundle returns expected subset; raises on missing
- combine_feature_dicts merges + last-wins
- bundle_size returns count
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.factors.factor_registry import RESEARCH_FACTORS
from core.research.ml.context_features import (
    BUNDLE_NAMES,
    BUNDLES,
    BUNDLES_FULL,
    ContextFeatureError,
    bundle_size,
    combine_feature_dicts,
    extract_feature_bundle,
)


def _stub_panel(name: str):
    """One-row panel with the factor name in dict — content not checked."""
    return pd.DataFrame({"A": [0.5]}, index=pd.bdate_range("2020-01-01", periods=1))


# ---------------------------------------------------------------------------
# Bundle registration + drift detection
# ---------------------------------------------------------------------------


class TestBundleRegistration:
    def test_bundle_names_match_dict_keys(self):
        assert set(BUNDLE_NAMES) == set(BUNDLES_FULL.keys())

    def test_all_context_is_union_of_atomic_bundles(self):
        union = set()
        for k, v in BUNDLES.items():
            union |= set(v)
        assert set(BUNDLES_FULL["all_context"]) == union

    def test_every_factor_in_every_bundle_is_in_research_registry(self):
        """Drift detection: if factor_generator renames a factor, this
        test catches the bundle stale-reference."""
        for bundle_name, names in BUNDLES.items():
            for n in names:
                assert n in RESEARCH_FACTORS, (
                    f"bundle {bundle_name!r} factor {n!r} not in "
                    f"RESEARCH_FACTORS — factor_generator drift?")

    def test_atomic_bundles_do_not_overlap(self):
        """all_context is the union — atomic bundles should be disjoint
        so the union has well-defined cardinality."""
        all_atomic = []
        for v in BUNDLES.values():
            all_atomic.extend(v)
        assert len(all_atomic) == len(set(all_atomic)), (
            f"Bundles overlap: duplicates = "
            f"{[n for n in all_atomic if all_atomic.count(n) > 1]}")


# ---------------------------------------------------------------------------
# extract_feature_bundle
# ---------------------------------------------------------------------------


class TestExtractFeatureBundle:
    def test_returns_subset_for_regime_state(self):
        # build a stub factor_panel containing all RESEARCH_FACTORS names
        factor_panel = {n: _stub_panel(n) for n in RESEARCH_FACTORS}
        out = extract_feature_bundle(factor_panel, "regime_state")
        assert set(out.keys()) == set(BUNDLES["regime_state"])

    def test_returns_subset_for_all_context(self):
        factor_panel = {n: _stub_panel(n) for n in RESEARCH_FACTORS}
        out = extract_feature_bundle(factor_panel, "all_context")
        assert set(out.keys()) == set(BUNDLES_FULL["all_context"])

    def test_unknown_bundle_raises(self):
        with pytest.raises(ContextFeatureError, match="unknown bundle_name"):
            extract_feature_bundle({}, "does_not_exist")

    def test_missing_factor_raises_with_list(self):
        # only some of regime_state present
        partial = {"regime_score_combined": _stub_panel("regime_score_combined")}
        with pytest.raises(ContextFeatureError, match="not in factor_panel"):
            extract_feature_bundle(partial, "regime_state")


# ---------------------------------------------------------------------------
# combine_feature_dicts
# ---------------------------------------------------------------------------


class TestCombineFeatureDicts:
    def test_merge_disjoint(self):
        a = {"f1": _stub_panel("f1")}
        b = {"f2": _stub_panel("f2")}
        out = combine_feature_dicts(a, b)
        assert set(out.keys()) == {"f1", "f2"}

    def test_last_wins_on_collision(self):
        a = {"f1": pd.DataFrame({"A": [1.0]})}
        b = {"f1": pd.DataFrame({"A": [99.0]})}
        out = combine_feature_dicts(a, b)
        assert out["f1"]["A"].iloc[0] == 99.0

    def test_empty(self):
        assert combine_feature_dicts() == {}


# ---------------------------------------------------------------------------
# bundle_size
# ---------------------------------------------------------------------------


class TestBundleSize:
    def test_regime_state_size(self):
        assert bundle_size("regime_state") == 3

    def test_all_context_equals_sum_of_atomics(self):
        total = sum(bundle_size(n) for n in BUNDLES)
        assert bundle_size("all_context") == total

    def test_unknown_bundle_raises(self):
        with pytest.raises(ContextFeatureError):
            bundle_size("does_not_exist")
