"""
FactorGenerator: auto-construct candidate factors from OHLCV + macro data.

Generates cross-sectional factor exposures for each trading day.
Each factor is a DataFrame: index=date, columns=symbols, values=factor exposure.

Factor families:
  - Momentum (multi-period return, risk-adjusted momentum)
  - Mean reversion (short-term reversal)
  - Volatility (realized vol, vol regime, vol-adjusted returns)
  - Volume (volume surge, price-volume divergence)
  - Quality (Sharpe-based, drawdown-based)
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)


def generate_all_factors(
    price_df: pd.DataFrame,
    volume_df: pd.DataFrame | None = None,
) -> Dict[str, pd.DataFrame]:
    """
    Generate all candidate factors from price (and optionally volume) data.

    Parameters
    ----------
    price_df  : close prices, index=date, columns=symbols
    volume_df : daily volume, same shape as price_df (optional)

    Returns
    -------
    Dict[factor_name → DataFrame] with same index/columns as price_df
    """
    factors: Dict[str, pd.DataFrame] = {}

    factors.update(_momentum_factors(price_df))
    factors.update(_mean_reversion_factors(price_df))
    factors.update(_volatility_factors(price_df))
    if volume_df is not None:
        factors.update(_volume_factors(price_df, volume_df))
    factors.update(_quality_factors(price_df))

    logger.info("FactorGenerator: produced %d candidate factors", len(factors))
    return factors


def _momentum_factors(price_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    factors = {}
    for lookback in [21, 63, 126, 252]:
        ret = price_df.pct_change(lookback)
        factors[f"mom_{lookback}d"] = ret

    mom_252 = price_df.pct_change(252)
    mom_21 = price_df.pct_change(21)
    factors["mom_12_1"] = mom_252 - mom_21

    vol_63 = price_df.pct_change().rolling(63).std()
    mom_63 = price_df.pct_change(63)
    factors["risk_adj_mom_63d"] = mom_63 / vol_63.replace(0, np.nan)

    return factors


def _mean_reversion_factors(price_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    factors = {}
    for lookback in [5, 10, 21]:
        ret = price_df.pct_change(lookback)
        factors[f"reversal_{lookback}d"] = -ret

    for window in [20, 50]:
        sma = price_df.rolling(window).mean()
        factors[f"mean_rev_sma{window}"] = -(price_df - sma) / sma.replace(0, np.nan)

    return factors


def _volatility_factors(price_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    factors = {}
    daily_ret = price_df.pct_change()

    for window in [21, 63]:
        vol = daily_ret.rolling(window).std() * np.sqrt(252)
        factors[f"vol_{window}d"] = -vol

    vol_short = daily_ret.rolling(21).std()
    vol_long = daily_ret.rolling(126).std()
    factors["vol_regime"] = -(vol_short / vol_long.replace(0, np.nan))

    cummax = price_df.cummax()
    dd = (price_df - cummax) / cummax
    factors["drawdown_current"] = dd

    return factors


def _volume_factors(
    price_df: pd.DataFrame,
    volume_df: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    factors = {}
    vol_ma20 = volume_df.rolling(20).mean()
    factors["volume_surge_20d"] = volume_df / vol_ma20.replace(0, np.nan)

    daily_ret = price_df.pct_change()
    vol_chg = volume_df.pct_change()
    factors["price_volume_div"] = daily_ret.rolling(20).mean() - vol_chg.rolling(20).mean()

    return factors


def _quality_factors(price_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    factors = {}
    daily_ret = price_df.pct_change()

    ret_126 = daily_ret.rolling(126).mean() * 252
    vol_126 = daily_ret.rolling(126).std() * np.sqrt(252)
    factors["rolling_sharpe_126d"] = ret_126 / vol_126.replace(0, np.nan)

    cummax = price_df.rolling(252, min_periods=63).max()
    dd = (price_df - cummax) / cummax
    max_dd_126 = dd.rolling(126, min_periods=21).min()
    factors["max_dd_126d"] = -max_dd_126

    return factors


def compute_forward_returns(
    price_df: pd.DataFrame,
    horizons: List[int] = None,
) -> Dict[int, pd.DataFrame]:
    """Compute forward returns for IC calculation."""
    horizons = horizons or [5, 10, 21]
    result = {}
    for h in horizons:
        result[h] = price_df.pct_change(h).shift(-h)
    return result
