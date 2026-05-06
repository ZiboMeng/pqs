"""PRD-AC v1.1 NAV-objective helpers (Phase 2 §4.6 anchor + I20 detector).

Module purpose: keep mining-internal NAV-objective math out of
`research_miner.py` to avoid bloat. This file owns:

  - `build_universe_baseline_residual_returns`: SPY-β-stripped residual
    return series of a universe-equal-weight baseline portfolio.
    Per PRD §4.6 Option β, the orthogonality anchor isolates *alpha
    overlap* (residuals) from the structural shared-SPY-beta floor
    that any long-only top-N spec on this universe inevitably carries.
  - `compute_spec_residual_pooled_raw_correlation`: Pearson correlation
    of (spec_residual_returns) vs (anchor_residual_returns), where the
    SPY-β strip is recomputed per-spec via train-only OLS (PRD §4.6
    I19 fix: full-period OLS, not rolling).
  - `classify_cross_asset_spec`: I20 detector — true iff the realized
    portfolio's time-averaged non-equity weight exceeds the cutoff
    (default 30% per PRD §4.6 I20). Cross-asset specs skip the
    orthogonality term because SPY-residual assumes spec-vs-SPY beta
    is meaningful; cross-asset spec β is ~0.3-0.5 and residual is
    largely cross-asset alpha unrelated to the SPY-bound long-only
    floor.

PRD §9 OOS: callers MUST pass train-only return series (computed from
panel restricted via `partition_for_role(role="miner")`). Anchor and
β values bake the train-period semantics; using full-panel returns
would leak validation/sealed information into the mining objective.

Out of scope:
  - Option γ fallback (skip orthogonality): just don't compute the
    anchor and pass `nav_correlation_vs_anchor_pooled_raw=NaN` to
    `compute_objective`; the NaN-safe path returns 0 contribution.
  - Anchor calibration smoke (Phase 4 §4.6): a separate dev script
    sweeps λ_orthogonality {0, 0.5, 1, 2}; this file owns only the
    primitive computations.
"""

from __future__ import annotations

from typing import Mapping, Optional

import numpy as np
import pandas as pd

from core.research.harness.composite_evaluator import _ols_beta
from core.research.risk_cluster_map import get_asset_class


# ── Anchor builder ──────────────────────────────────────────────────────────


def build_universe_baseline_residual_returns(
    price_df: pd.DataFrame,
    spy_series: pd.Series,
    *,
    min_obs: int = 30,
) -> pd.Series:
    """Build the SPY-β-stripped residual return series of a
    universe-equal-weight baseline portfolio (PRD §4.6 Option β anchor).

    Algorithm:
      1) compute per-symbol daily returns from ``price_df`` (skip leading NaN)
      2) baseline_returns = mean across symbols on each day (cross-sectional
         equal-weight; days with no data → NaN, dropped)
      3) β_baseline = OLS(baseline_returns, spy_returns) over the joint
         non-null window
      4) return baseline_residual = baseline_returns - β_baseline * spy_returns

    Caller responsibility: pass ``price_df`` restricted to the train-only
    panel (per ``partition_for_role(role='miner')``); the resulting
    residual is the anchor against which spec residuals will be compared
    via ``compute_spec_residual_pooled_raw_correlation``.

    Parameters
    ----------
    price_df : pd.DataFrame
        Adjusted close panel (date × symbol) restricted to train years.
    spy_series : pd.Series
        SPY adjusted close series covering at least the train window.
    min_obs : int
        Minimum joint non-null overlap; below this returns an all-NaN
        Series (anchor unusable; caller falls back to Option γ).

    Returns
    -------
    pd.Series
        Daily residual return series indexed by trading day. Returns
        an empty Series if input is degenerate.
    """
    if price_df.empty or spy_series.empty:
        return pd.Series(dtype="float64", name="universe_baseline_residual")
    sym_returns = price_df.pct_change()
    # Cross-sectional equal-weight average return (NaN-safe via skipna)
    baseline_ret = sym_returns.mean(axis=1, skipna=True)
    spy_ret = spy_series.pct_change()
    df = pd.DataFrame({"y": baseline_ret, "x": spy_ret}).dropna()
    if len(df) < min_obs:
        return pd.Series(
            np.nan, index=df.index, name="universe_baseline_residual",
        )
    beta = _ols_beta(df["y"], df["x"])
    if not np.isfinite(beta):
        return pd.Series(
            np.nan, index=df.index, name="universe_baseline_residual",
        )
    residual = df["y"] - beta * df["x"]
    residual.name = "universe_baseline_residual"
    return residual


