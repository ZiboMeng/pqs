from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.data.canonical_daily import reconstruct_as_traded_ohlcv
from dev.scripts.data_integrity.build_canonical_yfinance_daily import (
    executable_symbols,
    finalize_manifest,
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


def test_volume_rounding_tolerance_scales_with_large_split() -> None:
    index = pd.DatetimeIndex(["2020-01-02"])
    adjusted = pd.DataFrame(
        {"open": [10.0], "high": [10.0], "low": [10.0], "close": [10.0], "volume": [101]},
        index=index,
    )
    splits = pd.DataFrame(
        {"symbol": ["X"], "date": [pd.Timestamp("2021-01-01")], "from": [1], "to": [20]}
    )
    raw = reconstruct_as_traded_ohlcv(adjusted, splits)
    assert raw.iloc[0]["volume"] == 5


def test_reconstruction_refuses_incomplete_ohlcv() -> None:
    incomplete = pd.DataFrame(
        {"close": [10.0], "volume": [100]},
        index=pd.DatetimeIndex(["2024-01-02"]),
    )
    with pytest.raises(ValueError, match="missing columns"):
        reconstruct_as_traded_ohlcv(incomplete, pd.DataFrame())


def test_finalize_manifest_stamps_reference_hashes(tmp_path) -> None:
    data = tmp_path / "data"
    ref = data / "ref"
    ref.mkdir(parents=True)
    for name in (
        "splits.parquet",
        "distributions.parquet",
        "distribution_coverage.parquet",
        "split_coverage.parquet",
        "split_verification_events.parquet",
        "daily_source_boundaries.parquet",
    ):
        pd.DataFrame({"value": [1]}).to_parquet(ref / name)
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"schema_version": 1}\n')
    payload = finalize_manifest(manifest, data)
    assert payload["reference_artifacts"]["splits.parquet"]["rows"] == 1
    assert len(payload["reference_artifacts"]["distributions.parquet"]["sha256"]) == 64


def test_executable_symbol_builder_is_unique_and_excludes_blacklist() -> None:
    symbols = executable_symbols()
    assert len(symbols) == len(set(symbols))
    assert {"SPY", "QQQ", "TQQQ", "XLK", "BIL"}.issubset(symbols)
    assert "SQQQ" not in symbols
