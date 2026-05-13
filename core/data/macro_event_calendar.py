"""Macro event calendar (FOMC / CPI / NFP) for window-flag factors.

PRD 2026-05-12 Bucket A T1 batch 3 deferred items (Round D).

Calendar generation strategy:
  - **NFP** (Non-Farm Payrolls): exact rule — first Friday of each month.
    Generated algorithmically.
  - **CPI** (Consumer Price Index): approximation — second Tuesday of
    each month (real release day varies between 8th-15th business day
    of the month). Window-flag factor robustness: 2-day window catches
    most real release dates.
  - **FOMC** (Federal Open Market Committee): heuristic — 8 meetings
    per year, approximately every 6-7 weeks. Real schedule varies
    year-to-year. Defaults to a fixed grid; overridable via
    `config/macro_event_calendar.yaml::fomc_dates` (list of YYYY-MM-DD
    strings) for higher precision.

Caveats:
  - For mining / IC research, the heuristic approximation is acceptable
    (alpha-on-anticipation captures ±2 trading day window anyway).
  - For execution-grade timing, FOMC dates MUST be curated from
    federalreserve.gov. NFP / CPI heuristics are within ±2 trading
    days of truth.
  - Pre-2020 emergency FOMC meetings (March 2020 covid, January 2008
    inter-meeting cut) are NOT in heuristic — only yaml-override path
    catches them.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import pandas as pd
import yaml

logger = logging.getLogger(__name__)


def first_friday_of_month(year: int, month: int) -> pd.Timestamp:
    """Return the first Friday of a calendar month (NFP release rule)."""
    first = pd.Timestamp(year=year, month=month, day=1)
    # weekday(): Monday=0 ... Sunday=6. Friday=4.
    days_to_friday = (4 - first.weekday()) % 7
    return first + pd.Timedelta(days=days_to_friday)


def second_tuesday_of_month(year: int, month: int) -> pd.Timestamp:
    """Approximate CPI release date — second Tuesday of month.

    Real release day varies 8th-15th business day; window-flag factor
    accepts this approximation (within ±2 day window).
    """
    first = pd.Timestamp(year=year, month=month, day=1)
    days_to_tuesday = (1 - first.weekday()) % 7
    first_tuesday = first + pd.Timedelta(days=days_to_tuesday)
    return first_tuesday + pd.Timedelta(days=7)


def generate_nfp_dates(start_year: int, end_year: int) -> List[pd.Timestamp]:
    """All first-Fridays in range [start_year, end_year] inclusive."""
    out = []
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            out.append(first_friday_of_month(y, m))
    return out


def generate_cpi_dates(start_year: int, end_year: int) -> List[pd.Timestamp]:
    """All approximated second-Tuesdays in range. Real day varies ±5."""
    out = []
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            out.append(second_tuesday_of_month(y, m))
    return out


def generate_fomc_dates_heuristic(
    start_year: int, end_year: int,
) -> List[pd.Timestamp]:
    """Heuristic FOMC schedule: 8 meetings/year at fixed weeks.

    Approximate weeks (Wednesday of each):
      W4 / W11 / W18 / W26 / W33 / W41 / W48 / W52 (or close).

    Production users should curate `config/macro_event_calendar.yaml`
    with real FOMC dates from federalreserve.gov for higher precision.
    """
    out = []
    target_weeks = [4, 11, 18, 26, 33, 41, 48, 52]
    for y in range(start_year, end_year + 1):
        for w in target_weeks:
            # Wednesday of the target week
            jan1 = pd.Timestamp(year=y, month=1, day=1)
            # Use ISO week + Wednesday weekday (3 in iso, 2 in python)
            try:
                d = pd.Timestamp.fromisocalendar(y, w, 3)
                if d.year == y:  # avoid week 52 spilling to next year
                    out.append(d)
            except ValueError:
                continue
    return out


def load_calendar(
    yaml_path: str = "config/macro_event_calendar.yaml",
    start_year: int = 2008,
    end_year: int = 2027,
) -> dict[str, List[pd.Timestamp]]:
    """Load macro event calendar; yaml overrides supersede heuristics.

    Returns:
        {
            'fomc': [Timestamp, ...],
            'cpi':  [Timestamp, ...],
            'nfp':  [Timestamp, ...],
        }
    """
    calendar = {
        "fomc": generate_fomc_dates_heuristic(start_year, end_year),
        "cpi": generate_cpi_dates(start_year, end_year),
        "nfp": generate_nfp_dates(start_year, end_year),
    }
    path = Path(yaml_path)
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        for key in ("fomc", "cpi", "nfp"):
            if key in data and data[key]:
                # yaml dates override heuristic
                override = [pd.Timestamp(d) for d in data[key]]
                calendar[key] = sorted(override)
                logger.info("Loaded %d %s dates from yaml override", len(override), key)
    return calendar


def window_flag_panel(
    event_dates: List[pd.Timestamp],
    daily_idx: pd.DatetimeIndex,
    tickers: List[str],
    bars_before: int = 2,
    bars_after: int = 0,
) -> pd.DataFrame:
    """Build a (date × ticker) panel where cells in [event - bars_before,
    event + bars_after] are 1.0 and others are 0.0.

    Uses business-day arithmetic — event_dates are real calendar dates;
    bars_before counts trading days backward.
    """
    import numpy as np
    flag = pd.Series(0.0, index=daily_idx)
    for evt in event_dates:
        if evt not in daily_idx:
            # Snap to nearest prior business day
            valid = daily_idx[daily_idx <= evt]
            if len(valid) == 0:
                continue
            evt = valid[-1]
        pos = daily_idx.get_loc(evt)
        if isinstance(pos, slice):
            continue
        start = max(0, pos - bars_before)
        end = min(len(daily_idx) - 1, pos + bars_after)
        flag.iloc[start:end + 1] = 1.0
    # Broadcast to (date × ticker)
    panel = pd.DataFrame(
        np.tile(flag.values[:, None], (1, len(tickers))),
        index=daily_idx, columns=tickers,
    )
    return panel
