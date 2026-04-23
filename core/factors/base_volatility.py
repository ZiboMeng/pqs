"""Shared volatility / range helpers (PRD 20260423 Step 1, Round 2).

Canonical primitives for the Volatility / Range family:
  - hl_range(high_df, low_df, close_df, normalize=True)
  - dollar_volume_ma(close_df, volume_df, window)

Design rule (inherited from base_factors.py / base_returns.py): every
function is a pure function of its inputs. Sign convention: all
helpers return RAW, unsigned values.

Note: `vol_20d` and `volume_ratio_20d` are ALIAS names per PRD §D3 /
§3.1.C and handled in factor_generator.py as `factors["vol_20d"] =
factors["vol_21d"]` etc. No new implementation — same DataFrame
reference. See PRD for rationale.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def hl_range(
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    close_df: pd.DataFrame,
    normalize: bool = True,
) -> pd.DataFrame:
    """Daily high-low range, optionally normalized by prior close.

    When `normalize=True` (default), returns `(H - L) / close[t-1]`.
    When False, returns the raw dollar range `H - L`. PRD §6.2
    recommends close-normalized for cross-ticker comparability.

    Parameters
    ----------
    high_df   : daily high, index=date, columns=symbols
    low_df    : daily low, same shape as high_df
    close_df  : daily close, same shape as high_df
    normalize : if True divide by prior close for scale-invariance

    Returns
    -------
    DataFrame aligned to high_df. First row is NaN when normalize=True
    (no prior close).
    """
    aligned_low = low_df.reindex_like(high_df)
    aligned_close = close_df.reindex_like(high_df)
    raw = high_df - aligned_low
    if not normalize:
        return raw
    prev_close = aligned_close.shift(1)
    return raw / prev_close


def dollar_volume_ma(
    close_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    window: int = 20,
    min_periods: int | None = None,
) -> pd.DataFrame:
    """Rolling mean of close × volume.

    Used both as a research feature (per PRD §D2) and as the basis for
    tradability masks (generated separately). As a feature it exposes
    each bar's trailing liquidity in dollar terms.

    Parameters
    ----------
    close_df  : daily close, index=date, columns=symbols
    volume_df : daily share volume, same shape as close_df
    window    : rolling window in trading days (default 20)
    min_periods : min observations for a valid rolling value; defaults
                  to ceil(window / 2)

    Returns
    -------
    DataFrame aligned to close_df. Leading `min_periods - 1` rows are NaN.
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    aligned_vol = volume_df.reindex_like(close_df)
    dollar_vol = close_df * aligned_vol
    mp = min_periods if min_periods is not None else max(1, window // 2)
    return dollar_vol.rolling(window, min_periods=mp).mean()
