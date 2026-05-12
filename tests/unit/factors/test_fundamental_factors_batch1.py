"""Tests for fundamental factors batch 1 (Piotroski + Magic Formula).

PRD 2026-05-12. Uses fixture EDGAR cache.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.data.edgar_provider import EdgarProvider
from core.data.fundamentals_store import FundamentalsStore
from core.factors.factor_registry import RESEARCH_FACTORS
from core.factors.fundamental_factors import (
    FUNDAMENTAL_FACTORS_BATCH1_NAMES,
    compute_fundamental_factors_batch1,
    compute_piotroski_factors,
    compute_magic_formula_factors,
)


def _make_fixture_cache(tmp_path: Path) -> Path:
    """Single-ticker fixture with 3 years of complete fundamentals
    so Piotroski + Magic Formula factors can compute non-trivially."""
    cache_dir = tmp_path / "edgar_cache"
    cache_dir.mkdir()

    with open(cache_dir / "_cik_map.json", "w") as f:
        json.dump({"FOO": 1234, "BAR": 5678}, f)

    def make_quarterly(tag, vals_by_quarter, unit="USD"):
        """vals_by_quarter: list of (filed, end, val) tuples."""
        return {
            tag: {
                "label": tag,
                "units": {
                    unit: [
                        {"start": e.replace("-12-31", "-01-01").replace("-09-30", "-07-01")
                                  .replace("-06-30", "-04-01").replace("-03-31", "-01-01"),
                         "end": e, "val": v,
                         "accn": f"x{i}", "fy": int(e[:4]),
                         "fp": "Q4" if e.endswith("12-31") else "Q1",
                         # ALL quarters as 10-Q so load_ttm rolling 4-Q sums
                         # cleanly across the fixture's 12 sequential quarters.
                         # Real-world EDGAR has Q4 as 10-K (annual TTM already)
                         # and load_ttm handles that via the 10-K fallback
                         # path; this fixture exercises the rolling-Q path.
                         "form": "10-Q",
                         "filed": fd}
                        for i, (fd, e, v) in enumerate(vals_by_quarter)
                    ],
                },
            },
        }

    def make_instant(tag, vals, unit="USD"):
        return {
            tag: {"label": tag, "units": {unit: [
                {"end": e, "val": v, "accn": f"y{i}", "fy": int(e[:4]),
                 "fp": "Q1", "form": "10-Q", "filed": fd}
                for i, (fd, e, v) in enumerate(vals)
            ]}}
        }

    facts = {"cik": 1234, "entityName": "FOO", "facts": {"us-gaap": {}}}
    gaap = facts["facts"]["us-gaap"]

    # 3-yr quarterly TTM-friendly data:
    # 2022 Q1-Q4, 2023 Q1-Q4, 2024 Q1-Q4 — 12 quarters
    quarters_2022 = ["2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31"]
    quarters_2023 = ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31"]
    quarters_2024 = ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31"]
    all_qs = quarters_2022 + quarters_2023 + quarters_2024
    filed_dates = [f"{e[:8]}{int(e[8:10])+30:02d}" if int(e[8:10])+30 <= 30 else
                   f"{int(e[:4]) + (1 if e[5:7]=='12' else 0):04d}-{(int(e[5:7]) % 12) + 1:02d}-15"
                   for e in all_qs]
    # Simpler: filed = end + 1 month
    def filed_for(end):
        y, m, d = end.split("-")
        y, m = int(y), int(m)
        m += 1
        if m > 12:
            m = 1
            y += 1
        return f"{y:04d}-{m:02d}-01"
    filed_dates = [filed_for(e) for e in all_qs]

    # Revenues — growing trend
    revenues = [
        (filed_dates[i], e, 10e9 + i * 1e9)
        for i, e in enumerate(all_qs)
    ]
    gaap.update(make_quarterly("Revenues", revenues))

    # Gross profit — also growing (so gross margin stays roughly flat or rises)
    gross = [
        (filed_dates[i], e, 4e9 + i * 0.5e9)
        for i, e in enumerate(all_qs)
    ]
    gaap.update(make_quarterly("GrossProfit", gross))

    # NetIncomeLoss — positive
    ni = [
        (filed_dates[i], e, 2e9 + i * 0.3e9)
        for i, e in enumerate(all_qs)
    ]
    gaap.update(make_quarterly("NetIncomeLoss", ni))

    # CFO — positive AND > NI (high quality)
    cfo = [
        (filed_dates[i], e, 2.5e9 + i * 0.4e9)
        for i, e in enumerate(all_qs)
    ]
    gaap.update(make_quarterly("NetCashProvidedByUsedInOperatingActivities", cfo))

    # OperatingIncomeLoss (EBIT proxy for Magic Formula)
    oi = [
        (filed_dates[i], e, 2.5e9 + i * 0.35e9)
        for i, e in enumerate(all_qs)
    ]
    gaap.update(make_quarterly("OperatingIncomeLoss", oi))

    # Instant: Assets — growing
    assets = [(filed_dates[i], all_qs[i], 100e9 + i * 5e9) for i in range(len(all_qs))]
    gaap.update(make_instant("Assets", assets))

    # CurrentAssets — also growing
    ca = [(filed_dates[i], all_qs[i], 40e9 + i * 2e9) for i in range(len(all_qs))]
    gaap.update(make_instant("AssetsCurrent", ca))

    # CurrentLiabilities — slightly growing
    cl = [(filed_dates[i], all_qs[i], 20e9 + i * 0.5e9) for i in range(len(all_qs))]
    gaap.update(make_instant("LiabilitiesCurrent", cl))

    # LongTermDebt — decreasing (yoy ≤ 0)
    ltd = [(filed_dates[i], all_qs[i], 30e9 - i * 0.5e9) for i in range(len(all_qs))]
    gaap.update(make_instant("LongTermDebt", ltd))

    # Cash
    cash = [(filed_dates[i], all_qs[i], 15e9 + i * 0.5e9) for i in range(len(all_qs))]
    gaap.update(make_instant("CashAndCashEquivalentsAtCarryingValue", cash))

    # Shares — slightly decreasing (buyback → no dilution)
    shares = [(filed_dates[i], all_qs[i], 1e9 - i * 0.02e9) for i in range(len(all_qs))]
    gaap.update(make_instant("CommonStockSharesOutstanding", shares, unit="shares"))

    with open(cache_dir / "0000001234.json", "w") as f:
        json.dump(facts, f)

    # BAR: bare minimum (Assets only) to test multi-ticker NaN propagation
    bar_facts = {"cik": 5678, "entityName": "BAR", "facts": {"us-gaap": {
        "Assets": {"label": "Assets", "units": {"USD": [
            {"end": "2023-12-31", "val": 50e9, "accn": "z", "fy": 2023, "fp": "Q1",
             "form": "10-K", "filed": "2024-02-01"},
        ]}},
    }}}
    with open(cache_dir / "0000005678.json", "w") as f:
        json.dump(bar_facts, f)

    return cache_dir


@pytest.fixture
def fixture_cache(tmp_path):
    return _make_fixture_cache(tmp_path)


@pytest.fixture
def store(fixture_cache):
    return FundamentalsStore(provider=EdgarProvider(cache_dir=fixture_cache))


class TestRegistration:
    def test_all_15_in_research_factors(self):
        for name in FUNDAMENTAL_FACTORS_BATCH1_NAMES:
            assert name in RESEARCH_FACTORS, f"{name} not in registry"


class TestPiotroski:
    def test_factors_produced(self, store):
        idx = pd.bdate_range("2023-06-01", "2025-01-01")
        out = compute_piotroski_factors(idx, ["FOO"], store)
        # 9 boolean + composite + 2 derived = 12 piotroski factors
        piotroski_names = {n for n in FUNDAMENTAL_FACTORS_BATCH1_NAMES if "piotroski" in n}
        for name in piotroski_names:
            assert name in out

    def test_composite_in_0_to_9(self, store):
        idx = pd.bdate_range("2024-01-01", "2025-01-01")
        out = compute_piotroski_factors(idx, ["FOO"], store)
        composite = out["piotroski_f_score"].dropna().values
        assert (composite >= 0).all() and (composite <= 9).all()

    def test_high_filter_when_strong_fundamentals(self, store):
        """Fixture has growing revenue/profit/CFO + decreasing leverage/shares
        → expect Piotroski high score (≥ 7) once 1-yr lookback is satisfied.

        Idx must span ≥ 252 BD before evaluation date so YoY shift(252)
        has data. Fixture starts 2022-Q1 → use idx 2022-01-01 onwards."""
        idx = pd.bdate_range("2022-01-01", "2025-01-01")
        out = compute_piotroski_factors(idx, ["FOO"], store)
        composite = out["piotroski_f_score"]["FOO"]
        late = composite.iloc[-30:].dropna()
        assert len(late) > 0, "no piotroski composite by end of fixture period"
        # Strong fixture → all components should hit (score = 9 expected)
        assert late.max() >= 7, f"expected high score; max was {late.max()}"


class TestMagicFormula:
    def test_factors_produced(self, store):
        idx = pd.bdate_range("2024-01-01", "2024-12-31")
        # Need a price_df for market cap
        prices = pd.DataFrame({"FOO": np.full(len(idx), 100.0)}, index=idx)
        out = compute_magic_formula_factors(idx, ["FOO"], store, price_df=prices)
        for n in ["magic_earnings_yield_ttm", "magic_roic_ttm", "magic_formula_rank_composite"]:
            assert n in out

    def test_earnings_yield_positive_when_ebit_positive(self, store):
        idx = pd.bdate_range("2024-01-01", "2024-12-31")
        prices = pd.DataFrame({"FOO": np.full(len(idx), 100.0)}, index=idx)
        out = compute_magic_formula_factors(idx, ["FOO"], store, price_df=prices)
        ey = out["magic_earnings_yield_ttm"]["FOO"].dropna()
        # Fixture has positive EBIT/cash/decreasing-debt → EV > 0 → EY > 0
        assert (ey > 0).all(), f"expected positive earnings yield; min={ey.min()}"


class TestBatch1Convenience:
    def test_batch1_returns_all_15(self, store):
        idx = pd.bdate_range("2024-01-01", "2024-12-31")
        prices = pd.DataFrame({"FOO": np.full(len(idx), 100.0)}, index=idx)
        out = compute_fundamental_factors_batch1(idx, ["FOO"], store=store, price_df=prices)
        for name in FUNDAMENTAL_FACTORS_BATCH1_NAMES:
            assert name in out

    def test_unknown_ticker_gives_nan_panel(self, store):
        idx = pd.bdate_range("2024-01-01", "2024-12-31")
        prices = pd.DataFrame({"UNKNOWN_X": np.full(len(idx), 100.0)}, index=idx)
        out = compute_fundamental_factors_batch1(
            idx, ["UNKNOWN_X"], store=store, price_df=prices,
        )
        # All NaN for unknown ticker (graceful)
        for name, df in out.items():
            assert df["UNKNOWN_X"].isna().all(), f"{name} not all-NaN for unknown ticker"


class TestPITSemantics:
    def test_no_factor_value_before_first_filing(self, store):
        """Piotroski composite should be NaN before earliest filing
        + 252-day lookback (need YoY)."""
        idx = pd.bdate_range("2022-01-01", "2024-12-31")
        out = compute_piotroski_factors(idx, ["FOO"], store)
        # First filing is for 2022-Q1 end (filed 2022-05-01).
        # Plus 252-day lookback → ~2023-04 first valid composite
        early = out["piotroski_f_score"]["FOO"].iloc[:200]  # well before first filed
        assert early.isna().all(), "composite should be NaN before first filed"
