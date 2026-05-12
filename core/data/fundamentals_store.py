"""PIT fundamentals store — converts EDGAR raw facts to daily panel.

PRD-driven 2026-05-12 per:
- docs/memos/20260512-quant_factor_literature_synthesis_v2.md §1
- docs/memos/20260512-bucket_abc_macro_mvp_schedule.md §1 D5

PIT (point-in-time) discipline:
  - Facts are indexed by `filed` date (when filing reached SEC),
    NOT `end` date (reporting period end). This prevents lookahead:
    a Q3 2024 (end 2024-09-30) value filed on 2024-11-01 is only
    available to the strategy on 2024-11-01.
  - For Latest/TTM concepts (e.g. for daily mark-to-market), the
    raw value is forward-filled from filed_date onwards on the
    daily business-day calendar.
  - When multiple filings revise the same period (e.g. 10-K/A
    restatement), the latest filed value at time t wins (`groupby
    filed_date, take last`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.data.edgar_provider import EdgarProvider, TagFact, TAG_CHAINS

logger = logging.getLogger(__name__)


@dataclass
class _ConceptSeries:
    """Internal representation: TTM/latest-fact series for one ticker × concept."""
    ticker: str
    concept: str
    resolved_tag: str
    filed_index: pd.DatetimeIndex
    end_index: pd.DatetimeIndex
    values: np.ndarray
    period_kind: str  # 'instant' | 'quarterly' | 'annual'


class FundamentalsStore:
    """Daily PIT panel from EDGAR companyfacts cache.

    Usage:
        store = FundamentalsStore()
        ttm_revenue = store.load_ttm("AAPL", "revenues")
        panel = store.load_panel(["AAPL", "MSFT"], "gross_profit", as_of_dates=daily_idx)
    """

    def __init__(self, provider: Optional[EdgarProvider] = None):
        self.provider = provider or EdgarProvider()

    # ── Single ticker × single concept ──

    def _facts_to_dataframe(self, facts: List[TagFact]) -> pd.DataFrame:
        if not facts:
            return pd.DataFrame(columns=["start", "end", "val", "accn", "fy", "fp", "form", "filed"])
        df = pd.DataFrame([f.__dict__ for f in facts])
        df["filed"] = pd.to_datetime(df["filed"])
        df["end"] = pd.to_datetime(df["end"])
        df["start"] = pd.to_datetime(df["start"], errors="coerce")
        return df

    def load_concept_facts(self, ticker: str, concept: str) -> pd.DataFrame:
        """Return raw fact-level DataFrame for ticker × concept (after
        tag-chain resolution).

        Note: `provider.get_chain_facts` returns the UNION of all chain
        tags' facts (deduped by end+form, latest-filed wins), so concept
        coverage is maximised across mid-history tag switches.

        Columns: start, end, val, accn, fy, fp, form, filed."""
        _, facts = self.provider.get_chain_facts(ticker, concept)
        return self._facts_to_dataframe(facts)

    def load_pit_series(
        self,
        ticker: str,
        concept: str,
        prefer_quarterly: bool = True,
    ) -> pd.Series:
        """Return PIT-indexed series for ticker × concept.

        Index = filed_date (PIT effective date).
        Value = latest quarterly (10-Q) val if prefer_quarterly else 10-K
                annual val.
        Deduplicate by (filed_date, end_date): if multiple revisions hit
        same filed_date, take the latest end_date.
        """
        df = self.load_concept_facts(ticker, concept)
        if df.empty:
            return pd.Series(dtype=float, name=concept)

        forms_target = {"10-Q", "10-Q/A"} if prefer_quarterly else {"10-K", "10-K/A"}
        # If 10-K only (e.g. RetainedEarnings on annual), fall back to all forms.
        sub = df[df["form"].isin(forms_target)]
        if sub.empty:
            sub = df

        # Some balance-sheet items are "instant" (filed date == report date);
        # income/CF items are "duration" (Q vs annual TTM).
        # Sort, dedupe by filed_date, take latest end_date entry.
        sub = sub.sort_values(["filed", "end"])
        # Group by filed_date, keep the row with latest 'end'
        sub = sub.groupby("filed", as_index=False).last()
        series = pd.Series(sub["val"].values, index=pd.DatetimeIndex(sub["filed"]), name=concept)
        return series

    def load_ttm(self, ticker: str, concept: str) -> pd.Series:
        """Trailing-12-month flow concept (e.g. revenues, net_income).

        Sums last 4 quarterly 10-Q reports (or uses latest 10-K when
        available). Indexed by the filed_date of the latest contributing
        filing.

        For instant concepts (balance sheet), TTM is not meaningful —
        use `load_pit_series` directly.
        """
        df = self.load_concept_facts(ticker, concept)
        if df.empty:
            return pd.Series(dtype=float, name=f"{concept}_ttm")

        # Only Q reports (10-Q) for TTM rolling sum; annual 10-K already TTM
        quarterly = df[df["form"].isin({"10-Q", "10-Q/A"})].copy()
        if quarterly.empty:
            # Fall back to 10-K annual values (already TTM as-of fiscal year)
            annual = df[df["form"].isin({"10-K", "10-K/A"})].copy()
            if annual.empty:
                return pd.Series(dtype=float, name=f"{concept}_ttm")
            annual = annual.sort_values(["filed", "end"])
            annual = annual.groupby("filed", as_index=False).last()
            return pd.Series(
                annual["val"].values, index=pd.DatetimeIndex(annual["filed"]),
                name=f"{concept}_ttm",
            )

        # Compute TTM at each quarterly filing: sum the latest 4 quarter-end values
        # whose end <= current period end.
        quarterly = quarterly.sort_values("end")
        # Dedupe by end_date (take latest filed for each end)
        quarterly = quarterly.sort_values("filed").groupby("end", as_index=False).last()
        quarterly = quarterly.sort_values("end")
        # Rolling 4-quarter sum
        quarterly["ttm"] = quarterly["val"].rolling(4, min_periods=4).sum()
        out = quarterly.dropna(subset=["ttm"])
        return pd.Series(out["ttm"].values, index=pd.DatetimeIndex(out["filed"]), name=f"{concept}_ttm")

    def load_latest_balance(self, ticker: str, concept: str) -> pd.Series:
        """Balance-sheet (instant) concept: latest filed value indexed by filed_date."""
        return self.load_pit_series(ticker, concept, prefer_quarterly=True)

    # ── Cross-symbol panel join ──

    def load_panel(
        self,
        tickers: List[str],
        concept: str,
        as_of_dates: pd.DatetimeIndex,
        ttm: bool = False,
    ) -> pd.DataFrame:
        """Construct a daily PIT panel for `tickers` × `as_of_dates`.

        For each ticker:
          1. Load PIT series (TTM if ttm=True else latest filing).
          2. Forward-fill onto `as_of_dates` (value at time t = most
             recent filing with filed_date <= t).

        Returns DataFrame(index=as_of_dates, columns=tickers).
        """
        cols = {}
        for t in tickers:
            try:
                s = self.load_ttm(t, concept) if ttm else self.load_pit_series(t, concept)
            except (FileNotFoundError, ValueError):
                cols[t] = pd.Series(np.nan, index=as_of_dates)
                continue
            if s.empty:
                cols[t] = pd.Series(np.nan, index=as_of_dates)
                continue
            # Aggregate to daily, forward-fill across business days
            s = s.sort_index().groupby(level=0).last()
            s_daily = s.reindex(as_of_dates.union(s.index)).sort_index().ffill()
            cols[t] = s_daily.reindex(as_of_dates)
        return pd.DataFrame(cols, index=as_of_dates)