def compute_spec_residual_pooled_raw_correlation(
    spec_daily_returns: pd.Series,
    anchor_residual_returns: pd.Series,
    spy_series: pd.Series,
    *,
    min_obs: int = 30,
) -> float:
    """Pearson correlation of spec residual returns vs anchor residual
    returns, after stripping each spec's own SPY beta (PRD §4.6 I19
    full-period OLS).

    Returns NaN if either residual series is degenerate (insufficient
    overlap, zero variance, or non-finite β). The downstream objective
    treats NaN as 0-contribution (no orthogonality penalty), which is
    the desired behavior for Option γ fallback specs.

    Parameters
    ----------
    spec_daily_returns : pd.Series
        Spec NAV's daily return series (indexed by trading day).
    anchor_residual_returns : pd.Series
        Output of ``build_universe_baseline_residual_returns`` — the
        baseline portfolio's residual returns over the same window.
    spy_series : pd.Series
        SPY close series; used to compute spec_β via train-only OLS.
    min_obs : int
        Minimum joint non-null overlap; below this returns NaN.

    Returns
    -------
    float
        Pearson correlation in [-1, 1], or NaN if degenerate.
    """
    if (
        spec_daily_returns.empty
        or anchor_residual_returns.empty
        or spy_series.empty
    ):
        return float("nan")
    spy_ret = spy_series.pct_change()
    df = pd.DataFrame({
        "spec": spec_daily_returns,
        "anchor": anchor_residual_returns,
        "spy": spy_ret,
    }).dropna()
    if len(df) < min_obs:
        return float("nan")
    spy_var = float(df["spy"].var())
    if not np.isfinite(spy_var) or spy_var < 1e-12:
        return float("nan")
    beta_spec = float(df.cov().loc["spec", "spy"] / spy_var)
    if not np.isfinite(beta_spec):
        return float("nan")
    spec_res = df["spec"] - beta_spec * df["spy"]
    if spec_res.std() < 1e-12 or df["anchor"].std() < 1e-12:
        return float("nan")
    return float(spec_res.corr(df["anchor"]))


# ── Train-boundary gap-return masking (PRD §6 Phase 2 I9 fix) ──────────────


def mask_train_boundary_returns(
    daily_returns: pd.Series,
    *,
    gap_threshold_days: int = 30,
) -> pd.Series:
    """Zero out daily returns at year-boundary days where the prior trading
    day is more than ``gap_threshold_days`` calendar days earlier.

    Why: ``partition_for_role(role='miner')`` returns a non-contiguous
    train-only panel (e.g. ``alternating_regime_holdout_v1`` train years
    = 2009-2017+2020/2022/2024 with validation gaps). The harness
    BacktestEngine carries forward EOD positions across the gap, then
    on the first day of the next train segment computes
    ``pct_change`` between adjacent index dates — which represents a
    full-validation-year hold return, NOT an in-train-year alpha return.

    Empirical example (cycle #04 cap_aware_cross_asset top-1 trial
    ``ddc2896f9d8e`` per ``data/audit/i9_boundary_verify_*.json``):
    2022-12-31 → 2024-01-02 boundary return = +10.36% on positions
    held across the 2023 validation gap. Including this in NAV-Sharpe
    falsely rewards specs whose 2022 EOY portfolios happened to gain
    in 2023; the mining objective should select for in-train alpha,
    not cross-gap luck.

    Fix: zero out boundary returns BEFORE computing Sharpe / max_dd /
    nav_vs_qqq_excess. ``v1_legacy`` IC-only objective is unaffected
    (IC works on per-date forward returns, not NAV path).

    Parameters
    ----------
    daily_returns : pd.Series
        Daily return series (NAV.pct_change output).
    gap_threshold_days : int
        Calendar-day threshold above which the day-over-day return is
        masked. Default 30 (covers all train_year boundaries while
        leaving long-weekend / Christmas-week gaps intact).

    Returns
    -------
    pd.Series
        Copy of input with boundary returns set to 0.
    """
    if len(daily_returns) < 2:
        return daily_returns.copy()
    masked = daily_returns.copy()
    deltas = masked.index.to_series().diff()
    boundary_mask = deltas > pd.Timedelta(days=gap_threshold_days)
    masked.loc[boundary_mask] = 0.0
    return masked


