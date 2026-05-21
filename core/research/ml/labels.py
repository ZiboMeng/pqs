"""PRD #4 P4.4 sub-step 3 prereq — forward-return labels + bar-integrity smoke.

This module provides the discipline helpers that the real-data driver
(`dev/scripts/ml/walk_forward_rank_sign.py`) must call BEFORE handing
data to ``run_walk_forward``:

  1. ``make_forward_return_labels(price_df, horizon_days)``
     forward-shifted simple returns; horizon MUST match canonical
     candidate holding period (PRD #4 P4.1 AC binding constraint).

  2. ``assert_bar_integrity(panel)``
     CLAUDE.md hard requirement: weekend rows = 0 AND index is
     monotone-increasing AND no duplicate dates. Per
     ``feedback_bar_level_data_integrity_smoke`` (the SPY off-by-one
     bug crossed 5 cycles + 4 forwards because nobody ran this 5-min
     check).

  3. ``assert_no_sealed_year(panel, sealed_years)``
     Hard refuse if panel index contains any sealed-year date. Last
     line of defense before ML training touches sealed data
     (``feedback_temporal_split_discipline`` + sealed-2026 ledger
     rule).

  4. ``apply_tradeable_mask(labels, mask)``
     Set non-tradeable cells to NaN — keeps walk-forward eval honest
     by excluding non-investable symbols from rank-IC computation
     (P4.1 AC: tradeable-mask rank-IC must pass independently).

All checks raise ``ValueError`` on violation; non-blanket failure
verdicts happen at the run-level (per-fold metrics), not at this
pre-flight layer.

PRD: docs/prd/20260520-prd_rank_first_ml_pipeline.md §P4.4
"""
from __future__ import annotations

from typing import Iterable, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "make_forward_return_labels",
    "make_forward_log_return_labels",
    "assert_bar_integrity",
    "assert_no_sealed_year",
    "assert_panel_datetime_index",
    "apply_tradeable_mask",
]


# ---------------------------------------------------------------------------
# Forward-return labels
# ---------------------------------------------------------------------------


def make_forward_return_labels(
    price_df: pd.DataFrame, horizon_days: int,
) -> pd.DataFrame:
    """Forward-shifted simple return label.

    label[t, sym] = price[t + horizon] / price[t] - 1

    NaN appears at the last ``horizon_days`` rows where forward price
    is unknown. Caller is responsible for filtering these out (or
    relying on walk-forward to slice past them).

    Args:
        price_df: DataFrame(date × symbol) of adjusted close prices
        horizon_days: forward window in BUSINESS-DAY (bar-count) units
            (matches PRD-2 candidate holding_freq — caller picks
            21 for monthly, 5 for weekly, etc.)
    """
    if horizon_days < 1:
        raise ValueError(f"horizon_days must be ≥ 1, got {horizon_days}")
    assert_panel_datetime_index(price_df, name="price_df")
    forward = price_df.shift(-horizon_days)
    return forward.div(price_df) - 1.0


def make_forward_log_return_labels(
    price_df: pd.DataFrame, horizon_days: int,
) -> pd.DataFrame:
    """Forward-shifted log return label.

    label[t, sym] = ln(price[t + horizon] / price[t])

    Use when normality/additivity over multiple horizons matters
    (e.g. multi-period aggregation). Default for rank-based ML this
    PRD uses simple returns (sign equivalent under monotonic
    transform).
    """
    if horizon_days < 1:
        raise ValueError(f"horizon_days must be ≥ 1, got {horizon_days}")
    assert_panel_datetime_index(price_df, name="price_df")
    forward = price_df.shift(-horizon_days)
    ratio = forward.div(price_df)
    # log(0 or negative) → NaN (matches simple-return NaN policy)
    safe = ratio.where(ratio > 0)
    return np.log(safe)


# ---------------------------------------------------------------------------
# Residualized cross-sectional rank / quantile labels
# (PRD 20260521 §7.2 — canonical daily-stock-selection label modes)
# ---------------------------------------------------------------------------


