"""LLM-Phase Round 04 compute functions for 3 benchmark-relative candidates.

Focus: §3 benchmark-relative direction, specifically constructions that
use BOTH SPY and QQQ (our co-primary benchmarks per QQQ hard gate rule)
or cross-sectional panel mean. All past-only via explicit .shift() /
.pct_change() / .rolling().

Authored by LLM as candidate generator (PRD §2.1). Funnel + deep_check
determines verdict (§2.2).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def non_tech_rs_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """(RS vs QQQ) − (RS vs SPY) on 63d — tech-tilt isolation factor.

    Rationale: a stock whose excess return vs QQQ exceeds its excess
    return vs SPY is relatively LESS tech-tilted (tracks broad market
    better than tech benchmark). In tech-led bull markets these names
    lag; in tech-reversal regimes they outperform. This is a
    cross-benchmark differential that neither rs_vs_spy_* nor a hypothetical
    rs_vs_qqq_* alone captures.

    formula: (pct_change(63) - QQQ_pct_change(63))
           - (pct_change(63) - SPY_pct_change(63))
           = SPY_pct_change(63) - QQQ_pct_change(63)   (constant across symbols!)
    That's degenerate — need per-symbol dimension.

    Corrected construction: use RS IC (rank correlation proxy):
      rs_qqq = ret - qqq_ret       (per symbol, per date)
      rs_spy = ret - spy_ret       (per symbol, per date)
      Note rs_qqq - rs_spy = spy_ret - qqq_ret (symbol-invariant, bad).
      Use instead: RATIO of the two RS measures, or SIGN disagreement.

    Final construction:
      tech_tilt_score = rs_qqq * sign(rs_qqq - rs_spy)
      positive → stock outperforms QQQ AND outperforms it by more than it
                 outperforms SPY (i.e., a rotation-resistant name)
      negative → stock underperforms QQQ or its outperformance is
                 smaller than its SPY outperformance (tech beta residual)
    """
    ret = price_df.pct_change(63)
    if "QQQ" not in price_df.columns or "SPY" not in price_df.columns:
        return pd.DataFrame()
    rs_qqq = ret.sub(ret["QQQ"], axis=0)
    rs_spy = ret.sub(ret["SPY"], axis=0)
    diff = rs_qqq - rs_spy  # = spy_ret - qqq_ret per row (symbol-invariant)
    # To make per-symbol: multiply rs_qqq by the sign of its own RS
    # DIFFERENCE to SPY. In practice: rs_qqq * (rs_qqq > rs_spy ? 1 : -1)
    sign_term = (rs_qqq > rs_spy).astype(float) * 2 - 1  # +1 / -1 mask
    tech_tilt = rs_qqq * sign_term
    # Drop benchmark columns from output (not meaningful as candidates)
    tech_tilt = tech_tilt.drop(columns=["SPY", "QQQ"], errors="ignore")
    return _zscore_cs(tech_tilt)


def rs_vs_equal_weight_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Return relative to cross-sectional equal-weighted mean over 63d
    (§3 cross-sectional benchmark-relative).

    Rationale: isolates idiosyncratic alpha from panel beta. Different
    from rs_vs_spy_* because equal-weighted mean is universe-specific
    rather than market-cap-weighted. In a concentrated universe
    (Mag7-heavy), EW mean differs materially from SPY.

    formula:
      ret_63d = close.pct_change(63)
      ew_mean = ret_63d.mean(axis=1)
      rs_ew = ret_63d - ew_mean
    """
    ret = price_df.pct_change(63)
    ew_mean = ret.mean(axis=1)
    rs_ew = ret.sub(ew_mean, axis=0)
    return _zscore_cs(rs_ew)


def rs_21d_minus_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Short-horizon minus long-horizon RS vs SPY (§3 multi-horizon).

    Rationale: tests the TERM STRUCTURE of relative strength per symbol.
    Positive value → recent 21d RS > longer 63d RS → relative strength
    is accelerating. Negative → RS decelerating. Existing factors capture
    absolute RS at each horizon; this captures the DIFFERENCE, which is
    a distinct acceleration signal.

    formula:
      rs_21 = close.pct_change(21) - SPY.pct_change(21)
      rs_63 = close.pct_change(63) - SPY.pct_change(63)
      feat = rs_21 - rs_63
    """
    if "SPY" not in price_df.columns:
        return pd.DataFrame()
    ret_21 = price_df.pct_change(21)
    ret_63 = price_df.pct_change(63)
    rs_21 = ret_21.sub(ret_21["SPY"], axis=0)
    rs_63 = ret_63.sub(ret_63["SPY"], axis=0)
    feat = rs_21 - rs_63
    feat = feat.drop(columns=["SPY"], errors="ignore")
    return _zscore_cs(feat)