def _max_drawdown_from_returns(daily_returns: pd.Series) -> float:
    """Cumulative-product NAV → max drawdown (negative). Helper kept
    local to avoid a dependency on the harness."""
    if len(daily_returns) == 0:
        return 0.0
    nav = (1.0 + daily_returns.fillna(0.0)).cumprod()
    peak = nav.cummax()
    dd = (nav - peak) / peak
    return float(dd.min()) if len(dd) > 0 else 0.0


def _annualized_sharpe_from_returns(
    daily_returns: pd.Series, periods_per_year: int = 252,
) -> float:
    """Annualized Sharpe from daily returns; degenerate-safe."""
    if len(daily_returns) < 2:
        return 0.0
    sd = float(daily_returns.std())
    if not np.isfinite(sd) or sd < 1e-12:
        return 0.0
    return float(daily_returns.mean() / sd * np.sqrt(periods_per_year))


def recompute_nav_metrics_train_only(
    daily_returns: pd.Series,
    qqq_series: Optional[pd.Series] = None,
    *,
    gap_threshold_days: int = 30,
) -> dict:
    """Recompute (sharpe, max_dd, vs_qqq) AFTER masking train-boundary
    gap returns. Used by the PRD-AC v1.1 NAV gate in lieu of the harness's
    raw ``metrics_full_period`` values, which include cross-gap returns.

    Returns
    -------
    dict with keys ``sharpe``, ``max_dd``, ``vs_qqq`` (NaN if undefined).
    """
    masked = mask_train_boundary_returns(
        daily_returns, gap_threshold_days=gap_threshold_days,
    )
    sharpe = _annualized_sharpe_from_returns(masked)
    max_dd = _max_drawdown_from_returns(masked)
    vs_qqq = float("nan")
    if qqq_series is not None:
        # Compute QQQ daily return series, mask boundary, take cum_ret
        qqq_ret = qqq_series.pct_change().reindex(masked.index)
        qqq_masked = mask_train_boundary_returns(
            qqq_ret, gap_threshold_days=gap_threshold_days,
        )
        spec_cum = float((1.0 + masked.fillna(0.0)).prod() - 1.0)
        qqq_cum = float((1.0 + qqq_masked.fillna(0.0)).prod() - 1.0)
        vs_qqq = spec_cum - qqq_cum
    return {"sharpe": sharpe, "max_dd": max_dd, "vs_qqq": vs_qqq}


# ── I20 cross-asset spec detector ──────────────────────────────────────────


def classify_cross_asset_spec(
    weights_df: pd.DataFrame,
    *,
    non_equity_threshold: float = 0.30,
    asset_class_lookup: Optional[Mapping[str, str]] = None,
) -> bool:
    """Return True iff the realized portfolio's time-averaged non-equity
    weight exceeds ``non_equity_threshold`` (PRD §4.6 I20 default 30%).

    "Cross-asset" means the spec materially holds bonds / commodities /
    cash_anchor, where SPY-residual assumption (spec is mostly equity-
    beta-driven) breaks down. Such specs should skip the orthogonality
    term (caller substitutes ``nav_correlation_vs_anchor_pooled_raw=NaN``
    in CompositeMetrics so the term contributes 0).

    Parameters
    ----------
    weights_df : pd.DataFrame
        Realized target weights (date × symbol) from the harness backtest.
        Empty input returns False (treat as not-cross-asset; conservative).
    non_equity_threshold : float
        Fraction above which the spec is classified as cross-asset.
        Default 0.30 per PRD §4.6 I20.
    asset_class_lookup : Mapping[str, str], optional
        Symbol → asset_class. None uses the default unified map (stocks
        + cross-asset). Pass an explicit map when mining on a custom
        universe.

    Returns
    -------
    bool
        True iff cross-asset spec.
    """
    if weights_df.empty:
        return False
    if asset_class_lookup is None:
        # Lazy import default unified map; raises KeyError on unknown
        # symbol — wrap defensively to fall back to "equities" so an
        # unmapped symbol does not abort mining.
        def _lookup(sym: str) -> str:
            try:
                return get_asset_class(sym)
            except KeyError:
                return "equities"
    else:
        def _lookup(sym: str) -> str:
            return asset_class_lookup.get(sym, "equities")
    # Per-day per-class total weight
    classes = pd.Series(
        {sym: _lookup(sym) for sym in weights_df.columns}, name="asset_class",
    )
    if classes.empty:
        return False
    # Sum weights by class per day, then time-average
    by_class = weights_df.T.groupby(classes).sum().T
    avg_by_class = by_class.mean(axis=0)
    non_equity_weight = float(avg_by_class.drop(labels=["equities"], errors="ignore").sum())
    return non_equity_weight > non_equity_threshold
