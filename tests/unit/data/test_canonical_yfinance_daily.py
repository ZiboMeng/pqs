from __future__ import annotations

import numpy as np
import pandas as pd

from dev.scripts.data_integrity.build_canonical_yfinance_daily import (
    reconstruct_as_traded_ohlcv,
)


def test_reconstruct_as_traded_round_trips_prices_and_volume() -> None:
    index = pd.DatetimeIndex(["2020-01-02", "2020-01-03", "2020-01-06"])
    adjusted = pd.DataFrame(
        {
            "open": [50.0, 51.0, 52.0],
            "high": [51.0, 52.0, 53.0],
            "low": [49.0, 50.0, 51.0],
            "close": [50.5, 51.5, 52.5],
            "volume": [2000, 2200, 1000],
        },
        index=index,
    )
    splits = pd.DataFrame(
        {"symbol": ["X"], "date": [pd.Timestamp("2020-01-06")], "from": [1], "to": [2]}
    )
    raw = reconstruct_as_traded_ohlcv(adjusted, splits)
    assert raw.loc["2020-01-02", "close"] == 101.0
    assert raw.loc["2020-01-02", "volume"] == 1000
    assert raw.loc["2020-01-06", "close"] == 52.5
    factor = np.array([0.5, 0.5, 1.0])
    assert np.allclose(raw["close"].to_numpy() * factor, adjusted["close"])
    assert np.allclose(raw["volume"].to_numpy() / factor, adjusted["volume"])
