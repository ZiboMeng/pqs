"""Hand-curated sector mapping for the 79-symbol PQS universe.

PRD v3 §C lists sector concentration as one of the dimensions. The MVP
shipped this dimension as ``not_computed`` because no per-symbol sector
mapping was wired. Post-MVP audit fix (2026-04-25) wires this map so
the concentration report can populate sector concentration.

Sectors follow GICS-style top-level labels with three additions for
non-equity ETFs:

  - ``Treasury / Bond`` for IEF/SHY/TLT
  - ``Commodity`` for GLD/SLV
  - ``Factor / Multi-sector ETF`` for SPY/QQQ/MTUM/QUAL/SCHD/USMV/VLUE
  - ``Leveraged ETF`` for SOXL/TQQQ (treated as a separate label
    because their sector exposure is amplified, not pure)

Unknown symbols default to ``Unknown``. The map is intentionally a
plain Python dict so it's import-time fast and reviewable in code
review (no yaml indirection for a 79-row table).

Source: 2026-04-25 hand-coded from public sector classifications;
review when universe membership changes.
"""
from __future__ import annotations

# GICS-style sector labels for the 79 universe symbols (post-round-3).
SECTOR_MAP: dict = {
    # Sector ETFs — labeled as the sector they track
    "XLK": "Information Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",

    # Factor / multi-sector ETFs — separate bucket since their sector
    # exposure is by-design diversified (intentionally not in any GICS).
    "SPY": "Factor / Multi-sector ETF",
    "QQQ": "Factor / Multi-sector ETF",
    "MTUM": "Factor / Multi-sector ETF",
    "QUAL": "Factor / Multi-sector ETF",
    "SCHD": "Factor / Multi-sector ETF",
    "USMV": "Factor / Multi-sector ETF",
    "VLUE": "Factor / Multi-sector ETF",

    # Leveraged ETFs — treated as separate bucket; their concentration
    # signal is qualitatively different from cash-equity sector exposure.
    "SOXL": "Leveraged ETF",
    "TQQQ": "Leveraged ETF",

    # Treasury / bond ETFs
    "IEF": "Treasury / Bond",
    "SHY": "Treasury / Bond",
    "TLT": "Treasury / Bond",

    # Commodity ETFs
    "GLD": "Commodity",
    "SLV": "Commodity",

    # ── Stocks (GICS sector) ──────────────────────────────────────────
    "A": "Health Care",
    "ABT": "Health Care",
    "GILD": "Health Care",
    "ISRG": "Health Care",
    "JNJ": "Health Care",
    "LLY": "Health Care",
    "MCK": "Health Care",
    "TMO": "Health Care",
    "UNH": "Health Care",

    "AAPL": "Information Technology",
    "AVGO": "Information Technology",
    "KLAC": "Information Technology",
    "LRCX": "Information Technology",
    "MSFT": "Information Technology",
    "MU": "Information Technology",
    "NVDA": "Information Technology",
    "TER": "Information Technology",
    "TXN": "Information Technology",

    "AMZN": "Consumer Discretionary",
    "BKNG": "Consumer Discretionary",
    "CMG": "Consumer Discretionary",
    "DG": "Consumer Discretionary",
    "EA": "Communication Services",
    "GOOGL": "Communication Services",
    "META": "Communication Services",
    "TSLA": "Consumer Discretionary",
    "TJX": "Consumer Discretionary",
    "VZ": "Communication Services",

    "COST": "Consumer Staples",
    "GIS": "Consumer Staples",
    "WMT": "Consumer Staples",
    "TSN": "Consumer Staples",
    "CLX": "Consumer Staples",

    "AXP": "Financials",
    "BRK-B": "Financials",
    "C": "Financials",
    "ACGL": "Financials",
    "CME": "Financials",
    "GS": "Financials",
    "MS": "Financials",
    "TRV": "Financials",
    "TKO": "Communication Services",  # WWE/UFC parent

    "CAT": "Industrials",
    "PWR": "Industrials",
    "TT": "Industrials",
    "UNP": "Industrials",

    "APD": "Materials",

    "COP": "Energy",
    "OXY": "Energy",
    "TRGP": "Energy",

    "ED": "Utilities",
    "NEE": "Utilities",
    "WEC": "Utilities",

    "VICI": "Real Estate",
}


def sector_for(symbol: str) -> str:
    """Return GICS sector label for ``symbol``; ``"Unknown"`` if unmapped."""
    return SECTOR_MAP.get(symbol, "Unknown")
