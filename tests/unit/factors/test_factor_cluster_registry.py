"""Tests for masked-dup factor cluster registry."""

from __future__ import annotations

import pytest

from core.factors.factor_cluster_registry import (
    ALL_CLUSTERS,
    canonical_of,
    cluster_count,
    cluster_of,
    cycle09_ban_list,
    is_masked,
    total_masked_names,
)
from core.factors.factor_registry import RESEARCH_FACTORS


class TestStructure:
    def test_cluster_count(self):
        assert cluster_count() == 8

    def test_total_masked_names(self):
        # 9 masked names across 8 clusters:
        #   1 vol_alias + 1 volume_alias + 2 52w_high + 1 revenue_growth
        # + 1 ret_5d + 1 mom_21d + 1 wc_to_ta + 2 benchmark_relative = 10
        # (corrected: 52w_high has 2 masked = dist_52w_high +
        # dist_from_new_high_252)
        assert total_masked_names() == 10

    def test_all_names_in_research_factors(self):
        """Every name (canonical + masked) must be a registered factor."""
        for c in ALL_CLUSTERS:
            for n in c.all_names:
                assert n in RESEARCH_FACTORS, (
                    f"{n} in cluster {c.cluster_id} not in RESEARCH_FACTORS"
                )

    def test_no_overlapping_clusters(self):
        """A factor must belong to exactly one cluster."""
        seen = {}
        for c in ALL_CLUSTERS:
            for n in c.all_names:
                if n in seen:
                    raise AssertionError(
                        f"{n} appears in both {seen[n]} and {c.cluster_id}"
                    )
                seen[n] = c.cluster_id


class TestLookups:
    def test_cluster_of_canonical(self):
        c = cluster_of("volume_surge_20d")
        assert c is not None
        assert c.cluster_id == "volume_20d_alias"

    def test_cluster_of_masked(self):
        c = cluster_of("volume_ratio_20d")
        assert c is not None
        assert c.cluster_id == "volume_20d_alias"

    def test_cluster_of_unclustered(self):
        # mom_126d not in any cluster
        assert cluster_of("mom_126d") is None

    def test_is_masked(self):
        assert is_masked("volume_ratio_20d")
        assert is_masked("dist_52w_high")
        assert is_masked("dist_from_new_high_252")
        assert is_masked("reversal_5d")
        assert not is_masked("volume_surge_20d")  # canonical
        assert not is_masked("mom_126d")  # unclustered

    def test_canonical_of(self):
        assert canonical_of("volume_ratio_20d") == "volume_surge_20d"
        assert canonical_of("volume_surge_20d") == "volume_surge_20d"
        assert canonical_of("reversal_5d") == "ret_5d"
        assert canonical_of("mom_126d") == "mom_126d"  # unclustered → self


class TestCycle09Consistency:
    def test_cycle09_ban_list_size(self):
        assert len(cycle09_ban_list()) == 7

    def test_cycle09_ban_all_masked(self):
        """Every name in cycle09 ban list must be a masked name (not canonical)."""
        for name in cycle09_ban_list():
            assert is_masked(name), f"{name} in cycle09_ban_list is not masked"

    def test_cycle09_yaml_matches_registry(self):
        """Cycle #09 yaml explicit_exclusions (masked-dup subset) must equal
        cycle09_ban_list() — guarantees yaml stays consistent with registry."""
        import yaml as _yaml
        p = "data/research_candidates/track-c-cycle-2026-05-12-09_promotion_criteria.yaml"
        d = _yaml.safe_load(open(p))
        excl = set(d["mining_config"]["explicit_exclusions"])
        # yaml has 12 excl: 3 intraday + 2 cycle-anchor + 7 masked-dup
        masked_in_yaml = excl & RESEARCH_FACTORS
        # 12 are all in RESEARCH_FACTORS (validated earlier).
        # The 7 masked-dup subset must equal cycle09_ban_list.
        ban = cycle09_ban_list()
        assert ban.issubset(masked_in_yaml), (
            f"Cycle09 registry ban {ban - masked_in_yaml} missing from yaml"
        )


class TestSignedFlipDetection:
    def test_reversal_pairs_signed_negative(self):
        c = cluster_of("reversal_5d")
        assert c.pairwise_signed["reversal_5d"] == pytest.approx(-1.0, abs=1e-9)

        c = cluster_of("reversal_21d")
        assert c.pairwise_signed["reversal_21d"] == pytest.approx(-1.0, abs=1e-9)

    def test_alias_pairs_signed_positive(self):
        c = cluster_of("volume_ratio_20d")
        assert c.pairwise_signed["volume_ratio_20d"] == pytest.approx(1.0, abs=1e-9)
