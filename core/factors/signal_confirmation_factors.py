"""Multi-bar confirmation pattern factors.

PRD-driven 2026-05-12 per
`docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md` §4.1.

5 factors that capture setup-then-trigger patterns at the daily bar
level. Mining selects them when composite signal benefits from
multi-bar timing memory.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


SIGNAL_CONFIRMATION_FACTOR_NAMES = [
    "breakout_signal_age_5d",
    "retest_proximity_pct",
    "time_since_arm_bars",
    "confirmation_strength",
    "volume_surge_ratio_at_setup",
]


def compute_signal_confirmation_factors(
    price_df: pd.DataFrame,
    volume_df: Optional[pd.DataFrame] = None,
    setup_lookback: int = 20,
) -> Dict[str, pd.DataFrame]:
    """Compute 5 multi-bar confirmation factors.

    All factors use SHIFTED inputs (no same-bar lookahead).

    Definitions:
      breakout_signal_age_5d:
        bars since last 20d-high breakout (close > prior 20d max),
        capped at 5. NaN if no recent breakout in 20d.
      retest_proximity_pct:
        |close - rolling_5d_low(close)| / close ; how close is current
        price to a recent local low? Used post-breakout to detect
        successful retest setup.
      time_since_arm_bars:
        bars since the most recent volume surge above 1.5× 20d avg.
        Captures "armed not yet confirmed" state magnitude.
      confirmation_strength:
        (close - setup_price) / setup_price where setup_price = close
        at most recent breakout. Larger = stronger confirmation.
      volume_surge_ratio_at_setup:
        volume_20d_zscore at the most recent breakout setup bar.
        Captures volume conviction at arm time (preserved while
        signal armed).
    """
    factors: Dict[str, pd.DataFrame] = {}
    N = setup_lookback

    # Shifted by 1: no same-bar lookahead
    rolling_max_prior = price_df.rolling(N).max().shift(1)
    breakout = (price_df > rolling_max_prior).fillna(False)

    # breakout_signal_age_5d: bars since last True in `breakout`
    # If 0 = today is breakout, 1 = 1 bar ago, etc, NaN if no breakout
    # in last 5 bars.
    age = pd.DataFrame(np.nan, index=price_df.index, columns=price_df.columns)
    for col in price_df.columns:
        bk = breakout[col].values
        last_seen = -1  # bar idx
        for i, fired in enumerate(bk):
            if fired:
                last_seen = i
            if last_seen >= 0:
                lag = i - last_seen
                if lag <= 5:
                    age.iat[i, age.columns.get_loc(col)] = float(lag)
    factors["breakout_signal_age_5d"] = age

    # retest_proximity_pct: how close to local 5d low
    rolling_min_5 = price_df.rolling(5).min()
    factors["retest_proximity_pct"] = (
        (price_df - rolling_min_5) / price_df.replace(0, np.nan)
    )

    # volume_surge_ratio_at_setup: needs volume
    if volume_df is not None:
        vol_avg_20 = volume_df.rolling(20).mean().shift(1)
        vol_std_20 = volume_df.rolling(20).std().shift(1).replace(0, np.nan)
        vol_zscore = (volume_df - vol_avg_20) / vol_std_20

        # time_since_arm_bars: bars since last volume surge (z > 1.5)
        # Same forward-looking logic as breakout_signal_age but no cap
        surge = (vol_zscore > 1.5).fillna(False)
        tsince = pd.DataFrame(np.nan, index=price_df.index, columns=price_df.columns)
        for col in price_df.columns:
            sg = surge[col].values
            last = -1
            for i, fired in enumerate(sg):
                if fired:
                    last = i
                if last >= 0:
                    tsince.iat[i, tsince.columns.get_loc(col)] = float(i - last)
        factors["time_since_arm_bars"] = tsince

        # volume_surge_ratio_at_setup: hold-the-volume-z at breakout bar,
        # propagate forward for `setup_lookback` bars (carry-over signal).
        surge_at_breakout = vol_zscore.where(breakout)
        factors["volume_surge_ratio_at_setup"] = surge_at_breakout.ffill(limit=N)
    else:
        nan_panel = pd.DataFrame(
            np.nan, index=price_df.index, columns=price_df.columns,
        )
        factors["time_since_arm_bars"] = nan_panel
        factors["volume_surge_ratio_at_setup"] = nan_panel

    # confirmation_strength: (close - setup_price) / setup_price
    # setup_price = close at most recent breakout
    setup_price = price_df.where(breakout).ffill(limit=N)
    factors["confirmation_strength"] = (
        (price_df - setup_price) / setup_price.replace(0, np.nan)
    )

    return factors
