"""PRD-3 RA1 — A1 engineered stationary features (assembly module).

The highest-ROI signal arm per the 4-agent literature synthesis
(Grinsztajn/Krauss/ROCKET): engineered *stationary* features + a
shallow tree, with the frozen-probe embedding stacked on later (RA2).

Scope is honestly grounded (same R4/R6/R7 pattern as PRD-2): this
module **delegates** to canonical implementations that already exist
and does NOT reimplement them —

  * fractional-differenced price → ``core.ml.feature_prep.frac_diff_ffd``
    (Lopez de Prado AFML ch.5, look-ahead-safe).
  * Family T swing-structure → ``core.factors.swing_structure``
    (registry-resident; consumed by ``build_engineered_panel`` callers
    via the factor registry, not duplicated here).
  * S/R proxy → ``dist_from_new_high_252`` / ``dist_to_swing_*``
    (``core.factors.factor_generator``).
  * sample-uniqueness + purge/embargo → ``core.research.label_leakage``
    (PRD-1 P1.1 canonical SoT; this module exposes thin pass-throughs
    so RA2/RA3 wire leakage through ONE helper).

The genuinely-new RA1 surface implemented here:
  * ``close_pos_in_range`` — JKX-style implicit per-name scaling: the
    close's bounded [0,1] position inside its own trailing high-low
    band, multi-window. This is the cheap analogue of the image
    arm's implicit per-name normalization (JKX 2023), NOT the
    unbounded ``close/max - 1`` of ``dist_from_new_high_252``.
  * stationary K-line ``body`` / ``upper_wick`` / ``lower_wick`` /
    ``gap`` ratios (range-normalized → cross-name comparable).
  * trailing ``volume_z``.
  * the assembly + cross-sectional / monthly-cross-sectional rank.

All primitives are causal (trailing windows / ``shift(1)`` only) →
no look-ahead, and bounded/normalized → stationary across names.
"""
from __future__ import annotations

from typing import Dict, Iterable, Sequence, Set

import numpy as np
import pandas as pd

from core.ml.feature_prep import frac_diff_ffd
from core.research.label_leakage import (
    average_uniqueness_weights,
    purge_embargo_mask,
)

__all__ = [
    "close_pos_in_range",
    "kline_shape",
    "volume_z",
    "frac_diff_price",
    "cross_sectional_rank",
    "monthly_cross_sectional_rank",
    "build_engineered_panel",
    "engineered_sample_weights",
    "engineered_purge_mask",
]


# ── JKX normalized geometry ───────────────────────────────────────────
def close_pos_in_range(
    close_df: pd.DataFrame,
    windows: Sequence[int] = (20, 63, 126),
) -> Dict[str, pd.DataFrame]:
    """Bounded [0,1] position of close inside its trailing band.

    For each window ``w``::

        pos_t = (c_t - min(c[t-w+1..t])) / (max(...) - min(...))

    Trailing rolling (``min_periods=w``) → causal (no look-ahead).
    A degenerate flat window (max == min) yields NaN — never a fake
    0.5 (no information must not masquerade as a mid signal).
    """
    out: Dict[str, pd.DataFrame] = {}
    for w in windows:
        rmin = close_df.rolling(w, min_periods=w).min()
        rmax = close_df.rolling(w, min_periods=w).max()
        rng = rmax - rmin
        pos = (close_df - rmin) / rng
        pos = pos.where(rng > 0)  # max==min → NaN
        out[f"w{w}"] = pos
    return out


