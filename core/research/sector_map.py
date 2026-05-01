"""Static GICS sector classification for the PQS production universe.

Single source of truth for "which symbol belongs to which GICS sector"
(11 sectors per GICS taxonomy). Used by sector-relative top-K selection
in `core/research/harness/composite_evaluator.py::topn_signals_per_sector`
(introduced for cycle #03 sector-relative construction axis).

Design choices (cycle #03 path memo, 2026-05-01):

1. **Static map, not external API**: avoids yfinance / Polygon ticker
   reference data dependency + stale-data risk. In-repo, reproducible,
   git-diffable.

2. **ETFs excluded from sector ranking**: sector ETFs (XLK/XLF/etc.),
   factor ETFs (MTUM/QUAL/etc.), broad-market (SPY/QQQ), leveraged
   (TQQQ/SOXL), cross-asset (GLD/SLV/TLT/IEF/SHY) are NOT participants
   in sector ranking. ETFs are aggregates of single-name stocks; their
   presence in a sector pool would degenerate "sector winner = sector
   ETF self".

3. **GICS 11-sector taxonomy**: Communication Services / Consumer
   Discretionary / Consumer Staples / Energy / Financials / Health
   Care / Industrials / Information Technology / Materials / Real
   Estate / Utilities.

4. **GICS-strict over user comments**: where universe.yaml comments
   conflict with GICS official classification (e.g. COST = "staples/
   discretionary" in comment; GICS Consumer Staples), GICS wins for
   reproducibility.

When new symbols are added to the universe, this map MUST be updated
or `get_sector(sym)` will raise `KeyError` (fail-closed). This is
intentional: silent "Unknown" fallback would degenerate sector-
relative selection.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

# ── GICS 11 sectors ───────────────────────────────────────────────────

GICS_SECTORS: List[str] = [
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Financials",
    "Health Care",
    "Industrials",
    "Information Technology",
    "Materials",
    "Real Estate",
    "Utilities",
]


# ── Stock → GICS sector ────────────────────────────────────────────────
# 54 single-name stocks in the production universe (incl. BRK-B).
# When BRK-B is dropped per cycle yaml, 53 remain.

STOCK_SECTOR_MAP: Dict[str, str] = {
    # Communication Services (5)
    "META":  "Communication Services",
    "GOOGL": "Communication Services",
    "VZ":    "Communication Services",
    "EA":    "Communication Services",   # interactive media (gaming)
    "TKO":   "Communication Services",   # entertainment / sports

    # Consumer Discretionary (6)
    "AMZN":  "Consumer Discretionary",
    "TSLA":  "Consumer Discretionary",
    "TJX":   "Consumer Discretionary",
    "DG":    "Consumer Discretionary",
    "BKNG":  "Consumer Discretionary",
    "CMG":   "Consumer Discretionary",

    # Consumer Staples (5)
    "WMT":   "Consumer Staples",
    "GIS":   "Consumer Staples",
    "CLX":   "Consumer Staples",
    "TSN":   "Consumer Staples",
    "COST":  "Consumer Staples",     # GICS Consumer Staples (Food & Staples Retailing)

    # Energy (3)
    "OXY":   "Energy",
    "COP":   "Energy",
    "TRGP":  "Energy",

    # Financials (8)
    "GS":    "Financials",
    "MS":    "Financials",
    "C":     "Financials",
    "BRK-B": "Financials",
    "TRV":   "Financials",
    "AXP":   "Financials",
    "CME":   "Financials",
    "ACGL":  "Financials",

    # Health Care (9)
    "GILD":  "Health Care",
    "JNJ":   "Health Care",
    "ABT":   "Health Care",
    "UNH":   "Health Care",
    "LLY":   "Health Care",
    "ISRG":  "Health Care",
    "MCK":   "Health Care",
    "TMO":   "Health Care",
    "A":     "Health Care",

    # Industrials (5)
    "PWR":   "Industrials",
    "CAT":   "Industrials",
    "TER":   "Industrials",
    "TT":    "Industrials",
    "UNP":   "Industrials",

    # Information Technology (8)
    "AAPL":  "Information Technology",
    "MSFT":  "Information Technology",
    "NVDA":  "Information Technology",
    "LRCX":  "Information Technology",
    "KLAC":  "Information Technology",
    "MU":    "Information Technology",
    "AVGO":  "Information Technology",
    "TXN":   "Information Technology",

    # Materials (1)
    "APD":   "Materials",

    # Real Estate (1)
    "VICI":  "Real Estate",

    # Utilities (3)
    "WEC":   "Utilities",
    "ED":    "Utilities",
    "NEE":   "Utilities",
}


# ── ETFs / aggregates excluded from sector ranking ────────────────────

ETF_EXCLUDED_FROM_SECTOR_SELECTION: Set[str] = {
    # Sector ETFs (11)
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
    # Factor ETFs (5)
    "MTUM", "QUAL", "VLUE", "USMV", "SCHD",
    # Broad-market (2)
    "SPY", "QQQ",
    # Leveraged (2)
    "TQQQ", "SOXL",
    # Cross-asset / commodity / fixed-income (5)
    "GLD", "SLV", "TLT", "IEF", "SHY",
}


# ── API ────────────────────────────────────────────────────────────────


def get_sector(symbol: str) -> Optional[str]:
    """Return the GICS sector for a stock symbol, or None if the symbol
    is an ETF excluded from sector selection.

    Raises KeyError if the symbol is unknown (neither in STOCK_SECTOR_MAP
    nor ETF_EXCLUDED_FROM_SECTOR_SELECTION). Fail-closed for new symbols
    that haven't been mapped.
    """
    if symbol in ETF_EXCLUDED_FROM_SECTOR_SELECTION:
        return None
    if symbol in STOCK_SECTOR_MAP:
        return STOCK_SECTOR_MAP[symbol]
    raise KeyError(
        f"Unknown symbol {symbol!r}: not in STOCK_SECTOR_MAP and not in "
        f"ETF_EXCLUDED_FROM_SECTOR_SELECTION. Add to one or the other "
        f"(see core/research/sector_map.py)."
    )


def is_eligible_for_sector_selection(symbol: str) -> bool:
    """True iff symbol is a single-name stock with a GICS sector
    classification. False for ETFs and aggregates."""
    if symbol in ETF_EXCLUDED_FROM_SECTOR_SELECTION:
        return False
    if symbol in STOCK_SECTOR_MAP:
        return True
    raise KeyError(
        f"Unknown symbol {symbol!r}: must be added to STOCK_SECTOR_MAP "
        f"or ETF_EXCLUDED_FROM_SECTOR_SELECTION before sector-relative "
        f"selection can be applied."
    )


def get_eligible_stocks(symbols: List[str]) -> List[str]:
    """Filter to symbols eligible for sector-relative selection.
    Maintains input order. Raises KeyError on unknown symbols."""
    return [s for s in symbols if is_eligible_for_sector_selection(s)]


def stocks_by_sector(symbols: List[str]) -> Dict[str, List[str]]:
    """Group eligible stocks (excluding ETFs) by GICS sector.
    Empty sectors are NOT included in the output."""
    by_sector: Dict[str, List[str]] = {}
    for s in symbols:
        sec = get_sector(s)
        if sec is None:
            continue
        by_sector.setdefault(sec, []).append(s)
    return by_sector


def all_known_symbols() -> Set[str]:
    """Union of stocks + ETFs known to this map."""
    return set(STOCK_SECTOR_MAP) | ETF_EXCLUDED_FROM_SECTOR_SELECTION


# ── Sanity assertion at import time ────────────────────────────────────

# Catch silly typos / accidental sector-name drift.
_unique_sectors = set(STOCK_SECTOR_MAP.values())
assert _unique_sectors.issubset(set(GICS_SECTORS)), (
    f"STOCK_SECTOR_MAP contains sector(s) not in GICS_SECTORS: "
    f"{_unique_sectors - set(GICS_SECTORS)}"
)
