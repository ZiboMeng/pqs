import pandas as pd
import numpy as np

def intraday_support_21d(price_df, vol_df=None, regime=None, **kwargs):
    open_df = kwargs.get('open_df', price_df)
    high_df = kwargs.get('high_df', price_df)
    low_df = kwargs.get('low_df', price_df)
    
    lower_shadow = np.minimum(open_df, price_df) - low_df
    total_range = high_df - low_df
    total_range = total_range.replace(0, np.nan)
    
    ratio = lower_shadow / total_range
    return ratio.rolling(21, min_periods=10).mean().fillna(0)

def volume_trend_interaction(price_df, vol_df=None, regime=None, **kwargs):
    if vol_df is None: return pd.DataFrame(0, index=price_df.index, columns=price_df.columns)
    price_ret = price_df.pct_change(21)
    vol_mean_21 = vol_df.rolling(21, min_periods=10).mean()
    vol_mean_63 = vol_df.rolling(63, min_periods=30).mean().replace(0, np.nan)
    
    vol_trend = vol_mean_21 / vol_mean_63
    return (price_ret * vol_trend).fillna(0)

def turn_of_month_drift_126d(price_df, vol_df=None, regime=None, **kwargs):
    daily_ret = price_df.pct_change(1)
    days = pd.Series(price_df.index.day, index=price_df.index)
    is_tom = (days >= 28) | (days <= 3)
    
    tom_ret = daily_ret.where(is_tom.values[:, None], np.nan)
    return tom_ret.rolling(126, min_periods=10).mean().fillna(0)

def spy_divergence_21d(price_df, vol_df=None, regime=None, **kwargs):
    ret = price_df.pct_change(1)
    spy_ret = ret['SPY'] if 'SPY' in ret.columns else ret.mean(axis=1)
    
    down_days_mask = spy_ret < 0
    divergence_ret = ret.where(down_days_mask.values[:, None], 0)
    return divergence_ret.rolling(21, min_periods=5).sum().fillna(0)

def regime_bull_mom_21d(price_df, vol_df=None, regime=None, **kwargs):
    mom = price_df.pct_change(21)
    if regime is None: return mom.fillna(0)
    
    is_bull = (regime == 'BULL').astype(float)
    if isinstance(is_bull, pd.Series):
        return mom.multiply(is_bull, axis=0).fillna(0)
    return mom.fillna(0)

def fractal_dimension_proxy_63d(price_df, vol_df=None, regime=None, **kwargs):
    net_move = price_df.diff(63).abs()
    path_length = price_df.diff(1).abs().rolling(63, min_periods=30).sum().replace(0, np.nan)
    return (net_move / path_length).fillna(0)

def volatility_term_structure_ratio(price_df, vol_df=None, regime=None, **kwargs):
    ret = price_df.pct_change(1)
    vol_5d = ret.rolling(5, min_periods=3).std()
    vol_21d = ret.rolling(21, min_periods=10).std().replace(0, np.nan)
    return (-1 * (vol_5d / vol_21d)).fillna(0)

def xsec_volume_surge_5d(price_df, vol_df=None, regime=None, **kwargs):
    if vol_df is None: return pd.DataFrame(0, index=price_df.index, columns=price_df.columns)
    vol_5 = vol_df.rolling(5, min_periods=2).mean()
    vol_63 = vol_df.rolling(63, min_periods=20).mean().replace(0, np.nan)
    
    ratio = vol_5 / vol_63
    return ratio.rank(axis=1, pct=True).fillna(0.5)

def overnight_reversal_5d(price_df, vol_df=None, regime=None, **kwargs):
    open_df = kwargs.get('open_df', price_df)
    prev_close = price_df.shift(1).replace(0, np.nan)
    
    overnight_ret = (open_df - prev_close) / prev_close
    return (-1 * overnight_ret.rolling(5, min_periods=2).sum()).fillna(0)

def qqq_beta_divergence(price_df, vol_df=None, regime=None, **kwargs):
    ret = price_df.pct_change(1)
    qqq_ret = ret['QQQ'] if 'QQQ' in ret.columns else ret.mean(axis=1)
    
    var_63 = qqq_ret.rolling(63, min_periods=30).var().replace(0, np.nan)
    var_21 = qqq_ret.rolling(21, min_periods=10).var().replace(0, np.nan)
    
    cov_63 = ret.apply(lambda x: x.rolling(63, min_periods=30).cov(qqq_ret))
    cov_21 = ret.apply(lambda x: x.rolling(21, min_periods=10).cov(qqq_ret))
    
    beta_63 = cov_63.div(var_63, axis=0)
    beta_21 = cov_21.div(var_21, axis=0)
    
    return (beta_63 - beta_21).fillna(0)

