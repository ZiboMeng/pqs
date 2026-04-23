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
    """Summary metrics for a research composite (PRD §8.4 candidate schema)."""
    n_features: int
    n_families: int
    n_dates: int
    ic_mean: float
    ic_std: float
    ic_ir: float  # ic_mean / ic_std * sqrt(252)
    turnover_proxy: float
    corr_concentration: float

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
        }


def evaluate_composite(
    spec: ResearchCompositeSpec,
    factor_panel_map: Mapping[str, pd.DataFrame],
    fwd_returns: pd.DataFrame,
    mask: Optional[pd.DataFrame] = None,
) -> CompositeMetrics:
    """Evaluate a research composite spec against forward returns.

    Computes per-PRD §8.4:
      - IC (per-date spearman rank-correlation of composite vs fwd_ret)
      - IC mean / std / IR (annualized)
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

    Returns
    -------
    CompositeMetrics dataclass
    """
    composite = build_composite_series(spec, factor_panel_map)
    if mask is not None:
        # Import lazily to avoid circular
        from core.factors.base_masks import apply_research_mask
        composite = apply_research_mask(composite, mask)
    ic_series = _spearman_ic_per_date(composite, fwd_returns)
    ic_mean = float(ic_series.mean()) if len(ic_series) else float("nan")
    ic_std = float(ic_series.std()) if len(ic_series) > 1 else float("nan")
    # Annualized IR
    if ic_std > 0 and pd.notna(ic_std):
        ic_ir = ic_mean / ic_std * np.sqrt(252)
    else:
        ic_ir = float("nan")
    turnover = _turnover_proxy(composite)
    corr_conc = _corr_concentration(spec, factor_panel_map)
    return CompositeMetrics(
        n_features=spec.n_features,
        n_families=spec.n_families,
        n_dates=len(ic_series),
        ic_mean=ic_mean,
        ic_std=ic_std,
        ic_ir=float(ic_ir),
        turnover_proxy=turnover,
        corr_concentration=corr_conc,
    )


# ── R11: Optuna objective + ResearchMiner entry ─────────────────────────────


@dataclass(frozen=True)
class ObjectiveWeights:
    """PRD §8.6 weighted-sum objective weights.

    Default mirrors PRD example; callers can tune via CLI.
    """
    w_ir: float = 1.0               # + weight on OOS IR
    w_turnover: float = 0.5         # − penalty on turnover proxy
    w_corr_conc: float = 1.0        # − penalty on correlation concentration
    w_bench_excess: float = 0.3     # + weight on benchmark excess
    w_regime_stddev: float = 0.2    # − penalty on regime-IC stddev


def compute_objective(
    metrics: CompositeMetrics,
    benchmark_excess: float = 0.0,
    regime_stddev: float = 0.0,
    weights: Optional[ObjectiveWeights] = None,
) -> float:
    """PRD §8.6 weighted-sum objective.

    objective = w_ir * IR
              - w_turnover * turnover_proxy
              - w_corr_conc * corr_concentration
              + w_bench_excess * benchmark_excess
              - w_regime_stddev * regime_stddev

    NaN-safe: any NaN metric contributes 0 (logged at caller as "insufficient
    data"). Returns -inf if IC_IR itself is NaN (no signal).
    """
    w = weights or ObjectiveWeights()
    ir = metrics.ic_ir if np.isfinite(metrics.ic_ir) else float("-inf")
    if ir == float("-inf"):
        return float("-inf")
    turnover = metrics.turnover_proxy if np.isfinite(metrics.turnover_proxy) else 0.0
    corr_c = metrics.corr_concentration if np.isfinite(metrics.corr_concentration) else 0.0
    be = benchmark_excess if np.isfinite(benchmark_excess) else 0.0
    rs = regime_stddev if np.isfinite(regime_stddev) else 0.0
    return (
        w.w_ir * ir
        - w.w_turnover * turnover
        - w.w_corr_conc * corr_c
        + w.w_bench_excess * be
        - w.w_regime_stddev * rs
    )


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
        archive: Any = None,
        lineage_tag: Optional[str] = None,
        study_id: Optional[str] = None,
    ) -> None:
        self.factor_panel_map = factor_panel_map
        self.fwd_returns = fwd_returns
        self.mask = mask
        self.families = families
        self.objective_weights = objective_weights or ObjectiveWeights()
        self.min_families = min_families
        self.max_features_per_family = max_features_per_family
        self.weight_step = weight_step
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
        if archive is not None:
            archive.record_study(
                study_id=study_id,
                lineage_tag=lineage_tag,
                objective_weights={
                    "w_ir": self.objective_weights.w_ir,
                    "w_turnover": self.objective_weights.w_turnover,
                    "w_corr_conc": self.objective_weights.w_corr_conc,
                    "w_bench_excess": self.objective_weights.w_bench_excess,
                    "w_regime_stddev": self.objective_weights.w_regime_stddev,
                },
            )
        # Cache of trial results for in-memory analysis
        self.results: List[TrialResult] = []

    def run_trial(self, trial: Any) -> float:
        """Optuna-compatible objective function.

        Samples a spec via suggest_composite_spec, evaluates it, stores
        the TrialResult, returns the scalar objective (for Optuna to
        maximize). Raises optuna.TrialPruned when sampler rejects the
        spec (e.g. fewer than min_families).
        """
        spec = suggest_composite_spec(
            trial,
            families=self.families,
            min_families=self.min_families,
            max_features_per_family=self.max_features_per_family,
            weight_step=self.weight_step,
        )
        metrics = evaluate_composite(
            spec,
            self.factor_panel_map,
            self.fwd_returns,
            mask=self.mask,
        )
        objective = compute_objective(
            metrics,
            benchmark_excess=0.0,  # v1: simplified; R13 can wire real bench
            regime_stddev=0.0,     # v1: no regime stratification yet
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
        sampler = optuna.samplers.TPESampler(seed=seed)
        create_kwargs = dict(direction="maximize", sampler=sampler)
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
