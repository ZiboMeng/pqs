"""Tests for fundamental factors batch 2: Beneish + Altman + capital return + growth."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.data.edgar_provider import EdgarProvider
from core.data.fundamentals_store import FundamentalsStore
from core.factors.factor_registry import RESEARCH_FACTORS
from core.factors.fundamental_factors import (
    FUNDAMENTAL_FACTORS_BATCH2_NAMES,
    compute_beneish_factors,
    compute_altman_factors,
    compute_capital_return_factors,
    compute_growth_and_leverage_factors,
    compute_fundamental_factors_full,
)

# `fixture_cache` / `store` fixtures are provided by conftest.py


class TestBatch2Registration:
    def test_all_in_research_factors(self):
        for name in FUNDAMENTAL_FACTORS_BATCH2_NAMES:
            assert name in RESEARCH_FACTORS, f"{name} not registered"


class TestBeneish:
    def test_m_score_computed(self, store):
        # Beneish needs AR / PPE / Depreciation / SGA / TotalLiabilities;
        # fixture doesn't have these → most components NaN, M-score NaN.
        # Test that it doesn't crash and returns expected DataFrame shapes.
        idx = pd.bdate_range("2023-01-01", "2025-01-01")
        out = compute_beneish_factors(idx, ["FOO"], store)
        for name in [
            "beneish_dsri", "beneish_gmi", "beneish_aqi", "beneish_sgi",
            "beneish_depi", "beneish_sgai", "beneish_tata", "beneish_lvgi",
            "beneish_m_score",
        ]:
            assert name in out
            assert out[name].shape == (len(idx), 1)

    def test_tata_computable_from_ni_cfo_assets(self, store):
        """TATA = (NI - CFO) / Assets needs only NI/CFO/Assets (fixture has all)."""
        idx = pd.bdate_range("2023-01-01", "2025-01-01")
        out = compute_beneish_factors(idx, ["FOO"], store)
        tata = out["beneish_tata"]["FOO"].dropna()
        assert len(tata) > 0, "TATA should be computable from fixture"


class TestAltman:
    def test_components_computed(self, store):
        idx = pd.bdate_range("2023-01-01", "2025-01-01")
        prices = pd.DataFrame({"FOO": np.full(len(idx), 100.0)}, index=idx)
        out = compute_altman_factors(idx, ["FOO"], store, price_df=prices)
        for name in [
            "altman_wc_to_assets", "altman_re_to_assets", "altman_ebit_to_assets",
            "altman_sales_to_assets",
        ]:
            assert name in out

    def test_mveq_nan_without_price_df(self, store):
        idx = pd.bdate_range("2024-01-01", "2024-12-31")
        out = compute_altman_factors(idx, ["FOO"], store, price_df=None)
        assert out["altman_mveq_to_liab"].isna().all().all()


class TestCapitalReturn:
    def test_factors_computed(self, store):
        idx = pd.bdate_range("2023-01-01", "2025-01-01")
        prices = pd.DataFrame({"FOO": np.full(len(idx), 100.0)}, index=idx)
        out = compute_capital_return_factors(idx, ["FOO"], store, price_df=prices)
        for name in [
            "buyback_yield_ttm", "dividend_yield_ttm", "shareholder_yield_ttm",
            "fcf_yield_ttm", "fcf_to_assets_ttm",
        ]:
            assert name in out

    def test_fcf_to_assets_positive(self, store):
        """Fixture has positive CFO; capex panel empty (not in fixture) → FCF ≈ CFO."""
        idx = pd.bdate_range("2023-06-01", "2025-01-01")
        out = compute_capital_return_factors(idx, ["FOO"], store, price_df=None)
        fcf_ta = out["fcf_to_assets_ttm"]["FOO"].dropna()
        assert len(fcf_ta) > 0
        # CFO TTM > 0, assets > 0, capex 0 → FCF / Assets > 0
        assert (fcf_ta > 0).all(), f"expected positive FCF/Assets; min={fcf_ta.min()}"


class TestGrowthLeverage:
    def test_revenue_growth_positive_in_growing_fixture(self, store):
        idx = pd.bdate_range("2022-01-01", "2025-01-01")
        out = compute_growth_and_leverage_factors(idx, ["FOO"], store)
        rg = out["revenue_growth_yoy"]["FOO"].dropna()
        assert len(rg) > 0
        assert (rg > 0).all(), f"fixture has growing revenue; min={rg.min()}"

    def test_asset_growth_positive_in_growing_fixture(self, store):
        idx = pd.bdate_range("2022-01-01", "2025-01-01")
        out = compute_growth_and_leverage_factors(idx, ["FOO"], store)
        ag = out["asset_growth_yoy"]["FOO"].dropna()
        assert len(ag) > 0
        assert (ag > 0).all()


class TestFullPipeline:
    def test_compute_full_returns_all(self, store):
        idx = pd.bdate_range("2022-01-01", "2025-01-01")
        prices = pd.DataFrame({"FOO": np.full(len(idx), 100.0)}, index=idx)
        out = compute_fundamental_factors_full(idx, ["FOO"], store=store, price_df=prices)
        # Batch 1 (15) + Batch 2 (26) = 41 factor names
        from core.factors.fundamental_factors import FUNDAMENTAL_FACTORS_BATCH1_NAMES
        all_names = set(FUNDAMENTAL_FACTORS_BATCH1_NAMES) | set(FUNDAMENTAL_FACTORS_BATCH2_NAMES)
        for name in all_names:
            assert name in out, f"{name} missing"