def range_compression_5_63(price_df, vol_df=None, regime=None, **kwargs):
    high_df = kwargs.get('high_df', price_df)
    low_df = kwargs.get('low_df', price_df)
    
    range_ds = high_df - low_df
    atr_5 = range_ds.rolling(5, min_periods=2).mean()
    atr_63 = range_ds.rolling(63, min_periods=20).mean().replace(0, np.nan)
    
    return (-1 * (atr_5 / atr_63)).fillna(0)

def friday_seasonality_126d(price_df, vol_df=None, regime=None, **kwargs):
    ret = price_df.pct_change(1)
    is_friday = pd.Series(price_df.index.dayofweek == 4, index=price_df.index)
    
    friday_ret = ret.where(is_friday.values[:, None], np.nan)
    return friday_ret.rolling(126, min_periods=10).mean().fillna(0)

def intraday_overnight_ratio_21d(price_df, vol_df=None, regime=None, **kwargs):
    open_df = kwargs.get('open_df', price_df)
    prev_close = price_df.shift(1).replace(0, np.nan)
    safe_open = open_df.replace(0, np.nan)
    
    intraday_ret = (price_df - safe_open) / safe_open
    overnight_ret = (open_df - prev_close) / prev_close
    
    intra_mean = intraday_ret.rolling(21, min_periods=10).mean()
    over_std = overnight_ret.rolling(21, min_periods=10).std() + 1e-6
    
    return (intra_mean / over_std).fillna(0)

def skewness_63d(price_df, vol_df=None, regime=None, **kwargs):
    ret = price_df.pct_change(1)
    return (-1 * ret.rolling(63, min_periods=30).skew()).fillna(0)

def regime_cautious_low_vol(price_df, vol_df=None, regime=None, **kwargs):
    vol_21 = price_df.pct_change(1).rolling(21, min_periods=10).std().replace(0, np.nan)
    inv_vol = 1 / vol_21
    
    if regime is None: return inv_vol.fillna(0)
    
    is_cautious = (regime == 'CAUTIOUS').astype(float)
    if isinstance(is_cautious, pd.Series):
        return inv_vol.multiply(is_cautious, axis=0).fillna(0)
    return inv_vol.fillna(0)

def close_to_high_proximity_21d(price_df, vol_df=None, regime=None, **kwargs):
    high_df = kwargs.get('high_df', price_df)
    low_df = kwargs.get('low_df', price_df)
    
    high_21 = high_df.rolling(21, min_periods=10).max()
    low_21 = low_df.rolling(21, min_periods=10).min()
    rng = (high_21 - low_21).replace(0, np.nan)
    
    return ((price_df - low_21) / rng).fillna(0)

def vol_adjusted_mom_63d(price_df, vol_df=None, regime=None, **kwargs):
    ret_63 = price_df.pct_change(63)
    vol_63 = price_df.pct_change(1).rolling(63, min_periods=30).std().replace(0, np.nan)
    return (ret_63 / vol_63).fillna(0)

def up_day_volume_dominance_21d(price_df, vol_df=None, regime=None, **kwargs):
    if vol_df is None: return pd.DataFrame(0, index=price_df.index, columns=price_df.columns)
    ret = price_df.pct_change(1)
    
    vol_up = vol_df.where(ret > 0, np.nan).rolling(21, min_periods=5).mean()
    vol_down = vol_df.where(ret <= 0, np.nan).rolling(21, min_periods=5).mean().replace(0, np.nan)
    
    return (vol_up / vol_down).fillna(1)

def ew_relative_strength_21d(price_df, vol_df=None, regime=None, **kwargs):
    ret_21 = price_df.pct_change(21)
    ew_ret = ret_21.mean(axis=1)
    return ret_21.sub(ew_ret, axis=0).fillna(0)

def price_volume_divergence_5d(price_df, vol_df=None, regime=None, **kwargs):
    if vol_df is None: return pd.DataFrame(0, index=price_df.index, columns=price_df.columns)
    
    ret_5 = price_df.pct_change(5)
    ret_rank = ret_5.rank(axis=1, pct=True)
    
    vol_mean_21 = vol_df.rolling(21, min_periods=5).mean().replace(0, np.nan)
    vol_ratio = vol_df / vol_mean_21
    vol_rank = vol_ratio.rank(axis=1, pct=True)
    
    return (ret_rank + vol_rank).fillna(0)

