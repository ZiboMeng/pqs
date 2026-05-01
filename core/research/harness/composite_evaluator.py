"""Composite-spec evaluator (per-trial harness, Cycle #02 prep).

PRD: priority-realign Step 1 (`docs/memos/20260430-priority_realign_alpha_first.md` +
`docs/memos/20260430-step0_retro_c1_pivot.md`).

Public API:
  - ``HarnessConfig``: dataclass capturing per-evaluation knobs
    (top_n, rebalance_cadence, lag, horizon).
  - ``EvaluatedComposite``: result dataclass with NAV history,
    weights history, per-validation-year metrics, per-stress-slice
    metrics, concentration metrics, NAV-correlation diagnostics.
  - ``evaluate_composite_spec(spec, ...)``: pure entry point.
  - ``rebalance_mask(index, cadence)``: generate boolean mask of
    rebalance dates given a DatetimeIndex and a cadence
    ('monthly' | 'weekly' | 'daily').
  - ``topn_signals_from_composite(composite, mask, top_n)``:
    cross-section top-N → equal-weight → forward-fill between
    rebalances.

The harness DOES NOT mutate the input frames or modify any global
state (registry, archive). It is suitable for batch-evaluating top-N
mining candidates back-to-back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from core.mining.research_miner import ResearchCompositeSpec, build_composite_series


# ── Cadence helpers ──────────────────────────────────────────────────────────


_VALID_CADENCES = ("monthly", "weekly", "daily")


def rebalance_mask(index: pd.DatetimeIndex, cadence: str) -> pd.Series:
    """Boolean mask of rebalance dates over a DatetimeIndex.

    cadence='monthly': last trading day of each month → True.
    cadence='weekly':  last trading day of each ISO week → True.
    cadence='daily':   every date → True.
    """
    if cadence not in _VALID_CADENCES:
        raise ValueError(
            f"cadence must be one of {_VALID_CADENCES!r}, got {cadence!r}"
        )
    if cadence == "daily":
        return pd.Series(True, index=index)
    if cadence == "monthly":
        periods = index.to_period("M")
    else:  # weekly
        periods = index.to_period("W")
    mask = pd.Series(False, index=index)
    for p in periods.unique():
        period_dates = index[periods == p]
        if len(period_dates) > 0:
            mask.loc[period_dates[-1]] = True
    return mask


# ── Signal construction (composite → top-N equal-weight) ────────────────────


def topn_signals_from_composite(
    composite: pd.DataFrame,
    rebal_mask: pd.Series,
    top_n: int,
    *,
    min_holding_days: int = 1,
) -> pd.DataFrame:
    """At each rebalance date, pick top-N symbols by composite score
    (descending, NaN-aware), equal-weight them, then hold between
    rebalances.

    Returns
    -------
    signals_df : pd.DataFrame
      shape == composite.shape; rows are dates, columns are symbols;
      values are target weights summing to ≤ 1.0 (≤ because some
      rebalances may have fewer than top_n valid scores).

    Notes
    -----
    - NaN composite scores are skipped (cannot rank).
    - When fewer than ``top_n`` valid scores exist on a rebalance
      date, signals carry over from the previous rebalance (less
      churn than equal-weighting only the available subset).
    - ``min_holding_days`` enforces a minimum gap between
      rebalances; if a rebalance fires before ``min_holding_days``
      have elapsed since the last rebalance, signals carry over.
    """
    if top_n < 1:
        raise ValueError(f"top_n must be ≥ 1, got {top_n}")
    if min_holding_days < 1:
        raise ValueError(f"min_holding_days must be ≥ 1, got {min_holding_days}")

    signals = pd.DataFrame(0.0, index=composite.index, columns=composite.columns)
    last_selection = pd.Series(0.0, index=composite.columns)
    days_since_rebal = min_holding_days  # allow first rebalance immediately

    for date in composite.index:
        days_since_rebal += 1
        is_rebal_day = bool(rebal_mask.get(date, False))
        if not is_rebal_day or days_since_rebal < min_holding_days:
            signals.loc[date] = last_selection.values
            continue
        scores = composite.loc[date].dropna()
        if len(scores) < top_n:
            signals.loc[date] = last_selection.values
            continue
        top = scores.nlargest(top_n)
        new_selection = pd.Series(0.0, index=composite.columns)
        new_selection.loc[top.index] = 1.0 / top_n
        last_selection = new_selection
        signals.loc[date] = last_selection.values
        days_since_rebal = 0
    return signals


def topn_signals_with_caps(
    composite: pd.DataFrame,
    rebal_mask: pd.Series,
    *,
    target_n_picks: int,
    cluster_map: Dict[str, str],
    cluster_cap: float,
    max_single_weight: float,
    min_holding_days: int = 1,
    asset_class_map: Optional[Dict[str, str]] = None,
    asset_class_caps: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Cap-aware selection: greedy by composite score with cluster + single-name caps.

    Optional second-layer asset_class caps (cycle #04 cross-asset preflight):
    if both ``asset_class_map`` and ``asset_class_caps`` are provided, each
    candidate is also rejected if adding it would push its asset_class total
    weight past the corresponding cap. Asset_class caps trigger BEFORE
    cluster caps (asset_class is the broader bucket; failing asset_class
    means failing cluster automatically). When omitted (cycle #03 default
    behavior), no asset_class layer is enforced.

    At each rebalance date:
      1. Score row restricted to symbols in ``cluster_map`` (ETFs and
         unmapped symbols silently skipped — they do NOT participate in
         selection).
      2. Sort eligible symbols by composite score descending.
      3. Walk top-down. For each candidate symbol:
         - reject if adding it would push its cluster's total weight
           past ``cluster_cap``;
         - reject if its asset_class total weight would exceed
           ``asset_class_caps[asset_class]`` (only when both
           ``asset_class_map`` and ``asset_class_caps`` provided);
         - reject if individual weight (= 1/target_n_picks at this stage)
           exceeds ``max_single_weight``.
      4. Stop once ``target_n_picks`` accepted, or eligible exhausted.
      5. Equal-weight all accepted picks at 1/target_n_picks. The
         portfolio may NOT reach 100% invested if cluster caps bind
         tightly — remaining weight is implicit cash.
      6. Forward-fill between rebalances (same as topn_signals_from_composite).

    Why this exists (cycle #03 path memo, 2026-05-01):
    Cycles #01 + #02 confirmed that global top-N selection always picks
    the same {β + 12-1 mom + volume} winners (NVDA/AAPL/MSFT/AVGO).
    Risk-cluster cap forces structural diversification: each cluster
    contributes ≤ cluster_cap × portfolio. With cluster_cap=0.20 and
    target_n_picks=10, max 2 picks per cluster → 10 picks span ≥ 5
    clusters → cannot collapse to "all 10 are AI-capex bets".

    Parameters
    ----------
    composite          : DataFrame (date × symbol) of composite scores
    rebal_mask         : Series (date → bool) of rebalance flags
    target_n_picks     : target number of names held (e.g. 10)
    cluster_map        : dict[symbol → cluster_string]; ETFs and
                         unknown symbols (None or missing) are
                         excluded from selection
    cluster_cap        : maximum portfolio weight a single cluster
                         can hold (e.g. 0.20 = 20%)
    max_single_weight  : maximum portfolio weight a single name can
                         hold (e.g. 0.10 = 10%)
    min_holding_days   : minimum trading days between rebalances

    Returns
    -------
    signals_df : DataFrame (date × symbol). Weights sum to ≤ 1.0
                 (less when cluster caps bind tightly → implicit cash).
    """
    if target_n_picks < 1:
        raise ValueError(f"target_n_picks must be ≥ 1, got {target_n_picks}")
    if not (0 < cluster_cap <= 1.0):
        raise ValueError(
            f"cluster_cap must be in (0, 1], got {cluster_cap}"
        )
    if not (0 < max_single_weight <= 1.0):
        raise ValueError(
            f"max_single_weight must be in (0, 1], got {max_single_weight}"
        )
    if min_holding_days < 1:
        raise ValueError(f"min_holding_days must be ≥ 1, got {min_holding_days}")

    weight_per_pick = 1.0 / target_n_picks
    if weight_per_pick > max_single_weight + 1e-12:
        raise ValueError(
            f"weight_per_pick (1/{target_n_picks}={weight_per_pick:.4f}) "
            f"exceeds max_single_weight={max_single_weight}; either "
            f"increase target_n_picks or relax max_single_weight"
        )

    # Asset-class caps: optional second-layer constraint. Both map +
    # caps must be provided (or both omitted). Validate consistency.
    use_asset_class_caps = (
        asset_class_map is not None and asset_class_caps is not None
    )
    if (asset_class_map is None) != (asset_class_caps is None):
        raise ValueError(
            "asset_class_map and asset_class_caps must be provided together "
            "or both omitted; got map="
            f"{asset_class_map is not None} caps={asset_class_caps is not None}"
        )
    if use_asset_class_caps:
        for ac, cap in asset_class_caps.items():
            if not (0 < cap <= 1.0):
                raise ValueError(
                    f"asset_class_caps[{ac!r}]={cap} must be in (0, 1]"
                )
        # Every cluster_map symbol's asset_class must be representable.
        # We only need asset_class for symbols in cluster_map (the
        # eligible universe); missing entries fail-closed at selection
        # time below.

    eligible_cols = [c for c in composite.columns if c in cluster_map]
    if not eligible_cols:
        raise ValueError(
            "No composite columns are in cluster_map; cannot apply "
            "cap-aware selection. Did you pass STOCK_RISK_CLUSTER_MAP?"
        )

    signals = pd.DataFrame(0.0, index=composite.index, columns=composite.columns)
    last_selection = pd.Series(0.0, index=composite.columns)
    days_since_rebal = min_holding_days

    # Float-tolerant cap check: cluster_used + weight_per_pick ≤ cluster_cap.
    # Add a tiny epsilon to absorb 1e-15 fp drift from repeated additions.
    _eps = 1e-9

    for date in composite.index:
        days_since_rebal += 1
        is_rebal_day = bool(rebal_mask.get(date, False))
        if not is_rebal_day or days_since_rebal < min_holding_days:
            signals.loc[date] = last_selection.values
            continue

        scores = composite.loc[date, eligible_cols].dropna()
        if scores.empty:
            signals.loc[date] = last_selection.values
            continue

        sorted_idx = scores.sort_values(ascending=False).index
        picks: List[str] = []
        cluster_used: Dict[str, float] = {}
        ac_used: Dict[str, float] = {}  # asset_class → cumulative weight

        for sym in sorted_idx:
            if len(picks) >= target_n_picks:
                break
            clu = cluster_map[sym]
            # Asset-class layer (broader bucket; check first).
            if use_asset_class_caps:
                if sym not in asset_class_map:
                    # Fail-closed: cluster_map says sym is eligible but
                    # asset_class_map doesn't classify it. Skip to avoid
                    # silently violating the asset-class cap.
                    continue
                ac = asset_class_map[sym]
                if ac not in asset_class_caps:
                    # Asset class declared on sym but no cap → fail-closed
                    continue
                if ac_used.get(ac, 0.0) + weight_per_pick > asset_class_caps[ac] + _eps:
                    continue
            # Cluster layer.
            if cluster_used.get(clu, 0.0) + weight_per_pick > cluster_cap + _eps:
                continue
            picks.append(sym)
            cluster_used[clu] = cluster_used.get(clu, 0.0) + weight_per_pick
            if use_asset_class_caps:
                ac = asset_class_map[sym]
                ac_used[ac] = ac_used.get(ac, 0.0) + weight_per_pick

        if not picks:
            signals.loc[date] = last_selection.values
            continue

        new_selection = pd.Series(0.0, index=composite.columns)
        new_selection.loc[picks] = weight_per_pick
        last_selection = new_selection
        signals.loc[date] = last_selection.values
        days_since_rebal = 0
    return signals


