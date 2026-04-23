"""Codex round 04 compute functions: orthogonal candidate pack.

These candidates are intentionally spread across three different signal
families to reduce overlap:
1. beta-residual benchmark-relative strength
2. path-shape / return-distribution smoothness
3. regime-conditional return selectivity
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def _masked_rolling_mean(
    values: pd.DataFrame,
    mask: pd.Series,
    window: int,
    min_periods: int,
) -> pd.DataFrame:
    masked = values.mul(mask.astype(float), axis=0)
    roll_sum = masked.rolling(window, min_periods=min_periods).sum()
    roll_cnt = mask.astype(float).rolling(window, min_periods=min_periods).sum()
    return roll_sum.div(roll_cnt.replace(0, np.nan), axis=0)


def _masked_rolling_std(
    values: pd.DataFrame,
    mask: pd.Series,
    window: int,
    min_periods: int,
) -> pd.DataFrame:
    mean = _masked_rolling_mean(values, mask, window, min_periods)
    mean_sq = _masked_rolling_mean(values.pow(2), mask, window, min_periods)
    var = mean_sq - mean.pow(2)
    return np.sqrt(var.clip(lower=0))


def _rolling_positive_share(ret: pd.DataFrame, window: int, min_periods: int) -> pd.DataFrame:
    return ret.gt(0).astype(float).rolling(window, min_periods=min_periods).mean()


def _rolling_switch_rate(ret: pd.DataFrame, window: int, min_periods: int) -> pd.DataFrame:
    sign = np.sign(ret.fillna(0.0))
    switch = sign.diff().ne(0).astype(float)
    switch = switch.mask(sign.eq(0.0), np.nan)
    return switch.rolling(window, min_periods=min_periods).mean()


def _fallback_regime(price_df: pd.DataFrame) -> pd.Series:
    if "SPY" not in price_df.columns:
        return pd.Series("NEUTRAL", index=price_df.index)

    spy = price_df["SPY"]
    spy_ret_20 = spy.pct_change(20)
    spy_peak_126 = spy.rolling(126, min_periods=63).max()
    spy_dd_126 = spy.div(spy_peak_126).sub(1.0)

    out = pd.Series("NEUTRAL", index=price_df.index, dtype=object)
    out = out.mask(spy_dd_126 <= -0.15, "RISK_OFF")
    out = out.mask((spy_dd_126 > -0.15) & (spy_dd_126 <= -0.08), "CAUTIOUS")
    out = out.mask((spy_dd_126 > -0.08) & (spy_ret_20 > 0.08), "BULL")
    out = out.mask((spy_dd_126 > -0.08) & (spy_ret_20 > 0.02) & (spy_ret_20 <= 0.08), "RISK_ON")
    return out.ffill().fillna("NEUTRAL")


def ew_beta_residual_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """63d return net of beta-adjusted equal-weight universe return."""
    ret = price_df.pct_change()
    ew_daily = ret.mean(axis=1)
    ew_log = np.log1p(ew_daily.clip(lower=-0.95))
    ew_ret_63 = np.expm1(ew_log.rolling(63, min_periods=30).sum())

    ew_var_126 = ew_daily.rolling(126, min_periods=40).var()
    beta = pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    for col in price_df.columns:
        cov = ret[col].rolling(126, min_periods=40).cov(ew_daily)
        beta[col] = cov.div(ew_var_126.replace(0, np.nan))

    ret_63 = price_df.pct_change(63)
    feat = ret_63.sub(beta.mul(ew_ret_63, axis=0))
    return _zscore_cs(feat.shift(1))


def effective_path_breadth_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Net return scaled by how many days meaningfully contributed to the move."""
    ret = price_df.pct_change()
    net_ret_63 = price_df.pct_change(63)

    abs_sum_63 = ret.abs().rolling(63, min_periods=30).sum()
    sq_sum_63 = ret.pow(2).rolling(63, min_periods=30).sum()
    effective_n = abs_sum_63.pow(2).div(sq_sum_63.replace(0, np.nan))
    path_breadth = effective_n.div(63.0)

    feat = net_ret_63.mul(path_breadth)
    return _zscore_cs(feat.shift(1))


def ew_corr_diluted_trend_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """63d return discounted by equal-weight benchmark correlation."""
    ret = price_df.pct_change()
    ew_daily = ret.mean(axis=1)

    corr = pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    for col in price_df.columns:
        corr[col] = ret[col].rolling(63, min_periods=30).corr(ew_daily)

    feat = price_df.pct_change(63).mul(1.0 - corr.clip(lower=-1.0, upper=1.0))
    return _zscore_cs(feat.shift(1))


