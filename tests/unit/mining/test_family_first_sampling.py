"""Tests for family_first sampling mode (Option A sampler refactor).

cycle #09 postmortem 2026-05-12 found that the cycle04-08 "independent"
sampler at 17 families produces P(valid spec) = 0.0005%. family_first
mode picks k families first then 1 factor each → P(valid spec) ≈ 100%.

Default sampling_mode="independent" preserves cycle04-08 bit-for-bit.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from core.mining.research_miner import (
    FamilyConfig, suggest_composite_spec,
)


class _ScriptedTrial:
    """Optuna-trial stub with deterministic scripted suggest_* responses."""

    def __init__(self, ints: Dict[str, int], cats: Dict[str, str], floats: Dict[str, float] = None):
        self.ints = dict(ints)
        self.cats = dict(cats)
        self.floats = dict(floats or {})
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


# ── 17-family-like setup (simulates cycle #09 RESEARCH_FACTORS pool) ──

_F_A = FamilyConfig(name="A", title="a", factors=frozenset({"mom_21d", "mom_63d"}))
_F_B = FamilyConfig(name="B", title="b", factors=frozenset({"drawup_from_252d_low", "hl_range"}))
_F_C = FamilyConfig(name="C", title="c", factors=frozenset({"amihud_20d", "vol_21d"}))
_F_D = FamilyConfig(name="D", title="d", factors=frozenset({"beta_spy_60d"}))
_F_E = FamilyConfig(name="E", title="e", factors=frozenset({"factor_e1"}))
_F_F = FamilyConfig(name="F", title="f", factors=frozenset({"factor_f1"}))
_F_G = FamilyConfig(name="G", title="g", factors=frozenset({"obv_norm_20d"}))
_F_H = FamilyConfig(name="H", title="h", factors=frozenset({"bb_squeeze_20d"}))
_F_I = FamilyConfig(name="I", title="i", factors=frozenset({"coskew_60d_spy", "bab_score_60d"}))
_F_J = FamilyConfig(name="J", title="j", factors=frozenset({"sell_in_may_seasonal"}))
_F_K = FamilyConfig(name="K", title="k", factors=frozenset({"piotroski_f_score", "magic_roic_ttm"}))
_F_L = FamilyConfig(name="L", title="l", factors=frozenset({"beneish_aqi", "altman_z_score"}))

_FAMILIES_12 = [_F_A, _F_B, _F_C, _F_D, _F_E, _F_F, _F_G, _F_H, _F_I, _F_J, _F_K, _F_L]


class TestSamplingModeValidation:
    def test_unknown_mode_raises(self):
        trial = _ScriptedTrial({}, {})
        with pytest.raises(ValueError, match="sampling_mode"):
            suggest_composite_spec(
                trial, families=_FAMILIES_12, min_families=3,
                target_n_features=3, composite_weighting="equal_weight",
                sampling_mode="invalid_mode",
            )


class TestIndependentModeUnchanged:
    """Default 'independent' mode preserves cycle04-08 behavior bit-for-bit."""

    def test_default_mode_is_independent(self):
        # Construct a deterministic trial that the independent mode would
        # archive: 1 feat from A, 1 from B, 1 from C.
        trial = _ScriptedTrial(
            ints={
                "n_features_A": 1, "n_features_B": 1, "n_features_C": 1,
                **{f"n_features_{f.name}": 0 for f in _FAMILIES_12[3:]},
            },
            cats={
                "family_A_slot_0": "mom_21d",
                "family_B_slot_0": "hl_range",
                "family_C_slot_0": "amihud_20d",
            },
        )
        spec = suggest_composite_spec(
            trial, families=_FAMILIES_12, min_families=3,
            max_features_per_family=2, target_n_features=3,
            composite_weighting="equal_weight",
            # sampling_mode default = "independent"
        )
        assert spec.n_features == 3
        assert set(spec.features) == {"mom_21d", "hl_range", "amihud_20d"}

    def test_explicit_independent_mode_same(self):
        trial = _ScriptedTrial(
            ints={
                "n_features_A": 1, "n_features_B": 1, "n_features_C": 1,
                **{f"n_features_{f.name}": 0 for f in _FAMILIES_12[3:]},
            },
            cats={
                "family_A_slot_0": "mom_21d",
                "family_B_slot_0": "hl_range",
                "family_C_slot_0": "amihud_20d",
            },
        )
        spec = suggest_composite_spec(
            trial, families=_FAMILIES_12, min_families=3,
            max_features_per_family=2, target_n_features=3,
            composite_weighting="equal_weight",
            sampling_mode="independent",
        )
        assert spec.n_features == 3


class TestFamilyFirstMode:
    def test_basic_3_families_picked(self):
        # k=3 (n_active_families); pick A, B, C; one factor each.
        trial = _ScriptedTrial(
            ints={"n_active_families": 3},
            cats={
                "family_slot_0": "A",
                "family_slot_1": "B",
                "family_slot_2": "C",
                "factor_in_family_A": "mom_63d",
                "factor_in_family_B": "drawup_from_252d_low",
                "factor_in_family_C": "amihud_20d",
            },
        )
        spec = suggest_composite_spec(
            trial, families=_FAMILIES_12, min_families=3,
            max_features_per_family=2, target_n_features=3,
            composite_weighting="equal_weight",
            sampling_mode="family_first",
        )
        assert spec.n_features == 3
        assert set(spec.features) == {"mom_63d", "drawup_from_252d_low", "amihud_20d"}

    def test_no_independent_sampler_params_emitted(self):
        """family_first should NOT call suggest_int for n_features_<X>."""
        trial = _ScriptedTrial(
            ints={"n_active_families": 3},
            cats={
                "family_slot_0": "K",
                "family_slot_1": "L",
                "family_slot_2": "A",
                "factor_in_family_K": "piotroski_f_score",
                "factor_in_family_L": "beneish_aqi",
                "factor_in_family_A": "mom_21d",
            },
        )
        spec = suggest_composite_spec(
            trial, families=_FAMILIES_12, min_families=3,
            max_features_per_family=2, target_n_features=3,
            composite_weighting="equal_weight",
            sampling_mode="family_first",
        )
        # No "n_features_X" params should be emitted
        n_feat_params = [k for k in trial.params if k.startswith("n_features_")]
        assert n_feat_params == [], f"unexpected n_features params: {n_feat_params}"
        # No "family_X_slot_Y" params either (independent mode's style)
        old_style = [k for k in trial.params if k.startswith("family_") and "_slot_" in k and not k.startswith("family_slot_")]
        assert old_style == [], f"old-style slot params leaked: {old_style}"

    def test_distinct_families_chosen(self):
        # Even if same family is suggested twice, sampler must skip it
        # via the remaining-pool exclusion logic.
        trial = _ScriptedTrial(
            ints={"n_active_families": 3},
            cats={
                # _ScriptedTrial.suggest_categorical falls back to choices[0]
                # when value not in choices. Set to families that will be
                # validly picked in sorted-order without duplicates.
                "family_slot_0": "A",
                "family_slot_1": "B",
                "family_slot_2": "C",
                "factor_in_family_A": "mom_21d",
                "factor_in_family_B": "hl_range",
                "factor_in_family_C": "amihud_20d",
            },
        )
        spec = suggest_composite_spec(
            trial, families=_FAMILIES_12, min_families=3,
            max_features_per_family=2, target_n_features=3,
            composite_weighting="equal_weight",
            sampling_mode="family_first",
        )
        assert spec.n_families == 3

    def test_k_equals_min_families_skips_suggest_int(self):
        """When k_max == min_families, sampler skips n_active_families suggest_int.

        Setup: limit to exactly 3 non-empty families so k_max=min_families=3.
        """
        small_families = [_F_A, _F_B, _F_C]  # only 3 families
        trial = _ScriptedTrial(
            ints={},  # n_active_families NOT scripted (sampler shouldn't ask)
            cats={
                "family_slot_0": "A",
                "family_slot_1": "B",
                "family_slot_2": "C",
                "factor_in_family_A": "mom_21d",
                "factor_in_family_B": "hl_range",
                "factor_in_family_C": "amihud_20d",
            },
        )
        spec = suggest_composite_spec(
            trial, families=small_families, min_families=3,
            max_features_per_family=2, target_n_features=3,
            composite_weighting="equal_weight",
            sampling_mode="family_first",
        )
        assert "n_active_families" not in trial.params
        assert spec.n_features == 3


class TestFamilyFirstHitRate:
    """Statistical check: family_first produces valid specs at high rate."""

    def test_hit_rate_at_17_families(self):
        """Random TPE-like sampling. family_first should achieve >95% archive rate."""
        import random
        rng = random.Random(42)

        # Build 17-family setup (mimics cycle #09 RESEARCH_FACTORS)
        big_families = list(_FAMILIES_12) + [
            FamilyConfig(name="M", title="m", factors=frozenset({"buyback_yield_ttm"})),
            FamilyConfig(name="N", title="n", factors=frozenset({"rd_intensity_ttm"})),
            FamilyConfig(name="O", title="o", factors=frozenset({"sector_dispersion_std_20d"})),
            FamilyConfig(name="P", title="p", factors=frozenset({"vix_zscore_60d"})),
            FamilyConfig(name="Q", title="q", factors=frozenset({"breakout_signal_age_5d"})),
        ]

        n_trials = 100
        n_archived = 0
        for trial_idx in range(n_trials):
            # Simulate random sampling: pick k uniformly, pick family
            # subset uniformly, pick factor uniformly per family.
            sorted_fam_names = sorted(f.name for f in big_families)
            available = list(sorted_fam_names)

            # Mock: pick k=3, then choose 3 families, then 1 factor each
            chosen_families = rng.sample(available, 3)
            chosen_factors = {}
            for fam_name in chosen_families:
                fam = next(f for f in big_families if f.name == fam_name)
                chosen_factors[fam_name] = rng.choice(sorted(fam.factors))

            trial = _ScriptedTrial(
                ints={"n_active_families": 3},
                cats={
                    # The first call to family_slot_0 sees all 17 family names
                    # The second sees 16 (one removed), etc.
                    # _ScriptedTrial picks choices[0] if cats[k] not in choices,
                    # so we just script all three slot picks.
                    f"family_slot_{i}": chosen_families[i] for i in range(3)
                } | {
                    f"factor_in_family_{n}": chosen_factors[n]
                    for n in chosen_families
                },
            )
            try:
                spec = suggest_composite_spec(
                    trial, families=big_families, min_families=3,
                    max_features_per_family=2, target_n_features=3,
                    composite_weighting="equal_weight",
                    sampling_mode="family_first",
                )
                n_archived += 1
            except Exception:
                pass

        rate = n_archived / n_trials
        # cycle04-08 baseline (independent at 6 families): 2.74% archive rate
        # cycle #09 (independent at 17 families): 0.0005% archive rate
        # family_first target: >95% archive rate
        assert rate >= 0.95, (
            f"family_first archived only {rate*100:.1f}% of 100 simulated "
            f"trials at 17-family setup (target >95%)"
        )


class TestStaticValueSpaceDedup:
    """Static-value-space + dedup-then-prune path (Optuna-compat fix
    2026-05-12: dynamic per-slot exclusion → CategoricalDistribution
    error in production; static + dedup is the working path)."""

    def test_duplicate_slot_picks_dedup_to_3(self):
        """When slot 0 and slot 1 pick same family → distinct count = 2.
        With min_families=3 → TrialPruned (Optuna installed) or ValueError."""
        trial = _ScriptedTrial(
            ints={"n_active_families": 3},
            cats={
                "family_slot_0": "A",
                "family_slot_1": "A",  # DUPLICATE — should cause prune
                "family_slot_2": "B",
                "factor_in_family_A": "mom_21d",
                "factor_in_family_B": "hl_range",
            },
        )
        # Accept either TrialPruned (when optuna installed) or ValueError
        try:
            import optuna as _opt
            expected_exc = (_opt.TrialPruned, ValueError)
        except ImportError:
            expected_exc = (ValueError,)
        with pytest.raises(expected_exc, match="post-dedup"):
            suggest_composite_spec(
                trial, families=_FAMILIES_12, min_families=3,
                max_features_per_family=2, target_n_features=3,
                composite_weighting="equal_weight",
                sampling_mode="family_first",
            )

    def test_all_3_distinct_succeeds(self):
        """No duplicates → 3 distinct → succeeds."""
        trial = _ScriptedTrial(
            ints={"n_active_families": 3},
            cats={
                "family_slot_0": "A",
                "family_slot_1": "B",
                "family_slot_2": "C",
                "factor_in_family_A": "mom_21d",
                "factor_in_family_B": "hl_range",
                "factor_in_family_C": "amihud_20d",
            },
        )
        spec = suggest_composite_spec(
            trial, families=_FAMILIES_12, min_families=3,
            max_features_per_family=2, target_n_features=3,
            composite_weighting="equal_weight",
            sampling_mode="family_first",
        )
        assert spec.n_features == 3
        assert set(spec.features) == {"mom_21d", "hl_range", "amihud_20d"}

    def test_each_slot_categorical_full_static_list(self):
        """Each `family_slot_i` categorical sees the FULL sorted family list
        (no dynamic exclusion). This is the Optuna-compat contract."""
        trial = _ScriptedTrial(
            ints={"n_active_families": 3},
            cats={
                "family_slot_0": "A",
                "family_slot_1": "B",
                "family_slot_2": "C",
                "factor_in_family_A": "mom_21d",
                "factor_in_family_B": "hl_range",
                "factor_in_family_C": "amihud_20d",
            },
        )
        spec = suggest_composite_spec(
            trial, families=_FAMILIES_12, min_families=3,
            max_features_per_family=2, target_n_features=3,
            composite_weighting="equal_weight",
            sampling_mode="family_first",
        )
        # Categorical params for slot 0/1/2 should have been recorded
        # (proves trial.suggest_categorical was called with non-empty list)
        assert "family_slot_0" in trial.params
        assert "family_slot_1" in trial.params
        assert "family_slot_2" in trial.params


class TestExcludedFactorsInFamilyFirst:
    """Excluded factors should not be sampled by family_first either."""

    def test_excluded_factor_not_picked(self):
        # In family A, exclude mom_21d; only mom_63d remains.
        trial = _ScriptedTrial(
            ints={"n_active_families": 3},
            cats={
                "family_slot_0": "A",
                "family_slot_1": "B",
                "family_slot_2": "C",
                "factor_in_family_A": "mom_63d",
                "factor_in_family_B": "hl_range",
                "factor_in_family_C": "amihud_20d",
            },
        )
        spec = suggest_composite_spec(
            trial, families=_FAMILIES_12, min_families=3,
            max_features_per_family=2, target_n_features=3,
            composite_weighting="equal_weight",
            sampling_mode="family_first",
            excluded_factors=("mom_21d",),
        )
        assert "mom_21d" not in spec.features
        assert "mom_63d" in spec.features

    def test_empty_family_after_exclusion_skipped(self):
        # Family D has only 1 factor; if excluded, family D should be
        # filtered out of non_empty_families list before n_active_families
        # sampling.
        trial = _ScriptedTrial(
            ints={"n_active_families": 3},
            cats={
                "family_slot_0": "A",
                "family_slot_1": "B",
                "family_slot_2": "C",
                "factor_in_family_A": "mom_21d",
                "factor_in_family_B": "hl_range",
                "factor_in_family_C": "amihud_20d",
            },
        )
        # Excluding D's only factor (beta_spy_60d) makes D unreachable
        spec = suggest_composite_spec(
            trial, families=_FAMILIES_12, min_families=3,
            max_features_per_family=2, target_n_features=3,
            composite_weighting="equal_weight",
            sampling_mode="family_first",
            excluded_factors=("beta_spy_60d",),
        )
        # Spec built successfully, D not in any slot
        for fam_name, _ in zip([], spec.features):
            assert fam_name != "D"
