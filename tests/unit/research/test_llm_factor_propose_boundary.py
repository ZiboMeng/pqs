from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from scripts import llm_factor_propose as proposal


def test_llm_factor_loader_uses_adjusted_barstore_and_bounded_interval(
    monkeypatch,
):
    calls: list[dict] = []
    idx = pd.to_datetime(["2011-12-30", "2012-06-29", "2013-01-02"])
    bars = pd.DataFrame(
        {
            "open": [9.0, 10.0, 11.0],
            "high": [10.0, 11.0, 12.0],
            "low": [8.0, 9.0, 10.0],
            "close": [9.5, 10.5, 11.5],
            "volume": [1_000.0, 1_100.0, 1_200.0],
        },
        index=idx,
    )

    class FakeBarStore:
        def __init__(self, root):
            self.root = root

        def load(self, symbol, **kwargs):
            calls.append({"symbol": symbol, **kwargs})
            return bars

    monkeypatch.setattr(proposal, "BarStore", FakeBarStore)
    monkeypatch.setattr(proposal, "generate_all_factors", lambda *a, **k: {})
    cfg = SimpleNamespace(
        system=SimpleNamespace(paths=SimpleNamespace(data_dir="data")),
        universe=SimpleNamespace(
            seed_pool=["AAA"],
            sector_etfs=[],
            factor_etfs=[],
            cross_asset=[],
            blacklist=[],
            macro_reference=[],
        ),
    )

    price, _, _ = proposal._load_price_and_factors(
        cfg, n_symbols=1, start="2012-01-01", end="2012-12-31")

    assert list(price.index) == [pd.Timestamp("2012-06-29")]
    assert calls == [{
        "symbol": "AAA",
        "freq": "1d",
        "adjusted": True,
        "adjusted_total_return": False,
        "fallback": "local",
    }]