def run_persistence_spread_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Prefer paths with many up days and few sign changes."""
    ret = price_df.pct_change()
    positive_share = _rolling_positive_share(ret, window=63, min_periods=20)
    switch_rate = _rolling_switch_rate(ret, window=63, min_periods=20)
    feat = positive_share - switch_rate
    return _zscore_cs(feat.shift(1))


def segment_uniformity_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Reward 63d moves that are not dominated by a single 5d burst."""
    ret_63 = price_df.pct_change(63)
    move_5_abs = price_df.pct_change(5).abs()
    dominant_segment = move_5_abs.rolling(63, min_periods=20).max()
    feat = ret_63.div(dominant_segment.replace(0, np.nan))
    return _zscore_cs(feat.shift(1))


def break_even_recovery_21_63(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Short-window recovery strength net of medium-window overextension."""
    low_21 = price_df.rolling(21, min_periods=10).min()
    high_63 = price_df.rolling(63, min_periods=30).max()
    recovery = price_df.div(low_21).sub(1.0)
    gap_to_high = price_df.div(high_63).sub(1.0).abs()
    feat = recovery - gap_to_high
    return _zscore_cs(feat.shift(1))


def median_reclaim_strength_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Strength after reclaiming the 63d rolling median level."""
    median_63 = price_df.rolling(63, min_periods=30).median()
    gap = price_df.div(median_63).sub(1.0)
    reclaim_flag = price_df.shift(10).lt(median_63.shift(10))
    feat = gap.where(reclaim_flag, 0.0)
    return _zscore_cs(feat.shift(1))


def dispersion_day_alpha_spread_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Return spread between high-dispersion and low-dispersion market days."""
    ret = price_df.pct_change()
    dispersion = ret.std(axis=1)
    cutoff = dispersion.rolling(63, min_periods=20).median()
    high_disp = dispersion.gt(cutoff)
    low_disp = dispersion.le(cutoff)
    high_mean = _masked_rolling_mean(ret, high_disp, window=63, min_periods=15)
    low_mean = _masked_rolling_mean(ret, low_disp, window=63, min_periods=15)
    feat = high_mean - low_mean
    return _zscore_cs(feat.shift(1))


def breadth_alignment_share_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Hit-rate spread between strong-breadth and weak-breadth sessions."""
    ret = price_df.pct_change()
    breadth = ret.gt(0).mean(axis=1)
    strong = breadth.gt(0.60)
    weak = breadth.lt(0.40)
    hit = ret.gt(0).astype(float)
    strong_share = _masked_rolling_mean(hit, strong, window=63, min_periods=15)
    weak_share = _masked_rolling_mean(hit, weak, window=63, min_periods=15)
    feat = strong_share - weak_share
    return _zscore_cs(feat.shift(1))


def ew_tail_resilience_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Average stock return on the equal-weight universe's weakest days."""
    ret = price_df.pct_change()
    ew_daily = ret.mean(axis=1)
    tail_cut = ew_daily.rolling(63, min_periods=20).quantile(0.20)
    tail_mask = ew_daily.le(tail_cut)
    feat = _masked_rolling_mean(ret, tail_mask, window=63, min_periods=15)
    return _zscore_cs(feat.shift(1))


def regime_selectivity_spread_63d(
    price_df: pd.DataFrame,
    vol_df=None,
    regime=None,
    **kwargs,
) -> pd.DataFrame:
    """Average return in favorable regimes minus average return in cautious regimes."""
    ret = price_df.pct_change()

    if regime is None or len(regime) == 0:
        aligned = _fallback_regime(price_df)
    else:
        aligned = regime.reindex(price_df.index, method="ffill").fillna("NEUTRAL")

    favorable = aligned.isin(["BULL", "RISK_ON"])
    cautious = aligned.isin(["CAUTIOUS", "RISK_OFF"])

    favorable_mean = _masked_rolling_mean(ret, favorable, window=63, min_periods=10)
    cautious_mean = _masked_rolling_mean(ret, cautious, window=63, min_periods=10)
    feat = favorable_mean - cautious_mean
    return _zscore_cs(feat.shift(1))


def regime_volatility_selectivity_63d(
    price_df: pd.DataFrame,
    vol_df=None,
    regime=None,
    **kwargs,
) -> pd.DataFrame:
    """Prefer names whose volatility expands less in cautious regimes."""
    ret = price_df.pct_change()
    if regime is None or len(regime) == 0:
        aligned = _fallback_regime(price_df)
    else:
        aligned = regime.reindex(price_df.index, method="ffill").fillna("NEUTRAL")

    favorable = aligned.isin(["BULL", "RISK_ON"])
    cautious = aligned.isin(["CAUTIOUS", "RISK_OFF"])
    favorable_vol = _masked_rolling_std(ret, favorable, window=63, min_periods=10)
    cautious_vol = _masked_rolling_std(ret, cautious, window=63, min_periods=10)
    feat = -cautious_vol.div(favorable_vol.replace(0, np.nan))
    return _zscore_cs(feat.shift(1))


def bull_participation_share_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Positive-day share in favorable regimes relative to unconditional hit-rate."""
    ret = price_df.pct_change()
    if regime is None or len(regime) == 0:
        aligned = _fallback_regime(price_df)
    else:
        aligned = regime.reindex(price_df.index, method="ffill").fillna("NEUTRAL")

    favorable = aligned.isin(["BULL", "RISK_ON"])
    hit = ret.gt(0).astype(float)
    favorable_share = _masked_rolling_mean(hit, favorable, window=63, min_periods=10)
    all_share = hit.rolling(63, min_periods=20).mean()
    feat = favorable_share - all_share
    return _zscore_cs(feat.shift(1))


def cautious_hit_rate_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Positive-day share during cautious regimes."""
    ret = price_df.pct_change()
    if regime is None or len(regime) == 0:
        aligned = _fallback_regime(price_df)
    else:
        aligned = regime.reindex(price_df.index, method="ffill").fillna("NEUTRAL")

    cautious = aligned.isin(["CAUTIOUS", "RISK_OFF"])
    hit = ret.gt(0).astype(float)
    feat = _masked_rolling_mean(hit, cautious, window=63, min_periods=10)
    return _zscore_cs(feat.shift(1))


def tuesday_alpha_mean_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Average Tuesday return over the last 63 sessions."""
    ret = price_df.pct_change()
    mask = pd.Series(price_df.index.dayofweek == 1, index=price_df.index)
    feat = _masked_rolling_mean(ret, mask, window=63, min_periods=8)
    return _zscore_cs(feat.shift(1))


def month_half_rotation_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Return spread between early-mid and late-mid month sessions."""
    ret = price_df.pct_change()
    dom = pd.Series(price_df.index.day, index=price_df.index)
    early_mid = dom.between(6, 15)
    late_mid = dom.between(16, 25)
    early_mean = _masked_rolling_mean(ret, early_mid, window=63, min_periods=8)
    late_mean = _masked_rolling_mean(ret, late_mid, window=63, min_periods=8)
    feat = early_mean - late_mean
    return _zscore_cs(feat.shift(1))


def midmonth_strength_mean_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Average return during the middle of the month."""
    ret = price_df.pct_change()
    dom = pd.Series(price_df.index.day, index=price_df.index)
    mask = dom.between(11, 15)
    feat = _masked_rolling_mean(ret, mask, window=63, min_periods=8)
    return _zscore_cs(feat.shift(1))


def weekday_balance_spread_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Midweek return minus edge-of-week return."""
    ret = price_df.pct_change()
    dow = pd.Series(price_df.index.dayofweek, index=price_df.index)
    midweek = dow.isin([1, 2, 3])
    edge = dow.isin([0, 4])
    midweek_mean = _masked_rolling_mean(ret, midweek, window=63, min_periods=12)
    edge_mean = _masked_rolling_mean(ret, edge, window=63, min_periods=12)
    feat = midweek_mean - edge_mean
    return _zscore_cs(feat.shift(1))


def post_shock_drift_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Average return on the day after the stock's own downside shock."""
    ret = price_df.pct_change()
    shock_cut = ret.rolling(21, min_periods=10).quantile(0.10)
    post_shock = ret.shift(1).le(shock_cut.shift(1))
    masked = ret.where(post_shock)
    roll_sum = masked.rolling(63, min_periods=10).sum()
    roll_cnt = post_shock.astype(float).rolling(63, min_periods=10).sum()
    feat = roll_sum.div(roll_cnt.replace(0, np.nan))
    return _zscore_cs(feat.shift(1))


def crowding_gap_vs_qqq_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Trend scaled by whether the name behaves more like SPY than QQQ."""
    if "SPY" not in price_df.columns or "QQQ" not in price_df.columns:
        return pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)

    ret = price_df.pct_change()
    spy_ret = ret["SPY"]
    qqq_ret = ret["QQQ"]
    corr_spy = pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    corr_qqq = pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    for col in price_df.columns:
        corr_spy[col] = ret[col].rolling(63, min_periods=30).corr(spy_ret)
        corr_qqq[col] = ret[col].rolling(63, min_periods=30).corr(qqq_ret)

    corr_gap = corr_spy - corr_qqq
    feat = price_df.pct_change(63).mul(corr_gap)
    return _zscore_cs(feat.shift(1))
