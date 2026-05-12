"""SEC EDGAR companyfacts API client + tag-fallback helpers.

PRD-driven 2026-05-12 per:
- docs/memos/20260512-quant_factor_literature_synthesis_v2.md §1.2-1.3
- docs/memos/20260512-bucket_abc_macro_mvp_schedule.md §1 D4-D8

SEC official endpoint: https://data.sec.gov/api/xbrl/companyfacts/CIK########.json
Constraints (per SEC EDGAR docs):
  - Max 10 requests/second per IP
  - User-Agent header REQUIRED (format: "Name email@domain")
  - companyfacts returns ALL us-gaap tags for company in one request
  - ~2-5 MB JSON per company

Tag fallback: companies report same concept under different us-gaap
tags (e.g. Revenues vs SalesRevenueNet vs RevenueFromContractWithCustomer
ExcludingAssessedTax). This module ships a tag-chain helper for the
common multi-tag concepts.

Cache layout:
  data/fundamentals/edgar_cache/<CIK_padded_10>.json  raw companyfacts JSON
  data/fundamentals/edgar_cache/_meta.json            CIK ↔ ticker map
                                                      + last-fetched-at
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


SEC_EDGAR_BASE = "https://data.sec.gov"
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
DEFAULT_USER_AGENT = "PQS Research zibo.meng@innopeaktech.com"
DEFAULT_RATE_LIMIT_SECONDS = 0.11  # 9 req/sec — safely under SEC's 10 req/sec cap


# Tag fallback chains for common concepts where us-gaap taxonomy diverges
# across filers. First successful (non-empty) match wins.
TAG_CHAINS: Dict[str, List[str]] = {
    "revenues": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "gross_profit": [
        "GrossProfit",
    ],
    "net_income": [
        "NetIncomeLoss",
    ],
    "total_assets": [
        "Assets",
    ],
    "current_assets": [
        "AssetsCurrent",
    ],
    "current_liabilities": [
        "LiabilitiesCurrent",
    ],
    "total_liabilities": [
        "Liabilities",
    ],
    "stockholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "cfo": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ],
    "shares_outstanding": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ],
    "dividends_cash": [
        "DividendsCommonStockCash",
        "DividendsCash",
    ],
    "eps_diluted": [
        "EarningsPerShareDiluted",
    ],
    "eps_basic": [
        "EarningsPerShareBasic",
    ],
    "rd_expense": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    "sga_expense": [
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
    ],
    "cogs": [
        "CostOfGoodsAndServicesSold",
        "CostOfRevenue",
        "CostOfGoodsSold",
    ],
    "depreciation": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "Depreciation",
    ],
    "accounts_receivable": [
        "AccountsReceivableNetCurrent",
        "ReceivablesNetCurrent",
    ],
    "inventory": [
        "InventoryNet",
    ],
    "ppe_net": [
        "PropertyPlantAndEquipmentNet",
    ],
    "retained_earnings": [
        "RetainedEarningsAccumulatedDeficit",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
    ],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "Cash",
    ],
}


@dataclass
class TagFact:
    """A single XBRL fact entry — period, value, filing metadata."""
    start: Optional[str]
    end: str
    val: float
    accn: str
    fy: int
    fp: str
    form: str
    filed: str
    unit: str = "USD"


class EdgarProvider:
    """Reads cached SEC EDGAR companyfacts JSON; provides tag-fallback access."""

    def __init__(
        self,
        cache_dir: Path | str = "data/fundamentals/edgar_cache",
        user_agent: str = DEFAULT_USER_AGENT,
    ):
        self.cache_dir = Path(cache_dir)
        self.user_agent = user_agent
        self._cik_map: Optional[Dict[str, int]] = None

    # ── CIK lookup ──

    def get_cik_map(self, force_refresh: bool = False) -> Dict[str, int]:
        """Return {ticker: cik_int}. Reads from cache `_cik_map.json` if
        present, else fetches from SEC."""
        cache_path = self.cache_dir / "_cik_map.json"
        if not force_refresh and cache_path.exists():
            with open(cache_path) as f:
                self._cik_map = json.load(f)
            return self._cik_map

        import requests
        r = requests.get(
            SEC_COMPANY_TICKERS_URL,
            headers={"User-Agent": self.user_agent},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        # SEC layout: {"0": {"cik_str": 1045810, "ticker": "NVDA", ...}, "1": ...}
        cik_map = {entry["ticker"]: int(entry["cik_str"]) for entry in data.values()}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cik_map, f)
        self._cik_map = cik_map
        return cik_map

    def get_cik(self, ticker: str) -> Optional[int]:
        cmap = self.get_cik_map()
        return cmap.get(ticker.upper())

    # ── companyfacts download ──

    def download_company_facts(self, ticker: str) -> Path:
        """Download companyfacts JSON for ticker, cache to disk. Returns path.

        Caller is responsible for rate-limiting (call no more than 10/sec).
        """
        import requests
        cik = self.get_cik(ticker)
        if cik is None:
            raise ValueError(f"CIK lookup failed for ticker {ticker}")
        cik_padded = f"{cik:010d}"
        url = f"{SEC_EDGAR_BASE}/api/xbrl/companyfacts/CIK{cik_padded}.json"
        r = requests.get(url, headers={"User-Agent": self.user_agent}, timeout=30)
        r.raise_for_status()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{cik_padded}.json"
        with open(path, "wb") as f:
            f.write(r.content)
        return path

    # ── Cached read ──

    def load_company_facts(self, ticker: str) -> Dict:
        cik = self.get_cik(ticker)
        if cik is None:
            raise ValueError(f"CIK lookup failed for ticker {ticker}")
        path = self.cache_dir / f"{cik:010d}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"No cached EDGAR data for {ticker} (CIK {cik}). "
                f"Run dev/scripts/fundamentals/build_edgar_cache.py first."
            )
        with open(path) as f:
            return json.load(f)

    def get_tag_facts(self, ticker: str, tag: str, unit: str = "USD") -> List[TagFact]:
        """Return list of TagFact for a specific us-gaap tag."""
        facts = self.load_company_facts(ticker)
        gaap = facts.get("facts", {}).get("us-gaap", {})
        if tag not in gaap:
            return []
        units = gaap[tag].get("units", {})
        rows = units.get(unit, [])
        return [
            TagFact(
                start=r.get("start"),
                end=r["end"],
                val=float(r["val"]),
                accn=r["accn"],
                fy=int(r.get("fy") or 0),
                fp=r.get("fp", ""),
                form=r.get("form", ""),
                filed=r["filed"],
                unit=unit,
            )
            for r in rows
        ]

    def get_chain_facts(self, ticker: str, concept: str) -> tuple[List[str], List[TagFact]]:
        """Resolve concept (e.g. 'revenues') by union-ing ALL chain tags.

        Many companies switch tag mid-history (e.g. AAPL used `Revenues`
        through 2018, then `RevenueFromContractWithCustomerExcludingAssessedTax`
        post-2018). Single-tag fallback misses these. So we concatenate
        facts from every tag in the chain that has data, then dedupe by
        (end_date, form), keeping the most-recently-filed row.

        Returns (resolved_tag_names_list, deduped_facts_list).
        """
        if concept not in TAG_CHAINS:
            raise KeyError(f"Unknown concept {concept!r}. Known: {sorted(TAG_CHAINS)}")
        unit = "USD/shares" if concept.startswith("eps_") else "USD"
        if concept == "shares_outstanding":
            unit = "shares"

        all_facts: List[TagFact] = []
        resolved_tags: List[str] = []
        for tag in TAG_CHAINS[concept]:
            facts = self.get_tag_facts(ticker, tag, unit=unit)
            if facts:
                all_facts.extend(facts)
                resolved_tags.append(tag)

        if not all_facts:
            return [], []

        # Dedupe by (end, form): if same period appears under multiple
        # tags or revisions, keep the most-recently-filed version. Sort
        # by filed ascending so the LAST occurrence (latest filed) wins.
        seen: Dict[tuple, TagFact] = {}
        for f in sorted(all_facts, key=lambda x: x.filed):
            key = (f.end, f.form)
            seen[key] = f  # later overwrite wins (latest filed)
        deduped = sorted(seen.values(), key=lambda x: x.filed)
        return resolved_tags, deduped

    def list_universe_cached(self, tickers: List[str]) -> Dict[str, bool]:
        """For each ticker, report whether companyfacts cache exists."""
        return {t: (self.cache_dir / f"{self.get_cik(t) or 0:010d}.json").exists() if self.get_cik(t) else False for t in tickers}


def is_etf_or_unsupported(ticker: str) -> bool:
    """ETF / leveraged / cross-asset symbols don't file us-gaap 10-K/Q.

    Universe contains SPY/QQQ/GLD/TLT/IEF/SHY/BIL/SHV/USO/SLV/TQQQ/SOXL
    etc.; these have no EDGAR fundamental data. Caller should skip these
    for download + factor computation.
    """
    KNOWN_ETF_OR_LEVERAGED = {
        "SPY", "QQQ", "GLD", "TLT", "IEF", "SHY", "BIL", "SHV", "USO", "SLV",
        "TQQQ", "SOXL", "SQQQ", "SOXS", "XLF", "XLK", "XLY", "XLE", "XLI",
        "XLU", "XLV", "XLP", "XLB", "XLRE", "VOO", "IVV", "VTI", "DIA",
    }
    return ticker.upper() in KNOWN_ETF_OR_LEVERAGED