# ── Metrics extraction helpers ──────────────────────────────────────────────


def _annualized_sharpe(daily_returns: pd.Series, periods_per_year: int = 252) -> float:
    """Annualized Sharpe; zero-mean / zero-std-aware (returns 0.0 for
    degenerate series rather than NaN/inf)."""
    if len(daily_returns) < 2:
        return 0.0
    sd = float(daily_returns.std())
    if not np.isfinite(sd) or sd < 1e-12:
        return 0.0
    return float(daily_returns.mean() / sd * np.sqrt(periods_per_year))


def _max_drawdown(nav: pd.Series) -> float:
    """Max drawdown of a NAV series (returned as a negative number)."""
    if len(nav) == 0:
        return 0.0
    peak = nav.cummax()
    dd = (nav - peak) / peak
    return float(dd.min())


def _ols_beta(y: pd.Series, x: pd.Series) -> float:
    """OLS slope of y on x; defensive against degenerate input."""
    df = pd.DataFrame({"y": y, "x": x}).dropna()
    if len(df) < 5:
        return float("nan")
    var = df["x"].var()
    if not np.isfinite(var) or var < 1e-12:
        return float("nan")
    cov = df.cov().loc["y", "x"]
    return float(cov / var)


def _residual_correlation(y: pd.Series, bench: pd.Series) -> float:
    """Pearson correlation of (y - β_y_bench × bench) vs bench's
    residual against itself = 0; here we compute correlation of
    y's residual against bench. That's structurally 0 — instead
    we want corr(y_residual, bench_residual_vs_X) for some X.

    This helper is RESERVED. Caller should use _residual_pair_corr
    below for two-NAV comparisons."""
    raise NotImplementedError(
        "use _residual_pair_corr(a, b, bench) for residual correlation "
        "between two NAV series after stripping shared bench beta"
    )


