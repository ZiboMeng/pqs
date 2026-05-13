"""Compute IC + IR for full factor library on train years.

PRD-driven 2026-05-12 (Round Z1). Independent cross-validation of
162 factor library — answers "which factors actually have alpha vs
which are noise".
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_factor_ic_table(
    factor_panel_map: Dict[str, pd.DataFrame],
    forward_returns: pd.DataFrame,
    mask: Optional[pd.DataFrame] = None,
    lag_bars: int = 1,
) -> pd.DataFrame:
    """For each factor, compute cross-sectional Spearman IC time series,
    aggregate to mean / IR / sign-rate.

    Args:
        factor_panel_map: {factor_name: DataFrame(date × symbol)}
        forward_returns: DataFrame(date × symbol) of h-day forward return
                         already aligned to (date_t → return at t+h).
        mask: optional research mask (date × symbol) of bool
        lag_bars: shift factor by lag_bars before IC computation to
                  prevent contemporaneous leakage (default 1).

    Returns:
        DataFrame indexed by factor name with columns:
          - n_dates: number of valid date IC observations
          - mean_ic: average daily Spearman IC
          - ir: mean_ic / std_ic × sqrt(252)  (IR annualized)
          - positive_rate: fraction of dates with IC > 0
          - p50_abs_ic: median |IC|
    """
    rows = []
    for name, factor_df in factor_panel_map.items():
        if factor_df is None or factor_df.empty:
            continue
        # Shift factor by lag (PIT) and align to forward returns
        f = factor_df.shift(lag_bars)
        # Same index/cols intersection
        common_idx = f.index.intersection(forward_returns.index)
        common_cols = f.columns.intersection(forward_returns.columns)
        if len(common_idx) < 21 or len(common_cols) < 3:
            continue
        f = f.loc[common_idx, common_cols]
        r = forward_returns.loc[common_idx, common_cols]
        if mask is not None:
            m = mask.reindex(index=common_idx, columns=common_cols).fillna(True)
            f = f.where(m)
            r = r.where(m)

        # Per-date Spearman rank IC
        ic_series = []
        for d in f.index:
            x = f.loc[d].dropna()
            y = r.loc[d].dropna()
            common = x.index.intersection(y.index)
            if len(common) < 3:
                continue
            try:
                ic = x.loc[common].rank().corr(y.loc[common].rank())
            except Exception:
                continue
            if pd.notna(ic):
                ic_series.append(ic)
        if not ic_series:
            continue
        ic_arr = np.array(ic_series)
        mean_ic = float(np.mean(ic_arr))
        std_ic = float(np.std(ic_arr, ddof=1)) if len(ic_arr) > 1 else 0.0
        ir = mean_ic / std_ic * np.sqrt(252) if std_ic > 0 else 0.0
        rows.append({
            "factor": name,
            "n_dates": len(ic_arr),
            "mean_ic": mean_ic,
            "ir": ir,
            "positive_rate": float((ic_arr > 0).mean()),
            "p50_abs_ic": float(np.median(np.abs(ic_arr))),
        })

    if not rows:
        return pd.DataFrame(columns=["factor", "n_dates", "mean_ic", "ir",
                                       "positive_rate", "p50_abs_ic"])
    out = pd.DataFrame(rows).set_index("factor")
    return out.sort_values("ir", key=lambda s: s.abs(), ascending=False)
