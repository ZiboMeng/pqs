"""Canonical daily-bar transforms shared by ingestion and audit tooling.

Yahoo ``auto_adjust=False`` prices are expressed on today's split basis but
exclude dividend adjustment. The local daily store keeps as-traded OHLCV and
applies splits at read time, so vendor bars must be projected back through all
future splits before they can be published.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def split_factor(index: pd.DatetimeIndex, splits: pd.DataFrame) -> np.ndarray:
    """Return the local read-time price multiplier for each observation."""
    if splits.empty:
        return np.ones(len(index), dtype="float64")
    ordered = splits.sort_values("date").reset_index(drop=True)
    ratios = (ordered["from"].astype(float) / ordered["to"].astype(float)).to_numpy()
    suffix: np.ndarray = np.ones(len(ratios) + 1, dtype="float64")
    for position in range(len(ratios) - 1, -1, -1):
        suffix[position] = suffix[position + 1] * ratios[position]
    dates = pd.to_datetime(ordered["date"]).to_numpy(dtype="datetime64[ns]")
    observed = index.normalize().to_numpy(dtype="datetime64[ns]")
    return suffix[np.searchsorted(dates, observed, side="right")]


def reconstruct_as_traded_ohlcv(
    split_adjusted: pd.DataFrame,
    splits: pd.DataFrame,
) -> pd.DataFrame:
    """Reverse future split adjustment into the BarStore raw-bar basis."""
    if split_adjusted.empty:
        raise ValueError("cannot reconstruct an empty frame")
    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required - set(split_adjusted.columns))
    if missing:
        raise ValueError(f"split-adjusted frame is missing columns: {missing}")
    if not isinstance(split_adjusted.index, pd.DatetimeIndex):
        raise TypeError("split-adjusted frame index must be a DatetimeIndex")

    factor = split_factor(split_adjusted.index, splits)
    if not np.isfinite(factor).all() or (factor <= 0.0).any():
        raise ValueError("invalid split factor")
    raw = split_adjusted.copy()
    for column in ("open", "high", "low", "close"):
        raw[column] = split_adjusted[column].astype("float64") / factor
    raw["volume"] = (split_adjusted["volume"].astype("float64") * factor).round()
    raw["amount"] = raw["close"] * raw["volume"]
    raw["partial_day"] = False
    raw["thin_data"] = False

    # Publish is forbidden unless the exact BarStore forward transform is
    # reversible to the vendor series.
    for column in ("open", "high", "low", "close"):
        restored = raw[column].to_numpy(dtype="float64") * factor
        if not np.allclose(
            restored,
            split_adjusted[column].to_numpy(dtype="float64"),
            rtol=1e-9,
            atol=1e-6,
            equal_nan=False,
        ):
            raise ValueError(f"split reconstruction invariant failed for {column}")
    restored_volume = raw["volume"].to_numpy(dtype="float64") / factor
    volume_error = np.abs(
        restored_volume - split_adjusted["volume"].to_numpy(dtype="float64")
    )
    # Half one reconstructed raw share is the exact admissible rounding error;
    # projecting it to today's basis magnifies it by 1/factor.
    if (volume_error > (0.500001 / factor)).any():
        raise ValueError("split reconstruction invariant failed for volume")
    return raw


__all__ = ["reconstruct_as_traded_ohlcv", "split_factor"]