def _residual_pair_corr(a: pd.Series, b: pd.Series, bench: pd.Series) -> float:
    """Pearson correlation of (a − β_a × bench) vs (b − β_b × bench).
    Returns NaN if either residual series is degenerate."""
    df = pd.DataFrame({"a": a, "b": b, "bench": bench}).dropna()
    if len(df) < 5:
        return float("nan")
    bench_var = df["bench"].var()
    if not np.isfinite(bench_var) or bench_var < 1e-12:
        return float("nan")
    beta_a = df.cov().loc["a", "bench"] / bench_var
    beta_b = df.cov().loc["b", "bench"] / bench_var
    res_a = df["a"] - beta_a * df["bench"]
    res_b = df["b"] - beta_b * df["bench"]
    if res_a.std() < 1e-12 or res_b.std() < 1e-12:
        return float("nan")
    return float(res_a.corr(res_b))


# ── Configuration + Result dataclasses ──────────────────────────────────────


_VALID_CONSTRUCTION_MODES = ("global_top_n", "cap_aware", "cap_aware_cross_asset")


@dataclass(frozen=True)
class HarnessConfig:
    """Per-evaluation knobs for the harness.

    construction_mode:
      - 'global_top_n' (default): cycle #01+#02 path. Pick top_n
        symbols by composite score, equal-weight. No structural diversity.
      - 'cap_aware': cycle #03+ path. Greedy by composite score with
        cluster_cap + max_single_weight binding. Forces ≥ ceil(1 /
        cluster_cap) clusters to contribute. Requires cluster_map.
      - 'cap_aware_cross_asset': cycle #04+ path. Same as 'cap_aware'
        plus a second-layer asset_class_caps constraint binding bonds /
        commodities / cash_anchor / equities exposure. Requires both
        cluster_map AND asset_class_map AND asset_class_caps. Used with
        ``make_unified_cluster_map(include_cross_asset=True)`` and
        ``ASSET_CLASS_BY_CLUSTER`` from ``core.research.risk_cluster_map``.

    rebalance_cadence: one of 'monthly' | 'weekly' | 'daily'.
    top_n: under 'global_top_n' mode = picks held; under 'cap_aware*'
      = target_n_picks (greedy stops at this many).
    cluster_map: REQUIRED when construction_mode in {'cap_aware',
      'cap_aware_cross_asset'}.
    cluster_cap: max portfolio weight per cluster (e.g. 0.20 = 20%).
      Only used in cap_aware* modes.
    max_single_weight: max portfolio weight per name (e.g. 0.10).
      Only used in cap_aware* modes.
    asset_class_map: REQUIRED when construction_mode='cap_aware_cross_asset'.
      Maps each symbol → asset_class string (one of 'equities' | 'bonds' |
      'commodities' | 'cash_anchor'). Build via
      ``{sym: get_asset_class(sym) for sym in cluster_map}``.
    asset_class_caps: REQUIRED when construction_mode='cap_aware_cross_asset'.
      Maps asset_class string → max portfolio weight cap. Cycle #04 default
      from preflight: equities=0.70, bonds=0.40, commodities=0.20,
      cash_anchor=0.30.
    min_holding_days: min trading days between rebalances.
    horizon_days: mining forward-return horizon (NOT used by harness;
      recorded for evidence pack).
    initial_capital: starting NAV.
    rebalance_threshold: passed to BacktestEngine.
    integer_shares: integer-share execution flag.
    """
    rebalance_cadence: str = "monthly"
    construction_mode: str = "global_top_n"
    top_n: int = 10
    cluster_map: Optional[Dict[str, str]] = None
    cluster_cap: float = 0.20
    max_single_weight: float = 0.10
    asset_class_map: Optional[Dict[str, str]] = None
    asset_class_caps: Optional[Dict[str, float]] = None
    min_holding_days: int = 1
    horizon_days: int = 21
    initial_capital: float = 100_000.0
    rebalance_threshold: float = 0.02
    integer_shares: bool = False

    def __post_init__(self) -> None:
        if self.rebalance_cadence not in _VALID_CADENCES:
            raise ValueError(
                f"rebalance_cadence must be one of {_VALID_CADENCES!r}, "
                f"got {self.rebalance_cadence!r}"
            )
        if self.construction_mode not in _VALID_CONSTRUCTION_MODES:
            raise ValueError(
                f"construction_mode must be one of "
                f"{_VALID_CONSTRUCTION_MODES!r}, got {self.construction_mode!r}"
            )
        if self.top_n < 1:
            raise ValueError(f"top_n must be ≥ 1, got {self.top_n}")
        if not (0 < self.cluster_cap <= 1.0):
            raise ValueError(f"cluster_cap must be in (0, 1], got {self.cluster_cap}")
        if not (0 < self.max_single_weight <= 1.0):
            raise ValueError(
                f"max_single_weight must be in (0, 1], got {self.max_single_weight}"
            )
        if self.min_holding_days < 1:
            raise ValueError(f"min_holding_days must be ≥ 1, got {self.min_holding_days}")
        if self.horizon_days < 1:
            raise ValueError(f"horizon_days must be ≥ 1, got {self.horizon_days}")
        if self.initial_capital <= 0:
            raise ValueError(f"initial_capital must be > 0, got {self.initial_capital}")
        if (
            self.construction_mode in ("cap_aware", "cap_aware_cross_asset")
            and self.cluster_map is None
        ):
            raise ValueError(
                f"construction_mode={self.construction_mode!r} requires "
                f"cluster_map (pass core.research.risk_cluster_map."
                f"STOCK_RISK_CLUSTER_MAP for cap_aware, or "
                f"make_unified_cluster_map(include_cross_asset=True) for "
                f"cap_aware_cross_asset)"
            )
        if self.construction_mode == "cap_aware_cross_asset":
            if self.asset_class_map is None or self.asset_class_caps is None:
                raise ValueError(
                    "construction_mode='cap_aware_cross_asset' requires "
                    "BOTH asset_class_map and asset_class_caps; got "
                    f"map={self.asset_class_map is not None} "
                    f"caps={self.asset_class_caps is not None}"
                )
            valid_classes = {"equities", "bonds", "commodities", "cash_anchor"}
            unknown = set(self.asset_class_caps.keys()) - valid_classes
            if unknown:
                raise ValueError(
                    f"asset_class_caps has unknown classes: {unknown}; "
                    f"valid: {valid_classes}"
                )
        # weight_per_pick floor check (catches "target_n_picks=5,
        # max_single_weight=0.10" → 0.20 > 0.10 invalid)
        if self.construction_mode in ("cap_aware", "cap_aware_cross_asset"):
            wpp = 1.0 / self.top_n
            if wpp > self.max_single_weight + 1e-12:
                raise ValueError(
                    f"weight_per_pick (1/{self.top_n}={wpp:.4f}) exceeds "
                    f"max_single_weight={self.max_single_weight}; either "
                    f"raise top_n or relax max_single_weight"
                )


