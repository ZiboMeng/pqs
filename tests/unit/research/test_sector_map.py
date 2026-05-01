"""Tests for core/research/sector_map.py — GICS classification for the
PQS production universe (cycle #03 sector-relative construction prep).

Coverage:
- Map covers ALL universe stocks (no missing sym → KeyError defense)
- ETF exclusion list covers ALL universe ETFs
- 78-sym universe partitions cleanly into stocks + ETFs (no overlap, no
  gap)
- get_sector / is_eligible / get_eligible_stocks / stocks_by_sector
  return values as expected
- Fail-closed: unknown sym raises KeyError, NOT silent None
- All declared sectors are valid GICS-11 names
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.research.sector_map import (
    ETF_EXCLUDED_FROM_SECTOR_SELECTION,
    GICS_SECTORS,
    STOCK_SECTOR_MAP,
    all_known_symbols,
    get_eligible_stocks,
    get_sector,
    is_eligible_for_sector_selection,
    stocks_by_sector,
)


# ── Coverage vs production universe ───────────────────────────────────


def _load_production_universe():
    """Return the full 78-symbol tradable universe (post-BRK-B drop)."""
    from core.config.loader import load_config
    cfg = load_config(Path("/home/zibo/Documents/projects/pqs/config"))
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    return [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference]


def test_all_universe_symbols_mapped():
    """Every universe sym (incl. BRK-B) must be either in
    STOCK_SECTOR_MAP or ETF_EXCLUDED_FROM_SECTOR_SELECTION. Otherwise
    sector-relative harness will raise on it."""
    universe = _load_production_universe()
    known = all_known_symbols()
    unmapped = [s for s in universe if s not in known]
    assert not unmapped, (
        f"Universe symbols not in sector_map or ETF exclusion list: "
        f"{unmapped}. Add them to core/research/sector_map.py before use."
    )


def test_universe_partitions_cleanly():
    """No symbol can be in both STOCK_SECTOR_MAP and the ETF exclusion."""
    overlap = set(STOCK_SECTOR_MAP) & ETF_EXCLUDED_FROM_SECTOR_SELECTION
    assert not overlap, f"Symbols in both sets: {overlap}"


def test_no_extra_symbols_in_map():
    """Map should not contain symbols that are not in production
    universe (would indicate stale entries)."""
    universe = set(_load_production_universe())
    # +BRK-B is OK because cycle yamls drop it but sector_map still has it
    extra_stocks = set(STOCK_SECTOR_MAP) - universe - {"BRK-B"}
    extra_etfs = ETF_EXCLUDED_FROM_SECTOR_SELECTION - universe
    # Intentional ETFs we keep mapped even if not in current universe yaml
    intentional_extras = {"SLV"}  # cross_asset block sometimes has SLV
    extra_etfs -= intentional_extras
    assert not extra_stocks, f"Stale stocks in map: {extra_stocks}"
    assert not extra_etfs, f"Stale ETFs in exclusion list: {extra_etfs}"


# ── API behavior ──────────────────────────────────────────────────────


def test_get_sector_returns_correct_gics():
    """Spot-check known classifications."""
    assert get_sector("AAPL") == "Information Technology"
    assert get_sector("META") == "Communication Services"
    assert get_sector("GS") == "Financials"
    assert get_sector("WMT") == "Consumer Staples"
    assert get_sector("NEE") == "Utilities"


def test_get_sector_returns_none_for_etfs():
    """ETFs excluded from sector selection return None."""
    for etf in ("SPY", "QQQ", "XLK", "XLF", "MTUM", "TLT", "GLD"):
        assert get_sector(etf) is None, (
            f"{etf} should return None (ETF excluded), got {get_sector(etf)!r}"
        )


def test_get_sector_raises_on_unknown():
    """Unknown symbol must FAIL CLOSED, not silent None."""
    with pytest.raises(KeyError, match="Unknown symbol"):
        get_sector("ZZZZ_NOT_A_REAL_TICKER")


def test_is_eligible_separates_stocks_from_etfs():
    """is_eligible_for_sector_selection is True for stocks, False for ETFs."""
    assert is_eligible_for_sector_selection("AAPL") is True
    assert is_eligible_for_sector_selection("WMT") is True
    assert is_eligible_for_sector_selection("SPY") is False
    assert is_eligible_for_sector_selection("XLK") is False


def test_is_eligible_raises_on_unknown():
    with pytest.raises(KeyError, match="Unknown symbol"):
        is_eligible_for_sector_selection("UNKNOWN_TICKER")


def test_get_eligible_stocks_filters_etfs():
    """Filter mixed list down to stocks only."""
    mixed = ["AAPL", "SPY", "WMT", "XLK", "GS", "QQQ", "TLT"]
    result = get_eligible_stocks(mixed)
    assert result == ["AAPL", "WMT", "GS"]


def test_get_eligible_stocks_preserves_order():
    """Order must be preserved (some downstream code may rely on it)."""
    mixed = ["GS", "AAPL", "WMT", "JNJ"]
    assert get_eligible_stocks(mixed) == ["GS", "AAPL", "WMT", "JNJ"]


def test_stocks_by_sector_groups_correctly():
    """Stocks bucketed by their GICS sector."""
    syms = ["AAPL", "MSFT", "META", "GOOGL", "GS", "JNJ", "SPY", "XLK"]
    grouped = stocks_by_sector(syms)
    assert grouped["Information Technology"] == ["AAPL", "MSFT"]
    assert grouped["Communication Services"] == ["META", "GOOGL"]
    assert grouped["Financials"] == ["GS"]
    assert grouped["Health Care"] == ["JNJ"]
    # ETFs not in output
    assert "SPY" not in {s for sec in grouped.values() for s in sec}


def test_stocks_by_sector_excludes_empty_sectors():
    """Only sectors with at least 1 eligible stock appear in result."""
    syms = ["AAPL", "MSFT"]
    grouped = stocks_by_sector(syms)
    assert list(grouped.keys()) == ["Information Technology"]


def test_all_sectors_have_at_least_one_stock_in_universe():
    """Sanity: every GICS-11 sector that's referenced in the map must
    have ≥1 stock present (otherwise sector ranking degenerates)."""
    universe = _load_production_universe()
    grouped = stocks_by_sector(universe)
    sectors_referenced = set(STOCK_SECTOR_MAP.values())
    for sec in sectors_referenced:
        assert sec in grouped and len(grouped[sec]) >= 1, (
            f"Sector {sec!r} has 0 stocks in universe. "
            f"Cycle #03 sector-relative selection will skip it."
        )


def test_gics_sectors_list_is_canonical():
    """GICS_SECTORS list is the canonical 11-sector taxonomy."""
    assert len(GICS_SECTORS) == 11
    assert "Information Technology" in GICS_SECTORS
    # Real Estate was added 2016; if our taxonomy lacks it, failing is correct
    assert "Real Estate" in GICS_SECTORS


def test_all_map_sectors_are_valid_gics():
    """No sector in STOCK_SECTOR_MAP can be outside GICS_SECTORS."""
    invalid = set(STOCK_SECTOR_MAP.values()) - set(GICS_SECTORS)
    assert not invalid, f"Invalid sector strings in map: {invalid}"