# ── K-line stationary shape ───────────────────────────────────────────
def kline_shape(
    open_df: pd.DataFrame,
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    close_df: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """Range-normalized candle geometry (cross-name comparable).

    ``body`` ∈ [-1,1] = (close-open)/range; ``upper_wick`` /
    ``lower_wick`` ∈ [0,1]; ``gap`` = (open - prev_close)/prev_close
    (``shift(1)`` → causal). range==0 → NaN.
    """
    rng = (high_df - low_df)
    safe = rng.where(rng > 0)
    max_co = pd.DataFrame(np.maximum(close_df.to_numpy(),
                                     open_df.to_numpy()),
                          index=close_df.index, columns=close_df.columns)
    min_co = pd.DataFrame(np.minimum(close_df.to_numpy(),
                                     open_df.to_numpy()),
                          index=close_df.index, columns=close_df.columns)
    prev_c = close_df.shift(1)
    return {
        "body": (close_df - open_df) / safe,
        "upper_wick": (high_df - max_co) / safe,
        "lower_wick": (min_co - low_df) / safe,
        "gap": (open_df - prev_c) / prev_c,
    }


# ── volume z ──────────────────────────────────────────────────────────
def volume_z(volume_df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Trailing z-score of volume (causal; ``min_periods=window``)."""
    m = volume_df.rolling(window, min_periods=window).mean()
    s = volume_df.rolling(window, min_periods=window).std(ddof=1)
    return (volume_df - m) / s


# ── fractional-differenced price (DELEGATED, not reimplemented) ───────
def frac_diff_price(close_df: pd.DataFrame, d: float = 0.4,
                    thres: float = 1e-4) -> pd.DataFrame:
    """Per-symbol fixed-width fractional difference of close.

    Honest delegation to ``core.ml.feature_prep.frac_diff_ffd``
    (Lopez de Prado AFML ch.5) — stationary yet memory-preserving.
    """
    cols = {c: frac_diff_ffd(close_df[c], d, thres)
            for c in close_df.columns}
    return pd.DataFrame(cols, index=close_df.index)[list(close_df.columns)]


# ── cross-sectional / monthly rank ────────────────────────────────────
def cross_sectional_rank(df: pd.DataFrame) -> pd.DataFrame:
    """Per-date rank ACROSS symbols (axis=1), pct in (0,1]."""
    return df.rank(axis=1, pct=True)


def _month_end_rows(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(idx, index=idx)
    return pd.DatetimeIndex(
        s.groupby([idx.year, idx.month]).last().to_numpy())


def monthly_cross_sectional_rank(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional rank carried ONLY on month-end business rows
    (the monthly-rebalance cadence); all other rows NaN."""
    me = _month_end_rows(df.index)
    out = pd.DataFrame(np.nan, index=df.index, columns=df.columns)
    me_in = df.index.isin(me)
    out.loc[me_in] = df.loc[me_in].rank(axis=1, pct=True)
    return out


# ── assembly ──────────────────────────────────────────────────────────
def build_engineered_panel(
    open_df: pd.DataFrame,
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    close_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    close_windows: Sequence[int] = (20, 63, 126),
    volume_window: int = 20,
    frac_d: float = 0.4,
    monthly_rank: bool = False,
) -> Dict[str, pd.DataFrame]:
    """Assemble the A1 engineered stationary feature map.

    Keys: ``close_pos_w{w}`` per window, ``kline_{body,upper_wick,
    lower_wick,gap}``, ``volume_z{window}``, ``frac_diff_close``.
    ``monthly_rank=True`` → each feature is monthly cross-sectionally
    ranked (pct in (0,1] on month-end rows; NaN elsewhere).
    """
    feats: Dict[str, pd.DataFrame] = {}
    for w, df in close_pos_in_range(close_df, close_windows).items():
        feats[f"close_pos_{w}"] = df
    ks = kline_shape(open_df, high_df, low_df, close_df)
    for k, df in ks.items():
        feats[f"kline_{k}"] = df
    feats[f"volume_z{volume_window}"] = volume_z(volume_df, volume_window)
    feats["frac_diff_close"] = frac_diff_price(close_df, frac_d)
    if monthly_rank:
        feats = {k: monthly_cross_sectional_rank(v)
                 for k, v in feats.items()}
    return feats


# ── leakage-correct wiring: thin pass-throughs to the canonical SoT ──
def engineered_sample_weights(
    start_pos: np.ndarray,
    horizon: int,
    groups: np.ndarray | None = None,
) -> np.ndarray:
    """RA1 leakage wiring — delegates to the PRD-1 P1.1 canonical
    ``core.research.label_leakage.average_uniqueness_weights`` so
    RA2/RA3 fit on overlapping-label-downweighted samples through
    ONE helper (no duplicate uniqueness math)."""
    return average_uniqueness_weights(start_pos, horizon, groups=groups)


def engineered_purge_mask(
    t_pos: np.ndarray,
    year_of_pos: Iterable[int],
    horizon: int,
    holdout_years: Set[int],
    embargo: int = 5,
) -> np.ndarray:
    """RA1 leakage wiring — delegates to the canonical
    ``core.research.label_leakage.purge_embargo_mask``."""
    return purge_embargo_mask(t_pos, year_of_pos, horizon,
                              holdout_years, embargo=embargo)
