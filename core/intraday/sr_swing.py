"""Swing-extrema-based support / resistance detection.

Pure-functional module. Detects local swing high / swing low on any-frequency
OHLC bars (60m, 30m, daily, etc.) and derives nearest support / resistance
levels and signed % distances from the current close.

Used by:
  - Use 1 (intraday execution timing): 60m / 30m bar S/R drives
    `decide_timing` to defer entry / scale weight.
  - Use 2 (stop-loss placement): daily-bar S/R anchors stop levels in
    `core/risk/`.
  - Use 3 (factor mining): daily-bar S/R-derived metrics enter
    `core/factors/factor_registry.py` RESEARCH_FACTORS for IC research.

Design choices (PRD: docs/prd/20260505-* — TBD; logged in TODO checklist):

  * "Swing high at bar i" = bar.high strictly greater than the high of every
    bar in [i-n, i-1] and [i+1, i+n]. Strict inequality avoids ambiguous
    flat-top patterns producing multiple "swing highs" at the same level.
  * "Nearest" S/R uses CLOSEST IN PRICE within the lookback window
    (NOT most recent in time). For S/R analysis the price-closest level is
    what bounds current price action; chronological recency matters less.
  * Edge bars (within n of either end of the input frame) cannot be swing
    extrema (insufficient lookback / lookforward window). They get False.

Caller responsibility:
  * Frequency choice — this module does not assume a frequency. Pass 60m
    bars for intraday timing; daily bars for factor mining.
  * Lookback choice — short lookback (5-10 bars) tracks micro-S/R; long
    lookback (50+ bars) tracks regime-level S/R.
  * RTH filtering — pre-filter bars to regular trading hours before
    passing in if pre/post-market noise is unwanted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SwingConfig:
    """Default swing-detection parameters. Caller should override per use."""

    n_window: int = 5
    """Half-width of the local extremum window (total window = 2n+1 bars)."""

    lookback: int = 20
    """Number of prior bars to scan when computing nearest S/R."""

    min_swing_separation_pct: float = 0.0
    """Optional minimum % separation between swing extremum and current
    close to qualify as S/R. Default 0 (no filter)."""


def detect_swing_extrema(
    bars: pd.DataFrame,
    n: int = 5,
) -> pd.DataFrame:
    """Identify local swing high / swing low bars.

    Parameters
    ----------
    bars : pd.DataFrame
        OHLC bars; must have ``'high'`` and ``'low'`` columns. Index is the
        bar timestamp (any monotonically-increasing index works).
    n : int
        Half-width of the comparison window. A bar at index i is a swing
        high iff its ``high`` is STRICTLY greater than the high of every
        bar in [i-n, i-1] and [i+1, i+n]. Same for swing low on ``low``.

    Returns
    -------
    pd.DataFrame
        Same index as ``bars``, with columns:
          - ``is_swing_high`` (bool)
          - ``is_swing_low``  (bool)

        Edge bars (i < n or i >= len(bars) - n) get False on both columns
        because their window is incomplete.

    Raises
    ------
    ValueError
        If ``n < 1`` or required columns are missing.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    for col in ("high", "low"):
        if col not in bars.columns:
            raise ValueError(f"bars must have column {col!r}; got {list(bars.columns)}")

    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    L = len(bars)

    is_high = np.zeros(L, dtype=bool)
    is_low = np.zeros(L, dtype=bool)

    if L >= 2 * n + 1:
        # Vectorized: for each candidate i in [n, L-n), check window.
        for i in range(n, L - n):
            h_i = high[i]
            l_i = low[i]
            if np.isnan(h_i) or np.isnan(l_i):
                continue
            # Build [i-n, i-1] and [i+1, i+n] slice and require strict gt/lt.
            left_high = high[i - n: i]
            right_high = high[i + 1: i + n + 1]
            left_low = low[i - n: i]
            right_low = low[i + 1: i + n + 1]
            # NaN-safe: any NaN in window invalidates the bar (cannot prove
            # strict extremum without complete data).
            if not (np.isnan(left_high).any() or np.isnan(right_high).any()):
                if (h_i > left_high).all() and (h_i > right_high).all():
                    is_high[i] = True
            if not (np.isnan(left_low).any() or np.isnan(right_low).any()):
                if (l_i < left_low).all() and (l_i < right_low).all():
                    is_low[i] = True

    return pd.DataFrame(
        {"is_swing_high": is_high, "is_swing_low": is_low},
        index=bars.index,
    )


