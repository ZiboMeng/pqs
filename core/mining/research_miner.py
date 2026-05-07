"""Research Composite Miner v1 (PRD 20260424 §8). Maintainer note: R09
adds FamilyConfig + ResearchCompositeSpec + sampler; R10 adds composite
evaluator; R11 will add Optuna objective + mining entry.

Research-only composite miner. Distinct from production-linked
`MultiFactorSpace` in `core/mining/strategy_space.py` — this miner:

- Samples from research_factor subset (not PRODUCTION_FACTORS)
- Family-aware sampling (3-6 families per composite)
- Mask-aware panel consumption (integrates research_mask)
- Benchmark-relative objective (per PRD §8.6 formula)
- Non-promoting output (research candidates only, no direct promote)

Scope discipline (§13.4): this module CANNOT modify PRODUCTION_FACTORS,
cannot auto-promote, cannot mix with production MiningArchive. Its own
archive db will live at `data/mining/rcm_archive.db` (distinct schema).

R09 (this round) ships:
  - Family definitions covering the 12 PRD features + existing stable
    research factors
  - ResearchCompositeSpec dataclass: feature list + weights + family
    composition metadata
  - suggest_composite_spec() sampler scaffold usable with Optuna trial

Later rounds ship: composite evaluator (R10), objective + Optuna
integration (R11), archive DB (R12), first run (R13), analysis (R14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


# ── Family definitions ───────────────────────────────────────────────────────
#
# 4 families × representative factors. PRD 20260424 §9 mandates "new families
# should prioritize different economic dimensions, not similar-lookback
# variants of an existing family." v1 starts with the 12 PRD features plus
# a small set of existing stable research factors.


@dataclass(frozen=True)
class FamilyConfig:
    """Config for one factor family.

    `name`    : short label (A/B/C/D — stable identifier)
    `title`   : human-readable name for reports / logs
    `factors` : frozenset of factor names owned by this family
    """
    name: str
    title: str
    factors: FrozenSet[str]

    def __post_init__(self) -> None:
        if not self.factors:
            raise ValueError(f"Family {self.name!r} has empty factor set")


FAMILY_A = FamilyConfig(
    name="A",
    title="benchmark-relative / residual / risk-exposure",
    factors=frozenset({
        # PRD 20260424 Family A (R03)
        "rel_spy_20d", "rel_qqq_20d", "beta_spy_60d", "residual_mom_spy_20d",
        # Existing stable research factors that fit family A semantically
        "rs_vs_spy_21d", "rs_vs_spy_63d", "rs_vs_spy_126d",
        "rs_acceleration", "rel_spy_5d",
    }),
)

FAMILY_B = FamilyConfig(
    name="B",
    title="position / breakout / path-shape",
    factors=frozenset({
        # PRD 20260424 Family B (R04)
        "range_pos_252d", "days_since_52w_high",
        "breakout_20d_strength", "dist_from_new_high_252",
        # Existing stable research factors that fit family B
        "dist_52w_high", "drawup_from_252d_low", "max_dd_126d",
        "drawdown_current",
    }),
)

FAMILY_C = FamilyConfig(
    name="C",
    title="liquidity / cost-proxy / risk-state",
    factors=frozenset({
        # PRD 20260424 Family C (R05)
        "amihud_20d", "downside_vol_20d", "vol_ratio_5_20",
        # Existing stable research factors that fit family C
        "vol_21d", "vol_63d", "volume_surge_20d", "vol_regime",
    }),
)

FAMILY_D = FamilyConfig(
    name="D",
    title="trend-quality",
    factors=frozenset({
        # PRD 20260424 Family D (R05)
        "trend_tstat_20d",
        # Existing stable research factors that fit family D
        "mom_21d", "mom_63d", "mom_126d", "mom_252d",
        "mean_rev_sma20", "mean_rev_sma50",
        "rolling_sharpe_126d", "risk_adj_mom_63d",
    }),
)


FAMILIES_V1: List[FamilyConfig] = [FAMILY_A, FAMILY_B, FAMILY_C, FAMILY_D]


# ── FAMILIES_V2 (A++ patch 2026-04-30) ──────────────────────────────────────
#
# FAMILIES_V1 only reaches 33 of the 64 names registered in
# `core.factors.factor_registry.RESEARCH_FACTORS`. Track C cycle 2026-04-30
# #01's pre-registered criteria yaml asserts
# `factor_registry_pool: RESEARCH_FACTORS` — a contract requiring the
# sampler to be able to reach all 64. FAMILIES_V1 violates that contract
# (the cycle's mining run was therefore search-space-restricted: Cand-2's
# anchors `ret_5d` and `hl_range` were unreachable, among others).
#
# A++ extends FAMILIES_V1 with two new family containers (E + F) and adds
# the missing 31 factors to existing or new families so that
# union(FAMILIES_V2) == RESEARCH_FACTORS exactly. NO new factor is added
# to RESEARCH_FACTORS — only the family→factor mapping is broadened.
#
# Categorization decisions (2026-04-30, family ownership):
#   - Family A (benchmark-relative / residual / risk-exposure): adds
#     `weak_market_relative_strength_63d` (RS conditional on weak market),
#     `spy_trend_200d` (SPY long trend regime), `spy_trend_gated_mom_63d`
#     (gated momentum keyed on SPY trend).
#   - Family B (position / breakout / path-shape): adds `mom_12_1`
#     (12m-minus-1m momentum, classic position factor — long-horizon
#     trend MINUS short-horizon reversal makes it path-shape).
#   - Family C (liquidity / cost-proxy / risk-state): adds
#     `dollar_vol_20d`, `volume_ratio_20d`, `vol_20d`, `market_vol_ratio`,
#     `market_drawdown`, `cross_section_dispersion_21d`, `advance_ratio_10d`.
#     Market-internals breadth (advance_ratio) is assigned to C as a
#     risk-state proxy rather than to E (microstructure) because it is
#     a daily cross-asset breadth signal, not an intraday microstructure
#     feature.
#   - Family D (trend-quality): adds `return_per_risk_21d`,
#     `xsection_rank_21d`, `xsection_rank_63d`, `rank_momentum_change`.
#   - Family E (NEW: intraday/overnight/microstructure): the
#     `intraday_*`, `overnight_*`, `hl_range`, `realized_vol_60m_21d`,
#     `price_volume_div` cluster — features whose source signal is
#     within-day or overnight microstructure rather than daily-bar level.
#   - Family F (NEW: short-horizon reversal): the `ret_{1,2,5}d` and
#     `reversal_{5,10,21}d` cluster — features whose alpha thesis is
#     mean-reversion at < 1 month horizon, distinct from Family D's
#     trend-quality (which favors continuation at 21d-252d).
#
# The mapping is a mining-search-space concern only. It does NOT modify
# factor implementations and does NOT auto-promote anything to production.

FAMILY_A_V2 = FamilyConfig(
    name="A",
    title=FAMILY_A.title,
    factors=frozenset(FAMILY_A.factors | {
        "weak_market_relative_strength_63d",
        "spy_trend_200d",
        "spy_trend_gated_mom_63d",
    }),
)

FAMILY_B_V2 = FamilyConfig(
    name="B",
    title=FAMILY_B.title,
    factors=frozenset(FAMILY_B.factors | {
        "mom_12_1",
        # S/R Step 2 (commit b51d3f1, 2026-05-05): swing-extrema +
        # range-compression daily factors. Added to RESEARCH_FACTORS
        # but originally not added to FAMILIES_V2 (caught by
        # test_aplusplus_families_v2_union_equals_research_factors).
        # Family B = "position / breakout / path-shape" is the
        # natural home: dist_to_swing_high/low track distance to
        # swing-detected price extrema (path-shape), and
        # sr_range_compression_20d quantifies range tightness
        # (breakout precursor).
        "dist_to_swing_high_20d",
        "dist_to_swing_low_20d",
        "sr_range_compression_20d",
    }),
)

FAMILY_C_V2 = FamilyConfig(
    name="C",
    title=FAMILY_C.title,
    factors=frozenset(FAMILY_C.factors | {
        "dollar_vol_20d",
        "volume_ratio_20d",
        "vol_20d",
        "market_vol_ratio",
        "market_drawdown",
        "cross_section_dispersion_21d",
        "advance_ratio_10d",
    }),
)

FAMILY_D_V2 = FamilyConfig(
    name="D",
    title=FAMILY_D.title,
    factors=frozenset(FAMILY_D.factors | {
        "return_per_risk_21d",
        "xsection_rank_21d",
        "xsection_rank_63d",
        "rank_momentum_change",
    }),
)

FAMILY_E = FamilyConfig(
    name="E",
    title="intraday / overnight / microstructure",
    factors=frozenset({
        "hl_range",
        "intraday_ret_1d",
        "intraday_autocorr_21d",
        "intraday_vol_ratio_21d",
        "realized_vol_60m_21d",
        "overnight_ret_1d",
        "overnight_gap_5d",
        "overnight_gap_21d",
        "overnight_vs_intraday",
        "price_volume_div",
    }),
)

FAMILY_F = FamilyConfig(
    name="F",
    title="short-horizon reversal",
    factors=frozenset({
        "ret_1d",
        "ret_2d",
        "ret_5d",
        "reversal_5d",
        "reversal_10d",
        "reversal_21d",
    }),
)

FAMILIES_V2: List[FamilyConfig] = [
    FAMILY_A_V2, FAMILY_B_V2, FAMILY_C_V2, FAMILY_D_V2, FAMILY_E, FAMILY_F,
]


# ── pool→families selector + reachability preflight (A++ patch) ─────────────


def families_for_pool(
    pool_name: str,
) -> List[FamilyConfig]:
    """Return the family list for a named factor registry pool.

    Selector is fail-closed: an unknown pool name raises ``ValueError``
    rather than silently falling back. This is the mechanism by which
    the cycle-#01 yaml's `factor_registry_pool: RESEARCH_FACTORS` is
    bound to FAMILIES_V2 (the only family list whose union covers all
    64 RESEARCH_FACTORS names).

    Pool names supported:
      - ``"RESEARCH_FACTORS"``  → FAMILIES_V2
      - ``"FAMILIES_V1"``       → FAMILIES_V1 (legacy 33-factor subset)
      - ``"FAMILIES_V2"``       → FAMILIES_V2 (alias)
    """
    name = pool_name.strip()
    if name == "RESEARCH_FACTORS":
        return FAMILIES_V2
    if name == "FAMILIES_V2":
        return FAMILIES_V2
    if name == "FAMILIES_V1":
        return FAMILIES_V1
    raise ValueError(
        f"Unknown factor_registry_pool {pool_name!r}. Supported: "
        "'RESEARCH_FACTORS', 'FAMILIES_V1', 'FAMILIES_V2'."
    )


def assert_reachability_matches_pool(
    pool_name: str,
    families: Sequence[FamilyConfig],
    explicit_exclusions: Optional[Sequence[str]] = None,
) -> None:
    """Fail-closed contract assertion for the pre-registered pool→sampler binding.

    Layer split (A++ R3 audit refinement, 2026-04-30):
      - This helper checks the CODE-level question: "does the family
        mapping cover the named pool's registry exactly?" It is a
        symmetric set-equality check on `union(families) == registry`.
      - The OPERATIONAL question of which mapped factors are actually
        searched at trial time (e.g. when a factor's data dependency is
        unmet) is handled by `excluded_factors` in `suggest_composite_spec`
        and by the runner's panel-availability assertion. Excluded
        factors stay in the family mapping; they're filtered at sampler
        time only.

    `explicit_exclusions` is therefore intentionally NOT subtracted from
    `expected` here. It's accepted as a parameter for forward-compat /
    diagnostic clarity (callers can pass it and the helper just ignores
    it for reachability purposes).

    Raises
    ------
    ValueError
      if the union of `families`' factors differs from the named pool's
      registered name set. The error message lists missing-from-sampler
      (under-coverage) and extra-in-sampler (phantom factors not in
      registry) separately.

    Notes
    -----
    For ``pool_name == 'FAMILIES_V1'`` or ``'FAMILIES_V2'`` (legacy
    direct-pool selection), the assertion checks union(families) ==
    union(named pool) without consulting RESEARCH_FACTORS. This makes
    the helper usable in both yaml-driven and direct-pool flows.
    """
    from core.factors.factor_registry import RESEARCH_FACTORS  # lazy

    # Accepted for diagnostic / forward-compat use, but does NOT alter
    # the reachability set-equality check (see docstring layer-split note).
    _ = explicit_exclusions

    reachable = all_family_factors(families)

    if pool_name.strip() == "RESEARCH_FACTORS":
        expected = set(RESEARCH_FACTORS)
    elif pool_name.strip() == "FAMILIES_V1":
        expected = set(all_family_factors(FAMILIES_V1))
    elif pool_name.strip() == "FAMILIES_V2":
        expected = set(all_family_factors(FAMILIES_V2))
    else:
        raise ValueError(
            f"Unknown factor_registry_pool {pool_name!r} for "
            "reachability preflight."
        )

    missing_from_sampler = sorted(expected - reachable)
    extra_in_sampler = sorted(reachable - expected)

    if missing_from_sampler or extra_in_sampler:
        raise ValueError(
            "Sampler reachability does NOT match pre-registered "
            f"factor_registry_pool={pool_name!r}.\n"
            f"  Missing from sampler ({len(missing_from_sampler)}): "
            f"{missing_from_sampler}\n"
            f"  Extra in sampler    ({len(extra_in_sampler)}): "
            f"{extra_in_sampler}\n"
            "Resolution: broaden (or trim) the family mapping passed "
            "to ResearchMiner so its union exactly matches the named "
            "pool. (explicit_exclusions belong at the runner's panel-"
            "availability layer + sampler-time filter, NOT here.)"
        )


# Runtime lookup helpers. Keep them as functions so callers can override
# the family list for experimentation without mutating the module-level
# default.


def family_of_factor(
    factor_name: str, families: Sequence[FamilyConfig] = FAMILIES_V1,
) -> str | None:
    """Return the family name that contains `factor_name`, or None."""
    for fam in families:
        if factor_name in fam.factors:
            return fam.name
    return None


def all_family_factors(
    families: Sequence[FamilyConfig] = FAMILIES_V1,
) -> FrozenSet[str]:
    """Union of all factors across the given families."""
    acc: set[str] = set()
    for fam in families:
        acc.update(fam.factors)
    return frozenset(acc)


# ── Composite spec ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResearchCompositeSpec:
    """A research composite candidate: weighted combination of factors.

    Invariants:
      - features and weights are parallel; same length, >= 1
      - weights are non-negative and sum to 1.0 (within float tolerance)
      - family_counts maps family name → integer count of features from it
      - n_families ≥ min_families (default 3, per PRD §8.5)

    Immutable (frozen=True) so Optuna can hash for dedup.
    """
    features: Tuple[str, ...]
    weights: Tuple[float, ...]
    family_counts: Mapping[str, int] = field(default_factory=dict)
    # PRD-AC v1.1 §4.5 Phase 3 round 1 search-space extension.
    # Default None preserves backward compat: existing call sites
    # constructing ResearchCompositeSpec(features=..., weights=...,
    # family_counts=...) work unchanged.
    holding_freq: Optional[str] = None  # one of {None, 'daily', 'weekly', 'monthly'}
    # PRD-AC v1.1 §1.3 + master PRD §4.2 Phase B.2 (R4 ship 2026-05-07):
    # SR-defer search dim. Sampler may sample True when the study's
    # ``enable_sr_defer_choices`` includes True AND ResearchMiner was
    # constructed with non-None ``intraday_bars_60m``. evaluate_composite
    # applies apply_sr_defer_filter to the harness's baseline weights
    # and re-runs BacktestEngine on the filtered weights when activation
    # ≥ 5% (I6 prefilter). Default False preserves cycle04/05/06 archive
    # replay bit-for-bit.
    enable_sr_defer: bool = False

    # NOTE: __post_init__ validates invariants. Frozen dataclass still
    # allows this callback.
    def __post_init__(self) -> None:
        if len(self.features) != len(self.weights):
            raise ValueError(
                f"features ({len(self.features)}) and weights "
                f"({len(self.weights)}) length mismatch"
            )
        if not self.features:
            raise ValueError("spec must have at least 1 feature")
        if any(w < 0 for w in self.weights):
            raise ValueError(f"weights must be non-negative, got {self.weights}")
        total = sum(self.weights)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"weights must sum to 1.0, got {total} (diff {total-1.0:+.2e})"
            )
        if self.holding_freq is not None and self.holding_freq not in (
            "daily", "weekly", "monthly",
        ):
            raise ValueError(
                f"holding_freq must be one of None / 'daily' / 'weekly' / "
                f"'monthly', got {self.holding_freq!r}"
            )

    @property
    def n_features(self) -> int:
        return len(self.features)

    @property
    def n_families(self) -> int:
        return sum(1 for c in self.family_counts.values() if c > 0)


# ── Sampler ──────────────────────────────────────────────────────────────────


def suggest_composite_spec(
    trial: Any,
    families: Sequence[FamilyConfig] = FAMILIES_V1,
    min_families: int = 3,
    max_features_per_family: int = 2,
    weight_step: float = 0.05,
    composite_weighting: str = "tpe_normalized",
    target_n_features: Optional[int] = None,
    excluded_factors: Optional[Sequence[str]] = None,
    *,
    # PRD-AC v1.1 §4.5 Phase 3 round 1 search-space extension. Default
    # holding_freq_choices=None preserves legacy 2-dim search (factors +
    # weights). Pass an explicit list to opt into the holding_freq cell.
    holding_freq_choices: Optional[Sequence[str]] = None,
    # PRD-AC v1.1 §1.3 + master PRD §4.2 Phase B.2 (R4 ship): SR-defer
    # search dim. When the choices list contains True AND the caller
    # supplied ``intraday_bars_60m`` to ResearchMiner, sampling True
    # triggers apply_sr_defer_filter on the harness's baseline weights
    # and (when activation ≥ 5%) re-runs BacktestEngine to produce the
    # filtered NAV consumed by the objective. Phase 3 round 1 default
    # (False,) preserves bit-for-bit cycle04/05/06 behavior.
    enable_sr_defer_choices: Sequence[bool] = (False,),
) -> ResearchCompositeSpec:
    """Family-aware composite sampler (PRD §8.5).

    Protocol (Optuna trial-driven):
      1. For each family, Optuna suggests an integer count 0..max_features
         of features to draw from that family.
      2. If total selected families < min_families, raise optuna.TrialPruned
         (or caller re-draws).
      3. (cycle 2026-04-30 #01 A+ patch) If `target_n_features` is set
         and total deduped feature count != target_n_features, prune.
      4. For each selected feature, weights determined by
         `composite_weighting`:
           - "tpe_normalized" (default, legacy behavior): Optuna suggests
             a raw weight (float 0..1, step=weight_step) per feature;
             weights are normalized to sum=1.
           - "equal_weight": skip TPE weight sampling entirely; weights
             are uniform (1/n). Eliminates one cherry-pick degree-of-
             freedom (matches Cand-2 PRD §5.5 + cycle 2026-04-30 #01
             pre-registered criteria yaml).

    Notes:
      - Picks which specific features within a family via deterministic
        sorted order + Optuna categorical. Keeps the trial-name namespace
        flat and reproducible.
      - Does NOT run correlation / turnover penalty at sample time —
        those are applied in the objective function (R11).
      - Non-destructive: if normalization fails (all-zero weights raw),
        weights default to uniform.

    Parameters
    ----------
    trial            : Optuna Trial (any object with .suggest_* methods)
    families         : which families to sample from (default FAMILIES_V1)
    min_families     : reject spec with fewer active families
    max_features_per_family : upper bound on per-family feature count
    weight_step      : granularity for raw weight suggestions (only used
                       when composite_weighting="tpe_normalized")
    composite_weighting : "tpe_normalized" (default; legacy) or
                       "equal_weight". When "equal_weight", weights
                       become 1/n uniform and `trial.suggest_float`
                       is NOT called for w_<feat> — eliminates that
                       slice of search-space + cherry-pick risk.
    target_n_features : if set, post-dedup feature count MUST equal
                       this exact integer; mismatch → TrialPruned.
                       Default None (no enforcement; pre-A+ behavior).
                       Cycle 2026-04-30 #01 uses target_n_features=3
                       per pre-registered criteria yaml.

    Returns
    -------
    ResearchCompositeSpec

    Raises
    ------
    optuna.TrialPruned if the sampled spec has fewer than min_families,
    or (when target_n_features is set) if post-dedup cardinality != target.
    ValueError on invalid composite_weighting argument.
    """
    if composite_weighting not in ("tpe_normalized", "equal_weight"):
        raise ValueError(
            f"composite_weighting must be 'tpe_normalized' or 'equal_weight', "
            f"got {composite_weighting!r}"
        )

    # Import optuna lazily so this module is importable without optuna
    # for pure-dataclass tests.
    try:
        import optuna
    except ImportError:
        optuna = None  # sentinel

    selected: List[Tuple[str, str]] = []  # (family_name, factor_name)
    family_counts: dict[str, int] = {}

    # A++ patch 2026-04-30: filter `excluded_factors` out of every family's
    # categorical search space BEFORE TPE sees it. This keeps the sampler
    # in agreement with the runner's panel-availability assertion: an
    # excluded factor is never suggested. A family that ends up empty
    # after exclusion is skipped (its categorical is never invoked, so
    # TPE doesn't see a zero-arity choice).
    excl_set: set[str] = set(excluded_factors or ())

    for fam in families:
        sorted_factors = sorted(f for f in fam.factors if f not in excl_set)
        if not sorted_factors:
            family_counts[fam.name] = 0
            continue
        # How many features from this family?
        count = trial.suggest_int(
            f"n_features_{fam.name}", 0, max_features_per_family,
        )
        family_counts[fam.name] = count
        if count == 0:
            continue
        # Which specific features? Use categorical per slot.
        for slot in range(count):
            feat = trial.suggest_categorical(
                f"family_{fam.name}_slot_{slot}", sorted_factors,
            )
            selected.append((fam.name, feat))

    # Deduplicate (same factor picked in two different slots) while
    # preserving first occurrence.
    seen: set[str] = set()
    unique_selected: List[Tuple[str, str]] = []
    for fam_name, feat in selected:
        if feat not in seen:
            unique_selected.append((fam_name, feat))
            seen.add(feat)
        else:
            family_counts[fam_name] -= 1

    # Check min_families after dedup
    n_active_families = sum(1 for c in family_counts.values() if c > 0)
    if n_active_families < min_families or not unique_selected:
        if optuna is not None:
            raise optuna.TrialPruned(
                f"spec has {n_active_families} active families < "
                f"min_families={min_families}"
            )
        else:
            # For testing without optuna: fall back to raising ValueError
            raise ValueError(
                f"spec has {n_active_families} active families < "
                f"min_families={min_families}"
            )

    # ── A+ patch 2026-04-30: target_n_features exact-cardinality enforce ──
    # When pre-registered criteria specifies exact composite cardinality
    # (e.g. cycle #01 composite_cardinality=3), prune any trial whose
    # post-dedup feature count differs. This prevents the miner's natural
    # search shape (3 to ~12 features) from drifting away from the spec.
    if target_n_features is not None and len(unique_selected) != target_n_features:
        msg = (
            f"spec post-dedup has {len(unique_selected)} features, "
            f"target_n_features={target_n_features}"
        )
        if optuna is not None:
            raise optuna.TrialPruned(msg)
        else:
            raise ValueError(msg)

    # ── A+ patch 2026-04-30: composite_weighting branch ────────────────
    # equal_weight: skip TPE weight sampling entirely. Uniform 1/n.
    # tpe_normalized: legacy behavior — sample raw weights via TPE,
    # normalize to sum=1.
    if composite_weighting == "equal_weight":
        n = len(unique_selected)
        normalized = [1.0 / n] * n
    else:
        # Raw weights per selected feature (TPE-tuned normalized)
        raw_weights: List[float] = []
        for fam_name, feat in unique_selected:
            w = trial.suggest_float(
                f"w_{feat}", 0.0, 1.0, step=weight_step,
            )
            raw_weights.append(w)

        total_raw = sum(raw_weights)
        if total_raw <= 0:
            # All-zero edge: use uniform
            n = len(raw_weights)
            normalized = [1.0 / n] * n
        else:
            normalized = [w / total_raw for w in raw_weights]

    # Round normalized weights so the sum==1 check in ResearchCompositeSpec
    # tolerance (1e-6) is comfortable.
    features_tup = tuple(feat for _, feat in unique_selected)
    weights_tup = tuple(normalized)
    # Final check: correct any float-noise such that sum exactly = 1
    adj = 1.0 - sum(weights_tup)
    if abs(adj) > 0 and abs(adj) < 1e-6:
        # absorb into largest weight
        max_idx = max(range(len(weights_tup)), key=lambda i: weights_tup[i])
        weights_list = list(weights_tup)
        weights_list[max_idx] += adj
        weights_tup = tuple(weights_list)

    # PRD-AC v1.1 §4.5 search-dim sampling. holding_freq sampled at the
    # END so it doesn't perturb factor/weight TPE search-name namespace
    # (legacy trial keys preserved for cycle04/05 archive replay).
    holding_freq: Optional[str] = None
    if holding_freq_choices:
        holding_freq = trial.suggest_categorical(
            "holding_freq", list(holding_freq_choices),
        )
    enable_sr_defer = bool(trial.suggest_categorical(
        "enable_sr_defer", list(enable_sr_defer_choices),
    )) if len(enable_sr_defer_choices) > 1 else bool(enable_sr_defer_choices[0])

    return ResearchCompositeSpec(
        features=features_tup,
        weights=weights_tup,
        family_counts=dict(family_counts),
        holding_freq=holding_freq,
        enable_sr_defer=enable_sr_defer,
    )


# ── R10: composite signal builder + evaluator ───────────────────────────────


def zscore_cs(
    df: pd.DataFrame, min_periods: int = 5,
) -> pd.DataFrame:
    """Cross-sectional z-score per date (row).

    Each row (date) is standardized to zero mean + unit std across its
    valid (non-NaN) columns. Rows with fewer than `min_periods` valid
    columns return NaN. NaN cells in input stay NaN (no imputation).
    """
    mu = df.mean(axis=1, skipna=True)
    sd = df.std(axis=1, skipna=True, ddof=0).replace(0, np.nan)
    valid_count = df.notna().sum(axis=1)
    out = df.sub(mu, axis=0).div(sd, axis=0)
    # Blank-out rows that don't meet min_periods
    mask = valid_count < min_periods
    out.loc[mask] = np.nan
    return out


def build_composite_series(
    spec: ResearchCompositeSpec,
    factor_panel_map: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Weighted z-score composite of feature panels.

    For each feature in spec.features:
      1. z-score the factor panel cross-sectionally per date
      2. multiply by the feature's weight
    Sum across features → composite signal panel (date × symbol).

    Missing feature panels raise KeyError (caller must supply all
    spec.features). NaN cells in any component propagate via
    per-cell sum skipping NaN with `.sum(min_count=1)` — at least one
    valid component is required for a valid composite cell.

    Parameters
    ----------
    spec             : ResearchCompositeSpec
    factor_panel_map : mapping of factor name → DataFrame (date × symbol)

    Returns
    -------
    DataFrame aligned to the intersection of all component panels'
    date indices / symbol columns.
    """
    missing = [f for f in spec.features if f not in factor_panel_map]
    if missing:
        raise KeyError(
            f"factor_panel_map missing features: {missing}"
        )
    # Take the index/columns intersection across all components
    first = factor_panel_map[spec.features[0]]
    common_idx = first.index
    common_cols = first.columns
    for feat in spec.features[1:]:
        p = factor_panel_map[feat]
        common_idx = common_idx.intersection(p.index)
        common_cols = common_cols.intersection(p.columns)
    # z-score each component then weight and sum
    weighted_components: List[pd.DataFrame] = []
    for feat, w in zip(spec.features, spec.weights):
        p = factor_panel_map[feat].loc[common_idx, common_cols]
        z = zscore_cs(p)
        weighted_components.append(z * w)
    # Sum across features; each cell = Σ w_i * z_i where component not NaN
    # Use pd.concat with keys then sum across level 0 for robust NaN handling
    stacked = pd.concat(weighted_components, keys=range(len(weighted_components)))
    composite = stacked.groupby(level=1).sum(min_count=1)
    # Preserve original index ordering (common_idx)
    return composite.reindex(common_idx).reindex(columns=common_cols)


def _spearman_ic_per_date(
    signal: pd.DataFrame, fwd_returns: pd.DataFrame,
) -> pd.Series:
    """Per-date spearman rank-correlation of signal vs fwd_returns.

    Aligns on index and columns intersection. Requires ≥ 10 valid (sym)
    observations per date else returns NaN for that date.
    """
    common_idx = signal.index.intersection(fwd_returns.index)
    common_cols = signal.columns.intersection(fwd_returns.columns)
    sig = signal.loc[common_idx, common_cols]
    fwd = fwd_returns.loc[common_idx, common_cols]
    ics: Dict[pd.Timestamp, float] = {}
    for date in common_idx:
        s_row = sig.loc[date].dropna()
        f_row = fwd.loc[date].dropna()
        shared = s_row.index.intersection(f_row.index)
        if len(shared) < 10:
            continue
        # spearman = pearson on ranks
        s_rank = s_row.loc[shared].rank()
        f_rank = f_row.loc[shared].rank()
        # Only compute if ranks have variance
        if s_rank.std() == 0 or f_rank.std() == 0:
            continue
        corr = s_rank.corr(f_rank)
        if pd.notna(corr):
            ics[date] = float(corr)
    return pd.Series(ics, name="ic").sort_index()


def _turnover_proxy(signal: pd.DataFrame) -> float:
    """Cross-sectional rank stability proxy ∈ [0, 1].

    High turnover = ranks shuffle a lot between consecutive dates;
    low turnover = stable signal. Computed as mean of per-date average
    |rank change| normalized by the cross-sectional rank range.

    Returns 0.0 when signal is all-NaN or single-date.
    """
    if len(signal) < 2:
        return 0.0
    ranks = signal.rank(axis=1, method="average")
    n_sym = ranks.count(axis=1)
    # |rank diff| per cell
    diff = ranks.diff(1).abs()
    # Per-date mean |rank change|
    per_date_mean_abs_change = diff.mean(axis=1, skipna=True)
    # Normalize by cross-sectional n_sym to get [0,1]-ish scale
    normalized = per_date_mean_abs_change / n_sym.replace(0, np.nan)
    return float(normalized.mean(skipna=True)) if normalized.notna().any() else 0.0


def _corr_concentration(
    spec: ResearchCompositeSpec,
    factor_panel_map: Mapping[str, pd.DataFrame],
) -> float:
    """Mean of pairwise |Pearson correlation| between component factors.

    High value = components redundant (each pair highly correlated) →
    composite is essentially one signal repeated.
    Low value = components orthogonal → true diversification.

    Returns 0.0 when spec has only 1 feature (trivially zero redundancy).
    """
    if spec.n_features < 2:
        return 0.0
    # Flatten each component to a 1-D series (date × symbol)
    flat_series: List[pd.Series] = []
    for feat in spec.features:
        p = factor_panel_map[feat]
        # Pandas 2.x+ dropped `dropna` kwarg from stack; default now drops NaN.
        flat_series.append(p.stack())
    # Pairwise corr — compute symmetric matrix upper triangle
    corrs: List[float] = []
    for i in range(len(flat_series)):
        for j in range(i + 1, len(flat_series)):
            # Align on common index (date, symbol) pairs
            combined = pd.concat(
                [flat_series[i], flat_series[j]], axis=1, join="inner",
            )
            combined.columns = ["a", "b"]
            if len(combined) < 30:
                continue
            c = combined["a"].corr(combined["b"])
            if pd.notna(c):
                corrs.append(abs(float(c)))
    return float(np.mean(corrs)) if corrs else 0.0


@dataclass
class CompositeMetrics:
    """Summary metrics for a research composite (PRD §8.4 candidate schema).

    R14 fix: `ic_ir` uses horizon-aware annualization factor
    `sqrt(252 / horizon)` instead of naive `sqrt(252)`. For fwd horizon h,
    consecutive per-date IC observations share (h-1)/h of their forward
    window → correlation across the IC series deflates std → annualizing
    by sqrt(252) overstates IR by ~sqrt(h). The horizon-aware factor
    approximates non-overlapping sampling. Full Newey-West HAC is still
    stricter but out of v1 scope.
    """
    n_features: int
    n_families: int
    n_dates: int
    ic_mean: float
    ic_std: float
    ic_ir: float            # ic_mean / ic_std * sqrt(252 / horizon)
    turnover_proxy: float
    corr_concentration: float
    horizon: int = 21       # forecast horizon in trading days (for audit)
    # PRD-AC v1.1 §4.2: NAV-based metrics. Default NaN so v1_legacy
    # flow leaves them unset; v2_nav_based flow populates via the
    # mining-internal NAV gate (research_miner.py evaluate_composite +
    # core/research/harness/composite_evaluator.evaluate_composite_spec).
    nav_sharpe: float = float("nan")
    nav_max_dd: float = float("nan")
    nav_correlation_vs_anchor_pooled_raw: float = float("nan")
    nav_vs_qqq_excess_full_period: float = float("nan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_features": self.n_features,
            "n_families": self.n_families,
            "n_dates": self.n_dates,
            "ic_mean": self.ic_mean,
            "ic_std": self.ic_std,
            "ic_ir": self.ic_ir,
            "turnover_proxy": self.turnover_proxy,
            "corr_concentration": self.corr_concentration,
            "horizon": self.horizon,
            "nav_sharpe": self.nav_sharpe,
            "nav_max_dd": self.nav_max_dd,
            "nav_correlation_vs_anchor_pooled_raw": self.nav_correlation_vs_anchor_pooled_raw,
            "nav_vs_qqq_excess_full_period": self.nav_vs_qqq_excess_full_period,
        }


def evaluate_composite(
    spec: ResearchCompositeSpec,
    factor_panel_map: Mapping[str, pd.DataFrame],
    fwd_returns: pd.DataFrame,
    mask: Optional[pd.DataFrame] = None,
    horizon: int = 21,
    lag: int = 1,
    *,
    # PRD-AC v1.1 §4.3 NAV gate kwargs. Defaults preserve v1_legacy
    # behavior bit-for-bit (no NAV path executed). Pass non-None values
    # AND set ``compute_nav=True`` to opt into v2_nav_based: the harness's
    # ex-post evaluator runs a full BacktestEngine eval, four NAV metrics
    # are folded into CompositeMetrics, and the I20 cross-asset detector
    # zeros out the orthogonality term for >30%-non-equity specs.
    price_df: Optional[pd.DataFrame] = None,
    open_df: Optional[pd.DataFrame] = None,
    spy_series: Optional[pd.Series] = None,
    qqq_series: Optional[pd.Series] = None,
    anchor_residual_returns: Optional[pd.Series] = None,
    harness_config: Optional[Any] = None,
    compute_nav: bool = False,
    # PRD-AC v1.1 §1.3 + master PRD §4.2 Phase B.2 (R4 ship): SR defer
    # mining integration. When ``spec.enable_sr_defer=True`` AND this
    # dict is non-None AND I6 prefilter activation ≥ 5%, the harness's
    # baseline ``result.weights`` are filtered via apply_sr_defer_filter
    # and BacktestEngine is re-run on the filtered weights to produce
    # the NAV used in the objective. Default None preserves Phase 3 round
    # 1 stub behavior bit-for-bit.
    intraday_bars_60m: Optional[Dict[str, pd.DataFrame]] = None,
) -> CompositeMetrics:
    """Evaluate a research composite spec against forward returns.

    Computes per-PRD §8.4:
      - IC (per-date spearman rank-correlation of composite vs fwd_ret)
      - IC mean / std / IR (annualized as sqrt(252 / horizon))
      - turnover proxy (cross-sectional rank stability)
      - corr concentration (mean pairwise |corr| between components)

    If `mask` provided (date × symbol bool), composite cells where mask
    is False are set to NaN before metrics (PRD §7 sample definition).

    Parameters
    ----------
    spec             : ResearchCompositeSpec
    factor_panel_map : feature name → factor panel mapping
    fwd_returns      : forward-return panel (date × symbol)
    mask             : optional research_mask panel to filter samples
    horizon          : forecast horizon in trading days (default 21).
                       Controls the annualization factor on IC_IR.
    lag              : R15 fix. Number of bars to shift the composite
                       BEFORE computing IC. Default 1. Prevents "shared
                       close[t] leakage": if a factor at date t is a
                       function of close[t], and fwd_return[t] =
                       close[t+h]/close[t] - 1 also uses close[t] as
                       base, the same-bar noise in close[t] mechanically
                       creates correlation that has no forecasting
                       value. Shifting the composite by 1 ensures the
                       signal used at t is computed strictly from data
                       through t-1, matching the T+1-open execution
                       convention the backtest engine enforces. Set
                       lag=0 only for explicit contemporaneous IC
                       research (e.g. "does close[t] predict today's
                       intraday return?"); never for composite mining.

    Returns
    -------
    CompositeMetrics dataclass
    """
    if horizon <= 0:
        raise ValueError(f"horizon must be positive, got {horizon}")
    if lag < 0:
        raise ValueError(f"lag must be >= 0, got {lag}")
    composite = build_composite_series(spec, factor_panel_map)
    if lag > 0:
        composite = composite.shift(lag)
    if mask is not None:
        # Import lazily to avoid circular
        from core.factors.base_masks import apply_research_mask
        composite = apply_research_mask(composite, mask)
    ic_series = _spearman_ic_per_date(composite, fwd_returns)
    ic_mean = float(ic_series.mean()) if len(ic_series) else float("nan")
    ic_std = float(ic_series.std()) if len(ic_series) > 1 else float("nan")
    # Horizon-aware annualized IR (R14): sqrt(252/h) approximates
    # non-overlapping sampling scale.
    if ic_std > 0 and pd.notna(ic_std):
        ic_ir = ic_mean / ic_std * np.sqrt(252 / horizon)
    else:
        ic_ir = float("nan")
    turnover = _turnover_proxy(composite)
    corr_conc = _corr_concentration(spec, factor_panel_map)
    # PRD-AC v1.1 §4.3 NAV gate. Defaults all NaN → v1_legacy compute_objective
    # treats as 0 contribution. Triggered ONLY when caller passes
    # ``compute_nav=True`` AND the four required panels are all non-None.
    nav_sharpe = float("nan")
    nav_max_dd = float("nan")
    nav_corr_anchor = float("nan")
    nav_vs_qqq = float("nan")
    if compute_nav:
        if price_df is None or spy_series is None:
            raise ValueError(
                "evaluate_composite(compute_nav=True) requires non-None "
                "price_df and spy_series; got "
                f"price_df={price_df is not None} spy_series={spy_series is not None}"
            )
        from core.research.harness.composite_evaluator import (
            evaluate_composite_spec as expost_eval,
        )
        from core.mining.nav_objective import (
            classify_cross_asset_spec,
            compute_spec_residual_pooled_raw_correlation,
            mask_train_boundary_returns,
            recompute_nav_metrics_train_only,
        )
        # PRD-AC v1.1 §4.5 I8: spec.holding_freq overrides
        # harness_config.rebalance_cadence at runtime (frozen dataclass
        # → dataclasses.replace). Backward compat: spec.holding_freq=None
        # preserves caller-supplied harness_config cadence.
        effective_harness_config = harness_config
        if spec.holding_freq is not None and harness_config is not None:
            from dataclasses import replace as _dc_replace
            effective_harness_config = _dc_replace(
                harness_config, rebalance_cadence=spec.holding_freq,
            )
        result = expost_eval(
            spec,
            factor_panel_map=factor_panel_map,
            price_df=price_df,
            open_df=open_df,
            spy_series=spy_series,
            qqq_series=qqq_series,
            config=effective_harness_config,
            research_mask=mask,
        )
        # Master PRD §4.2 Phase B.2 (R4 ship): SR defer mining integration
        # per PRD-AC §1.3 user explicit-go. When spec opts in via
        # enable_sr_defer=True AND caller provides intraday_bars_60m:
        #   1. Apply SR defer filter to baseline result.weights
        #   2. I6 prefilter: if activation_rate < 5%, keep baseline NAV
        #      (sample efficiency; skip the second BacktestEngine run)
        #   3. Else: re-run BacktestEngine on filtered weights and replace
        #      result.weights + result.daily_returns with filtered NAV.
        # Phase 3 round 1 stub (intraday_bars_60m=None) preserved bit-for-bit.
        if spec.enable_sr_defer and intraday_bars_60m:
            from core.research.sr_signal_filter import (
                SRDeferConfig, apply_sr_defer_filter,
            )
            filtered_weights, stats = apply_sr_defer_filter(
                result.weights, intraday_bars_60m, config=SRDeferConfig(),
            )
            activation_rate = (
                stats.n_defers / stats.n_evaluated
                if stats.n_evaluated > 0 else 0.0
            )
            # I6 prefilter: only re-run BacktestEngine when SR defer
            # materially fires (≥ 5% activation). Below this threshold,
            # filter touches too few cells to move NAV — skip the
            # second harness invocation for sample-efficiency.
            if activation_rate >= 0.05:
                from core.backtest.backtest_engine import BacktestEngine
                from core.config.loader import load_config
                from core.execution.cost_model import CostModel
                # Re-run BacktestEngine on filtered weights; mirror harness
                # config (same cost_model + initial_capital + execution
                # semantics) so filtered NAV is comparable to baseline.
                cfg_full = load_config()
                cm = CostModel(cfg_full.cost_model)
                # Use harness defaults if effective_harness_config absent.
                init_capital = (
                    effective_harness_config.initial_capital
                    if effective_harness_config is not None else 1_000_000.0
                )
                rebal_thr = (
                    effective_harness_config.rebalance_threshold
                    if effective_harness_config is not None else 0.02
                )
                int_shares = (
                    effective_harness_config.integer_shares
                    if effective_harness_config is not None else False
                )
                engine = BacktestEngine(
                    cost_model=cm,
                    initial_capital=init_capital,
                    rebalance_threshold=rebal_thr,
                    integer_shares=int_shares,
                )
                # Align filtered_weights to price_df columns (both should
                # already match since result.weights came from the same
                # price_df, but be defensive).
                common_syms = [
                    s for s in filtered_weights.columns
                    if s in price_df.columns
                ]
                sig = filtered_weights[common_syms]
                px = price_df[common_syms].reindex(sig.index)
                op = (
                    open_df[common_syms].reindex(sig.index)
                    if open_df is not None else None
                )
                bt_result_filtered = engine.run(
                    signals_df=sig, price_df=px, open_df=op,
                    benchmark_series=spy_series,
                )
                nav_filtered = bt_result_filtered.equity_curve.copy()
                daily_ret_filtered = nav_filtered.pct_change().fillna(0.0)
                # Replace result.weights + result.daily_returns IN PLACE
                # (EvaluatedComposite is mutable @dataclass). Downstream
                # NAV recompute (recompute_nav_metrics_train_only) reads
                # result.daily_returns; orthogonality + benchmark
                # correlations also derive from result.daily_returns +
                # result.weights — all naturally pick up the filtered
                # version.
                result.weights = sig
                result.daily_returns = daily_ret_filtered
                result.nav = nav_filtered
        # PRD §6 Phase 2 I9 fix: harness ``metrics_full_period`` includes
        # gap-period returns on positions held across train_year
        # boundaries (empirically ~10% jump on cycle #04 top-1 at the
        # 2022→2024 boundary across the 2023 validation gap). Mining
        # objective must select for in-train alpha, not cross-gap luck;
        # recompute Sharpe / max_dd / vs_qqq after masking boundary
        # returns. v1_legacy IC-only objective is unaffected (no NAV
        # path). See docs/memos/20260506-i9_boundary_artifact_finding.md
        # for the empirical evidence.
        recomputed = recompute_nav_metrics_train_only(
            result.daily_returns, qqq_series=qqq_series,
        )
        nav_sharpe = float(recomputed["sharpe"])
        nav_max_dd = float(recomputed["max_dd"])
        nav_vs_qqq = float(recomputed["vs_qqq"])
        # I20 cross-asset detector: skip orthogonality (NaN → 0 penalty
        # in compute_objective) when realized non-equity weight > 30%.
        # SPY-residual anchor assumes equity-beta-driven spec; cross-
        # asset specs have low SPY β and residuals are largely cross-
        # asset alpha unrelated to the SPY-bound long-only floor.
        if anchor_residual_returns is not None and not classify_cross_asset_spec(
            result.weights,
        ):
            # Mask boundary returns on spec returns BEFORE residual corr
            # so the corr is computed on in-train days only (anchor
            # residual is built on train-only panel which already does
            # this implicitly via ``pct_change`` on a non-contiguous
            # index, but it produces NaN at boundary indices, dropped
            # by ``dropna``; spec returns from harness need explicit
            # masking).
            masked_spec_ret = mask_train_boundary_returns(result.daily_returns)
            nav_corr_anchor = compute_spec_residual_pooled_raw_correlation(
                masked_spec_ret, anchor_residual_returns, spy_series,
            )
        # else: nav_corr_anchor stays NaN → orthogonality term contributes 0
    return CompositeMetrics(
        n_features=spec.n_features,
        n_families=spec.n_families,
        n_dates=len(ic_series),
        ic_mean=ic_mean,
        ic_std=ic_std,
        ic_ir=float(ic_ir),
        turnover_proxy=turnover,
        corr_concentration=corr_conc,
        horizon=int(horizon),
        nav_sharpe=nav_sharpe,
        nav_max_dd=nav_max_dd,
        nav_correlation_vs_anchor_pooled_raw=nav_corr_anchor,
        nav_vs_qqq_excess_full_period=nav_vs_qqq,
    )


# ── R11: Optuna objective + ResearchMiner entry ─────────────────────────────


@dataclass(frozen=True)
class ObjectiveWeights:
    """PRD §8.6 weighted-sum objective weights.

    Default mirrors PRD example; callers can tune via CLI.

    PRD-AC v1.1 §4.1 NAV-based extension: ``w_nav_*`` fields default to
    0.0 → ``v1_legacy`` objective behavior preserved bit-for-bit on cycle
    #04/#05 archive replay. Setting any to non-zero opts the trial into
    the NAV path (mining-internal evaluator runs ex-post harness eval
    and folds nav_sharpe / nav_max_dd / nav_corr_anchor / nav_vs_qqq_excess
    into the weighted sum).
    """
    w_ir: float = 1.0               # + weight on OOS IR
    w_turnover: float = 0.5         # − penalty on turnover proxy
    w_corr_conc: float = 1.0        # − penalty on correlation concentration
    w_bench_excess: float = 0.3     # + weight on benchmark excess
    w_regime_stddev: float = 0.2    # − penalty on regime-IC stddev
    # PRD-AC v1.1 §4.1 — defaults all 0.0 = v1_legacy backward compat.
    w_nav_sharpe: float = 0.0           # + weight on full-period NAV Sharpe
    w_nav_max_dd_penalty: float = 0.0   # − penalty on |full-period max_dd|
    w_nav_orthogonality: float = 0.0    # − penalty on max(0, raw_corr_vs_anchor − 0.5)
    w_vs_qqq_excess: float = 0.0        # + weight on full-period vs_qqq excess

    def is_nav_based(self) -> bool:
        """True iff any ``w_nav_*`` weight is non-zero (objective_version=v2)."""
        return (
            self.w_nav_sharpe != 0.0
            or self.w_nav_max_dd_penalty != 0.0
            or self.w_nav_orthogonality != 0.0
            or self.w_vs_qqq_excess != 0.0
        )


# Regime classification used by ObjectiveWeightsV3 + regime-conditional
# objective. "BEAR" is an aggregate of CAUTIOUS / RISK_OFF / CRISIS per
# master PRD §4.3 C.1; per-regime weights below cover {BULL, RISK_ON,
# NEUTRAL, CAUTIOUS, RISK_OFF, CRISIS}.
_REGIME_BEAR_AGGREGATE = ("CAUTIOUS", "RISK_OFF", "CRISIS")


@dataclass(frozen=True)
class ObjectiveWeightsV3:
    """Master PRD §4.3 C.1 (R6 ship 2026-05-07) regime-conditional weights.

    v3 objective dispatches via ``isinstance(weights, ObjectiveWeightsV3)``
    in ``compute_objective`` (Issue N). v1/v2 callers see the existing
    ``ObjectiveWeights``-typed weights argument; v3 callers pass a
    ``Dict[regime, CompositeMetrics]`` as the first arg instead of a
    single ``CompositeMetrics``.

    Default favors BEAR-conditional alpha (``w_ir_RISK_OFF``=1.5,
    ``w_ir_CRISIS``=2.0) per PRD §4.3 C.1 example. Caller can tune.

    The full-period anchor / vs_qqq weights (``w_nav_orthogonality``,
    ``w_vs_qqq_excess``) operate on the regime-aggregated NAV (not
    regime-stratified) — they're full-period gates that should not
    differ across regimes.
    """
    # Per-regime IR weights (favor BEAR-conditional alpha)
    w_ir_BULL: float = 0.5
    w_ir_RISK_ON: float = 0.5
    w_ir_NEUTRAL: float = 0.5
    w_ir_CAUTIOUS: float = 1.0
    w_ir_RISK_OFF: float = 1.5
    w_ir_CRISIS: float = 2.0
    # Per-regime NAV-Sharpe weights (BEAR aggregates CAUTIOUS+RISK_OFF+CRISIS)
    w_nav_sharpe_BULL: float = 0.10
    w_nav_sharpe_BEAR: float = 0.30
    # Full-period (NOT regime-stratified)
    w_nav_orthogonality: float = 2.0
    w_vs_qqq_excess: float = 0.20

    def is_nav_based(self) -> bool:
        """v3 is always NAV-based (NAV-Sharpe + orthogonality + vs_qqq are
        intrinsic to the objective)."""
        return True


def compute_objective(
    metrics: "CompositeMetrics | Dict[str, CompositeMetrics]",
    benchmark_excess: float = 0.0,
    regime_stddev: float = 0.0,
    weights: "Optional[ObjectiveWeights | ObjectiveWeightsV3]" = None,
) -> float:
    """PRD §8.6 + PRD-AC v1.1 §4.4 weighted-sum objective.

    v1_legacy (default; all w_nav_* = 0):
        objective = w_ir * IR
                  - w_turnover * turnover_proxy
                  - w_corr_conc * corr_concentration
                  + w_bench_excess * benchmark_excess
                  - w_regime_stddev * regime_stddev

    v2_nav_based (any w_nav_* > 0):
        objective = (v1_legacy)
                  + w_nav_sharpe * nav_sharpe
                  - w_nav_max_dd_penalty * |nav_max_dd|
                  - w_nav_orthogonality * max(0, nav_corr_anchor - 0.5)
                  + w_vs_qqq_excess * nav_vs_qqq_excess_full_period

    NaN-safe: any NaN metric contributes 0 (logged at caller as "insufficient
    data"). Returns -inf if IC_IR itself is NaN (no signal). NaN nav_*
    metrics also contribute 0 → if a v2 trial has w_nav_sharpe>0 but the
    NAV gate did not run, that trial silently degrades to v1 ranking
    (caller must ensure NAV gate runs when w_nav_* > 0).

    v3_regime_conditional (master PRD §4.3 C.1, R6 ship 2026-05-07):
    when ``weights`` is an ``ObjectiveWeightsV3`` instance, dispatch to
    ``_compute_objective_v3`` (Issue N). The first arg must be a
    ``Dict[regime_name, CompositeMetrics]``; per-regime IR weights are
    applied + BEAR aggregate of CAUTIOUS/RISK_OFF/CRISIS NAV-Sharpe is
    averaged. Full-period anchor + vs_qqq use any regime's metrics
    (full-period values are the same across regimes by construction).
    """
    # Issue N: ObjectiveWeightsV3 isinstance dispatch
    if isinstance(weights, ObjectiveWeightsV3):
        if not isinstance(metrics, dict):
            raise TypeError(
                "compute_objective: ObjectiveWeightsV3 dispatch requires "
                "metrics_per_regime: Dict[regime_name, CompositeMetrics] "
                f"as first arg; got {type(metrics).__name__}"
            )
        return _compute_objective_v3(metrics, weights)
    w = weights or ObjectiveWeights()
    ir = metrics.ic_ir if np.isfinite(metrics.ic_ir) else float("-inf")
    if ir == float("-inf"):
        return float("-inf")
    turnover = metrics.turnover_proxy if np.isfinite(metrics.turnover_proxy) else 0.0
    corr_c = metrics.corr_concentration if np.isfinite(metrics.corr_concentration) else 0.0
    be = benchmark_excess if np.isfinite(benchmark_excess) else 0.0
    rs = regime_stddev if np.isfinite(regime_stddev) else 0.0
    legacy_terms = (
        w.w_ir * ir
        - w.w_turnover * turnover
        - w.w_corr_conc * corr_c
        + w.w_bench_excess * be
        - w.w_regime_stddev * rs
    )
    # PRD-AC v1.1 §4.4 NAV terms. NaN-safe: missing NAV metrics
    # contribute 0 (a v1_legacy trial with all w_nav_*=0 lands here
    # with all four terms = 0 and returns identical to legacy path).
    nav_sharpe = metrics.nav_sharpe if np.isfinite(metrics.nav_sharpe) else 0.0
    nav_max_dd = metrics.nav_max_dd if np.isfinite(metrics.nav_max_dd) else 0.0
    nav_corr = (
        metrics.nav_correlation_vs_anchor_pooled_raw
        if np.isfinite(metrics.nav_correlation_vs_anchor_pooled_raw)
        else 0.0
    )
    nav_vs_qqq = (
        metrics.nav_vs_qqq_excess_full_period
        if np.isfinite(metrics.nav_vs_qqq_excess_full_period)
        else 0.0
    )
    nav_terms = (
        w.w_nav_sharpe * nav_sharpe
        - w.w_nav_max_dd_penalty * abs(nav_max_dd)
        - w.w_nav_orthogonality * max(0.0, nav_corr - 0.5)
        + w.w_vs_qqq_excess * nav_vs_qqq
    )
    return legacy_terms + nav_terms


def _compute_objective_v3(
    metrics_per_regime: Dict[str, "CompositeMetrics"],
    weights: ObjectiveWeightsV3,
) -> float:
    """Master PRD §4.3 C.1 (R6 ship): regime-conditional objective.

    Per-regime IR weights × per-regime IC_IR + BEAR-aggregate NAV-Sharpe
    + full-period anchor + vs_qqq. NaN-safe: missing regime → 0
    contribution; missing nav metrics → 0 contribution.

    Returns -inf only when EVERY regime has NaN ic_ir (no signal anywhere).
    """
    if not metrics_per_regime:
        return float("-inf")
    # Per-regime IR contributions
    total = 0.0
    finite_ir_count = 0
    for regime, metrics in metrics_per_regime.items():
        w_attr = f"w_ir_{regime}"
        w_ir = getattr(weights, w_attr, 0.0)
        ir = metrics.ic_ir if np.isfinite(metrics.ic_ir) else 0.0
        if np.isfinite(metrics.ic_ir):
            finite_ir_count += 1
        total += w_ir * ir
    if finite_ir_count == 0:
        return float("-inf")
    # BULL NAV-Sharpe
    bull_metrics = metrics_per_regime.get("BULL")
    bull_sharpe = (
        bull_metrics.nav_sharpe
        if bull_metrics is not None
        and np.isfinite(bull_metrics.nav_sharpe)
        else 0.0
    )
    total += weights.w_nav_sharpe_BULL * bull_sharpe
    # BEAR NAV-Sharpe (aggregate across CAUTIOUS / RISK_OFF / CRISIS)
    bear_sharpes = []
    for regime in _REGIME_BEAR_AGGREGATE:
        m = metrics_per_regime.get(regime)
        if m is not None and np.isfinite(m.nav_sharpe):
            bear_sharpes.append(m.nav_sharpe)
    avg_bear_sharpe = (
        sum(bear_sharpes) / len(bear_sharpes) if bear_sharpes else 0.0
    )
    total += weights.w_nav_sharpe_BEAR * avg_bear_sharpe
    # Full-period anchor + vs_qqq (use any regime's full-period values
    # since they're identical by construction — full-period NAV is one
    # series sliced by regime for IC, not re-computed per regime)
    first = next(iter(metrics_per_regime.values()))
    nav_corr = (
        first.nav_correlation_vs_anchor_pooled_raw
        if np.isfinite(first.nav_correlation_vs_anchor_pooled_raw)
        else 0.0
    )
    nav_vs_qqq = (
        first.nav_vs_qqq_excess_full_period
        if np.isfinite(first.nav_vs_qqq_excess_full_period)
        else 0.0
    )
    total -= weights.w_nav_orthogonality * max(0.0, nav_corr - 0.5)
    total += weights.w_vs_qqq_excess * nav_vs_qqq
    return total


def evaluate_composite_regime_conditional(
    spec: ResearchCompositeSpec,
    factor_panel_map: Mapping[str, pd.DataFrame],
    fwd_returns: pd.DataFrame,
    daily_regime_labels: pd.Series,
    mask: Optional[pd.DataFrame] = None,
    horizon: int = 21,
    lag: int = 1,
    *,
    price_df: Optional[pd.DataFrame] = None,
    open_df: Optional[pd.DataFrame] = None,
    spy_series: Optional[pd.Series] = None,
    qqq_series: Optional[pd.Series] = None,
    anchor_residual_returns: Optional[pd.Series] = None,
    harness_config: Optional[Any] = None,
    intraday_bars_60m: Optional[Dict[str, pd.DataFrame]] = None,
    fallback_min_n_days: int = 200,
) -> Dict[str, "CompositeMetrics"]:
    """Master PRD §4.3 C.1 (R6 ship): regime-conditional composite evaluation.

    For each regime in ``daily_regime_labels.unique()``:
      1. Mask ``fwd_returns`` to days where ``regime_label == regime``
      2. Issue D fallback: if regime n_days on miner panel < ``fallback_
         min_n_days``, use full-period IC_IR for that regime (avoids
         spurious tiny-sample regime estimates)
      3. Compute per-regime ``CompositeMetrics`` (regime-stratified IC;
         full-period NAV — running BacktestEngine per regime is
         out-of-scope for R6 cardinality)

    The ``daily_regime_labels`` Series is typically produced by
    ``core.research.taa.regime_label_generator.daily_regime_labels``
    (same generator used by PRD-E TAA Phase 3).

    Returns
    -------
    Dict[regime_name, CompositeMetrics]
        Per-regime metrics. Each entry's NAV fields are FULL-PERIOD
        values (BacktestEngine ran once on the contiguous train panel);
        IC fields are regime-stratified (or full-period when fallback
        fires). Caller (compute_objective via ObjectiveWeightsV3) reads
        per-regime IC for IR weighting and aggregate NAV for the
        BEAR/BULL NAV-Sharpe + full-period anchor / vs_qqq terms.
    """
    nav_active = (
        price_df is not None
        and spy_series is not None
    )
    full = evaluate_composite(
        spec, factor_panel_map, fwd_returns, mask, horizon, lag,
        price_df=price_df, open_df=open_df,
        spy_series=spy_series, qqq_series=qqq_series,
        anchor_residual_returns=anchor_residual_returns,
        harness_config=harness_config, compute_nav=nav_active,
        intraday_bars_60m=intraday_bars_60m,
    )
    metrics_per_regime: Dict[str, "CompositeMetrics"] = {}
    label_index = daily_regime_labels.dropna()
    regimes_in_labels = sorted(label_index.unique())
    for regime in regimes_in_labels:
        regime_dates = label_index.index[label_index == regime]
        n_days = len(regime_dates)
        if n_days < fallback_min_n_days:
            # Issue D fallback: regime has too few days on miner panel
            # for a stable IC estimate — fall back to full-period IR
            # but record n_days for the audit trail.
            metrics_per_regime[regime] = CompositeMetrics(
                n_features=full.n_features,
                n_families=full.n_families,
                n_dates=n_days,
                ic_mean=full.ic_mean,
                ic_std=full.ic_std,
                ic_ir=full.ic_ir,  # FALLBACK: full-period
                turnover_proxy=full.turnover_proxy,
                corr_concentration=full.corr_concentration,
                horizon=full.horizon,
                nav_sharpe=full.nav_sharpe,
                nav_max_dd=full.nav_max_dd,
                nav_correlation_vs_anchor_pooled_raw=(
                    full.nav_correlation_vs_anchor_pooled_raw
                ),
                nav_vs_qqq_excess_full_period=(
                    full.nav_vs_qqq_excess_full_period
                ),
            )
            continue
        # Stratified IC: restrict fwd_returns to regime days
        regime_fwd = fwd_returns.reindex(
            fwd_returns.index.intersection(regime_dates)
        )
        regime_metrics = evaluate_composite(
            spec, factor_panel_map, regime_fwd,
            mask=(
                mask.reindex(mask.index.intersection(regime_dates))
                if mask is not None else None
            ),
            horizon=horizon, lag=lag,
            # Don't recompute NAV per regime — use full-period values
            compute_nav=False,
        )
        metrics_per_regime[regime] = CompositeMetrics(
            n_features=regime_metrics.n_features,
            n_families=regime_metrics.n_families,
            n_dates=regime_metrics.n_dates,
            ic_mean=regime_metrics.ic_mean,
            ic_std=regime_metrics.ic_std,
            ic_ir=regime_metrics.ic_ir,
            turnover_proxy=regime_metrics.turnover_proxy,
            corr_concentration=regime_metrics.corr_concentration,
            horizon=regime_metrics.horizon,
            # NAV is full-period (one BacktestEngine run, sliced by
            # regime is out of R6 scope; defer to R7+ if needed)
            nav_sharpe=full.nav_sharpe,
            nav_max_dd=full.nav_max_dd,
            nav_correlation_vs_anchor_pooled_raw=(
                full.nav_correlation_vs_anchor_pooled_raw
            ),
            nav_vs_qqq_excess_full_period=(
                full.nav_vs_qqq_excess_full_period
            ),
        )
    return metrics_per_regime


@dataclass
class TrialResult:
    """Result of a single Optuna trial in the research miner."""
    spec: ResearchCompositeSpec
    metrics: CompositeMetrics
    objective: float


class ResearchMiner:
    """Research Composite Miner v1 (PRD §8).

    Entry class wrapping:
      - Optuna study (maximize direction)
      - family-aware sampler
      - composite build + evaluate
      - weighted-sum objective
      - trial result collection

    v1 scope: in-memory only. R12 adds SQLite archive.
    v1 scope: single-horizon label (cc forward return); v2 can parameterize.
    v1 scope: benchmark_excess defaulted to 0; R13+ can wire benchmark
    portfolio simulation.
    """

    def __init__(
        self,
        factor_panel_map: Mapping[str, pd.DataFrame],
        fwd_returns: pd.DataFrame,
        mask: Optional[pd.DataFrame] = None,
        families: Sequence[FamilyConfig] = FAMILIES_V1,
        objective_weights: Optional[ObjectiveWeights] = None,
        min_families: int = 3,
        max_features_per_family: int = 2,
        weight_step: float = 0.05,
        composite_weighting: str = "tpe_normalized",
        target_n_features: Optional[int] = None,
        horizon: int = 21,
        lag: int = 1,
        archive: Any = None,
        lineage_tag: Optional[str] = None,
        study_id: Optional[str] = None,
        # Track A v1 (PRD 20260429) optional fingerprint fields. None on
        # legacy mining flows; populated by run_research_miner.py when
        # --temporal-split is active. Threaded through to insert_trial.
        split_name: Optional[str] = None,
        split_sha256: Optional[str] = None,
        panel_max_date: Optional[str] = None,
        role: Optional[str] = None,
        max_factor_lookback_days: Optional[int] = None,
        # A++ patch 2026-04-30: factor_registry_pool reachability contract.
        # When non-None, the constructor invokes
        # assert_reachability_matches_pool(factor_registry_pool, families,
        # explicit_exclusions) and fails closed if the sampler cannot
        # reach the named registry pool. Default None preserves
        # legacy / direct-instantiation behavior.
        factor_registry_pool: Optional[str] = None,
        explicit_exclusions: Optional[Sequence[str]] = None,
        # PRD-AC v1.1 §4.3 NAV gate kwargs. Required iff
        # objective_weights.is_nav_based() (any w_nav_* > 0). Default None
        # preserves v1_legacy behavior (no NAV path; cycle04/05 archive
        # replay reproduces).
        price_df: Optional[pd.DataFrame] = None,
        open_df: Optional[pd.DataFrame] = None,
        spy_series: Optional[pd.Series] = None,
        qqq_series: Optional[pd.Series] = None,
        harness_config: Optional[Any] = None,
        # PRD-AC v1.1 §4.5 Phase 3 round 1 search-space kwargs. Default
        # None / (False,) preserves cycle04/05 legacy behavior. Pass an
        # explicit holding_freq_choices list to opt into the search dim.
        holding_freq_choices: Optional[Sequence[str]] = None,
        enable_sr_defer_choices: Sequence[bool] = (False,),
        # Master PRD §4.2 Phase B.2 (R4 ship): per-symbol 60m bar dict for
        # SR defer filter. Required iff enable_sr_defer_choices contains
        # True. Cached on instance and threaded through to evaluate_composite
        # so the harness's filter step has access without re-loading bars
        # per trial.
        intraday_bars_60m: Optional[Dict[str, pd.DataFrame]] = None,
        # Master PRD §4.3 Phase C.1 (R6 wire): daily regime labels for
        # ObjectiveWeightsV3 dispatch. Required iff objective_weights is
        # ObjectiveWeightsV3. Default None preserves v1/v2 behavior.
        daily_regime_labels: Optional[pd.Series] = None,
    ) -> None:
        # A++ patch 2026-04-30: pre-flight assert reachability matches
        # the pre-registered factor_registry_pool. Run before storing
        # state so a failed contract aborts construction cleanly.
        if factor_registry_pool is not None:
            assert_reachability_matches_pool(
                pool_name=factor_registry_pool,
                families=families,
                explicit_exclusions=explicit_exclusions,
            )
        self.factor_registry_pool = factor_registry_pool
        self.explicit_exclusions = (
            tuple(explicit_exclusions) if explicit_exclusions else ()
        )
        self.factor_panel_map = factor_panel_map
        self.fwd_returns = fwd_returns
        self.mask = mask
        self.families = families
        self.objective_weights = objective_weights or ObjectiveWeights()
        self.min_families = min_families
        self.max_features_per_family = max_features_per_family
        self.weight_step = weight_step
        # A+ patch 2026-04-30: honor pre-registered composite_weighting
        # and composite_cardinality (target_n_features). Default values
        # preserve legacy behavior for any existing study.
        if composite_weighting not in ("tpe_normalized", "equal_weight"):
            raise ValueError(
                f"composite_weighting must be 'tpe_normalized' or "
                f"'equal_weight', got {composite_weighting!r}"
            )
        self.composite_weighting = composite_weighting
        if target_n_features is not None:
            if not isinstance(target_n_features, int) or target_n_features < 1:
                raise ValueError(
                    f"target_n_features must be positive int or None, "
                    f"got {target_n_features!r}"
                )
        self.target_n_features = target_n_features
        self.horizon = int(horizon)
        self.lag = int(lag)
        # R12: optional persistence. When archive is provided, each
        # successful run_trial also writes to archive under (study_id,
        # lineage_tag). Both must be set together or not at all.
        if archive is not None and (lineage_tag is None or study_id is None):
            raise ValueError(
                "archive requires both lineage_tag and study_id"
            )
        self.archive = archive
        self.lineage_tag = lineage_tag
        self.study_id = study_id
        # Track A: thread fingerprint to record_study + insert_trial.
        #
        # Codex R25 P1 fix (2026-04-29): the CLI script enforces
        # `--temporal-split` requires `--role`, but direct
        # ``ResearchMiner(... split_name=..., role=None)`` construction
        # would silently bypass the C5 role-remint guard (the guard
        # only runs when both fields are non-None). Reject partial
        # temporal-fingerprint tuples at construction so any non-CLI
        # caller hits the same fail-closed contract.
        _temporal_fields = {
            "split_name": split_name,
            "split_sha256": split_sha256,
            "role": role,
        }
        _set = {k: v for k, v in _temporal_fields.items() if v is not None}
        if _set and len(_set) != len(_temporal_fields):
            missing = sorted(set(_temporal_fields) - set(_set))
            raise ValueError(
                f"ResearchMiner: partial temporal-fingerprint tuple "
                f"{sorted(_set)} provided without {missing}. Pass all of "
                f"split_name + split_sha256 + role together (M6 C1+C2 + "
                f"C5 guard) or none at all (legacy mining). Mixing the "
                f"two would silently bypass the C5 role-remint guard."
            )
        self.split_name = split_name
        self.split_sha256 = split_sha256
        self.panel_max_date = panel_max_date
        self.role = role
        self.max_factor_lookback_days = max_factor_lookback_days
        if archive is not None:
            # PRD-AC v1.1 §4.7: objective_version + 4 new w_nav_* weights
            # are recorded inside the same JSON blob (no schema migration
            # needed at study level). v1_legacy = all w_nav_* default 0;
            # v2_nav_based opts in via at least one non-zero w_nav_*.
            ow = self.objective_weights
            # Master PRD §4.3 C.1 (R6 wire fix 2026-05-08): v3 record_study
            # serializes ObjectiveWeightsV3 fields. v1/v2 path unchanged.
            if isinstance(ow, ObjectiveWeightsV3):
                ow_dict = {
                    "objective_version": "v3_regime_conditional",
                    "w_ir_BULL": ow.w_ir_BULL,
                    "w_ir_RISK_ON": ow.w_ir_RISK_ON,
                    "w_ir_NEUTRAL": ow.w_ir_NEUTRAL,
                    "w_ir_CAUTIOUS": ow.w_ir_CAUTIOUS,
                    "w_ir_RISK_OFF": ow.w_ir_RISK_OFF,
                    "w_ir_CRISIS": ow.w_ir_CRISIS,
                    "w_nav_sharpe_BULL": ow.w_nav_sharpe_BULL,
                    "w_nav_sharpe_BEAR": ow.w_nav_sharpe_BEAR,
                    "w_nav_orthogonality": ow.w_nav_orthogonality,
                    "w_vs_qqq_excess": ow.w_vs_qqq_excess,
                }
            else:
                ow_dict = {
                    "objective_version": (
                        "v2_nav_based" if ow.is_nav_based() else "v1_legacy"
                    ),
                    "w_ir": ow.w_ir,
                    "w_turnover": ow.w_turnover,
                    "w_corr_conc": ow.w_corr_conc,
                    "w_bench_excess": ow.w_bench_excess,
                    "w_regime_stddev": ow.w_regime_stddev,
                    "w_nav_sharpe": ow.w_nav_sharpe,
                    "w_nav_max_dd_penalty": ow.w_nav_max_dd_penalty,
                    "w_nav_orthogonality": ow.w_nav_orthogonality,
                    "w_vs_qqq_excess": ow.w_vs_qqq_excess,
                }
            archive.record_study(
                study_id=study_id,
                lineage_tag=lineage_tag,
                objective_weights=ow_dict,
                split_name=split_name,
                split_sha256=split_sha256,
                role=role,
            )
        # PRD-AC v1.1 §4.3 NAV gate panel storage + anchor pre-build.
        # Validation is fail-closed when any w_nav_* > 0 but a required
        # panel is missing — surfaces miswired callers immediately rather
        # than silently degrading every trial to v1_legacy ranking.
        self.price_df = price_df
        self.open_df = open_df
        self.spy_series = spy_series
        self.qqq_series = qqq_series
        self.harness_config = harness_config
        # Phase 3 round 1 search-space configuration. None / (False,)
        # disables the search dim (legacy 2-dim factor+weights sampling).
        self.holding_freq_choices = (
            list(holding_freq_choices) if holding_freq_choices else None
        )
        self.enable_sr_defer_choices = tuple(enable_sr_defer_choices)
        # Master PRD §4.2 Phase B.2 R4 ship: store 60m bar dict for the
        # SR defer filter step inside evaluate_composite. Validate the
        # contract: if SR defer can be sampled True, intraday_bars_60m
        # MUST be provided (else SR defer would be a no-op for True
        # branches, defeating the search dim).
        if True in tuple(enable_sr_defer_choices) and intraday_bars_60m is None:
            raise ValueError(
                "ResearchMiner: enable_sr_defer_choices contains True "
                "but intraday_bars_60m is None. R4 ship requires the "
                "60m bar dict (e.g. via BarStore.load(sym, freq='60m') "
                "for tradable universe) so the filter can fire. Pass "
                "an explicit dict or remove True from the choices."
            )
        self.intraday_bars_60m = intraday_bars_60m
        # Master PRD §4.3 Phase C.1 R6 wire: daily_regime_labels contract.
        # When objective_weights is ObjectiveWeightsV3, regime labels MUST
        # be supplied (else evaluate_composite_regime_conditional has no
        # input). Default None preserves v1/v2 behavior.
        if isinstance(self.objective_weights, ObjectiveWeightsV3):
            if daily_regime_labels is None:
                raise ValueError(
                    "ResearchMiner: ObjectiveWeightsV3 requires daily_"
                    "regime_labels (e.g. via core.research.taa."
                    "regime_label_generator.daily_regime_labels). Pass "
                    "an explicit Series or use ObjectiveWeights for "
                    "v1/v2 paths."
                )
        self.daily_regime_labels = daily_regime_labels
        self._anchor_residual_returns: Optional[pd.Series] = None
        if self.objective_weights.is_nav_based():
            if price_df is None or spy_series is None:
                raise ValueError(
                    "ResearchMiner: objective_weights.is_nav_based()=True "
                    "requires non-None price_df and spy_series for the "
                    "PRD-AC v1.1 §4.3 NAV gate; got "
                    f"price_df={price_df is not None} "
                    f"spy_series={spy_series is not None}"
                )
            # Build the SPY-residual anchor ONCE at construction. The
            # anchor depends only on the panel + SPY (not per-spec), so
            # caching it here amortizes the OLS β computation across
            # all trials in the study.
            from core.mining.nav_objective import (
                build_universe_baseline_residual_returns,
            )
            self._anchor_residual_returns = build_universe_baseline_residual_returns(
                price_df, spy_series,
            )
        # Cache of trial results for in-memory analysis
        self.results: List[TrialResult] = []

    def run_trial(self, trial: Any) -> float:
        """Optuna-compatible objective function.

        Samples a spec via suggest_composite_spec, evaluates it, stores
        the TrialResult, returns the scalar objective (for Optuna to
        maximize). Raises optuna.TrialPruned when sampler rejects the
        spec (e.g. fewer than min_families) or when M6 C5 governance
        forbids re-minting the same spec under a different role within
        the same temporal split.
        """
        spec = suggest_composite_spec(
            trial,
            families=self.families,
            min_families=self.min_families,
            max_features_per_family=self.max_features_per_family,
            weight_step=self.weight_step,
            composite_weighting=self.composite_weighting,
            target_n_features=self.target_n_features,
            excluded_factors=(
                self.explicit_exclusions if self.explicit_exclusions else None
            ),
            holding_freq_choices=self.holding_freq_choices,
            enable_sr_defer_choices=self.enable_sr_defer_choices,
        )
        # Codex R21 P0.1: enforce M6 C5 role-remint guard BEFORE evaluation.
        # If the same spec was already recorded under a DIFFERENT role within
        # the same split_name, fail closed via TrialPruned (Optuna will
        # advance to the next trial). The guard is a no-op when the
        # temporal-split fingerprint isn't active (legacy mining flows).
        if (
            self.archive is not None
            and self.split_name is not None
            and self.role is not None
        ):
            from core.mining.rcm_archive import compute_spec_id
            from core.research.temporal_split import enforce_c5_no_role_remint

            spec_id = compute_spec_id(spec)
            try:
                enforce_c5_no_role_remint(
                    self.archive,
                    spec_sha256=spec_id,
                    split_name=self.split_name,
                    role=self.role,
                )
            except ValueError as exc:
                import logging
                logging.getLogger(__name__).info(
                    "C5 role-remint guard blocked trial: spec=%s split=%s role=%s; %s",
                    spec_id, self.split_name, self.role, exc,
                )
                try:
                    import optuna
                    raise optuna.TrialPruned(str(exc)) from exc
                except ImportError:
                    raise
        # PRD-AC v1.1 §4.3: route to NAV gate when the objective opts in
        # via any non-zero w_nav_*. v1_legacy path (compute_nav=False) is
        # bit-identical to the pre-PRD-AC behavior.
        nav_active = self.objective_weights.is_nav_based()
        v3_active = isinstance(self.objective_weights, ObjectiveWeightsV3)
        if v3_active:
            # Master PRD §4.3 C.1 (R6 wire): regime-conditional eval path.
            # Returns Dict[regime_name, CompositeMetrics] which compute_
            # objective dispatches via isinstance(weights, V3).
            metrics_per_regime = evaluate_composite_regime_conditional(
                spec,
                self.factor_panel_map,
                self.fwd_returns,
                self.daily_regime_labels,
                mask=self.mask,
                horizon=self.horizon,
                lag=self.lag,
                price_df=self.price_df,
                open_df=self.open_df,
                spy_series=self.spy_series,
                qqq_series=self.qqq_series,
                anchor_residual_returns=self._anchor_residual_returns,
                harness_config=self.harness_config,
                intraday_bars_60m=self.intraday_bars_60m,
            )
            # For TrialResult archive (single-CompositeMetrics schema),
            # use the BEAR-aggregate or first-regime metrics as primary.
            # Pick CRISIS if present (most informative for BEAR alpha);
            # else first regime in dict insertion order.
            primary = (
                metrics_per_regime.get("CRISIS")
                or next(iter(metrics_per_regime.values()))
            )
            objective = compute_objective(
                metrics_per_regime,
                weights=self.objective_weights,
            )
            metrics = primary
        else:
            metrics = evaluate_composite(
                spec,
                self.factor_panel_map,
                self.fwd_returns,
                mask=self.mask,
                horizon=self.horizon,
                lag=self.lag,
                price_df=self.price_df if nav_active else None,
                open_df=self.open_df if nav_active else None,
                spy_series=self.spy_series if nav_active else None,
                qqq_series=self.qqq_series if nav_active else None,
                anchor_residual_returns=(
                    self._anchor_residual_returns if nav_active else None
                ),
                harness_config=self.harness_config if nav_active else None,
                compute_nav=nav_active,
                intraday_bars_60m=(
                    self.intraday_bars_60m if nav_active else None
                ),
            )
            objective = compute_objective(
                metrics,
                benchmark_excess=0.0,
                regime_stddev=0.0,
                weights=self.objective_weights,
            )
        result = TrialResult(spec=spec, metrics=metrics, objective=objective)
        self.results.append(result)
        # R12: persist to archive when configured
        if self.archive is not None:
            try:
                self.archive.insert_trial(
                    result,
                    lineage_tag=self.lineage_tag,
                    study_id=self.study_id,
                    benchmark_excess=0.0,
                    regime_stddev=0.0,
                    split_sha256=self.split_sha256,
                    panel_max_date=self.panel_max_date,
                    role=self.role,
                    max_factor_lookback_days=self.max_factor_lookback_days,
                )
            except Exception as exc:  # noqa: BLE001
                # Persistence is advisory — don't fail the Optuna study
                # because of a DB issue; caller can audit self.results
                import logging
                logging.getLogger(__name__).warning(
                    "archive.insert_trial failed: %s", exc,
                )
        return objective

    def mine(
        self,
        n_trials: int = 50,
        seed: int = 42,
        *,
        sampler: str = "tpe",
        optuna_storage: Optional[str] = None,
        study_name: Optional[str] = None,
        load_if_exists: bool = False,
    ) -> List[TrialResult]:
        """Run an Optuna study for n_trials and return results sorted
        descending by objective.

        Persistence (R12):
          * `optuna_storage`: e.g. "sqlite:///data/mining/rcm_optuna.db" to
            persist the Optuna study (enables resume across processes).
          * `study_name`: required when using optuna_storage; groups trials
            under a named study. When `load_if_exists=True`, reopens an
            existing study of the same name instead of creating a new one.
          * Defaults (None, None, False) → in-memory study, fresh each call.

        Note: `optuna_storage` tracks Optuna's internal trial state
        (for resumption of the sampler). The TrialResult archive
        (rcm_archive.db, set via __init__) is independent.
        """
        try:
            import optuna
        except ImportError:
            raise RuntimeError(
                "optuna required for ResearchMiner.mine; "
                "install with `pip install optuna`"
            )
        # Silence optuna default INFO chatter during tests
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        if sampler.lower() == "tpe":
            sampler_obj = optuna.samplers.TPESampler(seed=seed)
        elif sampler.lower() == "random":
            sampler_obj = optuna.samplers.RandomSampler(seed=seed)
        else:
            raise ValueError(f"sampler must be 'tpe' or 'random', got {sampler!r}")
        create_kwargs = dict(direction="maximize", sampler=sampler_obj)
        if optuna_storage is not None:
            if study_name is None:
                raise ValueError(
                    "study_name required when optuna_storage is set"
                )
            create_kwargs["storage"] = optuna_storage
            create_kwargs["study_name"] = study_name
            create_kwargs["load_if_exists"] = load_if_exists
        study = optuna.create_study(**create_kwargs)
        study.optimize(self.run_trial, n_trials=n_trials, n_jobs=1)
        # Return successful trials only, sorted
        completed = [r for r in self.results if np.isfinite(r.objective)]
        completed.sort(key=lambda r: -r.objective)
        return completed

    def top_k(self, k: int = 10) -> List[TrialResult]:
        """Return top-K trials by objective (descending). Excludes -inf."""
        completed = [r for r in self.results if np.isfinite(r.objective)]
        completed.sort(key=lambda r: -r.objective)
        return completed[:k]
