"""Normalize and compare vendor split events with the canonical split table."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class SplitComparison:
    status: str
    details: pd.DataFrame
    canonical_event_count: int
    vendor_event_count: int
    matched_event_count: int
    canonical_only_count: int
    vendor_only_count: int
    ratio_mismatch_count: int


def normalize_canonical_splits(
    splits: pd.DataFrame,
    symbol: str,
    *,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> pd.DataFrame:
    """Return economically effective canonical ratios by event date."""

    required = {"symbol", "date", "from", "to"}
    missing = required - set(splits)
    if missing:
        raise ValueError(f"canonical splits lack columns: {sorted(missing)}")
    frame = splits[
        splits["symbol"].astype(str).str.upper() == str(symbol).upper()
    ].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize()
    frame["ratio"] = frame["to"].astype(float) / frame["from"].astype(float)
    frame = frame[
        frame["ratio"].notna()
        & np.isfinite(frame["ratio"])
        & (frame["ratio"] > 0)
        & ~np.isclose(frame["ratio"], 1.0, rtol=1e-8, atol=1e-10)
    ]
    start_date = pd.Timestamp(start).tz_localize(None).normalize()
    end_date = pd.Timestamp(end).tz_localize(None).normalize()
    frame = frame[(frame["date"] >= start_date) & (frame["date"] <= end_date)]
    if frame.empty:
        return pd.DataFrame(columns=["date", "canonical_ratio"])
    grouped = frame.groupby("date", as_index=False)["ratio"].prod()
    return grouped.rename(columns={"ratio": "canonical_ratio"})


def normalize_vendor_splits(
    splits: pd.Series,
    *,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> pd.DataFrame:
    """Return economically effective vendor ratios by NY event date."""

    if splits is None or len(splits) == 0:
        return pd.DataFrame(columns=["date", "vendor_ratio"])
    series = splits.copy()
    index = pd.DatetimeIndex(pd.to_datetime(series.index))
    if index.tz is not None:
        index = index.tz_convert("America/New_York").tz_localize(None)
    frame = pd.DataFrame({
        "date": index.normalize(),
        "vendor_ratio": pd.to_numeric(series.to_numpy(), errors="coerce"),
    })
    frame = frame[
        frame["vendor_ratio"].notna()
        & np.isfinite(frame["vendor_ratio"])
        & (frame["vendor_ratio"] > 0)
        & ~np.isclose(frame["vendor_ratio"], 1.0, rtol=1e-8, atol=1e-10)
    ]
    start_date = pd.Timestamp(start).tz_localize(None).normalize()
    end_date = pd.Timestamp(end).tz_localize(None).normalize()
    frame = frame[(frame["date"] >= start_date) & (frame["date"] <= end_date)]
    if frame.empty:
        return pd.DataFrame(columns=["date", "vendor_ratio"])
    return frame.groupby("date", as_index=False)["vendor_ratio"].prod()


def compare_split_events(
    canonical: pd.DataFrame,
    vendor: pd.DataFrame,
    *,
    ratio_rtol: float = 1e-4,
    ratio_atol: float = 1e-8,
) -> SplitComparison:
    """Compare normalized event tables and classify every date."""

    details = canonical.merge(vendor, on="date", how="outer", sort=True)
    has_canonical = details["canonical_ratio"].notna()
    has_vendor = details["vendor_ratio"].notna()
    both = has_canonical & has_vendor
    close = pd.Series(False, index=details.index)
    if both.any():
        close.loc[both] = np.isclose(
            details.loc[both, "canonical_ratio"],
            details.loc[both, "vendor_ratio"],
            rtol=ratio_rtol,
            atol=ratio_atol,
        )
    details["comparison"] = "RATIO_MISMATCH"
    details.loc[both & close, "comparison"] = "MATCH"
    details.loc[has_canonical & ~has_vendor, "comparison"] = "CANONICAL_ONLY"
    details.loc[~has_canonical & has_vendor, "comparison"] = "VENDOR_ONLY"
    counts = details["comparison"].value_counts()
    non_matches = int((details["comparison"] != "MATCH").sum())
    return SplitComparison(
        status="OK" if non_matches == 0 else "MISMATCH",
        details=details,
        canonical_event_count=int(len(canonical)),
        vendor_event_count=int(len(vendor)),
        matched_event_count=int(counts.get("MATCH", 0)),
        canonical_only_count=int(counts.get("CANONICAL_ONLY", 0)),
        vendor_only_count=int(counts.get("VENDOR_ONLY", 0)),
        ratio_mismatch_count=int(counts.get("RATIO_MISMATCH", 0)),
    )


__all__ = [
    "SplitComparison",
    "compare_split_events",
    "normalize_canonical_splits",
    "normalize_vendor_splits",
]
