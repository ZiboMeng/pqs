"""Volume profile / Point of Control (POC) detection.

Pure-functional module. Aggregates intraday volume by price bucket to
identify per-session POC, Value Area High (VAH), Value Area Low (VAL),
and session VWAP. These are core institutional S/R reference levels:
prior session's POC is the most-traded price (where the most participants
have inventory at risk) and tends to act as gravity in subsequent sessions.

Used by:
  - Use 1 (intraday execution timing): yesterday's POC + value area
    band as 60m timing reference; entry near VAL, exit near VAH.
  - Use 2 (stop-loss placement): stops anchored just outside prior VAH/VAL.
  - Use 3 (factor mining): daily-resolution `pct_above_prior_poc`,
    `range_compression_vs_atr20`, `value_area_position` enter
    RESEARCH_FACTORS for IC research.

Data input convention:
  - Bars must be 1-minute frequency (this is what `data/intraday/1m/` ships).
  - Bars must be RTH-filtered if pre/post-market noise is unwanted; this
    module does not filter — caller's responsibility.
  - Bars must have ``'close'`` and ``'volume'`` columns. Volume is
    attributed to the bar's close price (standard convention; alternative
    "TPO" attribution is out of scope for v1).

Bucket sizing default:
  - Auto = (session_high - session_low) / 100 → 100 buckets per session,
    yielding ~1 bps resolution on a $100 stock with $5 daily range.
  - Override via ``bucket_size`` (absolute price units) or
    ``bucket_size_pct_of_close`` (fraction).

Caveats — read before relying on factor outputs:
  * 1m bar coverage is uneven across the universe. Stocks 2015+ are
    polygon flat-files; 2024+ uses per-ticker CSV; ETFs 2024+ have
    trades_backfill. Pre-2015 stocks may have NO 1m data, in which case
    ``compute_daily_volume_profile`` returns NaN columns. Caller must
    guard.
  * Symbol provenance is in ``data/ref/bar_provenance.parquet``;
    factors using volume profile should mask via
    ``data_sensitivity_volume`` per the existing factor-guard system.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class VolumeProfile:
    """Single-session volume profile result."""

    poc_price: float
    """Price (bucket center) with maximum total volume in the session."""

    vah: float
    """Value Area High — top of the contiguous price band capturing
    ``value_area_pct`` of total session volume centered at POC."""

    val: float
    """Value Area Low — bottom of the value area band."""

    vwap: float
    """Volume-weighted average close price for the session."""

    total_volume: float
    """Sum of all bar volumes in the session."""

    n_bars: int
    """Number of bars contributing to this profile (after NaN drop)."""

    bucket_size: float
    """Bucket width used (price units)."""

    session_high: float
    session_low: float


def _compute_session_profile(
    closes: np.ndarray,
    volumes: np.ndarray,
    bucket_size: Optional[float] = None,
    bucket_size_pct_of_close: Optional[float] = None,
    value_area_pct: float = 0.70,
) -> Optional[VolumeProfile]:
    """Inner per-session computation. Returns None on insufficient data.

    Numeric stability: NaN-filtering then bucket bin assignment via
    integer division. Edge case (only one valid bar) returns a profile
    with poc=vah=val=that close.
    """
    mask = (~np.isnan(closes)) & (~np.isnan(volumes)) & (volumes > 0)
    if not mask.any():
        return None

    closes = closes[mask]
    volumes = volumes[mask]
    n = len(closes)

    session_high = float(closes.max())
    session_low = float(closes.min())

    # Resolve bucket size
    if bucket_size is not None:
        bs = float(bucket_size)
    elif bucket_size_pct_of_close is not None:
        bs = float(bucket_size_pct_of_close) * float(np.median(closes))
    else:
        # Auto: span / 100, with a floor at 1 cent
        span = session_high - session_low
        bs = max(span / 100.0, 0.01)

    if bs <= 0:
        bs = max(0.01, abs(closes[0]) * 1e-4)

    # Bucket index for each bar
    # Bucket center = (idx + 0.5) * bs + offset, but we need consistent
    # baseline. Use session_low as origin so all buckets are non-negative.
    bucket_idx = np.floor((closes - session_low) / bs).astype(np.int64)
    # Edge: if all closes == session_low + 0, bucket_idx all 0; that's fine.
    n_buckets = int(bucket_idx.max()) + 1
    vol_per_bucket = np.zeros(n_buckets, dtype=np.float64)
    np.add.at(vol_per_bucket, bucket_idx, volumes)

    # POC
    poc_bucket = int(vol_per_bucket.argmax())
    poc_price = float(session_low + (poc_bucket + 0.5) * bs)

    # Value Area: expand outward from POC until cumulative >= value_area_pct
    total_vol = float(volumes.sum())
    target = total_vol * value_area_pct
    vah_idx = poc_bucket
    val_idx = poc_bucket
    captured = vol_per_bucket[poc_bucket]
    while captured < target and (val_idx > 0 or vah_idx < n_buckets - 1):
        # Step toward whichever side has more volume in the next bucket
        up_vol = vol_per_bucket[vah_idx + 1] if vah_idx + 1 < n_buckets else -1
        dn_vol = vol_per_bucket[val_idx - 1] if val_idx > 0 else -1
        if up_vol >= dn_vol and up_vol >= 0:
            vah_idx += 1
            captured += up_vol
        elif dn_vol >= 0:
            val_idx -= 1
            captured += dn_vol
        else:
            break

    vah = float(session_low + (vah_idx + 1) * bs)  # top edge of last bucket
    val = float(session_low + val_idx * bs)

    vwap = float((closes * volumes).sum() / total_vol)

    return VolumeProfile(
        poc_price=poc_price,
        vah=vah,
        val=val,
        vwap=vwap,
        total_volume=total_vol,
        n_bars=n,
        bucket_size=bs,
        session_high=session_high,
        session_low=session_low,
    )


def compute_session_volume_profile(
    bars_1m: pd.DataFrame,
    bucket_size: Optional[float] = None,
    bucket_size_pct_of_close: Optional[float] = None,
    value_area_pct: float = 0.70,
) -> Optional[VolumeProfile]:
    """Compute volume profile for a SINGLE-SESSION 1m bar frame.

    Caller must pre-filter to one trading session. To compute per-day
    profiles across many sessions, use :func:`compute_daily_volume_profile`.

    Parameters
    ----------
    bars_1m : pd.DataFrame
        1-minute bars; must have ``'close'`` and ``'volume'`` columns.
        Index can be DatetimeIndex but not strictly required.
    bucket_size : float, optional
        Absolute price-unit bucket width. Mutually exclusive with
        ``bucket_size_pct_of_close``.
    bucket_size_pct_of_close : float, optional
        Bucket width as fraction of session median close (e.g., 0.001 =
        10 bps). Mutually exclusive with ``bucket_size``.
    value_area_pct : float
        Fraction of session volume to capture in value area (standard
        institutional convention is 0.70 = 1σ-equivalent).

    Returns
    -------
    VolumeProfile or None
        ``None`` if no valid bars (all NaN or zero-volume).

    Raises
    ------
    ValueError
        On bad parameter combinations or missing required columns.
    """
    if bucket_size is not None and bucket_size_pct_of_close is not None:
        raise ValueError(
            "specify exactly one of bucket_size, bucket_size_pct_of_close"
        )
    for col in ("close", "volume"):
        if col not in bars_1m.columns:
            raise ValueError(
                f"bars_1m must have column {col!r}; got {list(bars_1m.columns)}"
            )
    if not (0 < value_area_pct < 1):
        raise ValueError(
            f"value_area_pct must be in (0,1), got {value_area_pct}"
        )

    return _compute_session_profile(
        closes=bars_1m["close"].to_numpy(dtype=np.float64),
        volumes=bars_1m["volume"].to_numpy(dtype=np.float64),
        bucket_size=bucket_size,
        bucket_size_pct_of_close=bucket_size_pct_of_close,
        value_area_pct=value_area_pct,
    )


def compute_daily_volume_profile(
    bars_1m: pd.DataFrame,
    bucket_size_pct_of_close: float = 0.001,
    value_area_pct: float = 0.70,
) -> pd.DataFrame:
    """Per-session profile aggregation across multi-day 1m bars.

    Groups by trading date (from the bars' DatetimeIndex.date) and
    computes a :class:`VolumeProfile` per session.

    Parameters
    ----------
    bars_1m : pd.DataFrame
        Multi-day 1m bars with DatetimeIndex; must have ``'close'`` and
        ``'volume'`` columns.
    bucket_size_pct_of_close : float
        Bucket width as fraction of session median close. 0.001 = 10 bps.
    value_area_pct : float
        Standard 0.70.

    Returns
    -------
    pd.DataFrame
        Indexed by trading date (pd.Timestamp); columns:
          - ``poc_price``     (float)
          - ``vah``           (float)
          - ``val``           (float)
          - ``vwap``          (float)
          - ``total_volume``  (float)
          - ``n_bars``        (int)
          - ``session_high``  (float)
          - ``session_low``   (float)
        Sessions with no valid bars are omitted from the output.

    Raises
    ------
    ValueError
        If index is not a DatetimeIndex or required columns missing.
    """
    if not isinstance(bars_1m.index, pd.DatetimeIndex):
        raise ValueError(
            f"bars_1m index must be DatetimeIndex, got {type(bars_1m.index).__name__}"
        )
    for col in ("close", "volume"):
        if col not in bars_1m.columns:
            raise ValueError(
                f"bars_1m must have column {col!r}; got {list(bars_1m.columns)}"
            )

    rows: list[dict] = []
    for trade_date, group in bars_1m.groupby(bars_1m.index.date):
        vp = _compute_session_profile(
            closes=group["close"].to_numpy(dtype=np.float64),
            volumes=group["volume"].to_numpy(dtype=np.float64),
            bucket_size_pct_of_close=bucket_size_pct_of_close,
            value_area_pct=value_area_pct,
        )
        if vp is None:
            continue
        rows.append({
            "date": pd.Timestamp(trade_date),
            "poc_price": vp.poc_price,
            "vah": vp.vah,
            "val": vp.val,
            "vwap": vp.vwap,
            "total_volume": vp.total_volume,
            "n_bars": vp.n_bars,
            "session_high": vp.session_high,
            "session_low": vp.session_low,
        })

    if not rows:
        return pd.DataFrame(
            columns=[
                "poc_price", "vah", "val", "vwap", "total_volume",
                "n_bars", "session_high", "session_low",
            ]
        )
    out = pd.DataFrame(rows).set_index("date").sort_index()
    return out


def position_within_value_area(
    price: float,
    val: float,
    vah: float,
) -> float:
    """Map price to a normalized [0, 1] position within [VAL, VAH].

    Returns
    -------
    float
        0.0 = at VAL, 1.0 = at VAH; can extend < 0 (below value area)
        or > 1 (above). NaN if val == vah (degenerate single-bucket
        session).
    """
    if not np.isfinite(val) or not np.isfinite(vah) or val == vah:
        return float("nan")
    return float((price - val) / (vah - val))
