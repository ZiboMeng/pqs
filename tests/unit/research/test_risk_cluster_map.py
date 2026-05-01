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
