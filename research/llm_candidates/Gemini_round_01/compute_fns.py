import numpy as np
import pandas as pd

def volatility_squeeze_20d_gemini(price_df, vol_df=None, regime=None, **kwargs):
    # Calculate daily returns
    daily_ret = price_df.pct_change()
    
    # 20-day return
    ret_20d = price_df.pct_change(20)
    
    # Short-term and long-term volatility
    vol_20d = daily_ret.rolling(20, min_periods=10).std()
    vol_126d = daily_ret.rolling(126, min_periods=40).std()
    
    # Volatility ratio (squeeze measure). Lower ratio = tighter squeeze
    vol_ratio = vol_20d / vol_126d.replace(0, np.nan)
    
    # The factor: favor stocks with positive returns but tight consolidation
    # We add a small epsilon to avoid division by zero
    squeeze_factor = ret_20d / (vol_ratio + 1e-6)
    
    return squeeze_factor

def volume_exhaustion_reversal(price_df, vol_df=None, regime=None, **kwargs):
    if vol_df is None or vol_df.empty:
        return pd.DataFrame(0.0, index=price_df.index, columns=price_df.columns)
        
    # 5-day reversal (negative 5-day return)
    ret_5d = price_df.pct_change(5)
    reversal_5d = -ret_5d
    
    # Volume surge (current volume vs 20-day MA)
    vol_ma20 = vol_df.rolling(20, min_periods=10).mean()
    vol_surge = vol_df / vol_ma20.replace(0, np.nan)
    
    # Factor interaction: we only want to reward drops (reversal > 0) that have high volume.
    # To prevent rewarding high volume on price *increases* (which would be negative factor value),
    # we clip the reversal to only look at negative returns.
    reversal_only = reversal_5d.clip(lower=0)
    
    exhaustion_factor = reversal_only * vol_surge
    
    return exhaustion_factor

def regime_adjusted_quality_63d_gemini(price_df, vol_df=None, regime=None, **kwargs):
    # Calculate 63-day rolling Sharpe (Quality)
    daily_ret = price_df.pct_change()
    ret_63 = daily_ret.rolling(63, min_periods=20).mean() * 252
    vol_63 = daily_ret.rolling(63, min_periods=20).std() * np.sqrt(252)
    
    sharpe_63d = ret_63 / vol_63.replace(0, np.nan)
    
    # If regime is not provided, fallback to standard quality
    if regime is None or regime.empty:
        return sharpe_63d
        
    # Map regime states to weight multipliers
    regime_weights = {"CRISIS": 1.5, "RISK_OFF": 1.2, "CAUTIOUS": 1.0, "NEUTRAL": 0.8, "RISK_ON": 0.5, "BULL": 0.5}
    aligned_regime = regime.reindex(price_df.index, method="ffill").fillna("NEUTRAL")
    mult_series = aligned_regime.map(lambda r: regime_weights.get(str(r), 1.0))
    
    regime_adj_quality = sharpe_63d.multiply(mult_series, axis=0)
    return regime_adj_quality