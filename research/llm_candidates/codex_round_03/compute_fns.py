"""LLM-Phase Round 21 compute functions: broad directional pack.

Goal: cover multiple candidate directions in one batch while remaining
compatible with Claude's current daily funnel.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def _rolling_positive_share(ret_df: pd.DataFrame, window: int, min_periods: int) -> pd.DataFrame:
    return ret_df.gt(0).astype(float).rolling(window, min_periods=min_periods).mean()


def volatility_squeeze_20d_codex(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    ret = price_df.pct_change()
    ret_20 = price_df.pct_change(20)
    vol_20 = ret.rolling(20, min_periods=10).std()
    vol_126 = ret.rolling(126, min_periods=40).std()
    vol_ratio = vol_20.div(vol_126.replace(0, np.nan))
    feat = ret_20.div(vol_ratio.replace(0, np.nan))
    return _zscore_cs(feat.shift(1))


def regime_adjusted_quality_63d_codex(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    ret = price_df.pct_change()
    sharpe_63 = ret.rolling(63, min_periods=20).mean().div(
        ret.rolling(63, min_periods=20).std().replace(0, np.nan)
    )
    if regime is None or len(regime) == 0:
        if "SPY" in price_df.columns:
            spy = price_df["SPY"]
            spy_dd = spy.div(spy.rolling(126, min_periods=63).max()) - 1.0
            mult = pd.Series(1.0, index=price_df.index)
            mult = mult.mask(spy_dd <= -0.20, 1.5)
            mult = mult.mask((spy_dd > -0.20) & (spy_dd <= -0.10), 1.2)
            mult = mult.mask((spy_dd > -0.10) & (spy_dd <= -0.05), 1.0)
            mult = mult.mask((spy_dd > -0.05) & (spy_dd <= 0.0), 0.8)
            mult = mult.mask(spy_dd > 0.0, 0.5)
        else:
            mult = pd.Series(1.0, index=price_df.index)
    else:
        aligned = regime.reindex(price_df.index, method="ffill").fillna("NEUTRAL")
        weights = {
            "CRISIS": 1.5, "RISK_OFF": 1.2, "CAUTIOUS": 1.0,
            "NEUTRAL": 0.8, "RISK_ON": 0.5, "BULL": 0.5,
        }
        mult = aligned.map(lambda x: weights.get(str(x), 1.0))
    feat = sharpe_63.mul(mult, axis=0)
    return _zscore_cs(feat.shift(1))


def return_path_fragmentation_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    ret = price_df.pct_change()
    net_ret = price_df.pct_change(63)
    sign_switch = ret.fillna(0).apply(np.sign).diff().ne(0).astype(float)
    fragmentation = sign_switch.rolling(63, min_periods=30).mean()
    feat = net_ret.div(1.0 + fragmentation)
    return _zscore_cs(feat.shift(1))


def relative_drawdown_vs_spy_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    if "SPY" not in price_df.columns:
        return pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    rolling_peak = price_df.rolling(63, min_periods=30).max()
    dd = price_df.div(rolling_peak) - 1.0
    spy_dd = dd["SPY"]
    feat = dd.sub(spy_dd, axis=0)
    return _zscore_cs(feat.shift(1))


def breadth_participation_gap_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    ret = price_df.pct_change()
    pos_share_5 = _rolling_positive_share(ret, 5, 3)
    pos_share_63 = _rolling_positive_share(ret, 63, 20)
    feat = pos_share_5 - pos_share_63
    return _zscore_cs(feat.shift(1))


def downside_gap_ratio_21d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    if "SPY" not in price_df.columns:
        return pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    ret = price_df.pct_change()
    spy = ret["SPY"]
    down_days = spy.lt(0)
    weak_ret = ret.where(down_days)
    strong_ret = ret.where(~down_days)
    weak_mean = weak_ret.rolling(21, min_periods=8).mean()
    strong_mean = strong_ret.rolling(21, min_periods=8).mean()
    feat = weak_mean.div(strong_mean.abs().replace(0, np.nan))
    return _zscore_cs(feat.shift(1))


def trend_stall_score_21_63(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    ret_21 = price_df.pct_change(21)
    ret_63 = price_df.pct_change(63)
    dist_to_63_high = price_df.div(price_df.rolling(63, min_periods=30).max()) - 1.0
    feat = (ret_21 - ret_63).sub(dist_to_63_high.abs())
    return _zscore_cs(feat.shift(1))


def rebound_asymmetry_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    ret = price_df.pct_change()
    up_capture = ret.clip(lower=0).rolling(63, min_periods=20).mean()
    down_capture = ret.clip(upper=0).abs().rolling(63, min_periods=20).mean()
    feat = up_capture.div(down_capture.replace(0, np.nan))
    return _zscore_cs(feat.shift(1))
