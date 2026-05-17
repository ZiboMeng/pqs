"""R1 — literature-grade labeling layer (supplementary PRD §4).

Per literature review §1.B [S5][S8]. Phase 3 naive attempts used a bare
21-day forward return as the label, which (a) overlaps across samples
(21-day horizons of adjacent days share ~95% of their window → samples
are NOT independent, inflating effective sample size and miscalibrating
paired tests) and (b) ignores path (a +X% that first drew down -Y%).

This module adds the two López de Prado labeling primitives:

- ``concurrency_weights`` / ``avg_uniqueness``: per-sample weight =
  mean reciprocal label concurrency over its lifespan. Independent
  sample → 1.0; fully overlapping → →0. Use as sample_weight (or
  bagging max_samples).
- ``triple_barrier_labels``: upper (profit) / lower (stop) / vertical
  (expiry) barriers → {+1, 0, -1}; barrier widths scale with trailing
  realized vol × a config multiplier.

The bare 21d forward return is retained as the control label (callers
keep using ``compute_forward_returns``) for A/B comparison — this module
does not delete it.

Config-sourced (`config/ml_labeling.yaml`); causal (label of bar t uses
only [t, t+h]).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def concurrency_count(index: pd.DatetimeIndex, horizon: int) -> pd.Series:
    """Number of label windows live at each bar.

    Sample i spans bars [i, i+horizon]. Concurrency at bar b = #samples
    whose [start, end] contains b. O(n) via a +1/-1 sweep.
    """
    n = len(index)
    delta = np.zeros(n + 1, dtype=float)
    for i in range(n):
        end = min(i + horizon, n - 1)
        delta[i] += 1.0
        delta[end + 1] -= 1.0
    conc = np.cumsum(delta[:n])
    return pd.Series(conc, index=index)


def avg_uniqueness(index: pd.DatetimeIndex, horizon: int) -> pd.Series:
    """Per-sample average uniqueness = mean over [i, i+h] of 1/concurrency.

    Independent (non-overlapping) sample → 1.0; sample whose whole
    lifespan is shared with many others → →0. [S5][S8]
    """
    conc = concurrency_count(index, horizon).to_numpy()
    n = len(index)
    inv = np.where(conc > 0, 1.0 / conc, 0.0)
    out = np.zeros(n)
    for i in range(n):
        end = min(i + horizon, n - 1)
        seg = inv[i: end + 1]
        out[i] = seg.mean() if len(seg) else 0.0
    return pd.Series(out, index=index)


def concurrency_weights(index: pd.DatetimeIndex, horizon: int) -> pd.Series:
    """Sample weights = normalized average uniqueness (mean ≈ 1).

    Normalizing so the weights average ~1 keeps loss scale comparable
    to the unweighted baseline (only the relative down-weighting of
    overlapping samples matters).
    """
    u = avg_uniqueness(index, horizon)
    m = u.mean()
    return u / m if m > 0 else u


def triple_barrier_labels(
    close: pd.Series,
    horizon: int,
    pt_mult: float,
    sl_mult: float,
    vol_lookback: int,
) -> pd.DataFrame:
    """Triple-barrier label for one symbol's close series. [S5][S8]

    For each bar t: upper barrier = +pt_mult·σ_t, lower = -sl_mult·σ_t
    (σ_t = trailing realized vol over ``vol_lookback``, causal: uses
    returns up to t), vertical barrier = t+horizon. Returns DataFrame
    with columns ``label`` ∈ {+1,0,-1}, ``touch_idx``, ``ret`` (return
    at the touched bar). Causal: only bars in [t, t+horizon] are read.
    """
    px = close.to_numpy(dtype=float)
    ret = np.diff(np.log(np.where(px > 0, px, np.nan)))
    vol = pd.Series(ret).rolling(vol_lookback,
                                 min_periods=max(2, vol_lookback // 2)).std()
    vol = np.concatenate([[np.nan], vol.to_numpy()])  # align to px length
    n = len(px)
    lab = np.zeros(n)
    touch = np.full(n, -1, dtype=int)
    rr = np.full(n, np.nan)
    for t in range(n):
        s = vol[t]
        if not np.isfinite(s) or s <= 0 or not np.isfinite(px[t]) or px[t] <= 0:
            lab[t] = np.nan
            continue
        up = px[t] * np.exp(pt_mult * s)
        dn = px[t] * np.exp(-sl_mult * s)
        end = min(t + horizon, n - 1)
        hit = 0
        for j in range(t + 1, end + 1):
            if not np.isfinite(px[j]):
                continue
            if px[j] >= up:
                hit, touch[t] = 1, j
                break
            if px[j] <= dn:
                hit, touch[t] = -1, j
                break
        if touch[t] == -1:
            touch[t] = end
        lab[t] = hit
        if px[t] > 0 and np.isfinite(px[touch[t]]):
            rr[t] = px[touch[t]] / px[t] - 1.0
    return pd.DataFrame({"label": lab, "touch_idx": touch, "ret": rr},
                        index=close.index)
