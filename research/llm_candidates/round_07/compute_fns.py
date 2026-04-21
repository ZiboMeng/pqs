"""LLM-Phase Round 07 compute functions: 3 interaction candidates
from Round 7's pairwise interaction mining (PRD §7 cross-signal).

Each is constructed as a multiplicative interaction between a parent
factor and a "regime gate" or complementary horizon. Parents are the
top-ranked features from Round 6's XGBoost permutation importance.

All computations use .shift() / .rolling() / .pct_change() for past-
only data. Interactions are cross-sectional z-scored per date so
they plug cleanly into the z-score composite used by MFS.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def _spy_trend_200d(price_df: pd.DataFrame) -> pd.Series:
    """Recreate factor_generator's spy_trend_200d as a per-date signed
    regime indicator (+1 if SPY > 200d EMA, −1 else). Returns Series
    indexed by date."""
    if "SPY" not in price_df.columns:
        return pd.Series(dtype=float)
    spy = price_df["SPY"]
    ema = spy.ewm(span=200, adjust=False).mean()
    trend = (spy > ema).astype(float) * 2 - 1
    return trend


def rs_qqq_regime_conditioned_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """rs_vs_qqq_63d × spy_trend_200d (Round 7 top interaction,
    incremental IC +0.058).

    Rationale: rs_vs_qqq_63d has modest univariate IC (+0.029) but
    XGBoost ranks it #3 because its value depends on MARKET REGIME.
    When SPY is above 200d EMA (bull), RS vs QQQ signal amplifies;
    when below (bear), sign inverts. This is a direct PRD §3
    'regime-conditioned factor' construction.

    formula:
      rs_qqq_63 = close.pct_change(63) - QQQ.pct_change(63)
      spy_trend = sign(SPY > SPY.ewm(span=200).mean())  # per date
      feat = rs_qqq_63 * spy_trend
      cross-sectional z-score per date
    """
    if "QQQ" not in price_df.columns or "SPY" not in price_df.columns:
        return pd.DataFrame()
    ret_63 = price_df.pct_change(63)
    rs_qqq = ret_63.sub(ret_63["QQQ"], axis=0)
    trend = _spy_trend_200d(price_df)
    # Broadcast trend across symbols (element-wise multiply preserves
    # per-symbol rs_qqq, per-date trend)
    feat = rs_qqq.mul(trend, axis=0)
    feat = feat.drop(columns=["SPY", "QQQ"], errors="ignore")
    return _zscore_cs(feat)


def mom_regime_conditioned_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """mom_63d × spy_trend_200d (Round 7 #2 interaction, tied +0.058
    incremental IC).

    Rationale: 63d momentum alone has IC +0.029 but produces much
    stronger signal when gated by market regime. In bull markets
    (spy_trend +1), momentum continues; in bear (−1), momentum factor
    inverts to mean-revert. Classical regime-conditioned momentum —
    not in existing registry.

    formula:
      mom_63 = close.pct_change(63)
      trend = sign(SPY > SPY.ewm(span=200).mean())
      feat = mom_63 * trend
    """
    if "SPY" not in price_df.columns:
        return pd.DataFrame()
    mom = price_df.pct_change(63)
    trend = _spy_trend_200d(price_df)
    feat = mom.mul(trend, axis=0)
    feat = feat.drop(columns=["SPY"], errors="ignore")
    return _zscore_cs(feat)


def rs_qqq_mom_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """rs_vs_qqq_63d × mom_63d (Round 7 #3 interaction, incr +0.040).

    Rationale: Both factors have modest univariate IC (~0.029 each)
    but their PRODUCT captures "stocks outperforming QQQ AND absolutely
    rising". The interaction filters out false positives where RS is
    high because QQQ is falling fast (stock is also falling, just less).
    Require BOTH positive for a positive factor score.

    formula:
      mom_63 = close.pct_change(63)
      rs_qqq = mom_63 - QQQ.pct_change(63)
      feat = mom_63 * rs_qqq
    """
    if "QQQ" not in price_df.columns:
        return pd.DataFrame()
    mom = price_df.pct_change(63)
    rs_qqq = mom.sub(mom["QQQ"], axis=0)
    feat = mom * rs_qqq
    feat = feat.drop(columns=["QQQ"], errors="ignore")
    return _zscore_cs(feat)
