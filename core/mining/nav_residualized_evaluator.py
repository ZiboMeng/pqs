"""NAV-residualized mining target (cycle10 axis, PRD 20260513).

Implements Blitz-Huij-Martens (2011, J. Empirical Finance 18(3):506-521)
"Residual Momentum" methodology, adapted for fleet-orthogonalization:
mining target = forward return − β × fleet NAV return.

Math (Blitz 2011 + Grinold-Kahn ch 16 generalization):

    r[s, t] − r_f = α[s] + Σ_k β[s, k] × r_fleet[k, t] + ε[s, t]

    β estimated by 36-month rolling OLS (multi-factor with K=3 fleet members).

    residual_fwd_ret[s, t→t+21]
        = fwd_ret[s, t→t+21]
          − Σ_k β[s, k, t-1] × cum_fleet_ret[k, t→t+21]

Use:
    >>> from core.mining.nav_residualized_evaluator import (
    ...     compute_rolling_beta, compute_residual_forward_returns,
    ... )
    >>> beta = compute_rolling_beta(stock_returns, fleet_returns, window_months=36)
    >>> resid_fwd = compute_residual_forward_returns(fwd_returns, fleet_fwd_returns, beta)
    >>> # pass resid_fwd as fwd_returns to evaluate_composite()

Caveats:
    - 36m rolling β requires ≥ 756 trading days of history per (stock, fleet)
      pair. Pre-warmup dates return NaN β.
    - Fleet daily NAV must be DAILY RETURN series (not cumulative NAV).
    - For research mining on 2009-2024 panel, fleet specs must be back-cast
      first to produce shared daily return series (Cand-2 / RCMv1 / Trial9_v2
      research-period). See PRD §6.3 mitigation + B6 audit §R3.
"""

from __future__ import annotations

from typing import Dict, Mapping

import numpy as np
import pandas as pd

DEFAULT_BETA_WINDOW_MONTHS = 36
TRADING_DAYS_PER_MONTH = 21


def compute_rolling_beta(
    stock_returns: pd.DataFrame,
    fleet_returns: pd.DataFrame,
    *,
    window_months: int = DEFAULT_BETA_WINDOW_MONTHS,
    min_periods_fraction: float = 0.5,
) -> Dict[str, pd.DataFrame]:
    """Multi-factor rolling OLS β of each stock on the fleet.

    Parameters
    ----------
    stock_returns : DataFrame[date × symbol], daily returns (decimal).
    fleet_returns : DataFrame[date × fleet_id], daily returns (decimal).
    window_months : OLS lookback in months (Blitz 2011 default = 36).
    min_periods_fraction : min fraction of window required to emit β (else NaN).

    Returns
    -------
    Dict[str, DataFrame]: keys = symbols; values = DataFrame[date × fleet_id]
    holding β estimate at end-of-day t (excluding t from regression to
    prevent lookahead).

    Notes
    -----
    Implementation: for each date t (after warmup), runs OLS on the past
    `window_months × 21` trading days of (stock vs fleet). Returns β only
    for dates with ≥ `min_periods_fraction × window_days` non-NaN samples.

    Multi-factor OLS handles fleet members simultaneously via numpy
    lstsq (more numerically stable than sequential single-factor regression
    when fleet members are correlated).
    """
    if stock_returns.empty:
        raise ValueError("stock_returns empty")
    if fleet_returns.empty:
        raise ValueError("fleet_returns empty")

    common_idx = stock_returns.index.intersection(fleet_returns.index)
    if common_idx.empty:
        raise ValueError("stock_returns and fleet_returns share no dates")

    sr = stock_returns.loc[common_idx]
    fr = fleet_returns.loc[common_idx]

    window_days = window_months * TRADING_DAYS_PER_MONTH
    min_periods = int(min_periods_fraction * window_days)
    fleet_cols = list(fr.columns)
    K = len(fleet_cols)

    result: Dict[str, pd.DataFrame] = {}

    # Fleet matrix once (rows=dates)
    F_full = fr.to_numpy()  # shape (T, K)

    for sym in sr.columns:
        y_full = sr[sym].to_numpy()  # shape (T,)
        beta_rows = np.full((len(common_idx), K), np.nan)
        # Iterate over end-dates; regression window = (t - window_days, t-1]
        # i.e., excludes t itself to prevent lookahead.
        for end_idx in range(window_days, len(common_idx)):
            start_idx = end_idx - window_days
            y_win = y_full[start_idx:end_idx]
            F_win = F_full[start_idx:end_idx]
            mask = ~np.isnan(y_win) & ~np.any(np.isnan(F_win), axis=1)
            n_valid = int(mask.sum())
            if n_valid < min_periods:
                continue
            y_clean = y_win[mask]
            F_clean = F_win[mask]
            # OLS via lstsq: F β = y → β = (F'F)^-1 F'y
            # Add intercept for numerical correctness (matches Blitz spec)
            F_with_intercept = np.column_stack([np.ones(n_valid), F_clean])
            try:
                coeffs, *_ = np.linalg.lstsq(F_with_intercept, y_clean, rcond=None)
                beta_rows[end_idx] = coeffs[1:]  # skip intercept
            except np.linalg.LinAlgError:
                # Singular matrix (e.g. perfectly collinear fleet members);
                # leave NaN.
                continue
        result[sym] = pd.DataFrame(
            beta_rows, index=common_idx, columns=fleet_cols
        )

    return result


