"""S3 / R2 — canonical multiplicative ML sample weighting
(PRD 20260521 §8.2; supplement 20260522 S3).

Audit finding R2: master §8.2 mandates a multiplicative sample weight
threaded through ML training, default-on; the prior code shipped none
(uniform weighting), so overlapping 21-day labels inflated the effective
sample size and noisy / illiquid samples carried full weight.

`sample_weight = uniqueness × liquidity × volatility × freshness`

  uniqueness — per-date overlapping-label decay (López de Prado);
               reuses core/ml/labeling.concurrency_weights.
  liquidity  — per-(date,symbol); trailing share-volume, cross-
               sectionally normalised (illiquid names down-weighted).
  volatility — per-(date,symbol) INVERSE vol, winsorized (§3.3 /
               AUDIT-2026-05-21 — a noisier sample is down-weighted).
  freshness  — per-date exponential recency decay (half-life in bars).

Each component is normalised to mean ≈ 1, so the product is an
interpretable multiplier and disabling a component ≈ multiplying by 1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "uniqueness_weight", "liquidity_weight", "volatility_weight",
    "freshness_weight", "sample_weight", "COMPONENT_FORMULAS",
]

# §8.4 auditability — recorded verbatim into the artifact governance.
COMPONENT_FORMULAS = {
    "uniqueness": "concurrency_weights(index, horizon) — mean reciprocal "
                  "label concurrency over [i, i+horizon]",
    "liquidity": "rolling(liq_lookback) mean volume, per-date cross-"
                 "sectionally normalised to mean 1",
    "volatility": "1 / rolling(vol_lookback) std of returns, winsorized "
                  "per-date at [winsor, 1-winsor], normalised to mean 1",
    "freshness": "0.5 ** (age_bars / half_life), normalised to mean 1",
    "combination": "multiplicative; product normalised to mean ≈ 1",
}


def _min_periods(lookback: int) -> int:
    return max(2, lookback // 3)


def uniqueness_weight(index: pd.DatetimeIndex, horizon: int) -> pd.Series:
    """Per-date overlapping-label uniqueness, normalised mean ≈ 1."""
    from core.ml.labeling import concurrency_weights
    return concurrency_weights(index, horizon)


def liquidity_weight(volume: pd.DataFrame, lookback: int = 21) -> pd.DataFrame:
    """Per-(date,symbol) liquidity weight — trailing mean share volume,
    cross-sectionally normalised so each date's row averages 1."""
    vt = volume.rolling(lookback, min_periods=_min_periods(lookback)).mean()
    row_mean = vt.mean(axis=1).replace(0.0, np.nan)
    return vt.div(row_mean, axis=0)


def volatility_weight(close: pd.DataFrame, lookback: int = 21,
                      winsor: float = 0.05) -> pd.DataFrame:
    """Per-(date,symbol) INVERSE-vol weight, winsorized (§3.3 / AUDIT):
    a noisier (high-vol) sample is down-weighted. Normalised per date."""
    vol = close.pct_change().rolling(
        lookback, min_periods=_min_periods(lookback)).std()
    inv = 1.0 / vol.replace(0.0, np.nan)
    lo = inv.quantile(winsor, axis=1)
    hi = inv.quantile(1.0 - winsor, axis=1)
    inv_w = inv.clip(lower=lo, upper=hi, axis=0)
    row_mean = inv_w.mean(axis=1).replace(0.0, np.nan)
    return inv_w.div(row_mean, axis=0)


def freshness_weight(index: pd.DatetimeIndex, half_life: int) -> pd.Series:
    """Per-date exponential recency weight (most recent bar = highest),
    half-life in bars. Normalised mean ≈ 1."""
    if half_life <= 0:
        raise ValueError(f"half_life must be > 0, got {half_life}")
    age = np.arange(len(index))[::-1].astype(float)   # last bar → age 0
    w = pd.Series(0.5 ** (age / half_life), index=index)
    m = w.mean()
    return w / m if m else w


def sample_weight(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    horizon: int,
    *,
    half_life: int = 252,
    vol_lookback: int = 21,
    liq_lookback: int = 21,
    winsor: float = 0.05,
    normalized: bool = True,
) -> pd.DataFrame:
    """Canonical multiplicative sample weight (master §8.2).

    Returns a (date × symbol) weight panel. uniqueness + freshness are
    per-date (broadcast across symbols); liquidity + volatility are
    per-(date,symbol). The product is normalised to mean ≈ 1 unless
    ``normalized=False``.
    """
    u = uniqueness_weight(close.index, horizon)            # per-date
    liq = liquidity_weight(volume, liq_lookback)           # date × symbol
    volw = volatility_weight(close, vol_lookback, winsor)  # date × symbol
    fw = freshness_weight(close.index, half_life)           # per-date
    w = liq.mul(u, axis=0).mul(fw, axis=0) * volw
    if normalized:
        m = float(np.nanmean(w.to_numpy()))
        if m and np.isfinite(m):
            w = w / m
    return w
