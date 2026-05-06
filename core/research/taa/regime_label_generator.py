"""PRD-E v1.1 §4.4 monthly-cadence regime label generator.

Wraps ``core.regime.regime_detector.RegimeDetector.classify_series`` to:
  * Compute daily regime labels (T-day only, no lookahead).
  * Resample to month-start cadence per PRD §4.4 I16 design choice
    (monthly default; daily variant available via ``cadence='D'`` for
    Phase 2 sensitivity check).

Also exposes ``manual_regime_labels`` — a year-tag → daily-label expander
matching the convention in ``trial9_historical_walkforward_prior.py``.
This is the manual ground-truth side of the M9 regime reconciliation
(§5.2 Phase 1 acceptance: KL divergence / Hamming distance vs auto).

Output schema (verified in tests):
  ``pd.Series`` indexed by trading day (or month-start), dtype=str,
  values = RegimeState.value strings (BULL / RISK_ON / NEUTRAL /
  CAUTIOUS / RISK_OFF / CRISIS).
"""

from __future__ import annotations

from typing import Mapping, Optional

import numpy as np
import pandas as pd

from core.regime.regime_detector import RegimeDetector, RegimeState


def daily_regime_labels(
    spy: pd.Series,
    vix: pd.Series,
    detector: RegimeDetector,
    *,
    tnx: Optional[pd.Series] = None,
) -> pd.Series:
    """Compute daily regime labels via RegimeDetector.

    Pure delegation to ``detector.classify_series``. Provided as a
    named layer so callers can swap the underlying classifier later
    without touching the monthly-resample logic below.

    PRD-E §4.4 lookahead invariant: ``RegimeDetector.classify_series``
    uses only same-day-or-earlier values from spy/vix/tnx (the EMA /
    drawdown / VIX-level checks). T-day labels use ONLY data through T.
    """
    return detector.classify_series(spy=spy, vix=vix, tnx=tnx)


def monthly_regime_labels(
    daily_labels: pd.Series,
    *,
    cadence: str = "MS",
) -> pd.Series:
    """Resample daily labels to monthly cadence (default month-start).

    PRD-E §4.4 monthly cadence design choice (I16): TAA portfolio
    rebalances at month-start using the regime label observed AT the
    month-start day. Mid-month regime changes do NOT trigger
    intra-month rebalance (low-turnover; cost-aware).

    Parameters
    ----------
    daily_labels : pd.Series
        Output of ``daily_regime_labels``; values are RegimeState
        string values, index is trading days.
    cadence : str
        Pandas resample frequency. Default "MS" = month-start (first
        trading day per month). Use "D" for daily variant (PRD-E §5.2
        Phase 2 sensitivity check). Use "W-MON" for weekly cadence.

    Returns
    -------
    pd.Series
        Indexed at the cadence boundary (month-start trading days),
        value = label observed at that day.
    """
    if daily_labels.empty:
        return pd.Series(dtype=str, name=daily_labels.name)
    if cadence == "D":
        return daily_labels.copy()
    # Resample with first() to grab the label at the cadence boundary.
    # Day-aligned to the daily index AFTER the resample so we use the
    # actual trading day on or after the calendar boundary.
    resampled = daily_labels.resample(cadence).first().dropna()
    return resampled


def manual_regime_labels(
    year_tags: Mapping[int, str],
    daily_index: pd.DatetimeIndex,
) -> pd.Series:
    """Expand year → manual_tag dict to a daily Series of regime labels.

    Convention matches ``trial9_historical_walkforward_prior.py``: each
    year is assigned a single dominant manual tag (e.g. 2020 →
    "covid_crisis" → CRISIS), and that tag is applied to every trading
    day within the year.

    Parameters
    ----------
    year_tags : Mapping[int, str]
        Year → RegimeState.value string. Years in ``daily_index`` not
        present in this mapping receive ``NEUTRAL`` (defensive default;
        operator should populate explicitly).
    daily_index : pd.DatetimeIndex
        Target daily index to expand to.

    Returns
    -------
    pd.Series
        Indexed by ``daily_index``, dtype=str, values =
        RegimeState.value strings.
    """
    valid = {s.value for s in RegimeState}
    invalid = {v for v in year_tags.values() if v not in valid}
    if invalid:
        raise ValueError(
            f"manual year_tags contain non-RegimeState values: {sorted(invalid)}; "
            f"valid: {sorted(valid)}"
        )
    out = pd.Series(
        [year_tags.get(d.year, RegimeState.NEUTRAL.value) for d in daily_index],
        index=daily_index, dtype=str,
    )
    return out


# ── M9 disagreement metrics (PRD-E §5.2 Phase 1 acceptance §4.5) ───────────


def regime_label_kl_divergence(
    series_a: pd.Series,
    series_b: pd.Series,
    *,
    smoothing: float = 1e-6,
) -> float:
    """KL divergence of regime label distributions: KL(P_a || P_b).

    Per PRD-E §5.2 Phase 1 + I12 fix: a distributional similarity check
    between manual and auto regime classifiers. KL < 0.5 = similar
    distributions; high disagreement triggers M9 user-go review.

    Both series should cover the same period (caller's responsibility);
    this function operates on the value distributions, NOT day-by-day
    alignment (use ``regime_label_hamming_distance`` for that).

    KL is asymmetric: KL(P || Q) measures information loss when Q
    approximates P. We return KL(a || b); caller decides which is
    "truth" (typically manual).

    Parameters
    ----------
    series_a, series_b : pd.Series
        Regime label series (any length; index ignored). Values must
        be RegimeState string values.
    smoothing : float
        Add to each empirical count BEFORE normalization (avoids log(0)
        when one distribution lacks a regime present in the other).
        Default 1e-6 — large enough to avoid divergence, small enough
        to barely shift the empirical distribution.

    Returns
    -------
    float
        KL divergence in nats. NaN if either series is empty.
    """
    if series_a.empty or series_b.empty:
        return float("nan")
    states = sorted(s.value for s in RegimeState)
    pa = pd.Series(0.0, index=states)
    pb = pd.Series(0.0, index=states)
    for v, c in series_a.value_counts().items():
        if v in states:
            pa[v] = c
    for v, c in series_b.value_counts().items():
        if v in states:
            pb[v] = c
    pa = pa + smoothing
    pb = pb + smoothing
    pa = pa / pa.sum()
    pb = pb / pb.sum()
    return float((pa * np.log(pa / pb)).sum())


def regime_label_hamming_distance(
    series_a: pd.Series,
    series_b: pd.Series,
) -> float:
    """Day-by-day disagreement rate (proportion of days where labels differ).

    Per PRD-E §5.2 Phase 1 + I12 fix: complementary to KL; measures
    label-level mismatch even when distributions are similar. Hamming
    distance < 0.30 = labels mostly agree; high disagreement triggers
    M9 user-go review.

    Both series are aligned on their joint index intersection; days
    present in only one series are excluded from the count.

    Returns
    -------
    float
        Fraction of joint days where ``series_a[d] != series_b[d]``.
        NaN if joint index is empty.
    """
    common = series_a.index.intersection(series_b.index)
    if len(common) == 0:
        return float("nan")
    a = series_a.loc[common]
    b = series_b.loc[common]
    return float((a != b).mean())
