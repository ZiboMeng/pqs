"""Unit tests for core/ml/phase3_eval.py — chart-structure P3-A3.

The PRD-audit (2026-05-16) found P3-A3's "eval 函数有 purge 单测" clause
unmet. This is that purge unit test: it pins that a fit sample whose
horizon-ahead label lands in an OOS year IS embargoed, and that OOS
samples + interior fit samples are NOT.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.ml.phase3_eval import purged_fit_mask


def _panel_dates(start: str, end: str) -> np.ndarray:
    return pd.bdate_range(start, end).to_numpy()


def test_purge_embargoes_fit_oos_year_boundary():
    dates = _panel_dates("2016-01-04", "2017-12-29")
    yrs = np.array([pd.Timestamp(d).year for d in dates])
    keep = purged_fit_mask(
        sample_dates=dates, sample_years=yrs,
        fit_years=[2016], oos_years=[2017], horizon=21,
        all_sorted_dates=dates,
    )
    kd = pd.Series(keep, index=[pd.Timestamp(d) for d in dates])

    # late-Dec-2016 fit sample: 21 bdays ahead lands in 2017 (OOS) → drop
    assert kd[pd.Timestamp("2016-12-27")] == False  # noqa: E712
    # mid-2016 fit sample: label well inside 2016 → keep
    assert kd[pd.Timestamp("2016-06-01")] == True   # noqa: E712
    # any 2017 (OOS) sample is never embargoed
    assert kd[pd.Timestamp("2017-03-15")] == True   # noqa: E712
    assert kd[pd.Timestamp("2017-12-15")] == True   # noqa: E712


def test_purge_only_drops_within_horizon_of_boundary():
    dates = _panel_dates("2016-11-01", "2017-02-28")
    yrs = np.array([pd.Timestamp(d).year for d in dates])
    keep = purged_fit_mask(
        dates, yrs, fit_years=[2016], oos_years=[2017],
        horizon=21, all_sorted_dates=dates,
    )
    # exactly the last 21 trading rows of 2016 are dropped (their +21
    # label crosses into 2017); everything before is kept.
    d2016 = [pd.Timestamp(d) for d in dates if pd.Timestamp(d).year == 2016]
    dropped = [d for d, k in zip(
        [pd.Timestamp(x) for x in dates], keep) if not k]
    assert all(d.year == 2016 for d in dropped)
    assert len(dropped) == 21
    assert min(d2016) not in dropped  # early-Nov kept


def test_purge_noop_when_no_adjacent_oos_year():
    dates = _panel_dates("2016-01-04", "2016-12-30")
    yrs = np.array([pd.Timestamp(d).year for d in dates])
    keep = purged_fit_mask(
        dates, yrs, fit_years=[2016], oos_years=[2024],
        horizon=21, all_sorted_dates=dates,
    )
    assert keep.all()  # 2024 not reachable from 2016 by 21 bdays