@dataclass
class EvaluatedComposite:
    """Result of evaluating a composite spec via the harness.

    nav: pd.Series indexed by trading date; daily portfolio NAV.
    weights: pd.DataFrame indexed by date × symbol; daily target weights.
    daily_returns: pd.Series of daily portfolio returns (NAV.pct_change).
    metrics_full_period: dict with cum_ret, sharpe, max_dd, vs_spy,
      vs_qqq computed over the full backtest window.
    metrics_per_validation_year: dict[year:int → metrics dict].
    metrics_per_stress_slice: dict[slice_name:str → metrics dict].
    concentration: dict (top1_max, top3_max, n_dates_with_weights).
    nav_correlation_vs_benchmark: dict with raw + residual Pearson
      correlations vs SPY and QQQ.
    config: echo of HarnessConfig used for this evaluation.
    spec: echo of ResearchCompositeSpec evaluated.
    n_observed_days: number of days in the backtest window.
    """
    nav: pd.Series
    weights: pd.DataFrame
    daily_returns: pd.Series
    metrics_full_period: Dict[str, float] = field(default_factory=dict)
    metrics_per_validation_year: Dict[int, Dict[str, float]] = field(default_factory=dict)
    metrics_per_stress_slice: Dict[str, Dict[str, float]] = field(default_factory=dict)
    concentration: Dict[str, Any] = field(default_factory=dict)
    nav_correlation_vs_benchmark: Dict[str, float] = field(default_factory=dict)
    config: Optional[HarnessConfig] = None
    spec: Optional[ResearchCompositeSpec] = None
    n_observed_days: int = 0


