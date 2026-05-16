"""Phase 3 eval purge helper — chart-structure P3-A3 (PRD-audit 2026-05-16).

Main PRD §5.6 P3-A3 requires the eval to run "purged WF + 真实成本 +
换手惩罚" AND that "eval 函数有 purge 单测". The P3·R2/R4/R5 attempt
runners use a year-block fit/OOS split (fit years vs disjoint OOS years).
A year-block split still leaks at a fit-year that *directly precedes* an
OOS year: a fit sample dated late-December has a 21d forward-return label
that lands in the next (OOS) calendar year, so the model trains on a
label derived from OOS-year price action.

`purged_fit_mask` removes exactly those boundary fit samples whose
``horizon``-bar-ahead label end falls in an OOS year — a panel-driven
embargo (uses the real trading-day index, not calendar days). OOS
samples are never touched. This is conclusion-conservative: dropping
leaked fit samples can only *weaken* a chart-native model, so any
pre-purge negative verdict stands at least as strongly post-purge.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np


def purged_fit_mask(
    sample_dates: np.ndarray,
    sample_years: np.ndarray,
    fit_years: Iterable[int],
    oos_years: Iterable[int],
    horizon: int,
    all_sorted_dates: np.ndarray,
) -> np.ndarray:
    """Boolean mask over samples: True = keep (not a leaking fit sample).

    A sample is dropped iff its year is a fit year AND the trading day
    ``horizon`` rows ahead of its date (in ``all_sorted_dates``) falls
    in an OOS year. OOS-year samples are always kept (mask True) — the
    embargo only prunes the training side.
    """
    fit_set = set(int(y) for y in fit_years)
    oos_set = set(int(y) for y in oos_years)
    sorted_dates = np.asarray(all_sorted_dates)
    pos = {d: i for i, d in enumerate(sorted_dates)}
    last = len(sorted_dates) - 1

    keep = np.ones(len(sample_dates), dtype=bool)
    for k in range(len(sample_dates)):
        yr = int(sample_years[k])
        if yr not in fit_set:
            continue  # OOS / other — never embargoed
        i = pos.get(sample_dates[k])
        if i is None:
            continue
        label_end = sorted_dates[min(i + horizon, last)]
        end_yr = label_end.year if hasattr(label_end, "year") else \
            np.datetime64(label_end, "Y").astype(int) + 1970
        if int(end_yr) in oos_set:
            keep[k] = False
    return keep