def _rolling_market_beta(
    daily_returns: pd.DataFrame, market_returns: pd.Series, window: int,
) -> pd.DataFrame:
    """Trailing rolling OLS beta of each column vs the market.

    beta[t, sym] = Cov(ret_sym, ret_mkt) / Var(ret_mkt) over the trailing
    ``window`` bars ending at t. Estimated from returns known at t — the
    label this feeds is itself forward-looking, so beta as a known-at-t
    quantity needs no extra shift.
    """
    min_p = max(window // 2, 2)
    cov = daily_returns.rolling(window, min_periods=min_p).cov(market_returns)
    var = market_returns.rolling(window, min_periods=min_p).var()
    return cov.div(var, axis=0)


def make_residualized_rank_labels(
    price_df: pd.DataFrame, horizon_days: int, market_series: pd.Series,
    beta_window: int = 252,
) -> pd.DataFrame:
    """Per-bar cross-sectional rank of the market-residualized fwd return.

    PRD 20260521 §7.2 ``cross_sectional_residual_rank`` (market component;
    sector residualization is a separate follow-up)::

        fwd_ret[t,sym]  = price[t+h]/price[t] - 1
        fwd_mkt[t]      = market[t+h]/market[t] - 1
        residual[t,sym] = fwd_ret[t,sym] - beta[t,sym] * fwd_mkt[t]
        label[t,sym]    = cross-sectional rank of residual in bar t, ∈ (0,1]

    Residualization removes the market-beta-driven component so the label
    scores stock-specific performance — aligned with a long-only top-k
    book that wants the genuinely strongest names, not the highest-beta
    names. NaN at the first ``beta_window`` rows (beta unknown) and the
    last ``horizon_days`` rows (forward price unknown).

    Args:
        price_df: DataFrame(date × symbol) of adjusted close prices
        horizon_days: forward window in bar-count units
        market_series: market benchmark close series (e.g. SPY)
        beta_window: trailing window for the rolling market beta
    """
    if horizon_days < 1:
        raise ValueError(f"horizon_days must be ≥ 1, got {horizon_days}")
    if beta_window < 2:
        raise ValueError(f"beta_window must be ≥ 2, got {beta_window}")
    assert_panel_datetime_index(price_df, name="price_df")
    fwd_ret = make_forward_return_labels(price_df, horizon_days)
    market = market_series.reindex(price_df.index)
    fwd_mkt = market.shift(-horizon_days).div(market) - 1.0
    beta = _rolling_market_beta(
        price_df.pct_change(), market.pct_change(), beta_window)
    residual = fwd_ret.sub(beta.mul(fwd_mkt, axis=0))
    return residual.rank(axis=1, pct=True)


def make_residualized_quantile_labels(
    price_df: pd.DataFrame, horizon_days: int, market_series: pd.Series,
    beta_window: int = 252, quantile_buckets: int = 10,
) -> pd.DataFrame:
    """Per-bar cross-sectional quantile bucket of the market-residualized
    forward return. Bucket 0 = weakest, ``quantile_buckets - 1`` =
    strongest. NaN policy follows ``make_residualized_rank_labels``.
    """
    if quantile_buckets < 2:
        raise ValueError(
            f"quantile_buckets must be ≥ 2, got {quantile_buckets}")
    rank = make_residualized_rank_labels(
        price_df, horizon_days, market_series, beta_window)
    bucket = np.floor(rank * quantile_buckets).clip(upper=quantile_buckets - 1)
    return bucket.where(rank.notna())


# ---------------------------------------------------------------------------
# Bar-integrity smoke
# ---------------------------------------------------------------------------


def assert_panel_datetime_index(
    panel: pd.DataFrame | dict, name: str = "panel",
) -> None:
    """Raise if panel index is not a DatetimeIndex.

    Sub-step 1 R3 catch (Round 23): ``_slice_panel_dict`` implicitly
    assumed DatetimeIndex; this helper makes the contract explicit
    at driver entry.
    """
    if isinstance(panel, dict):
        for k, v in panel.items():
            if not isinstance(v.index, pd.DatetimeIndex):
                raise ValueError(
                    f"{name}[{k!r}] must have DatetimeIndex; got "
                    f"{type(v.index).__name__}")
        return
    if not isinstance(panel.index, pd.DatetimeIndex):
        raise ValueError(
            f"{name} must have DatetimeIndex; got "
            f"{type(panel.index).__name__}")


def assert_bar_integrity(panel: pd.DataFrame, name: str = "panel") -> None:
    """Hard-fail if panel violates CLAUDE.md bar-level smoke:
    - DatetimeIndex
    - monotone increasing
    - no duplicate dates
    - no weekend rows (Saturday=5, Sunday=6)

    Per ``feedback_bar_level_data_integrity_smoke``: the SPY off-by-one
    bug crossed 5 cycles + 4 forward candidates because nobody ran
    this 5-min check. Any heavy ML / mining / forward init MUST
    call this before consuming the panel.

    Note: holiday-day omission is NOT checked (NYSE has many irregular
    holidays; ``pandas_market_calendars`` is the right tool if
    holiday-coverage gates are needed — separate concern).
    """
    assert_panel_datetime_index(panel, name=name)
    idx = panel.index
    if not idx.is_monotonic_increasing:
        raise ValueError(
            f"{name} index is not monotone-increasing — sort or "
            f"deduplicate before training.")
    if idx.has_duplicates:
        dupes = idx[idx.duplicated()].unique().tolist()[:5]
        raise ValueError(
            f"{name} has duplicate date entries (first 5): {dupes}")
    # weekend check: 5=Sat, 6=Sun
    weekend_mask = idx.dayofweek >= 5
    if weekend_mask.any():
        weekend_dates = idx[weekend_mask].tolist()[:5]
        raise ValueError(
            f"{name} contains {int(weekend_mask.sum())} weekend rows "
            f"(first 5: {[d.date() for d in weekend_dates]}); SPY "
            f"off-by-one precedent — weekend pollution breaks "
            f"alignment. Fix the data ingest before training.")


def assert_no_sealed_year(
    panel: pd.DataFrame | dict,
    sealed_years: Iterable[int],
    name: str = "panel",
) -> None:
    """Hard-fail if any date in panel index falls within a sealed year.

    Last line of defense — the ``WalkForwardConfig.end_year`` guard
    in ``core.research.ml.pipeline`` is at config level; this is at
    data level. Both should always agree.
    """
    sealed_set = set(sealed_years)
    if not sealed_set:
        return  # no sealed years configured
    if isinstance(panel, dict):
        for k, v in panel.items():
            assert_no_sealed_year(v, sealed_set, name=f"{name}[{k!r}]")
        return
    assert_panel_datetime_index(panel, name=name)
    years_present = set(panel.index.year.unique())
    overlap = years_present & sealed_set
    if overlap:
        raise ValueError(
            f"{name} contains data for sealed year(s) {sorted(overlap)} "
            f"— per config/temporal_split.yaml + "
            f"feedback_temporal_split_discipline, these dates must be "
            f"stripped BEFORE the panel reaches ML training. "
            f"Slice your data with year-based filter.")


# ---------------------------------------------------------------------------
# Tradeable mask
# ---------------------------------------------------------------------------


def apply_tradeable_mask(
    labels: pd.DataFrame, mask: pd.DataFrame | None,
) -> pd.DataFrame:
    """Return labels with non-tradeable cells set to NaN.

    Args:
        labels: (date × symbol) forward returns or other label panel
        mask: same-shape boolean (True = tradeable); if None, returns
            labels unchanged.

    Reindexes mask to labels' shape (missing cells treated as
    not-tradeable, i.e. NaN out the label).
    """
    if mask is None:
        return labels
    if not isinstance(mask, pd.DataFrame):
        raise TypeError(
            f"mask must be DataFrame or None; got {type(mask).__name__}")
    # align mask to labels grid
    aligned = mask.reindex(index=labels.index, columns=labels.columns)
    aligned = aligned.fillna(False).astype(bool)
    return labels.where(aligned)
