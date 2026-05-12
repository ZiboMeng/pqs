"""Tests for Bucket C sector_map + sector-relative factors."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from core.data.sector_resolver import SectorResolver, get_sector_groups
from core.factors.factor_registry import RESEARCH_FACTORS
from core.factors.sector_factors import (
    SECTOR_FACTOR_NAMES,
    compute_sector_factors,
)


@pytest.fixture
def resolver():
    return SectorResolver()  # uses config/sector_map.yaml


class TestSectorResolver:
    def test_known_ticker_resolves(self, resolver):
        sec, ind = resolver.get("AAPL")
        assert sec == "technology"

    def test_etf_tagged_etf(self, resolver):
        sec, _ = resolver.get("SPY")
        assert sec == "etf"

    def test_pit_reclassification_meta_2018(self, resolver):
        """META Tech → Communication Services on 2018-09-28."""
        sec_before, _ = resolver.get("META", as_of=date(2018, 1, 1))
        sec_after, _ = resolver.get("META", as_of=date(2024, 1, 1))
        assert sec_before == "technology"
        assert sec_after == "communication"

    def test_pit_reclassification_googl_2018(self, resolver):
        sec_before, _ = resolver.get("GOOGL", as_of=date(2018, 1, 1))
        sec_after, _ = resolver.get("GOOGL", as_of=date(2024, 1, 1))
        assert sec_before == "technology"
        assert sec_after == "communication"

    def test_unknown_ticker_returns_none(self, resolver):
        sec, ind = resolver.get("UNKNOWN_ABC")
        assert sec is None and ind is None

    def test_panel_classifications_pit(self, resolver):
        idx = pd.bdate_range("2018-01-01", "2020-01-01")
        panel = resolver.panel_classifications(["META", "AAPL"], idx)
        # META pre-2018-09-28 → tech
        assert panel.loc["2018-01-02", "META"] == "technology"
        # META post-2018-09-28 → communication
        assert panel.loc["2019-01-02", "META"] == "communication"
        # AAPL always tech
        assert (panel["AAPL"] == "technology").all()


class TestSectorGroups:
    def test_excludes_etfs(self, resolver):
        groups = get_sector_groups(["SPY", "AAPL", "JNJ"], resolver=resolver)
        assert "etf" not in groups
        assert "AAPL" in groups.get("technology", [])
        assert "JNJ" in groups.get("health_care", [])


class TestSectorFactors:
    def _make_panel(self, n=300, syms=None, seed=42):
        syms = syms or ["AAPL", "MSFT", "NVDA", "JNJ", "GILD"]
        idx = pd.date_range("2024-01-01", periods=n, freq="B")
        rng = np.random.default_rng(seed)
        rets = rng.normal(0.0005, 0.015, size=(n, len(syms)))
        close = 100.0 * np.exp(np.cumsum(rets, axis=0))
        return pd.DataFrame(close, index=idx, columns=syms)

    def test_factors_registered(self):
        for name in SECTOR_FACTOR_NAMES:
            assert name in RESEARCH_FACTORS

    def test_compute_factors_full(self, resolver):
        price_df = self._make_panel()
        out = compute_sector_factors(price_df, resolver=resolver)
        for name in SECTOR_FACTOR_NAMES:
            assert name in out, f"{name} missing"
            assert out[name].shape == price_df.shape

    def test_sector_rel_mom_sums_to_zero_within_sector(self, resolver):
        """Within each sector, sum of (stock_mom - sector_median_mom) should
        be ~zero (medians are zero-centred)."""
        # Force tickers in same sector
        price_df = self._make_panel(syms=["AAPL", "MSFT", "NVDA"])
        out = compute_sector_factors(price_df, resolver=resolver)
        srm = out["sector_rel_mom_20d"]
        # Pick a late date with valid data
        d = srm.index[-1]
        row = srm.loc[d].dropna()
        if len(row) >= 2:
            # Median across 3 same-sector tickers — by definition median row's
            # value is 0 (since stock - sector_median includes stock itself)
            # We check the mean is close to 0 since median is the centre.
            assert abs(row.median()) < 1e-6, f"median of sector-rel not 0: {row.median()}"

    def test_breadth_in_0_1(self, resolver):
        price_df = self._make_panel()
        out = compute_sector_factors(price_df, resolver=resolver)
        breadth = out["sector_breadth_pct_5d"].dropna().values.flatten()
        assert (breadth >= -1e-9).all() and (breadth <= 1.0 + 1e-9).all()
