"""LLM-Phase Round 08 compute functions: soft-gate regime-conditioned
variants of Round 7 candidates (§3 regime-conditioned).

Round 7 used binary sign(SPY > 200d EMA) as regime gate. Q4 2024-2026
data showed IC collapsing to ~0 — hypothesis: in long persistent bull
markets the binary gate constantly outputs +1 and the factor degenerates
to its parent. Soft gate replaces sign(x) with tanh(x * scale), giving
continuous regime strength rather than a discrete switch.

If Q4 IC recovers under soft gate, the hypothesis is confirmed and
soft-gate becomes the preferred regime-conditioning approach.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def _spy_soft_regime(price_df: pd.DataFrame, scale: float = 20.0) -> pd.Series:
    """Continuous regime score = tanh((SPY - EMA200) / EMA200 * scale).
    Output in [-1, +1] with ~linear region near 0. scale=20 gives
    tanh(0.05 * 20) = tanh(1.0) ≈ 0.76 at a typical 5% SPY-above-EMA
    — saturates at large deviations, stays graded near the boundary."""
    if "SPY" not in price_df.columns:
        return pd.Series(dtype=float)
    spy = price_df["SPY"]
    ema = spy.ewm(span=200, adjust=False).mean()
    pct = (spy - ema) / ema
    return np.tanh(pct * scale)


def rs_qqq_soft_regime_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """rs_vs_qqq_63d × tanh-soft regime gate (§3 regime-conditioned).

    Soft-gate analog of Round 7's `rs_qqq_regime_conditioned_63d`. Uses
    continuous regime strength instead of binary sign. Tests whether
    the Q4 2024-2026 IC collapse (observed in Round 7) was due to binary
    gate degeneracy in persistent bull markets.
    """
    if "QQQ" not in price_df.columns or "SPY" not in price_df.columns:
        return pd.DataFrame()
    ret_63 = price_df.pct_change(63)
    rs_qqq = ret_63.sub(ret_63["QQQ"], axis=0)
    regime = _spy_soft_regime(price_df)
    feat = rs_qqq.mul(regime, axis=0)
    feat = feat.drop(columns=["SPY", "QQQ"], errors="ignore")
    return _zscore_cs(feat)


def mom_soft_regime_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """mom_63d × tanh-soft regime gate.

    Soft-gate analog of Round 7's `mom_regime_conditioned_63d`. Same
    Q4-decay test for momentum factor.
    """
    if "SPY" not in price_df.columns:
        return pd.DataFrame()
    mom = price_df.pct_change(63)
    regime = _spy_soft_regime(price_df)
    feat = mom.mul(regime, axis=0)
    feat = feat.drop(columns=["SPY"], errors="ignore")
    return _zscore_cs(feat)


def drawup_soft_regime_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """drawup_from_252d_low × tanh-soft regime gate.

    Round 1 & Round 3-5 candidate `drawup_from_252d_low` has IC +0.10
    but 1-factor backtest MaxDD -77.79% (Round 5 FAIL). Regime-gated
    version should reduce drawdown exposure (lower weight in bear
    regimes). Tests whether regime-conditioning is the missing risk
    management for this factor.
    """
    if "SPY" not in price_df.columns:
        return pd.DataFrame()
    rolling_min = price_df.rolling(252, min_periods=126).min()
    drawup = (price_df - rolling_min) / rolling_min.replace(0, np.nan)
    regime = _spy_soft_regime(price_df)
    feat = drawup.mul(regime, axis=0)
    feat = feat.drop(columns=["SPY"], errors="ignore")
    return _zscore_cs(feat)
