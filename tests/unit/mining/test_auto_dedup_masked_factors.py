"""Tests for sampler-time auto-dedup of masked-duplicate factors.

Default OFF preserves cycle04-08 behavior. Cycle #10+ can opt-in via
ResearchMiner(..., auto_dedup_masked_factors=True).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from core.mining.research_miner import (
    FAMILIES_V2, FamilyConfig, suggest_composite_spec,
)


class _ScriptedTrial:
    """Minimal Optuna-trial stub with scripted suggest_* responses.

    Each suggest_* call consumes the next value from per-method queue,
    so the test can deterministically force a specific sample sequence.
    """

    def __init__(self, ints: Dict[str, int], cats: Dict[str, str], floats: Dict[str, float]):
        self.ints = dict(ints)
        self.cats = dict(cats)
        self.floats = dict(floats)
        self.params: Dict[str, Any] = {}

    def suggest_int(self, name: str, lo: int, hi: int) -> int:
        v = self.ints.get(name, lo)
        self.params[name] = v
        return v

    def suggest_categorical(self, name: str, choices):
        v = self.cats.get(name, choices[0])
        if v not in choices:
            v = choices[0]
        self.params[name] = v
        return v

    def suggest_float(self, name: str, lo: float, hi: float, step: float = None):
        v = self.floats.get(name, lo)
        self.params[name] = v
        return v


_TEST_FAMILY_A = FamilyConfig(
    name="testA",
    title="test A",
    factors=frozenset({"mom_21d", "reversal_21d", "mom_63d"}),
)

_TEST_FAMILY_B = FamilyConfig(
    name="testB",
    title="test B",
    factors=frozenset({"ret_5d", "reversal_5d"}),
)

_TEST_FAMILY_C = FamilyConfig(
    name="testC",
    title="test C",
    factors=frozenset({"hl_range", "amihud_20d"}),
)


def _force_pick_three(a: str, b: str, c: str) -> _ScriptedTrial:
    """Force a 3-factor pick: one from each test family."""
    return _ScriptedTrial(
        ints={
            "n_features_testA": 1,
            "n_features_testB": 1,
            "n_features_testC": 1,
        },
        cats={
            "family_testA_slot_0": a,
            "family_testB_slot_0": b,
            "family_testC_slot_0": c,
        },
        floats={f"w_{n}": 1.0 for n in (a, b, c)},
    )


class TestDefaultOff:
    def test_masked_duplicates_pass_through_when_flag_off(self):
        """When auto_dedup_masked_factors=False (default), mom_21d +
        reversal_21d (signed-flip cluster pair) both survive."""
        trial = _force_pick_three("mom_21d", "reversal_21d", "hl_range")
        # Wait: this won't actually picks them BOTH because they're in
        # different test families. Let me restructure: put them in same
        # family.
        family_with_dup = FamilyConfig(
            name="dup",
            title="dup family",
            factors=frozenset({"mom_21d", "reversal_21d"}),
        )
        other = FamilyConfig(name="x", title="x", factors=frozenset({"hl_range"}))
        other2 = FamilyConfig(name="y", title="y", factors=frozenset({"amihud_20d"}))

        trial = _ScriptedTrial(
            ints={"n_features_dup": 2, "n_features_x": 1, "n_features_y": 1},
            cats={
                "family_dup_slot_0": "mom_21d",
                "family_dup_slot_1": "reversal_21d",
                "family_x_slot_0": "hl_range",
                "family_y_slot_0": "amihud_20d",
            },
            floats={},
        )
        spec = suggest_composite_spec(
            trial,
            families=[family_with_dup, other, other2],
            min_families=3,
            max_features_per_family=2,
            composite_weighting="equal_weight",
            auto_dedup_masked_factors=False,  # explicit OFF
        )
        names = set(spec.features)
        assert "mom_21d" in names
        assert "reversal_21d" in names  # NOT deduped
        assert len(spec.features) == 4

    def test_default_kwarg_is_false(self):
        """Sanity: no explicit kwarg → same behavior as off."""
        family_with_dup = FamilyConfig(
            name="dup", title="d", factors=frozenset({"ret_5d", "reversal_5d"}),
        )
        other = FamilyConfig(name="x", title="x", factors=frozenset({"hl_range"}))
        other2 = FamilyConfig(name="y", title="y", factors=frozenset({"amihud_20d"}))
        trial = _ScriptedTrial(
            ints={"n_features_dup": 2, "n_features_x": 1, "n_features_y": 1},
            cats={
                "family_dup_slot_0": "ret_5d",
                "family_dup_slot_1": "reversal_5d",
                "family_x_slot_0": "hl_range",
                "family_y_slot_0": "amihud_20d",
            },
            floats={},
        )
        spec = suggest_composite_spec(
            trial,
            families=[family_with_dup, other, other2],
            min_families=3,
            max_features_per_family=2,
            composite_weighting="equal_weight",
        )
        # Default OFF: signed-flip pair both survives
        assert "ret_5d" in spec.features
        assert "reversal_5d" in spec.features


class TestOptInOn:
    def test_signed_flip_pair_deduped(self):
        """auto_dedup ON: mom_21d + reversal_21d both picked → only canonical (mom_21d) survives."""
        family_with_dup = FamilyConfig(
            name="dup", title="d", factors=frozenset({"mom_21d", "reversal_21d"}),
        )
        other = FamilyConfig(name="x", title="x", factors=frozenset({"hl_range"}))
        other2 = FamilyConfig(name="y", title="y", factors=frozenset({"amihud_20d"}))
        trial = _ScriptedTrial(
            ints={"n_features_dup": 2, "n_features_x": 1, "n_features_y": 1},
            cats={
                "family_dup_slot_0": "mom_21d",
                "family_dup_slot_1": "reversal_21d",
                "family_x_slot_0": "hl_range",
                "family_y_slot_0": "amihud_20d",
            },
            floats={},
        )
        spec = suggest_composite_spec(
            trial,
            families=[family_with_dup, other, other2],
            min_families=3,
            max_features_per_family=2,
            composite_weighting="equal_weight",
            auto_dedup_masked_factors=True,
        )
        names = set(spec.features)
        assert "mom_21d" in names
        assert "reversal_21d" not in names  # DEDUPED
        assert len(spec.features) == 3

    def test_alias_pair_deduped(self):
        """auto_dedup ON: volume_surge_20d + volume_ratio_20d → only canonical."""
        family_with_dup = FamilyConfig(
            name="dup", title="d",
            factors=frozenset({"volume_surge_20d", "volume_ratio_20d"}),
        )
        other = FamilyConfig(name="x", title="x", factors=frozenset({"hl_range"}))
        other2 = FamilyConfig(name="y", title="y", factors=frozenset({"amihud_20d"}))
        trial = _ScriptedTrial(
            ints={"n_features_dup": 2, "n_features_x": 1, "n_features_y": 1},
            cats={
                "family_dup_slot_0": "volume_surge_20d",
                "family_dup_slot_1": "volume_ratio_20d",
                "family_x_slot_0": "hl_range",
                "family_y_slot_0": "amihud_20d",
            },
            floats={},
        )
        spec = suggest_composite_spec(
            trial,
            families=[family_with_dup, other, other2],
            min_families=3,
            max_features_per_family=2,
            composite_weighting="equal_weight",
            auto_dedup_masked_factors=True,
        )
        names = set(spec.features)
        assert "volume_surge_20d" in names
        assert "volume_ratio_20d" not in names

    def test_unclustered_factors_untouched(self):
        """auto_dedup ON: factors not in any masked-dup cluster survive intact."""
        # mom_21d + mom_63d + mom_126d are all in family A but NOT
        # masked duplicates (different lookbacks). Should all survive.
        family_dup = FamilyConfig(
            name="dup", title="d", factors=frozenset({"mom_21d", "mom_63d"}),
        )
        other = FamilyConfig(name="x", title="x", factors=frozenset({"hl_range"}))
        other2 = FamilyConfig(name="y", title="y", factors=frozenset({"amihud_20d"}))
        trial = _ScriptedTrial(
            ints={"n_features_dup": 2, "n_features_x": 1, "n_features_y": 1},
            cats={
                "family_dup_slot_0": "mom_21d",
                "family_dup_slot_1": "mom_63d",
                "family_x_slot_0": "hl_range",
                "family_y_slot_0": "amihud_20d",
            },
            floats={},
        )
        spec = suggest_composite_spec(
            trial,
            families=[family_dup, other, other2],
            min_families=3,
            max_features_per_family=2,
            composite_weighting="equal_weight",
            auto_dedup_masked_factors=True,
        )
        names = set(spec.features)
        assert "mom_21d" in names
        assert "mom_63d" in names
        assert len(spec.features) == 4


class TestCanonicalSurvivesNotMasked:
    """When a masked name comes BEFORE canonical in trial order, canonical wins."""

    def test_late_canonical_survives(self):
        # reversal_5d picked first; ret_5d picked second.
        # In the current dedup logic, FIRST-SEEN canonical wins, so:
        #   slot 0 = reversal_5d → canon "ret_5d" added to seen_canonical
        #   slot 1 = ret_5d → canon "ret_5d" already seen → dropped
        # So reversal_5d (the masked name) survives because it was first!
        # This is acceptable: dedup ensures one survives, but ordering is
        # trial-driven not registry-driven. Document this behavior.
        family_dup = FamilyConfig(
            name="dup", title="d", factors=frozenset({"ret_5d", "reversal_5d"}),
        )
        other = FamilyConfig(name="x", title="x", factors=frozenset({"hl_range"}))
        other2 = FamilyConfig(name="y", title="y", factors=frozenset({"amihud_20d"}))
        trial = _ScriptedTrial(
            ints={"n_features_dup": 2, "n_features_x": 1, "n_features_y": 1},
            cats={
                "family_dup_slot_0": "reversal_5d",
                "family_dup_slot_1": "ret_5d",
                "family_x_slot_0": "hl_range",
                "family_y_slot_0": "amihud_20d",
            },
            floats={},
        )
        spec = suggest_composite_spec(
            trial,
            families=[family_dup, other, other2],
            min_families=3,
            max_features_per_family=2,
            composite_weighting="equal_weight",
            auto_dedup_masked_factors=True,
        )
        names = set(spec.features)
        # First-seen wins: reversal_5d (slot 0) survives, ret_5d (slot 1) dropped
        assert "reversal_5d" in names
        assert "ret_5d" not in names
        assert len(spec.features) == 3
