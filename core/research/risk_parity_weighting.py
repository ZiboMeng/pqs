"""Risk-parity (inverse-volatility) weighting for harness construction modes.

C10-2-A per `docs/memos/20260513-cycle10_construction_axis_design.md`.

Provides `reweight_inverse_vol()` that takes signals from existing
`topn_signals_with_caps` (equal-weighted selection) and replaces weights
with inverse-volatility weights, subject to existing cap constraints
(max_single_weight + optional cluster_cap).

Used by HarnessConfig.construction_mode='cap_aware_risk_parity' to test
whether equal-weighting is part of the cycle04-09b sibling-by-construction
binding constraint.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd


def _detect_rebalance_rows(signals: pd.DataFrame) -> pd.Series:
    """Return Series of date → True for rows where signals change from
    previous row (with forward-fill assumption).

    A rebalance row is any row where ANY symbol's weight differs from
    its previous-row value (after sort by date).
    """
    if signals.empty:
        return pd.Series(dtype=bool)
    sorted_signals = signals.sort_index()
    changes = sorted_signals.ne(sorted_signals.shift(1)).any(axis=1)
    # First row is always a "rebalance" if any name held
    changes.iloc[0] = sorted_signals.iloc[0].any()
    return changes


def _compute_inverse_vol_weights(
    held_symbols: list[str],
    price_df: pd.DataFrame,
    rebal_date: pd.Timestamp,
    lookback: int,
    max_single_weight: float,
    cluster_map: Optional[Dict[str, str]] = None,
    cluster_cap: float = 0.20,
    min_history: int = 20,
) -> pd.Series:
    """For held_symbols on rebal_date, compute 1/vol weights.

    Returns Series indexed by held_symbols. Weights sum to 1 (or less if
    cluster_cap is binding). Edge cases:
      - σ_i = 0 or NaN: use median(σ_others); if all zero/NaN → equal weight
      - <min_history days available: equal weight fallback for that symbol
      - max_single_weight cap: clip and redistribute residual proportionally
      - cluster_cap: re-enforce cluster cap; if binding, proportionally scale
        within cluster
    """
    if not held_symbols:
        return pd.Series(dtype=float)

    # Slice price_df up to lookback days before rebal_date
    # Use [:rebal_date) — strict less than to avoid using rebal_date itself
    window_end = rebal_date - pd.Timedelta(days=1)
    window_start = window_end - pd.Timedelta(days=int(lookback * 2))  # buffer for weekends
    panel_window = price_df.loc[window_start:window_end, held_symbols]
    # Use up to `lookback` most-recent rows
    panel_window = panel_window.tail(lookback)

    # Compute daily returns then daily vol per symbol
    returns = panel_window.pct_change().dropna(how="all")
    vols = returns.std()  # NaN if insufficient data

    # Fallback for symbols with insufficient history or zero vol
    valid_vols = vols.dropna()
    valid_vols = valid_vols[valid_vols > 1e-9]
    if valid_vols.empty:
        # All symbols lack data → equal weight
        n = len(held_symbols)
        w = pd.Series(1.0 / n, index=held_symbols)
    else:
        median_vol = valid_vols.median()
        # Fill missing vols with median (so they don't get infinite weight)
        vols_filled = vols.fillna(median_vol).clip(lower=1e-9)
        inv_vols = 1.0 / vols_filled
        w = inv_vols / inv_vols.sum()

    # Cap clipping for single-name max_single_weight
    w = _apply_single_name_cap(w, max_single_weight)

    # Cluster cap re-enforcement (if applicable)
    if cluster_map is not None:
        w = _apply_cluster_cap(w, cluster_map, cluster_cap, max_single_weight)

    return w


def _apply_single_name_cap(
    w: pd.Series, max_single_weight: float, max_iters: int = 10
) -> pd.Series:
    """Clip any weight > max_single_weight to max_single_weight + redistribute
    residual to uncapped names proportionally. Iterate until converged."""
    for _ in range(max_iters):
        over = w[w > max_single_weight + 1e-12]
        if over.empty:
            break
        residual = (over - max_single_weight).sum()
        w.loc[over.index] = max_single_weight
        # Redistribute proportionally to uncapped names
        uncapped = w[w < max_single_weight - 1e-12]
        if uncapped.empty:
            break
        # Proportional add
        addition = residual * (uncapped / uncapped.sum())
        w.loc[uncapped.index] += addition
    return w


def _apply_cluster_cap(
    w: pd.Series,
    cluster_map: Dict[str, str],
    cluster_cap: float,
    max_single_weight: float,
    max_iters: int = 10,
) -> pd.Series:
    """Re-enforce cluster_cap after inverse-vol weighting.

    Approach: For each cluster, sum the weights. If > cluster_cap, scale
    down proportionally within the cluster, redistribute the excess to
    OTHER clusters proportionally. Iterate until converged or no
    feasible solution.
    """
    for _ in range(max_iters):
        # Compute cluster totals
        clusters = pd.Series([cluster_map.get(s, "__unknown__") for s in w.index],
                            index=w.index)
        cluster_totals = w.groupby(clusters).sum()
        over = cluster_totals[cluster_totals > cluster_cap + 1e-12]
        if over.empty:
            break
        # For each over-budget cluster, scale weights down to cluster_cap
        total_excess = 0.0
        for cluster_name, total in over.items():
            cluster_syms = clusters[clusters == cluster_name].index
            scale = cluster_cap / total
            w.loc[cluster_syms] = w.loc[cluster_syms] * scale
            total_excess += total - cluster_cap
        # Redistribute total_excess to under-budget clusters proportionally
        # (but still respecting single-name cap)
        under = cluster_totals[cluster_totals < cluster_cap - 1e-12]
        if under.empty:
            break
        under_syms = clusters[clusters.isin(under.index)].index
        if len(under_syms) == 0:
            break
        under_total = w.loc[under_syms].sum()
        if under_total < 1e-12:
            break
        proportional_add = total_excess * (w.loc[under_syms] / under_total)
        w.loc[under_syms] += proportional_add
        # Re-apply single-name cap after redistribution
        w = _apply_single_name_cap(w, max_single_weight)
    return w


def reweight_inverse_vol(
    signals: pd.DataFrame,
    price_df: pd.DataFrame,
    lookback: int = 60,
    max_single_weight: float = 0.10,
    cluster_map: Optional[Dict[str, str]] = None,
    cluster_cap: float = 0.20,
) -> pd.DataFrame:
    """Take signals from `topn_signals_with_caps` and replace equal-weight
    with inverse-volatility weights.

    The SELECTION is preserved (which symbols have non-zero weight on each
    rebalance date). Only the WEIGHTS change.

    Returns DataFrame with same shape as input. Forward-fills weights
    between rebalance dates (same convention as `topn_signals_with_caps`).
    """
    if signals.empty:
        return signals.copy()
    sorted_signals = signals.sort_index()
    # Align price_df to signals' date range + columns
    price_aligned = price_df.reindex(
        index=sorted_signals.index.union(price_df.index).sort_values(),
        columns=sorted_signals.columns,
    ).ffill()

    rebal_mask = _detect_rebalance_rows(sorted_signals)
    rebal_dates = sorted_signals.index[rebal_mask]

    new_signals = pd.DataFrame(
        0.0, index=sorted_signals.index, columns=sorted_signals.columns,
    )
    last_weights = pd.Series(0.0, index=sorted_signals.columns)

    for d in sorted_signals.index:
        if d in rebal_dates:
            row = sorted_signals.loc[d]
            held = row[row > 0].index.tolist()
            if not held:
                last_weights = pd.Series(0.0, index=sorted_signals.columns)
            else:
                w = _compute_inverse_vol_weights(
                    held, price_aligned, d, lookback,
                    max_single_weight, cluster_map, cluster_cap,
                )
                last_weights = pd.Series(0.0, index=sorted_signals.columns)
                last_weights.loc[w.index] = w.values
        new_signals.loc[d] = last_weights.values
    return new_signals
