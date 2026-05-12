"""Shared pytest fixtures for fundamental_factors tests.

Builds a 12-quarter mini EDGAR companyfacts cache covering 2022-2024
with growing revenue/profit/CFO + decreasing leverage/shares so
Piotroski/Magic/Beneish/Altman batches can compute non-trivial values.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.data.edgar_provider import EdgarProvider
from core.data.fundamentals_store import FundamentalsStore


def _make_fixture_cache(tmp_path: Path) -> Path:
    cache_dir = tmp_path / "edgar_cache"
    cache_dir.mkdir()

    with open(cache_dir / "_cik_map.json", "w") as f:
        json.dump({"FOO": 1234, "BAR": 5678}, f)

    def filed_for(end: str) -> str:
        y, m, d = end.split("-")
        y, m = int(y), int(m)
        m += 1
        if m > 12:
            m = 1
            y += 1
        return f"{y:04d}-{m:02d}-01"

    quarters_2022 = ["2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31"]
    quarters_2023 = ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31"]
    quarters_2024 = ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31"]
    all_qs = quarters_2022 + quarters_2023 + quarters_2024
    filed_dates = [filed_for(e) for e in all_qs]

    def make_quarterly(tag, vals_by_quarter, unit="USD"):
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

    revenues = [(filed_dates[i], e, 10e9 + i * 1e9) for i, e in enumerate(all_qs)]
    gaap.update(make_quarterly("Revenues", revenues))

    gross = [(filed_dates[i], e, 4e9 + i * 0.5e9) for i, e in enumerate(all_qs)]
    gaap.update(make_quarterly("GrossProfit", gross))

    ni = [(filed_dates[i], e, 2e9 + i * 0.3e9) for i, e in enumerate(all_qs)]
    gaap.update(make_quarterly("NetIncomeLoss", ni))

    cfo = [(filed_dates[i], e, 2.5e9 + i * 0.4e9) for i, e in enumerate(all_qs)]
    gaap.update(make_quarterly("NetCashProvidedByUsedInOperatingActivities", cfo))

    oi = [(filed_dates[i], e, 2.5e9 + i * 0.35e9) for i, e in enumerate(all_qs)]
    gaap.update(make_quarterly("OperatingIncomeLoss", oi))

    assets = [(filed_dates[i], all_qs[i], 100e9 + i * 5e9) for i in range(len(all_qs))]
    gaap.update(make_instant("Assets", assets))

    ca = [(filed_dates[i], all_qs[i], 40e9 + i * 2e9) for i in range(len(all_qs))]
    gaap.update(make_instant("AssetsCurrent", ca))

    cl = [(filed_dates[i], all_qs[i], 20e9 + i * 0.5e9) for i in range(len(all_qs))]
    gaap.update(make_instant("LiabilitiesCurrent", cl))

    ltd = [(filed_dates[i], all_qs[i], 30e9 - i * 0.5e9) for i in range(len(all_qs))]
    gaap.update(make_instant("LongTermDebt", ltd))

    cash = [(filed_dates[i], all_qs[i], 15e9 + i * 0.5e9) for i in range(len(all_qs))]
    gaap.update(make_instant("CashAndCashEquivalentsAtCarryingValue", cash))

    shares = [(filed_dates[i], all_qs[i], 1e9 - i * 0.02e9) for i in range(len(all_qs))]
    gaap.update(make_instant("CommonStockSharesOutstanding", shares, unit="shares"))

    with open(cache_dir / "0000001234.json", "w") as f:
        json.dump(facts, f)

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
