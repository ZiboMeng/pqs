"""Factor bundle helper for IntradayReversalRunner.

T1a.3 — wires up the 4 factor panels required by `IntradayReversalRunner`:

  Daily factors (from `core.factors.factor_generator.generate_all_factors`):
    - weekly_reversal_signal_5d (= -ret_5d × volume_zscore_5d)
    - vol_21d (Parkinson high-low vol over 21d window)

  Intraday factors (from `core.factors.alt_a_intraday_inputs.compute_alt_a_intraday_inputs`):
    - intraday_volume_60m_zscore (first-regular-session 60m bar volume z-scored 20d)
    - early_session_return_pct (first-regular-session 60m bar (close-open)/open)

This module is a thin glue layer — neither factor compute is new. Both
existing modules are PRD-aligned per
`docs/prd/20260512-alt_archetype_intraday_reversal_prd.md` §11 LOCKED
defaults.

Output bundle matches the IntradayReversalRunner __init__ kwargs so
the caller can spread it directly:

    bundle = build_intraday_reversal_factor_bundle(...)
    runner = IntradayReversalRunner(strategy=strat, price_df=..., **bundle)
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import pandas as pd

from core.factors.alt_a_intraday_inputs import compute_alt_a_intraday_inputs
from core.factors.factor_generator import generate_all_factors

logger = logging.getLogger(__name__)


def build_intraday_reversal_factor_bundle(
    price_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    bars_60m_by_symbol: Dict[str, pd.DataFrame],
    rolling_window_days: int = 20,
    open_df: Optional[pd.DataFrame] = None,
    high_df: Optional[pd.DataFrame] = None,
    low_df: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """Compute the 4 factor panels needed by IntradayReversalRunner.

    Parameters
    ----------
    price_df : DataFrame
        Daily close prices (date × symbol). Drives weekly_reversal_signal_5d
        + vol_21d compute.
    volume_df : DataFrame
        Daily volume aligned with price_df. Drives weekly_reversal volume z-score.
    bars_60m_by_symbol : dict[str, DataFrame]
        Per-symbol 60m intraday bars (OHLCV). From BarStore.load(sym, freq="60m").
        Drives intraday_volume_60m_zscore + early_session_return_pct compute.
    rolling_window_days : int
        Lookback for intraday volume z-score (default 20 per PRD).
    open_df / high_df / low_df : DataFrame (optional)
        Daily OHL panels. If provided, enables Parkinson vol estimator.

    Returns
    -------
    {
      "weekly_reversal_signal_5d":   DataFrame (dates × symbols),
      "vol_21d":                     DataFrame (dates × symbols),
      "intraday_volume_60m_zscore":  DataFrame (dates × symbols),
      "early_session_return_pct":    DataFrame (dates × symbols),
    }

    All 4 panels share index = price_df.index and columns = sorted union of
    price_df.columns + 60m symbol keys (alignment via .reindex on output).
    """
    # 1. Daily factors via factor_generator
    daily_factors = generate_all_factors(
        price_df=price_df,
        volume_df=volume_df,
        open_df=open_df,
        high_df=high_df,
        low_df=low_df,
    )

    if "weekly_reversal_signal_5d" not in daily_factors:
        raise RuntimeError(
            "weekly_reversal_signal_5d not in factor_generator output — "
            "verify volume_df provided + factor_generator unchanged"
        )
    if "vol_21d" not in daily_factors:
        raise RuntimeError("vol_21d not in factor_generator output")

    wr = daily_factors["weekly_reversal_signal_5d"]
    vol = daily_factors["vol_21d"]

    # 2. Intraday factors via alt_a_intraday_inputs
    intraday_factors = compute_alt_a_intraday_inputs(
        bars_60m_by_symbol=bars_60m_by_symbol,
        daily_dates=price_df.index,
        rolling_window_days=rolling_window_days,
    )

    iv = intraday_factors["intraday_volume_60m_zscore"]
    er = intraday_factors["early_session_return_pct"]

    # 3. Align panels — all share price_df.index; columns may differ if
    # 60m bars cover different symbol set than price_df
    universe = sorted(set(price_df.columns) | set(bars_60m_by_symbol.keys()))
    wr = wr.reindex(index=price_df.index, columns=universe)
    vol = vol.reindex(index=price_df.index, columns=universe)
    iv = iv.reindex(index=price_df.index, columns=universe)
    er = er.reindex(index=price_df.index, columns=universe)

    logger.info(
        "intraday_factor_bundle: built 4 panels (%d dates × %d symbols)",
        len(price_df.index), len(universe),
    )

    return {
        "weekly_reversal_signal_5d": wr,
        "vol_21d": vol,
        "intraday_volume_60m_zscore": iv,
        "early_session_return_pct": er,
    }
