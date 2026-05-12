"""PIT GICS sector / industry resolver.

PRD 2026-05-12 (Bucket C). Reads `config/sector_map.yaml`; resolves
ticker → (sector, industry) with point-in-time correctness for known
historical reclassifications (e.g. META + GOOGL Tech → Communication
Services on 2018-09-28).
"""

from __future__ import annotations

import logging
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd
import yaml

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_sector_yaml(path: str = "config/sector_map.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


class SectorResolver:
    """Resolve ticker → GICS sector/industry at a given date.

    Default current state from `sector_map`; reclassifications stored
    as a list of {symbol, from_sector, to_sector, from_industry, to_industry,
    effective_date}. Before effective_date, return `from_*`; on/after,
    return `to_*` (which should agree with sector_map's "current" value).
    """

    def __init__(self, config_path: str = "config/sector_map.yaml"):
        cfg = _load_sector_yaml(config_path)
        self.sector_map: Dict[str, dict] = cfg.get("sector_map", {})
        self.reclass: list = cfg.get("historical_reclassifications", []) or []

    def get(self, ticker: str, as_of: Optional[date] = None) -> Tuple[Optional[str], Optional[str]]:
        """Return (sector, industry) for ticker at `as_of`. If as_of is
        None, return current classification."""
        ticker = ticker.upper()
        if ticker not in self.sector_map:
            return None, None
        current = self.sector_map[ticker]
        current_sector = current.get("sector")
        current_industry = current.get("industry")

        if as_of is None:
            return current_sector, current_industry

        # Check reclassifications: if a reclass entry says ticker's
        # to_sector matches current_sector AND as_of < effective_date,
        # roll back to from_sector.
        as_of_dt = pd.Timestamp(as_of).date()
        for r in self.reclass:
            if r.get("symbol") != ticker:
                continue
            eff = r.get("effective_date")
            if isinstance(eff, str):
                eff = pd.Timestamp(eff).date()
            elif hasattr(eff, "year"):  # date object from yaml
                eff = pd.Timestamp(eff).date()
            if as_of_dt < eff:
                return r.get("from_sector"), r.get("from_industry")
        return current_sector, current_industry

    def panel_classifications(
        self,
        tickers: list[str],
        as_of_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """Return DataFrame(index=as_of_dates, columns=tickers) of GICS sector
        names — PIT-aware (handles reclassifications across the index).

        Cells where ticker missing from map are NaN."""
        out = pd.DataFrame(index=as_of_dates, columns=tickers, dtype=object)
        # Per-ticker, find break dates from reclass and fill each segment.
        for t in tickers:
            t_up = t.upper()
            if t_up not in self.sector_map:
                continue
            t_reclass = sorted(
                [r for r in self.reclass if r.get("symbol") == t_up],
                key=lambda r: pd.Timestamp(r["effective_date"]),
            )
            current_sector = self.sector_map[t_up].get("sector")
            if not t_reclass:
                out[t] = current_sector
                continue
            # Sweep dates: before earliest effective_date → first from_sector;
            # within [eff_i, eff_{i+1}) → eff_i.to_sector; after last → current_sector
            # Easy approach: start with current_sector, then walk reclass list
            # in reverse-time order and apply from_sector to earlier segments.
            sector_series = pd.Series(current_sector, index=as_of_dates)
            for r in reversed(t_reclass):
                eff = pd.Timestamp(r["effective_date"])
                from_sec = r.get("from_sector")
                sector_series.loc[sector_series.index < eff] = from_sec
            out[t] = sector_series.values
        return out


def get_sector_groups(
    tickers: list[str],
    resolver: Optional[SectorResolver] = None,
    as_of: Optional[date] = None,
) -> Dict[str, list[str]]:
    """Return {sector_name: [tickers_in_sector]}, excluding etf-sector tickers."""
    resolver = resolver or SectorResolver()
    groups: Dict[str, list[str]] = {}
    for t in tickers:
        sec, _ = resolver.get(t, as_of=as_of)
        if sec is None or sec == "etf":
            continue
        groups.setdefault(sec, []).append(t)
    return groups
