"""Risk-cluster classification for the PQS production universe.

Single-layer classification at the "same trade" level. Used by the
harness's cap-aware selector (cycle #03+) to prevent the construction-
collapse failure mode where 10 winners turn out to be 10 different
spellings of the same alpha bet (e.g., NVDA + AVGO + LRCX + KLAC + MU
all = "AI capex / data-center semiconductor cycle").

Why this exists (and not just GICS sector):
GICS top-level Information Technology lumps 8 production-universe stocks
(AAPL/MSFT/NVDA/AVGO/LRCX/KLAC/MU/TXN) into ONE bucket, but their
trading drivers are very different — see the cluster table below.
A "top-1 per GICS sector" selector would still pick the same {β + 12-1
mom + volume} winners (likely NVDA) inside IT and not break the cycle
#01 + cycle #02 sibling-collapse pattern.

Design choices (cycle #03 path memo + risk-cluster discussion 2026-05-01):

1. **Single layer (not nested sector→cluster)**: simpler cap semantics.
   `cluster_cap` directly bounds "max picks per same trade".
   sector_map.py kept separately for concentration reporting only.

2. **17 clusters, average 3 stocks/cluster**: granular enough to
   separate the trades that matter (AI semi vs cyclical semi vs
   mega-cap platform) without being so granular that it becomes
   single-stock buckets everywhere (which would be lookahead bias).

3. **Single-stock clusters allowed for genuinely idiosyncratic risk**:
   TSLA (EV/autonomy, no peer), VICI (single REIT in universe), APD
   (single materials/chemicals).

4. **Justification per cluster**: each cluster's docstring entry below
   explains the trade thesis. This makes the classification auditable
   and resistant to lookahead-bias accusations (anyone reading the
   table can argue with the choices).

When new symbols are added: add them to STOCK_RISK_CLUSTER_MAP with a
cluster name that exists in CLUSTER_DEFINITIONS (or add a new cluster
entry). Otherwise `get_risk_cluster(sym)` raises KeyError (fail-closed).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set


# ── Cluster definitions (trade thesis per cluster) ────────────────────

CLUSTER_DEFINITIONS: Dict[str, str] = {
    "mega_cap_platform": (
        "Mega-cap quality / cloud / consumer-platform monopoly. Low-to-"
        "moderate beta (0.9-1.1), high margin, dominant network effects. "
        "Drivers: cloud capex cycle, ad-revenue elasticity, regulatory "
        "headlines."
    ),
    "mega_cap_internet_consumer": (
        "Mega-cap consumer-facing internet. Ad-supported (META) + "
        "e-commerce + AWS (AMZN). Higher beta than mega_cap_platform; "
        "drivers similar but with consumer-spend cyclicality."
    ),
    "ai_compute_semi": (
        "AI accelerator + AI networking semis. Driven directly by hyper-"
        "scaler capex spend on data-center compute. NVDA = GPU; AVGO = "
        "AI networking + custom silicon. Highly correlated to AI capex "
        "narrative; high beta."
    ),
    "cyclical_semi": (
        "Equipment + memory + analog semis with classical cyclical "
        "drivers (wafer-fab capex / DRAM-NAND price cycle / analog auto-"
        "industrial cycle). LRCX/KLAC = wafer fab equipment; MU = "
        "memory cycle; TXN = analog/industrial."
    ),
    "ev_disruptor": (
        "EV / autonomy single-name idiosyncratic bet. TSLA. No close "
        "peer in production universe."
    ),
    "money_center_finance": (
        "Money-center banks + brokers + exchanges. GS/MS/C = investment "
        "banks; AXP = card network; CME = derivatives exchange. Driven "
        "by rates, capital-markets activity, equity volume."
    ),
    "insurance_quality": (
        "Insurance + Berkshire-style quality compounders. BRK-B = mixed "
        "holding; TRV/ACGL = P&C insurance. Driven by underwriting "
        "cycle, float yield, equity book."
    ),
    "mega_pharma": (
        "Mega-cap pharma + managed care. JNJ/GILD/LLY/ABT = drug-"
        "company franchises (with LLY being current GLP-1 winner); UNH "
        "= managed care payor. Driven by FDA, payor reimbursement, "
        "drug pipelines."
    ),
    "medtech_services": (
        "Medical devices + life-sciences instruments + pharma services. "
        "ISRG = surgical robotics; TMO/A = lab/research instruments; "
        "MCK = drug distribution. Driven by hospital capex, R&D "
        "budgets, drug volume."
    ),
    "staples_defensive": (
        "Consumer staples — defensive, recession-resistant. WMT/COST = "
        "mass retail; GIS/CLX/TSN = food/CPG. Beta < 0.7 typically. "
        "Driven by consumer-staples pricing power, input costs."
    ),
    "disc_premium": (
        "Consumer discretionary excluding mega-cap internet. TJX = off-"
        "price retail; BKNG = travel; CMG = restaurant; DG = dollar "
        "store. Mid-beta, driven by consumer wallet share."
    ),
    "industrials_infra": (
        "Industrials + infrastructure + capex enablers. PWR = electrical "
        "infra; CAT = construction/mining equipment; TER = test "
        "equipment; TT = HVAC/climate; UNP = rails. Driven by capex "
        "cycle, infrastructure spending, industrial production."
    ),
    "energy_oilgas": (
        "Energy — oil & gas + midstream. OXY/COP = E&P; TRGP = "
        "midstream/pipeline. Highly correlated to crude oil price + "
        "rig count cycle. High beta to commodity price."
    ),
    "utilities_regulated": (
        "Regulated utilities — defensive yield. NEE = renewables-tilted "
        "utility; WEC/ED = traditional regulated electric. Beta < 0.5; "
        "driven by rate-base growth + interest rates."
    ),
    "communication_legacy": (
        "Communication services — legacy / non-platform. VZ = telecom "
        "wireless; EA = video games; TKO = sports/entertainment. "
        "Heterogeneous bucket but all are NOT mega-cap-platform. Lower "
        "correlation with C1 mega_cap_platform than IT-internal "
        "stocks would be."
    ),
    "real_estate": (
        "Real estate. VICI = casino-property REIT (single-name in "
        "universe). Driven by interest rates, lease re-rating, casino "
        "industry cyclicality."
    ),
    "materials_chemicals": (
        "Materials. APD = industrial gases (single-name). Driven by "
        "industrial production, energy-cost pass-through, hydrogen "
        "economy narrative."
    ),
}


# ── Stock → cluster ────────────────────────────────────────────────────
# 54 single-name stocks (incl. BRK-B). When BRK-B dropped per cycle yaml,
# 53 remain. Each entry maps to a key in CLUSTER_DEFINITIONS.

STOCK_RISK_CLUSTER_MAP: Dict[str, str] = {
    # mega_cap_platform (3)
    "AAPL":  "mega_cap_platform",
    "MSFT":  "mega_cap_platform",
    "GOOGL": "mega_cap_platform",

    # mega_cap_internet_consumer (2)
    "META":  "mega_cap_internet_consumer",
    "AMZN":  "mega_cap_internet_consumer",

    # ai_compute_semi (2)
    "NVDA":  "ai_compute_semi",
    "AVGO":  "ai_compute_semi",

    # cyclical_semi (4)
    "LRCX":  "cyclical_semi",
    "KLAC":  "cyclical_semi",
    "MU":    "cyclical_semi",
    "TXN":   "cyclical_semi",

    # ev_disruptor (1)
    "TSLA":  "ev_disruptor",

    # money_center_finance (5)
    "GS":    "money_center_finance",
    "MS":    "money_center_finance",
    "C":     "money_center_finance",
    "AXP":   "money_center_finance",
    "CME":   "money_center_finance",

    # insurance_quality (3)
    "BRK-B": "insurance_quality",
    "TRV":   "insurance_quality",
    "ACGL":  "insurance_quality",

    # mega_pharma (5)
    "JNJ":   "mega_pharma",
    "GILD":  "mega_pharma",
    "LLY":   "mega_pharma",
    "ABT":   "mega_pharma",
    "UNH":   "mega_pharma",

    # medtech_services (4)
    "ISRG":  "medtech_services",
    "MCK":   "medtech_services",
    "TMO":   "medtech_services",
    "A":     "medtech_services",

    # staples_defensive (5)
    "WMT":   "staples_defensive",
    "COST":  "staples_defensive",
    "GIS":   "staples_defensive",
    "CLX":   "staples_defensive",
    "TSN":   "staples_defensive",

    # disc_premium (4)
    "TJX":   "disc_premium",
    "BKNG":  "disc_premium",
    "CMG":   "disc_premium",
    "DG":    "disc_premium",

    # industrials_infra (5)
    "PWR":   "industrials_infra",
    "CAT":   "industrials_infra",
    "TER":   "industrials_infra",
    "TT":    "industrials_infra",
    "UNP":   "industrials_infra",

    # energy_oilgas (3)
    "OXY":   "energy_oilgas",
    "COP":   "energy_oilgas",
    "TRGP":  "energy_oilgas",

    # utilities_regulated (3)
    "NEE":   "utilities_regulated",
    "WEC":   "utilities_regulated",
    "ED":    "utilities_regulated",

    # communication_legacy (3)
    "VZ":    "communication_legacy",
    "EA":    "communication_legacy",
    "TKO":   "communication_legacy",

    # real_estate (1)
    "VICI":  "real_estate",

    # materials_chemicals (1)
    "APD":   "materials_chemicals",
}


# Re-export the ETF exclusion list from sector_map (single source of
# truth for "what is NOT a single-name stock"). Cluster selection uses
# the same exclusion semantics.
from core.research.sector_map import ETF_EXCLUDED_FROM_SECTOR_SELECTION  # noqa: E402

ETF_EXCLUDED_FROM_CLUSTER_SELECTION: Set[str] = ETF_EXCLUDED_FROM_SECTOR_SELECTION


# ── Cross-asset extension (cycle #04 cross-asset preflight) ────────────
# Authority: docs/memos/20260501-cycle04_cross_asset_preflight.md
# (D5 design: 5 new cross-asset clusters; total → 22).
#
# These clusters cover bond / commodity / cash ETFs that participate in
# cycle #04+ cap_aware_cross_asset selection. They are NOT in
# STOCK_RISK_CLUSTER_MAP (which is stocks-only for cycle #03 backwards
# compatibility). Cycle #04 callers use ``make_unified_cluster_map(
# include_cross_asset=True)`` to merge both into one dict for the
# selector.
#
# USO deliberately excluded (cycle #04 preflight memo §"USO 单独提示"):
# 2 single-day jumps > 50%, futures roll yield structurally different
# from spot oil — re-evaluate in a future cycle.

CROSS_ASSET_CLUSTER_DEFINITIONS: Dict[str, str] = {
    "bond_long_duration": (
        "Long-duration Treasury bond ETF. TLT = 20+ year Treasury. "
        "Beta ~ -0.2 to 0.0 (mildly negative in equity drawdowns). "
        "Drivers: long-end rates, term-premium, flight-to-quality flows."
    ),
    "bond_intermediate_duration": (
        "Intermediate-duration Treasury ETF. IEF = 7-10 year Treasury. "
        "Beta ~ -0.1 to 0.1; lower vol than TLT. Drivers: belly-of-curve "
        "rates, Fed-path expectations."
    ),
    "bond_short_duration": (
        "Short-duration Treasury ETF. SHY = 1-3 year Treasury. Near-cash "
        "with mild duration. Drivers: short-end rates."
    ),
    "commodity_metals": (
        "Precious metals commodity ETF. GLD = gold bullion (physically "
        "backed; no roll yield). Beta to equities ~ 0; high beta to USD "
        "weakness + real-rates falling. Drivers: real rates, USD, "
        "inflation expectations, geopolitical premium."
    ),
    "cash_anchor": (
        "Ultra-short T-bill ETF. BIL/SHV = 1-3 month / sub-1-year T-bills. "
        "Behaves as cash with current Fed rate yield. Beta ~ 0 to all "
        "asset classes. Drivers: Fed funds rate. Both ETFs grouped "
        "together because they are functionally interchangeable cash "
        "proxies; cluster_cap=0.20 prevents 'load 20% in BIL + 20% in "
        "SHV = 40% cash' from passing through as 2 distinct positions."
    ),
}


CROSS_ASSET_RISK_CLUSTER_MAP: Dict[str, str] = {
    "TLT": "bond_long_duration",
    "IEF": "bond_intermediate_duration",
    "SHY": "bond_short_duration",
    "GLD": "commodity_metals",
    "BIL": "cash_anchor",
    "SHV": "cash_anchor",
}


# ── Asset class (for cycle #04 asset_class_caps) ────────────────────────
# Per cycle #04 yaml `construction.asset_class_caps`. Maps every cluster
# (stock + cross-asset) to its asset_class. The cap_aware selector reads
# this when building the second-layer asset_class cap on top of the
# cluster cap.
#
# 4 asset classes: equities | bonds | commodities | cash_anchor.
#   - equities: all 17 stock clusters
#   - bonds: bond_long_duration, bond_intermediate_duration, bond_short_duration
#   - commodities: commodity_metals
#   - cash_anchor: cash_anchor

ASSET_CLASS_BY_CLUSTER: Dict[str, str] = {
    # Cross-asset
    "bond_long_duration":         "bonds",
    "bond_intermediate_duration": "bonds",
    "bond_short_duration":        "bonds",
    "commodity_metals":           "commodities",
    "cash_anchor":                "cash_anchor",
    # Stocks (all 17 stock clusters → equities)
    **{cluster: "equities" for cluster in CLUSTER_DEFINITIONS},
}


def make_unified_cluster_map(include_cross_asset: bool = False) -> Dict[str, str]:
    """Build the symbol→cluster map for the requested universe scope.

    include_cross_asset=False (cycle #03 default): returns
    STOCK_RISK_CLUSTER_MAP (54 stocks; ETFs excluded).

    include_cross_asset=True (cycle #04+): merges STOCK_RISK_CLUSTER_MAP
    with CROSS_ASSET_RISK_CLUSTER_MAP (54 stocks + 6 cross-asset ETFs;
    USO and equity-sector ETFs still excluded). The cap_aware selector
    receives this merged dict; symbols not in the dict are filtered
    silently.
    """
    if not include_cross_asset:
        return dict(STOCK_RISK_CLUSTER_MAP)
    merged = dict(STOCK_RISK_CLUSTER_MAP)
    # Cross-asset symbols never collide with stocks in PQS universe;
    # assert defensively in case future expansion adds collisions.
    for sym, clu in CROSS_ASSET_RISK_CLUSTER_MAP.items():
        if sym in merged:
            raise ValueError(
                f"Symbol {sym!r} appears in both STOCK_RISK_CLUSTER_MAP "
                f"and CROSS_ASSET_RISK_CLUSTER_MAP — disambiguate before "
                f"calling make_unified_cluster_map(include_cross_asset=True)."
            )
        merged[sym] = clu
    return merged


def get_asset_class_for_cluster(cluster: str) -> str:
    """Return the asset class for a cluster string (equities | bonds |
    commodities | cash_anchor). Raises KeyError on unknown cluster."""
    if cluster not in ASSET_CLASS_BY_CLUSTER:
        raise KeyError(
            f"Unknown cluster {cluster!r}: not in ASSET_CLASS_BY_CLUSTER. "
            f"Add to risk_cluster_map.py."
        )
    return ASSET_CLASS_BY_CLUSTER[cluster]


def get_asset_class(symbol: str) -> str:
    """Return the asset class for a symbol. Convenience wrapper for
    sym → cluster → asset_class lookup. Uses unified cluster map
    (stocks + cross-asset). Raises KeyError on unknown symbol."""
    unified = make_unified_cluster_map(include_cross_asset=True)
    if symbol not in unified:
        raise KeyError(
            f"Symbol {symbol!r} not in unified cluster map "
            f"(stocks + cross-asset). Add to STOCK_RISK_CLUSTER_MAP "
            f"or CROSS_ASSET_RISK_CLUSTER_MAP."
        )
    return get_asset_class_for_cluster(unified[symbol])


# ── API ────────────────────────────────────────────────────────────────


def get_risk_cluster(symbol: str) -> Optional[str]:
    """Return the risk_cluster for a stock, or None if the symbol is
    an ETF (excluded from selection). Raises KeyError on unknown sym
    (fail-closed)."""
    if symbol in ETF_EXCLUDED_FROM_CLUSTER_SELECTION:
        return None
    if symbol in STOCK_RISK_CLUSTER_MAP:
        return STOCK_RISK_CLUSTER_MAP[symbol]
    raise KeyError(
        f"Unknown symbol {symbol!r}: not in STOCK_RISK_CLUSTER_MAP and "
        f"not in ETF_EXCLUDED_FROM_CLUSTER_SELECTION. Add to "
        f"core/research/risk_cluster_map.py before use."
    )


def is_eligible_for_cluster_selection(symbol: str) -> bool:
    """True iff symbol has a risk_cluster (single-name stock)."""
    if symbol in ETF_EXCLUDED_FROM_CLUSTER_SELECTION:
        return False
    if symbol in STOCK_RISK_CLUSTER_MAP:
        return True
    raise KeyError(
        f"Unknown symbol {symbol!r}: must be added to "
        f"STOCK_RISK_CLUSTER_MAP or the ETF exclusion list."
    )


def stocks_by_cluster(symbols: List[str]) -> Dict[str, List[str]]:
    """Group eligible stocks by risk_cluster. Empty clusters NOT in output."""
    by_cluster: Dict[str, List[str]] = {}
    for s in symbols:
        clu = get_risk_cluster(s)
        if clu is None:
            continue
        by_cluster.setdefault(clu, []).append(s)
    return by_cluster


def all_clusters() -> List[str]:
    """All cluster names declared in CLUSTER_DEFINITIONS (canonical list)."""
    return list(CLUSTER_DEFINITIONS.keys())


# ── Sanity assertions at import time ───────────────────────────────────

# Every cluster name in STOCK_RISK_CLUSTER_MAP must exist in
# CLUSTER_DEFINITIONS (catch typos / drift).
_referenced = set(STOCK_RISK_CLUSTER_MAP.values())
_declared = set(CLUSTER_DEFINITIONS.keys())
assert _referenced.issubset(_declared), (
    f"STOCK_RISK_CLUSTER_MAP references undeclared cluster(s): "
    f"{_referenced - _declared}"
)

# Every declared cluster must have at least one stock (or it's dead
# code that should be removed).
_used = {STOCK_RISK_CLUSTER_MAP[s] for s in STOCK_RISK_CLUSTER_MAP}
assert _used == _declared, (
    f"CLUSTER_DEFINITIONS has unused entries: {_declared - _used}"
)
