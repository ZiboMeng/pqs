"""Single as-of read interface shared by future V6 research and PAPER."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.data.pit_filings import PitFilingCorpus
from core.data.pit_fundamentals import PitFundamentalStore
from core.data.pit_industry import PitIndustryStore
from core.data.pit_market_data import PitMarketDataStore
from core.data.pit_security_master import FORMAL_HISTORICAL_PIT, PitSecurityMaster


class PitAsOfError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EligibleAssetsResult:
    decision_session: str
    asset_ids: tuple[str, ...]
    evidence_scope: str
    source: str = "precomputed_pit_universe_mask"


class PitAsOfData:
    """No ``latest`` shortcut: every method requires an explicit session."""

    def __init__(
        self,
        *,
        security_master: PitSecurityMaster,
        market_data: PitMarketDataStore | None = None,
        fundamentals: PitFundamentalStore | None = None,
        filings: PitFilingCorpus | None = None,
        industries: PitIndustryStore | None = None,
        universe_mask: pd.DataFrame | None = None,
    ):
        self.security_master = security_master
        self.market_data = market_data
        self.fundamentals = fundamentals
        self.filings = filings
        self.industries = industries
        self.universe_mask = universe_mask.copy() if universe_mask is not None else None

    @staticmethod
    def _session(value: str | pd.Timestamp) -> pd.Timestamp:
        return pd.Timestamp(value).tz_localize(None).normalize()

    def get_security_state(
        self, asset_id: str, decision_session: str | pd.Timestamp
    ) -> pd.Series:
        rows = self.security_master.as_of(decision_session)
        rows = rows[rows["asset_id"].eq(asset_id)]
        if len(rows) != 1:
            raise KeyError(
                f"no unique security state for {asset_id} at {decision_session}"
            )
        return rows.iloc[0].copy()

    def get_eligible_assets(
        self, decision_session: str | pd.Timestamp
    ) -> EligibleAssetsResult:
        if self.universe_mask is None:
            raise PitAsOfError("universe mask is not configured")
        date = self._session(decision_session)
        if date not in self.universe_mask.index:
            raise KeyError(f"universe mask has no decision session {date.date()}")
        asset_ids = tuple(
            str(asset_id)
            for asset_id, eligible in self.universe_mask.loc[date].items()
            if bool(eligible)
        )
        active = set(
            self.security_master.as_of(
                date, evidence_scope=FORMAL_HISTORICAL_PIT
            )["asset_id"]
        )
        if not set(asset_ids).issubset(active):
            raise PitAsOfError("universe mask contains inactive/non-formal assets")
        return EligibleAssetsResult(
            decision_session=str(date.date()),
            asset_ids=asset_ids,
            evidence_scope=FORMAL_HISTORICAL_PIT,
        )

    def get_price(
        self,
        asset_id: str,
        session: str | pd.Timestamp,
        *,
        basis: str = "raw",
    ) -> pd.Series:
        if self.market_data is None:
            raise PitAsOfError("market data store is not configured")
        if basis != "raw":
            raise PitAsOfError(
                "V6 Phase A exposes raw formal OHLCV only; adjusted basis requires "
                "a separately certified action transform"
            )
        date = self._session(session)
        rows = self.market_data.bars
        rows = rows[rows["asset_id"].eq(asset_id) & rows["session"].eq(date)]
        if len(rows) != 1:
            raise KeyError(f"no unique raw price for {asset_id} at {date.date()}")
        return rows.iloc[0].copy()

    def get_fundamental(
        self,
        asset_id: str,
        concept_id: str,
        decision_session: str | pd.Timestamp,
        *,
        unit: str | None = None,
    ) -> pd.Series:
        if self.fundamentals is None:
            raise PitAsOfError("fundamental store is not configured")
        return self.fundamentals.latest_period_fact_as_of(
            asset_id=asset_id,
            concept=concept_id,
            decision_session=decision_session,
            unit=unit,
        )

    def get_filing_documents(
        self,
        asset_id: str,
        decision_session: str | pd.Timestamp,
        *,
        forms: tuple[str, ...] = ("10-K", "10-Q"),
    ) -> pd.DataFrame:
        if self.filings is None:
            raise PitAsOfError("filing corpus is not configured")
        return self.filings.documents_as_of(
            decision_session, asset_id=asset_id, forms=forms
        )

    def get_industry(
        self,
        asset_id: str,
        decision_session: str | pd.Timestamp,
        *,
        classification_system: str,
    ) -> pd.Series:
        if self.industries is None:
            raise PitAsOfError("industry store is not configured")
        return self.industries.as_of(
            asset_id,
            decision_session,
            classification_system=classification_system,
        )


__all__ = ["EligibleAssetsResult", "PitAsOfData", "PitAsOfError"]
