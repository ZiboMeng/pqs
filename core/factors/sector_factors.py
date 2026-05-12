"""Sector-relative factor family (Bucket C, PRD 2026-05-12).

Inputs: price_df (close panel), sector mapping via SectorResolver
(PIT-aware reclassification). Outputs: cross-sectional sector-relative
metrics + sector breadth / dispersion stats.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.data.sector_resolver import SectorResolver

logger = logging.getLogger(__name__)


SECTOR_FACTOR_NAMES = [
    "sector_rel_mom_20d",
    "sector_neutral_drawup_252d",
    "sector_leader_rank_mom_12_1",
    "sector_breadth_pct_5d",
    "sector_dispersion_std_20d",
]


def _sector_median_panel(
    daily_panel: pd.DataFrame,
    sector_panel: pd.DataFrame,
) -> pd.DataFrame:
    """For each (date, ticker), compute sector-mate median value.

    daily_panel : (date × ticker) of values to median over
    sector_panel: (date × ticker) of sector names (string)
    Returns same-shape DataFrame: each cell = median of daily_panel cells
    in same row whose sector_panel value matches the cell's sector.
    Tickers with no sector (NaN) or sector == 'etf' get NaN.
    """
    out = pd.DataFrame(np.nan, index=daily_panel.index, columns=daily_panel.columns)
    # For each date, group by sector and compute medians; broadcast back
    for d in daily_panel.index:
        row_vals = daily_panel.loc[d]
        row_sectors = sector_panel.loc[d]
        # Build sector → median dict
        df = pd.DataFrame({"v": row_vals, "s": row_sectors}).dropna(subset=["s"])
        df = df[df["s"] != "etf"]
        if df.empty:
            continue
        med_by_sector = df.groupby("s")["v"].median()
        # Broadcast back
        mapped = row_sectors.map(med_by_sector)
        out.loc[d] = mapped
    return out


def compute_sector_factors(
    price_df: pd.DataFrame,
    resolver: Optional[SectorResolver] = None,
) -> Dict[str, pd.DataFrame]:
    """Compute 5 sector-relative factors.

    Sign convention (PQS): higher value → expected higher forward
    return. Mining infers IC sign from history.
    """
    resolver = resolver or SectorResolver()
    factors: Dict[str, pd.DataFrame] = {}

    tickers = list(price_df.columns)
    daily_ret = price_df.pct_change()

    # PIT sector panel
    sector_panel = resolver.panel_classifications(tickers, price_df.index)

    # 1. sector_rel_mom_20d: stock 20d ret - sector median 20d ret
    mom_20 = price_df.pct_change(20)
    sec_median_20 = _sector_median_panel(mom_20, sector_panel)
    factors["sector_rel_mom_20d"] = mom_20 - sec_median_20

    # 2. sector_neutral_drawup_252d: stock (close - 252d_min) / 252d_min
    #    minus sector median of same quantity
    rolling_min_252 = price_df.rolling(252, min_periods=63).min()
    drawup = (price_df - rolling_min_252) / rolling_min_252.replace(0, np.nan)
    sec_median_drawup = _sector_median_panel(drawup, sector_panel)
    factors["sector_neutral_drawup_252d"] = drawup - sec_median_drawup

    # 3. sector_leader_rank_mom_12_1: cross-sectional rank of 12-1 momentum
    #    WITHIN each sector at each date (1 = best, n = worst; pct-rank for
    #    cross-sector comparability)
    # 12-1 momentum: 12-month return excluding most recent month
    mom_12_1 = price_df.pct_change(252) - price_df.pct_change(21)
    leader_rank = pd.DataFrame(np.nan, index=mom_12_1.index, columns=mom_12_1.columns)
    for d in mom_12_1.index:
        row_vals = mom_12_1.loc[d]
        row_sectors = sector_panel.loc[d]
        df = pd.DataFrame({"v": row_vals, "s": row_sectors}).dropna(subset=["s", "v"])
        df = df[df["s"] != "etf"]
        if df.empty:
            continue
        df["rank"] = df.groupby("s")["v"].rank(pct=True, ascending=True)
        leader_rank.loc[d, df.index] = df["rank"].values
    factors["sector_leader_rank_mom_12_1"] = leader_rank

    # 4. sector_breadth_pct_5d: in each sector, what % of members had
    #    positive 5d return? Broadcast to each ticker in sector.
    ret_5d = price_df.pct_change(5)
    breadth = pd.DataFrame(np.nan, index=ret_5d.index, columns=ret_5d.columns)
    for d in ret_5d.index:
        row_vals = ret_5d.loc[d]
        row_sectors = sector_panel.loc[d]
        df = pd.DataFrame({"v": row_vals, "s": row_sectors}).dropna(subset=["s"])
        df = df[df["s"] != "etf"]
        if df.empty:
            continue
        df["pos"] = (df["v"] > 0).astype(float)
        pct_by_sector = df.groupby("s")["pos"].mean()
        mapped = row_sectors.map(pct_by_sector)
        breadth.loc[d] = mapped
    factors["sector_breadth_pct_5d"] = breadth

    # 5. sector_dispersion_std_20d: 20d std of daily returns within
    #    each sector. Broadcast to each ticker.
    sec_disp = pd.DataFrame(np.nan, index=daily_ret.index, columns=daily_ret.columns)
    # Rolling per sector — compute by aggregating within-sector daily
    # cross-sectional std for each date, then rolling-mean 20d
    daily_cross_std = pd.DataFrame(np.nan, index=daily_ret.index, columns=daily_ret.columns)
    for d in daily_ret.index:
        row_vals = daily_ret.loc[d]
        row_sectors = sector_panel.loc[d]
        df = pd.DataFrame({"v": row_vals, "s": row_sectors}).dropna(subset=["s"])
        df = df[df["s"] != "etf"]
        if df.empty:
            continue
        std_by_sector = df.groupby("s")["v"].std()
        mapped = row_sectors.map(std_by_sector)
        daily_cross_std.loc[d] = mapped
    # Take 20d rolling mean of daily cross-sectional std to get
    # short-window dispersion estimate.
    factors["sector_dispersion_std_20d"] = daily_cross_std.rolling(20).mean()

    return factors
