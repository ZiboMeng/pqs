"""PRD-1 P1.1 — canonical leakage-correct label helpers.

López de Prado, *Advances in Financial Machine Learning* (2018):
- Ch.4 average uniqueness: overlapping forward-return labels share
  future bars; uniform-weight fitting over-counts the overlap and
  inflates IC / Track-A. Down-weight each sample by its average
  uniqueness (mean of 1/concurrency over its label window).
- Ch.7 purge + embargo: a training row whose label window reaches
  into a holdout (validation/sealed) year leaks; purge it (plus an
  embargo buffer).

PRD-1 §2 / cross-audit §C contract: these act on the **probe-fit /
sample layer ONLY**. They MUST NOT alter `cpcv_acceptance` §3
fold-aggregation sample-SIZE weighting (a different layer; §3 bans
discretionary recency/regime fold weighting — uniqueness is a
principled overlapping-label bias correction, not a discretionary
DOF, so §3's rationale does not apply and the two layers are
orthogonal).

Extracted + generalized from the run4-validated prototype in
dev/scripts/chart_native_l3/run_chart_native_l3_track_a.py.
"""
from __future__ import annotations

from typing import Iterable, Optional, Set

import numpy as np


def average_uniqueness_weights(
    start_pos: np.ndarray,
    horizon: int,
    groups: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Mean-normalized average-uniqueness sample weights.

    Parameters
    ----------
    start_pos : int array, label-window start position (per group's
        own time axis). Label window = ``[p, p + horizon]`` inclusive.
    horizon : forward-return horizon H (window spans H+1 positions).
    groups : optional per-sample group id (e.g. symbol). Concurrency
        is computed WITHIN a group only (cross-symbol labels never
        overlap). ``None`` → single group.

    Returns
    -------
    weights aligned to ``start_pos``, mean-normalized to 1.0. Empty
    in → empty out; weight ∝ mean(1/concurrency over the label window).
    """
    start_pos = np.asarray(start_pos)
    n = len(start_pos)
    if n == 0:
        return np.empty((0,), float)
    sp = start_pos.astype(int)
    w = np.ones(n, float)
    if groups is None:
        grp_iter = [np.arange(n)]
    else:
        groups = np.asarray(groups)
        grp_iter = [np.where(groups == g)[0] for g in np.unique(groups)]
    for idx in grp_iter:
        if idx.size == 0:
            continue
        gpos = sp[idx]
        span = int(gpos.max()) + horizon + 1
        conc = np.zeros(span, float)
        for p in gpos:
            conc[p:p + horizon + 1] += 1.0
        for k, p in enumerate(gpos):
            seg = conc[p:p + horizon + 1]
            seg = seg[seg > 0]
            w[idx[k]] = float(np.mean(1.0 / seg)) if seg.size else 1.0
    m = w.mean()
    return w / m if m > 0 else w


def purge_embargo_mask(
    t_pos: np.ndarray,
    year_of_pos: Iterable[int],
    horizon: int,
    holdout_years: Set[int],
    embargo: int = 5,
) -> np.ndarray:
    """Keep-mask: ``True`` = the training row's label window
    ``[p, p + horizon + embargo]`` (clipped at the panel end) does
    NOT reach into any ``holdout_years`` → safe to fit on. ``False``
    = purged (label leaks into a holdout year).

    Empty ``t_pos`` → empty mask.
    """
    t_pos = np.asarray(t_pos)
    if len(t_pos) == 0:
        return np.empty((0,), bool)
    yrs = list(year_of_pos)
    n = len(yrs)
    hold = set(holdout_years)
    keep = np.ones(len(t_pos), bool)
    for i, p in enumerate(t_pos.astype(int)):
        hi = min(p + horizon + embargo, n - 1)
        if any(yrs[q] in hold for q in range(p, hi + 1)):
            keep[i] = False
    return keep
