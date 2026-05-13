"""Masked-duplicate factor cluster registry.

Source: Z1 strict-train cluster_pairs_train_only.csv (2026-05-12).
Pairs with |r| ≥ 0.99 grouped into clusters; one canonical name kept,
others marked masked.

Two consumption modes:
  (1) cycle #09 yaml uses static `explicit_exclusions` (sha256 locked
      2026-05-12, commit 46ec4cd). cluster_register here documents
      WHICH names were banned and WHY; it does NOT mutate the yaml.
  (2) cycle #10+ mining can opt-in to sampler-time auto-dedup via
      mining_config.auto_dedup_masked_factors=true (default False).
      When enabled, sampler checks `is_masked()` and rejects spec if
      ≥2 factors from same cluster appear.

Cluster definition rule:
  - r ≥ |0.99| between train-only IC vectors (3131 train trading days)
  - 8 clusters covering 19 factor names (162 RESEARCH_FACTORS)
  - One canonical per cluster, others masked
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional


@dataclass(frozen=True)
class MaskedDuplicateCluster:
    """One cluster of near-perfectly correlated factors."""
    cluster_id: str
    canonical: str
    masked: FrozenSet[str]
    abs_corr_min: float
    pairwise_signed: Dict[str, float]  # masked → signed r vs canonical
    rationale: str

    @property
    def all_names(self) -> FrozenSet[str]:
        return frozenset({self.canonical}) | self.masked


# ── 8 clusters from Z1 strict-train (2026-05-12) ────────────────────

CLUSTER_VOLUME_ALIAS = MaskedDuplicateCluster(
    cluster_id="volume_20d_alias",
    canonical="volume_surge_20d",
    masked=frozenset({"volume_ratio_20d"}),
    abs_corr_min=1.0,
    pairwise_signed={"volume_ratio_20d": 1.0},
    rationale="DataFrame alias (research-only; factor_generator emits "
              "the same panel under two names). Cycle #09 ban via yaml.",
)

CLUSTER_VOL_ALIAS = MaskedDuplicateCluster(
    cluster_id="vol_21d_alias",
    canonical="vol_21d",
    masked=frozenset({"vol_20d"}),
    abs_corr_min=1.0,
    pairwise_signed={"vol_20d": 1.0},
    rationale="DataFrame alias (vol_20d → vol_21d → low_vol cascade per "
              "PRD 20260423 §D3). Cycle #09 ban via yaml.",
)

CLUSTER_52W_HIGH = MaskedDuplicateCluster(
    cluster_id="distance_from_52w_high",
    canonical="nearness_to_52w_high",
    masked=frozenset({"dist_52w_high", "dist_from_new_high_252"}),
    abs_corr_min=0.9988,
    pairwise_signed={
        "dist_52w_high": 1.0,
        "dist_from_new_high_252": 0.9988,
    },
    rationale="Three computations of 'distance from 252d rolling close max' "
              "with trivial formulation differences. Cycle #09 yaml bans "
              "dist_52w_high (one of the two masked); dist_from_new_high_252 "
              "remains reachable for cycle #09 (R4 audit notes it as cluster-"
              "partial overlap acceptable since g_new_family_anchor dominates).",
)

CLUSTER_REVENUE_GROWTH = MaskedDuplicateCluster(
    cluster_id="revenue_growth_proxy",
    canonical="revenue_growth_yoy",
    masked=frozenset({"beneish_sgi"}),
    abs_corr_min=1.0,
    pairwise_signed={"beneish_sgi": 1.0},
    rationale="beneish_sgi (Beneish Sales Growth Index from family L "
              "distress) = revenue_growth_yoy (family N growth). Same TTM "
              "yoy formula. Cycle #09 ban via yaml.",
)

CLUSTER_RET_5D = MaskedDuplicateCluster(
    cluster_id="5d_return_signed_flip",
    canonical="ret_5d",
    masked=frozenset({"reversal_5d"}),
    abs_corr_min=1.0,
    pairwise_signed={"reversal_5d": -1.0},
    rationale="reversal_5d = -ret_5d. Signed sibling — mining picking "
              "both into one composite is double-counting with sign flip. "
              "Cycle #09 ban via yaml.",
)

CLUSTER_MOM_21D = MaskedDuplicateCluster(
    cluster_id="21d_momentum_signed_flip",
    canonical="mom_21d",
    masked=frozenset({"reversal_21d"}),
    abs_corr_min=1.0,
    pairwise_signed={"reversal_21d": -1.0},
    rationale="reversal_21d = -mom_21d. Signed sibling. Cycle #09 ban via yaml.",
)

CLUSTER_WC_TO_TA = MaskedDuplicateCluster(
    cluster_id="working_capital_to_total_assets",
    canonical="ohlson_wc_to_ta",
    masked=frozenset({"altman_wc_to_assets"}),
    abs_corr_min=1.0,
    pairwise_signed={"altman_wc_to_assets": 1.0},
    rationale="altman_wc_to_assets (family L distress, Altman Z X1) = "
              "ohlson_wc_to_ta (family L Ohlson). Same balance-sheet ratio. "
              "Cycle #09 ban via yaml.",
)

CLUSTER_BENCHMARK_RELATIVE_20D = MaskedDuplicateCluster(
    cluster_id="benchmark_relative_20d_proxy",
    canonical="rs_vs_spy_21d",
    masked=frozenset({"rel_spy_20d", "rel_qqq_20d"}),
    abs_corr_min=0.9925,
    pairwise_signed={
        "rel_spy_20d": 0.9966,
        "rel_qqq_20d": 0.9925,
    },
    rationale="Three benchmark-relative 20d return computations cluster "
              "near-perfectly (SPY and QQQ are themselves 0.95+ correlated "
              "at 20d horizon over train years). NOT banned in cycle #09 "
              "yaml — left for cycle #10+ auto-dedup (R4 boundary notes "
              "that since g_new_family_anchor requires new-family anchor, "
              "these benchmark-relative names being co-sampled is less "
              "binding than for cycle04-08 generation).",
)


ALL_CLUSTERS: List[MaskedDuplicateCluster] = [
    CLUSTER_VOLUME_ALIAS,
    CLUSTER_VOL_ALIAS,
    CLUSTER_52W_HIGH,
    CLUSTER_REVENUE_GROWTH,
    CLUSTER_RET_5D,
    CLUSTER_MOM_21D,
    CLUSTER_WC_TO_TA,
    CLUSTER_BENCHMARK_RELATIVE_20D,
]


# ── Public API ──────────────────────────────────────────────────────


def cluster_of(factor_name: str) -> Optional[MaskedDuplicateCluster]:
    """Return the cluster containing this factor, or None.

    Canonical and masked names both return the cluster.
    """
    for c in ALL_CLUSTERS:
        if factor_name == c.canonical or factor_name in c.masked:
            return c
    return None


def is_masked(factor_name: str) -> bool:
    """Return True if factor is a masked (non-canonical) duplicate."""
    for c in ALL_CLUSTERS:
        if factor_name in c.masked:
            return True
    return False


def canonical_of(factor_name: str) -> str:
    """Return canonical name for the factor's cluster (or itself if unclustered).

    Use for sampler-time auto-dedup: spec is valid iff all canonical
    names are unique.
    """
    c = cluster_of(factor_name)
    if c is None:
        return factor_name
    return c.canonical


def cycle09_ban_list() -> FrozenSet[str]:
    """Return the 7 masked-dup names banned in cycle #09 yaml.

    Useful for cross-checking yaml explicit_exclusions consistency.
    """
    return frozenset({
        "volume_ratio_20d",       # cluster_volume_alias
        "vol_20d",                # cluster_vol_alias
        "dist_52w_high",          # cluster_52w_high (1 of 2 masked)
        "beneish_sgi",            # cluster_revenue_growth
        "reversal_5d",            # cluster_ret_5d
        "reversal_21d",           # cluster_mom_21d
        "altman_wc_to_assets",    # cluster_wc_to_ta
    })


def cluster_count() -> int:
    """Number of masked-dup clusters in registry."""
    return len(ALL_CLUSTERS)


def total_masked_names() -> int:
    """Total number of masked (non-canonical) names across all clusters."""
    return sum(len(c.masked) for c in ALL_CLUSTERS)
