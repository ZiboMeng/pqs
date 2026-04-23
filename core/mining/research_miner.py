"""Research Composite Miner v1 (PRD 20260424 §8).

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
from typing import Any, FrozenSet, List, Mapping, Sequence, Tuple


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
) -> ResearchCompositeSpec:
    """Family-aware composite sampler (PRD §8.5).

    Protocol (Optuna trial-driven):
      1. For each family, Optuna suggests an integer count 0..max_features
         of features to draw from that family.
      2. If total selected families < min_families, raise optuna.TrialPruned
         (or caller re-draws).
      3. For each selected feature, Optuna suggests a raw weight
         (float 0..1, step=weight_step). Weights are normalized to sum=1.

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
    weight_step      : granularity for raw weight suggestions

    Returns
    -------
    ResearchCompositeSpec

    Raises
    ------
    optuna.TrialPruned if the sampled spec has fewer than min_families.
    """
    # Import optuna lazily so this module is importable without optuna
    # for pure-dataclass tests.
    try:
        import optuna
    except ImportError:
        optuna = None  # sentinel

    selected: List[Tuple[str, str]] = []  # (family_name, factor_name)
    family_counts: dict[str, int] = {}

    for fam in families:
        sorted_factors = sorted(fam.factors)
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

    # Raw weights per selected feature
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

    return ResearchCompositeSpec(
        features=features_tup,
        weights=weights_tup,
        family_counts=dict(family_counts),
    )