def compute_nearest_sr(
    bars: pd.DataFrame,
    n: int = 5,
    lookback: int = 20,
    min_separation_pct: float = 0.0,
) -> pd.DataFrame:
    """For each bar, compute the nearest swing-based support / resistance
    within the prior ``lookback`` bars.

    "Nearest" = closest IN PRICE (not in time). Resistance is the swing
    high level whose value is above current close and minimizes the gap;
    support is the swing low level below current close minimizing the gap.

    A swing extremum bar at index i is "available" when computing S/R at
    bar j > i (i.e., extrema cannot be used to set S/R until they are
    confirmed; swing detection inherently looks forward by n bars, so an
    extremum at i is actually "confirmed" only at i + n. We enforce this
    with a lookback shift below.)

    Parameters
    ----------
    bars : pd.DataFrame
        Must have ``'high'``, ``'low'``, ``'close'`` columns.
    n : int
        Half-width for swing detection (passed to detect_swing_extrema).
    lookback : int
        How many prior bars to scan for S/R candidates. Counted from
        index j BACKWARD (excluding j itself).
    min_separation_pct : float
        Optional filter — extrema closer than this % to current close are
        excluded. Default 0 (no filter).

    Returns
    -------
    pd.DataFrame
        Same index as ``bars``, with columns:
          - ``resistance`` (float; NaN if no qualifying swing high)
          - ``support``    (float; NaN if no qualifying swing low)
          - ``resistance_lag_bars``  (int, NaN if no R; how many bars ago)
          - ``support_lag_bars``    (int, NaN if no S; how many bars ago)
    """
    if "close" not in bars.columns:
        raise ValueError(f"bars must have 'close' column; got {list(bars.columns)}")
    if lookback < 1:
        raise ValueError(f"lookback must be >= 1, got {lookback}")

    extrema = detect_swing_extrema(bars, n=n)
    # Confirmation lag: a swing at i is detectable only at i + n (we need
    # n bars after i to confirm strict-greater). Shift extrema so they're
    # only "visible" from i + n onward.
    high_levels = bars["high"].to_numpy()
    low_levels = bars["low"].to_numpy()
    is_high = extrema["is_swing_high"].to_numpy()
    is_low = extrema["is_swing_low"].to_numpy()
    close = bars["close"].to_numpy()
    L = len(bars)

    res = np.full(L, np.nan)
    sup = np.full(L, np.nan)
    res_lag = np.full(L, np.nan)
    sup_lag = np.full(L, np.nan)

    for j in range(L):
        if np.isnan(close[j]):
            continue
        # Window: [max(0, j - lookback), j - n) — extrema confirmed by bar j.
        # We exclude bars within n of j because their swing status isn't
        # yet confirmed at j.
        upper = j - n
        lower = max(0, j - lookback)
        if upper <= lower:
            continue

        cj = close[j]
        # Resistance: among confirmed swing highs in [lower, upper) whose
        # high value > cj, pick the one with smallest (h - cj).
        best_r_val = np.nan
        best_r_lag = np.nan
        best_s_val = np.nan
        best_s_lag = np.nan
        for i in range(upper - 1, lower - 1, -1):
            if is_high[i]:
                hv = high_levels[i]
                if hv > cj:
                    gap = hv - cj
                    if min_separation_pct > 0:
                        if (gap / cj) * 100.0 < min_separation_pct:
                            pass  # skip too-close
                        else:
                            if np.isnan(best_r_val) or gap < (best_r_val - cj):
                                best_r_val = hv
                                best_r_lag = j - i
                    else:
                        if np.isnan(best_r_val) or gap < (best_r_val - cj):
                            best_r_val = hv
                            best_r_lag = j - i
            if is_low[i]:
                lv = low_levels[i]
                if lv < cj:
                    gap = cj - lv
                    if min_separation_pct > 0:
                        if (gap / cj) * 100.0 < min_separation_pct:
                            pass
                        else:
                            if np.isnan(best_s_val) or gap < (cj - best_s_val):
                                best_s_val = lv
                                best_s_lag = j - i
                    else:
                        if np.isnan(best_s_val) or gap < (cj - best_s_val):
                            best_s_val = lv
                            best_s_lag = j - i

        res[j] = best_r_val
        sup[j] = best_s_val
        res_lag[j] = best_r_lag
        sup_lag[j] = best_s_lag

    return pd.DataFrame(
        {
            "resistance": res,
            "support": sup,
            "resistance_lag_bars": res_lag,
            "support_lag_bars": sup_lag,
        },
        index=bars.index,
    )


def distance_to_sr(
    bars: pd.DataFrame,
    n: int = 5,
    lookback: int = 20,
    min_separation_pct: float = 0.0,
) -> pd.DataFrame:
    """Signed % distance from current close to nearest support / resistance,
    plus a compression metric (R-S range as % of close).

    Returns
    -------
    pd.DataFrame
        Same index as ``bars``, with columns:
          - ``dist_to_resistance_pct``: (resistance - close) / close * 100
            (always non-negative when defined; NaN if no R)
          - ``dist_to_support_pct``:    (close - support) / close * 100
            (always non-negative when defined; NaN if no S)
          - ``sr_range_pct``:           (resistance - support) / close * 100
            (NaN if either missing); a measure of S/R "compression" — small
            values indicate price wedged between near S and near R, often
            preceding expansion.
          - ``resistance``, ``support``, ``resistance_lag_bars``,
            ``support_lag_bars`` (passed through from compute_nearest_sr).
    """
    sr = compute_nearest_sr(
        bars, n=n, lookback=lookback,
        min_separation_pct=min_separation_pct,
    )
    close = bars["close"]

    dist_r = (sr["resistance"] - close) / close * 100.0
    dist_s = (close - sr["support"]) / close * 100.0
    range_pct = (sr["resistance"] - sr["support"]) / close * 100.0

    out = pd.DataFrame(
        {
            "dist_to_resistance_pct": dist_r,
            "dist_to_support_pct": dist_s,
            "sr_range_pct": range_pct,
            "resistance": sr["resistance"],
            "support": sr["support"],
            "resistance_lag_bars": sr["resistance_lag_bars"],
            "support_lag_bars": sr["support_lag_bars"],
        },
        index=bars.index,
    )
    return out
