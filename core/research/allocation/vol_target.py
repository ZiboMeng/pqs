"""P4 — volatility-target exposure overlay (PRD 20260521 §4.8
`risk_scaling`).

A SEPARATE lever from the score-to-weight mapping. `score_to_weight`
re-weights WITHIN the top-k; this overlay scales the whole book's GROSS
exposure up or down so the portfolio's trailing realized volatility
targets `target_vol` — the lever that actually cuts systematic
drawdown (P4 verdict Option B attempt 2, user-authorised 2026-05-22).

LONG-ONLY / NO-MARGIN GUARDRAIL: the scale is capped at `max_leverage`
(default 1.0), so the overlay can only ever DE-RISK — it never levers
the book above fully-invested. When it de-risks, the freed weight
becomes cash.
"""
from __future__ import annotations

import pandas as pd

__all__ = ["apply_vol_target_overlay"]


def apply_vol_target_overlay(
    weights: pd.DataFrame,
    close: pd.DataFrame,
    target_vol: float = 0.15,
    vol_lookback: int = 60,
    max_leverage: float = 1.0,
) -> pd.DataFrame:
    """Scale each bar's gross weights toward a portfolio vol target.

    Args:
        weights: (date × symbol) long-only target weights
        close: (date × symbol) adjusted close covering the weight span
        target_vol: annualized portfolio volatility target
        vol_lookback: trailing window (bars) for the realized-vol estimate
        max_leverage: hard cap on the scale factor (1.0 = no-margin —
            the overlay only de-risks, never levers up)

    Returns the scaled weight panel. Trailing realized vol is estimated
    from the *unscaled* book's return (a one-pass approximation); the
    scale at bar t uses only returns realized through t (no lookahead).
    """
    if weights.empty:
        return weights
    cols = [c for c in weights.columns if c in close.columns]
    rets = close[cols].reindex(weights.index).pct_change().fillna(0.0)
    # unscaled book return — weight set at T earned over T+1 (shift, no peek)
    gross_port_ret = (weights[cols].shift(1).fillna(0.0) * rets).sum(axis=1)
    realized_vol = (gross_port_ret.rolling(vol_lookback, min_periods=20).std()
                    * (252 ** 0.5))
    # scale ≤ max_leverage → only ever de-risk; warmup (NaN vol) = no scaling
    scale = (target_vol / realized_vol).clip(upper=max_leverage)
    scale = scale.fillna(max_leverage)
    return weights.mul(scale, axis=0)
