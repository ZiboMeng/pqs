"""P4 — reusable portfolio acceptance metrics (PRD 20260521 §9.2).

§9.2 mandates the P4 acceptance harness "first factor common code into
a reusable module" rather than duplicate it. This module is that common
block: it turns a daily target-weight panel + a close panel into the
canonical acceptance metrics every P4 path (A non-ML baseline / B ML
sidecar / C sidecar+partial-rebalance / D ranker-to-portfolio) reports.

Pricing convention mirrors the existing PRD #4 acceptance
(`r29_acceptance_r_ml_a_vs_b.py`): weights are shifted by one bar before
being multiplied by returns — a weight set at T is earned over T+1, no
lookahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["portfolio_metrics"]


def portfolio_metrics(
    daily_weights: pd.DataFrame,
    close: pd.DataFrame,
    benchmark: pd.Series | None = None,
) -> dict:
    """Acceptance metrics from a daily target-weight panel.

    Args:
        daily_weights: (date × symbol) long-only target weights
        close: (date × symbol) adjusted close, covering the weight span
        benchmark: optional benchmark close series for vs-bench excess

    Returns dict: cum_return / annualized_sharpe / annualized_vol /
    max_drawdown / turnover_mean / n_periods (+ vs_benchmark_excess_cum
    when a benchmark is given).
    """
    if daily_weights.empty:
        return {"cum_return": 0.0, "annualized_sharpe": 0.0,
                "annualized_vol": 0.0, "max_drawdown": 0.0,
                "turnover_mean": 0.0, "n_periods": 0}
    cols = [c for c in daily_weights.columns if c in close.columns]
    rets = close[cols].reindex(daily_weights.index).pct_change().fillna(0.0)
    # shift weights by one bar — weight set at T earned over T+1 (no lookahead)
    shifted = daily_weights[cols].shift(1).fillna(0.0)
    port_ret = (shifted * rets).sum(axis=1)
    nav = (1.0 + port_ret).cumprod()
    ann_ret = float(port_ret.mean()) * 252.0
    ann_vol = float(port_ret.std()) * np.sqrt(252.0)
    sharpe = (ann_ret / ann_vol) if ann_vol > 0 else 0.0
    cum = float(nav.iloc[-1] - 1.0)
    dd = (nav - nav.cummax()) / nav.cummax()
    max_dd = float(dd.min())
    turnover = float(
        daily_weights[cols].fillna(0.0).diff().abs().sum(axis=1).mean())
    out = {
        "cum_return": round(cum, 4),
        "annualized_sharpe": round(sharpe, 4),
        "annualized_vol": round(ann_vol, 4),
        "max_drawdown": round(max_dd, 4),
        "turnover_mean": round(turnover, 4),
        "n_periods": int(len(port_ret)),
    }
    if benchmark is not None:
        b = benchmark.reindex(daily_weights.index).dropna()
        if len(b) >= 2:
            out["vs_benchmark_excess_cum"] = round(
                cum - float(b.iloc[-1] / b.iloc[0] - 1.0), 4)
    return out
