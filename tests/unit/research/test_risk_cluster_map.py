"""Tests for core/research/risk_cluster_map.py — single-layer risk-cluster
classification (cycle #03 prep).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.research.risk_cluster_map import (
    CLUSTER_DEFINITIONS,
    ETF_EXCLUDED_FROM_CLUSTER_SELECTION,
    STOCK_RISK_CLUSTER_MAP,
    all_clusters,
    get_risk_cluster,
    is_eligible_for_cluster_selection,
    stocks_by_cluster,
)


def _load_universe():
    from core.config.loader import load_config
    cfg = load_config(Path("/home/zibo/Documents/projects/pqs/config"))
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    return [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference]


# ── Coverage vs production universe ───────────────────────────────────


def test_all_universe_covered():
    """Every universe sym must be in STOCK_RISK_CLUSTER_MAP or in the
    ETF exclusion list. Otherwise selector raises KeyError on it."""
    universe = _load_universe()
    known = set(STOCK_RISK_CLUSTER_MAP) | ETF_EXCLUDED_FROM_CLUSTER_SELECTION
    unmapped = [s for s in universe if s not in known]
    assert not unmapped, f"Unmapped symbols: {unmapped}"


def test_no_overlap_between_stocks_and_etfs():
    overlap = set(STOCK_RISK_CLUSTER_MAP) & ETF_EXCLUDED_FROM_CLUSTER_SELECTION
    assert not overlap


def test_n_stocks_count():
    """Sanity: should be 54 single-name stocks (incl BRK-B)."""
    assert len(STOCK_RISK_CLUSTER_MAP) == 54


# ── Cluster definitions invariants ────────────────────────────────────


def test_n_clusters():
    """Designed for 17 clusters (cycle #03 path memo)."""
    assert len(CLUSTER_DEFINITIONS) == 17


def test_every_cluster_has_at_least_one_stock():
    """No dead clusters."""
    used_clusters = set(STOCK_RISK_CLUSTER_MAP.values())
    declared = set(CLUSTER_DEFINITIONS.keys())
    assert used_clusters == declared, (
        f"Unused cluster(s) declared: {declared - used_clusters}; "
        f"undeclared cluster(s) referenced: {used_clusters - declared}"
    )


def test_every_cluster_has_definition_string():
    """Each cluster docstring entry should be non-empty (meaningful description)."""
    for name, desc in CLUSTER_DEFINITIONS.items():
        assert desc.strip(), f"Cluster {name} has empty description"


def test_no_oversized_cluster():
    """Defensive: if any cluster has >= 8 stocks, the granularity is
    probably wrong (we're back to GICS-level coarseness)."""
    grouped = stocks_by_cluster(list(STOCK_RISK_CLUSTER_MAP.keys()))
    for cluster, members in grouped.items():
        assert len(members) <= 7, (
            f"Cluster {cluster} has {len(members)} stocks ({members}); "
            f"too coarse for cycle #03 risk-cluster purpose"
        )


def test_critical_separations_preserved():
    """Spot-check the separations that motivated the new design."""
    # AI capex semis MUST be separated from cyclical_semi
    assert get_risk_cluster("NVDA") == "ai_compute_semi"
    assert get_risk_cluster("AVGO") == "ai_compute_semi"
    assert get_risk_cluster("LRCX") == "cyclical_semi"
    assert get_risk_cluster("KLAC") == "cyclical_semi"
    assert get_risk_cluster("MU") == "cyclical_semi"
    assert get_risk_cluster("TXN") == "cyclical_semi"

    # Mega-cap platform separated from internet_consumer
    assert get_risk_cluster("AAPL") == "mega_cap_platform"
    assert get_risk_cluster("MSFT") == "mega_cap_platform"
    assert get_risk_cluster("GOOGL") == "mega_cap_platform"
    assert get_risk_cluster("META") == "mega_cap_internet_consumer"
    assert get_risk_cluster("AMZN") == "mega_cap_internet_consumer"

    # TSLA in own cluster (idiosyncratic)
    assert get_risk_cluster("TSLA") == "ev_disruptor"

    # Money-center banks vs insurance separated
    assert get_risk_cluster("GS") == "money_center_finance"
    assert get_risk_cluster("BRK-B") == "insurance_quality"


# ── API behavior ──────────────────────────────────────────────────────


def test_get_cluster_returns_none_for_etfs():
    for etf in ("SPY", "QQQ", "XLK", "MTUM", "TLT", "GLD"):
        assert get_risk_cluster(etf) is None


def test_get_cluster_raises_on_unknown():
    with pytest.raises(KeyError, match="Unknown symbol"):
        get_risk_cluster("NOT_A_REAL_TICKER")


def test_is_eligible_separates_stocks_from_etfs():
    assert is_eligible_for_cluster_selection("AAPL") is True
    assert is_eligible_for_cluster_selection("LRCX") is True
    assert is_eligible_for_cluster_selection("SPY") is False


def test_is_eligible_raises_on_unknown():
    with pytest.raises(KeyError):
        is_eligible_for_cluster_selection("UNKNOWN")


def test_stocks_by_cluster_groups_correctly():
    syms = ["AAPL", "MSFT", "NVDA", "AVGO", "LRCX", "MU", "GS", "WMT", "SPY", "XLK"]
    grouped = stocks_by_cluster(syms)
    assert sorted(grouped["mega_cap_platform"]) == ["AAPL", "MSFT"]
    assert sorted(grouped["ai_compute_semi"]) == ["AVGO", "NVDA"]
    assert sorted(grouped["cyclical_semi"]) == ["LRCX", "MU"]
    assert grouped["money_center_finance"] == ["GS"]
    assert grouped["staples_defensive"] == ["WMT"]
    # ETFs not grouped
    for sec in grouped.values():
        assert "SPY" not in sec and "XLK" not in sec


def test_all_clusters_returns_canonical_list():
    clusters = all_clusters()
    assert "mega_cap_platform" in clusters
    assert "ai_compute_semi" in clusters
    assert "cyclical_semi" in clusters
    assert "ev_disruptor" in clusters
    assert len(clusters) == 17


# ── Cross-asset extension (cycle #04 preflight) ───────────────────────


def test_cross_asset_cluster_definitions_complete():
    """5 cross-asset clusters defined per cycle #04 preflight memo §D5."""
    from core.research.risk_cluster_map import CROSS_ASSET_CLUSTER_DEFINITIONS
    assert set(CROSS_ASSET_CLUSTER_DEFINITIONS.keys()) == {
        "bond_long_duration",
        "bond_intermediate_duration",
        "bond_short_duration",
        "commodity_metals",
        "cash_anchor",
    }
    for name, desc in CROSS_ASSET_CLUSTER_DEFINITIONS.items():
        assert isinstance(desc, str) and len(desc) > 50, (
            f"{name} description too short: {desc!r}"
        )


def test_cross_asset_map_covers_6_etfs():
    """6 cross-asset ETFs mapped; USO deliberately excluded."""
    from core.research.risk_cluster_map import CROSS_ASSET_RISK_CLUSTER_MAP
    assert set(CROSS_ASSET_RISK_CLUSTER_MAP.keys()) == {
        "TLT", "IEF", "SHY", "GLD", "BIL", "SHV",
    }
    # USO must NOT be in the map (cycle #04 design exclusion)
    assert "USO" not in CROSS_ASSET_RISK_CLUSTER_MAP


def test_cross_asset_map_assignments():
    from core.research.risk_cluster_map import CROSS_ASSET_RISK_CLUSTER_MAP
    assert CROSS_ASSET_RISK_CLUSTER_MAP["TLT"] == "bond_long_duration"
    assert CROSS_ASSET_RISK_CLUSTER_MAP["IEF"] == "bond_intermediate_duration"
    assert CROSS_ASSET_RISK_CLUSTER_MAP["SHY"] == "bond_short_duration"
    assert CROSS_ASSET_RISK_CLUSTER_MAP["GLD"] == "commodity_metals"
    # BIL + SHV both → cash_anchor (functionally interchangeable)
    assert CROSS_ASSET_RISK_CLUSTER_MAP["BIL"] == "cash_anchor"
    assert CROSS_ASSET_RISK_CLUSTER_MAP["SHV"] == "cash_anchor"


def test_make_unified_cluster_map_default_is_stocks_only():
    from core.research.risk_cluster_map import (
        STOCK_RISK_CLUSTER_MAP, make_unified_cluster_map,
    )
    unified = make_unified_cluster_map(include_cross_asset=False)
    assert unified == STOCK_RISK_CLUSTER_MAP
    # Must be a copy not a reference (mutation of caller-side
    # shouldn't poison the canonical dict)
    unified["NEW_TICKER"] = "synthetic_cluster"
    assert "NEW_TICKER" not in STOCK_RISK_CLUSTER_MAP


def test_make_unified_cluster_map_with_cross_asset_merges_correctly():
    from core.research.risk_cluster_map import (
        CROSS_ASSET_RISK_CLUSTER_MAP, STOCK_RISK_CLUSTER_MAP,
        make_unified_cluster_map,
    )
    unified = make_unified_cluster_map(include_cross_asset=True)
    # All stocks present
    for sym, clu in STOCK_RISK_CLUSTER_MAP.items():
        assert unified[sym] == clu
    # All cross-asset present
    for sym, clu in CROSS_ASSET_RISK_CLUSTER_MAP.items():
        assert unified[sym] == clu
    # No collision (n_stocks + n_cross_asset == total)
    assert len(unified) == (
        len(STOCK_RISK_CLUSTER_MAP) + len(CROSS_ASSET_RISK_CLUSTER_MAP)
    )


def test_asset_class_by_cluster_complete():
    """ASSET_CLASS_BY_CLUSTER covers every cluster (stock + cross-asset)."""
    from core.research.risk_cluster_map import (
        ASSET_CLASS_BY_CLUSTER, CLUSTER_DEFINITIONS,
        CROSS_ASSET_CLUSTER_DEFINITIONS,
    )
    expected_clusters = (
        set(CLUSTER_DEFINITIONS.keys()) | set(CROSS_ASSET_CLUSTER_DEFINITIONS.keys())
    )
    assert set(ASSET_CLASS_BY_CLUSTER.keys()) == expected_clusters
    # Asset class values are the canonical 4
    valid_classes = {"equities", "bonds", "commodities", "cash_anchor"}
    for cluster, asset_class in ASSET_CLASS_BY_CLUSTER.items():
        assert asset_class in valid_classes, (
            f"{cluster} → {asset_class!r} not in valid classes"
        )


def test_asset_class_by_cluster_assignments():
    from core.research.risk_cluster_map import ASSET_CLASS_BY_CLUSTER
    # All 17 stock clusters → equities
    assert ASSET_CLASS_BY_CLUSTER["mega_cap_platform"] == "equities"
    assert ASSET_CLASS_BY_CLUSTER["ai_compute_semi"] == "equities"
    assert ASSET_CLASS_BY_CLUSTER["energy_oilgas"] == "equities"
    # Cross-asset → respective classes
    assert ASSET_CLASS_BY_CLUSTER["bond_long_duration"] == "bonds"
    assert ASSET_CLASS_BY_CLUSTER["bond_intermediate_duration"] == "bonds"
    assert ASSET_CLASS_BY_CLUSTER["bond_short_duration"] == "bonds"
    assert ASSET_CLASS_BY_CLUSTER["commodity_metals"] == "commodities"
    assert ASSET_CLASS_BY_CLUSTER["cash_anchor"] == "cash_anchor"


def test_get_asset_class_for_cluster():
    from core.research.risk_cluster_map import get_asset_class_for_cluster
    assert get_asset_class_for_cluster("mega_cap_platform") == "equities"
    assert get_asset_class_for_cluster("bond_long_duration") == "bonds"
    assert get_asset_class_for_cluster("cash_anchor") == "cash_anchor"
    with pytest.raises(KeyError, match="Unknown cluster"):
        get_asset_class_for_cluster("non_existent_cluster")


def test_get_asset_class_for_symbol():
    from core.research.risk_cluster_map import get_asset_class
    # Stock
    assert get_asset_class("AAPL") == "equities"
    assert get_asset_class("NVDA") == "equities"
    # Cross-asset
    assert get_asset_class("TLT") == "bonds"
    assert get_asset_class("GLD") == "commodities"
    assert get_asset_class("BIL") == "cash_anchor"
    assert get_asset_class("SHV") == "cash_anchor"
    # Unknown raises
    with pytest.raises(KeyError):
        get_asset_class("NOT_A_REAL_TICKER")


def test_uso_excluded_from_cross_asset():
    """USO must NOT be eligible for cycle #04 (per preflight memo)."""
    from core.research.risk_cluster_map import (
        CROSS_ASSET_RISK_CLUSTER_MAP, make_unified_cluster_map,
    )
    assert "USO" not in CROSS_ASSET_RISK_CLUSTER_MAP
    unified = make_unified_cluster_map(include_cross_asset=True)
    assert "USO" not in unified
    # USO also not eligible for legacy stocks-only behavior
    from core.research.risk_cluster_map import is_eligible_for_cluster_selection
    assert is_eligible_for_cluster_selection("USO") is False


def test_cross_asset_unified_22_clusters_total():
    """Cycle #04 universe: 17 stock clusters + 5 cross-asset = 22 total."""
    from core.research.risk_cluster_map import (
        CLUSTER_DEFINITIONS, CROSS_ASSET_CLUSTER_DEFINITIONS,
    )
    total_clusters = (
        set(CLUSTER_DEFINITIONS.keys()) | set(CROSS_ASSET_CLUSTER_DEFINITIONS.keys())
    )
    assert len(total_clusters) == 22, (
        f"Expected 22 clusters total (17 stock + 5 cross-asset), got {len(total_clusters)}"
    )