# ── Main entry point ─────────────────────────────────────────────────────────


def evaluate_composite_spec(
    spec: ResearchCompositeSpec,
    *,
    factor_panel_map: Mapping[str, pd.DataFrame],
    price_df: pd.DataFrame,
    open_df: Optional[pd.DataFrame] = None,
    spy_series: Optional[pd.Series] = None,
    qqq_series: Optional[pd.Series] = None,
    cost_model: Optional[Any] = None,
    config: Optional[HarnessConfig] = None,
    validation_years: Optional[List[int]] = None,
    stress_slices: Optional[Dict[str, tuple[str, str]]] = None,
    research_mask: Optional[pd.DataFrame] = None,
) -> EvaluatedComposite:
    """Evaluate a research composite spec end-to-end.

    Parameters
    ----------
    spec : ResearchCompositeSpec
      Output of the research miner. ``spec.features`` and
      ``spec.weights`` define the composite. ``factor_panel_map`` must
      contain a panel for every feature in ``spec.features``.
    factor_panel_map : Mapping[str, pd.DataFrame]
      Pre-built factor panels (the same object the miner consumes).
      Each panel is indexed by date × symbol.
    price_df : pd.DataFrame
      Adjusted close panel (date × symbol). Must contain all symbols
      that any factor panel covers (the harness intersects).
    open_df : pd.DataFrame, optional
      Adjusted open panel; required for T+1-open execution semantics
      in the backtest. If None, BacktestEngine falls back to
      same-day close (warned by the engine).
    spy_series, qqq_series : pd.Series, optional
      SPY / QQQ benchmark close series for vs-benchmark metrics +
      NAV correlation diagnostics. None disables those metrics.
    cost_model : CostModel, optional
      Cost model for the BacktestEngine. If None, uses default config
      from config/cost_model.yaml.
    config : HarnessConfig, optional
      Per-evaluation knobs. None → defaults (monthly / top-10 / etc.).
    validation_years : list[int], optional
      Years for per-year metrics breakdown. None → no per-year split.
    stress_slices : dict[str, (start_date, end_date)], optional
      Named ranges for per-slice metrics (e.g.
      ``{"covid_flash": ("2020-02-19", "2020-03-23"), ...}``).

    Returns
    -------
    EvaluatedComposite
    """
    cfg = config or HarnessConfig()

    # 1) Build composite series from spec
    composite = build_composite_series(spec, factor_panel_map)
    if composite.empty:
        raise ValueError("composite series is empty; check spec features and panel map")

    # Apply research_mask if provided. This matches the paper-candidate
    # code path (`scripts/run_paper_candidate.py::_compute_composite_signal`)
    # which masks the composite AFTER weighted-zscore aggregation but
    # BEFORE top-N selection. Without this, harness-vs-paper composite
    # signals diverge on dates+symbols where research_mask=False (e.g.,
    # thin-data or low-volume cells).
    if research_mask is not None:
        from core.factors.base_masks import apply_research_mask
        composite = apply_research_mask(composite, research_mask)

    # 2) Construct rebalance mask + signals (selector by mode)
    mask = rebalance_mask(composite.index, cadence=cfg.rebalance_cadence)
    if cfg.construction_mode == "cap_aware":
        signals = topn_signals_with_caps(
            composite, mask,
            target_n_picks=cfg.top_n,
            cluster_map=cfg.cluster_map,
            cluster_cap=cfg.cluster_cap,
            max_single_weight=cfg.max_single_weight,
            min_holding_days=cfg.min_holding_days,
        )
    elif cfg.construction_mode == "cap_aware_cross_asset":
        signals = topn_signals_with_caps(
            composite, mask,
            target_n_picks=cfg.top_n,
            cluster_map=cfg.cluster_map,
            cluster_cap=cfg.cluster_cap,
            max_single_weight=cfg.max_single_weight,
            min_holding_days=cfg.min_holding_days,
            asset_class_map=cfg.asset_class_map,
            asset_class_caps=cfg.asset_class_caps,
        )
    else:  # global_top_n (default; cycle #01+#02 path)
        signals = topn_signals_from_composite(
            composite, mask,
            top_n=cfg.top_n,
            min_holding_days=cfg.min_holding_days,
        )

    # 3) Run BacktestEngine
    if cost_model is None:
        from core.config.loader import load_config
        from core.execution.cost_model import CostModel
        cfg_full = load_config()
        cost_model = CostModel(cfg_full.cost_model)

    from core.backtest.backtest_engine import BacktestEngine
    engine = BacktestEngine(
        cost_model=cost_model,
        initial_capital=cfg.initial_capital,
        rebalance_threshold=cfg.rebalance_threshold,
        integer_shares=cfg.integer_shares,
    )

    # Align price_df / open_df to signals' columns + dates
    common_syms = [s for s in signals.columns if s in price_df.columns]
    if not common_syms:
        raise ValueError("no overlap between signals columns and price_df columns")
    sig = signals[common_syms]
    px = price_df[common_syms].reindex(sig.index)
    op = open_df[common_syms].reindex(sig.index) if open_df is not None else None

    bt_result = engine.run(signals_df=sig, price_df=px, open_df=op,
                           benchmark_series=spy_series)

    # 4) NAV + daily-return series
    nav = bt_result.equity_curve.copy()
    nav.name = "nav"
    daily_ret = nav.pct_change().fillna(0.0)
    daily_ret.name = "daily_ret"

    # 5) Metrics
    full = _compute_window_metrics(nav, daily_ret, spy_series, qqq_series)

    per_year: Dict[int, Dict[str, float]] = {}
    if validation_years:
        for y in validation_years:
            year_start = pd.Timestamp(f"{y}-01-01")
            year_end = pd.Timestamp(f"{y}-12-31")
            slc_nav = nav.loc[(nav.index >= year_start) & (nav.index <= year_end)]
            if len(slc_nav) < 2:
                continue
            slc_ret = slc_nav.pct_change().fillna(0.0)
            per_year[y] = _compute_window_metrics(
                slc_nav, slc_ret, spy_series, qqq_series,
            )

    per_slice: Dict[str, Dict[str, float]] = {}
    if stress_slices:
        for slc_name, (s_start, s_end) in stress_slices.items():
            sw = pd.Timestamp(s_start)
            ew = pd.Timestamp(s_end)
            slc_nav = nav.loc[(nav.index >= sw) & (nav.index <= ew)]
            if len(slc_nav) < 2:
                continue
            slc_ret = slc_nav.pct_change().fillna(0.0)
            per_slice[slc_name] = _compute_window_metrics(
                slc_nav, slc_ret, spy_series, qqq_series,
            )

    # 6) Concentration metrics
    from core.backtest.concentration_metrics import compute_concentration_metrics
    concentration = compute_concentration_metrics(bt_result.weights)

    # 7) NAV correlation diagnostics
    nav_corr = {}
    if spy_series is not None:
        spy_ret = spy_series.pct_change().reindex(daily_ret.index).dropna()
        d = daily_ret.reindex(spy_ret.index).dropna()
        if len(d) >= 5:
            nav_corr["raw_pearson_vs_spy"] = float(d.corr(spy_ret))
            nav_corr["beta_vs_spy"] = _ols_beta(d, spy_ret)
    if qqq_series is not None:
        qqq_ret = qqq_series.pct_change().reindex(daily_ret.index).dropna()
        d = daily_ret.reindex(qqq_ret.index).dropna()
        if len(d) >= 5:
            nav_corr["raw_pearson_vs_qqq"] = float(d.corr(qqq_ret))
            nav_corr["beta_vs_qqq"] = _ols_beta(d, qqq_ret)

    return EvaluatedComposite(
        nav=nav,
        weights=bt_result.weights,
        daily_returns=daily_ret,
        metrics_full_period=full,
        metrics_per_validation_year=per_year,
        metrics_per_stress_slice=per_slice,
        concentration=concentration,
        nav_correlation_vs_benchmark=nav_corr,
        config=cfg,
        spec=spec,
        n_observed_days=int(len(nav)),
    )


def _compute_window_metrics(
    nav: pd.Series,
    daily_ret: pd.Series,
    spy: Optional[pd.Series],
    qqq: Optional[pd.Series],
) -> Dict[str, float]:
    """Per-window metrics dict: cum_ret, sharpe, max_dd, vs_spy, vs_qqq."""
    if len(nav) < 2:
        return {}
    cum_ret = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    sharpe = _annualized_sharpe(daily_ret)
    max_dd = _max_drawdown(nav)
    out = {"cum_ret": cum_ret, "sharpe": sharpe, "max_dd": max_dd}
    if spy is not None:
        spy_window = spy.reindex(nav.index).dropna()
        if len(spy_window) >= 2:
            spy_cum = float(spy_window.iloc[-1] / spy_window.iloc[0] - 1.0)
            out["vs_spy"] = cum_ret - spy_cum
            out["spy_cum_ret"] = spy_cum
    if qqq is not None:
        qqq_window = qqq.reindex(nav.index).dropna()
        if len(qqq_window) >= 2:
            qqq_cum = float(qqq_window.iloc[-1] / qqq_window.iloc[0] - 1.0)
            out["vs_qqq"] = cum_ret - qqq_cum
            out["qqq_cum_ret"] = qqq_cum
    return out