def compute_residual_forward_returns(
    fwd_returns: pd.DataFrame,
    fleet_fwd_returns: pd.DataFrame,
    beta_by_sym: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Compute residual forward returns: fwd_ret − Σ_k β[k] × fleet_fwd_ret[k].

    Parameters
    ----------
    fwd_returns : DataFrame[date × symbol], cumulative forward returns
        (e.g. 21-day forward log or simple return).
    fleet_fwd_returns : DataFrame[date × fleet_id], cumulative fleet
        forward returns over the same horizon as fwd_returns.
    beta_by_sym : Mapping[symbol, DataFrame[date × fleet_id]], rolling β
        from `compute_rolling_beta()`. β at date t is used for residual
        at date t (β estimated from data up to t-1; no lookahead).

    Returns
    -------
    DataFrame[date × symbol] of residual forward returns. Cells where any
    β is NaN (warmup) or fleet_fwd_ret is NaN result in NaN.
    """
    if fwd_returns.empty:
        raise ValueError("fwd_returns empty")

    residual = pd.DataFrame(
        np.nan, index=fwd_returns.index, columns=fwd_returns.columns
    )
    fleet_cols = list(fleet_fwd_returns.columns)

    for sym in fwd_returns.columns:
        if sym not in beta_by_sym:
            # No β series → cannot residualize; leave all NaN
            continue
        beta_df = beta_by_sym[sym]
        # Align all three on common dates
        common_idx = fwd_returns.index.intersection(beta_df.index).intersection(
            fleet_fwd_returns.index
        )
        if common_idx.empty:
            continue
        y = fwd_returns.loc[common_idx, sym].to_numpy()
        beta_mat = beta_df.loc[common_idx, fleet_cols].to_numpy()  # (T, K)
        fleet_fwd = fleet_fwd_returns.loc[common_idx, fleet_cols].to_numpy()  # (T, K)
        explained = (beta_mat * fleet_fwd).sum(axis=1)  # (T,)
        resid = y - explained
        # Propagate NaN from inputs
        nan_mask = np.isnan(y) | np.any(np.isnan(beta_mat), axis=1) | np.any(
            np.isnan(fleet_fwd), axis=1
        )
        resid[nan_mask] = np.nan
        residual.loc[common_idx, sym] = resid

    return residual


def build_fleet_forward_returns_from_nav(
    fleet_nav: pd.DataFrame,
    horizon_days: int = 21,
) -> pd.DataFrame:
    """Convert daily NAV (level) series to forward H-day cumulative return.

    Parameters
    ----------
    fleet_nav : DataFrame[date × fleet_id], daily NAV level (e.g. starting
        at 10000 and evolving). Daily.
    horizon_days : forward horizon (PQS standard = 21).

    Returns
    -------
    DataFrame[date × fleet_id] where row t = (NAV[t+H] / NAV[t]) - 1.
    The last `horizon_days` rows are NaN (no forward data).
    """
    if (fleet_nav <= 0).any().any():
        raise ValueError("fleet_nav must be strictly positive")
    fwd = fleet_nav.shift(-horizon_days) / fleet_nav - 1.0
    return fwd
