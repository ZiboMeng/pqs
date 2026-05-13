"""New-factor vs existing-candidate NAV correlation diagnostic.

PRD-driven 2026-05-12 (Round Z1).

For each new factor, run a simple top-N long-only backtest on train
years and compute its NAV correlation vs anchor candidates (RCMv1,
Cand-2, Trial 9). Factors with high NAV correlation to anchors are
sibling-disguised; factors with low correlation are real alpha
candidates for cycle #09.

This is a lightweight proxy — full mining-grade composite construction
is at `core/mining/research_miner.py`. This module is for fast
diagnostic ranking.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _simple_top_n_nav(
    factor_panel: pd.DataFrame,
    forward_returns: pd.DataFrame,
    top_n: int = 10,
    rebalance_freq: int = 21,
) -> pd.Series:
    """Long-only top-N equal-weight NAV from a single factor.

    Sort by factor each rebalance bar, hold top N, equal-weight.
    Returns a NAV series indexed by date.
    """
    common_idx = factor_panel.index.intersection(forward_returns.index)
    common_cols = factor_panel.columns.intersection(forward_returns.columns)
    if len(common_idx) < rebalance_freq * 2 or len(common_cols) < top_n:
        return pd.Series(dtype=float)

    f = factor_panel.loc[common_idx, common_cols]
    r = forward_returns.loc[common_idx, common_cols]

    nav = [1.0]
    rebalance_dates = common_idx[::rebalance_freq]
    daily_rets = []
    current_weights = None

    for i, d in enumerate(common_idx):
        # Rebalance
        if d in rebalance_dates:
            row = f.loc[d].dropna()
            if len(row) < top_n:
                current_weights = None
            else:
                # Top N by factor (descending — convention: high factor = expected high return)
                top = row.nlargest(top_n).index
                current_weights = pd.Series(1.0 / top_n, index=top)
        if current_weights is not None:
            row_r = r.loc[d].reindex(current_weights.index).fillna(0)
            period_ret = (current_weights * row_r).sum()
            nav.append(nav[-1] * (1 + period_ret / rebalance_freq))
        else:
            nav.append(nav[-1])
    nav_series = pd.Series(nav[1:], index=common_idx, name="nav")
    return nav_series


def compute_anchor_nav_correlation(
    factor_panel_map: Dict[str, pd.DataFrame],
    forward_returns: pd.DataFrame,
    anchor_navs: Dict[str, pd.Series],
    top_n: int = 10,
    rebalance_freq: int = 21,
) -> pd.DataFrame:
    """For each factor, compute simple top-N NAV and Pearson correlation
    of its log-returns vs each anchor NAV's log-returns.

    Args:
        factor_panel_map: {factor_name: panel}
        forward_returns: 1-bar forward returns panel (used for proxy NAV)
        anchor_navs: {anchor_name: NAV series}
        top_n: long-only top-N to hold (default 10)
        rebalance_freq: bars between rebalance (default 21 = monthly)

    Returns:
        DataFrame indexed by factor name, columns = anchor names, values
        = log-return Pearson correlation. Plus 'max_corr' column.
    """
    rows = []
    for name, fdf in factor_panel_map.items():
        if fdf is None or fdf.empty:
            continue
        try:
            f_nav = _simple_top_n_nav(fdf, forward_returns, top_n=top_n,
                                       rebalance_freq=rebalance_freq)
        except Exception:
            continue
        if len(f_nav) < 60:
            continue
        f_log_ret = np.log(f_nav.replace(0, np.nan)).diff().dropna()
        row = {"factor": name}
        for anchor_name, anchor_nav in anchor_navs.items():
            anchor_log_ret = np.log(anchor_nav.replace(0, np.nan)).diff().dropna()
            common = f_log_ret.index.intersection(anchor_log_ret.index)
            if len(common) < 30:
                row[anchor_name] = np.nan
                continue
            row[anchor_name] = float(
                f_log_ret.loc[common].corr(anchor_log_ret.loc[common])
            )
        anchors = list(anchor_navs.keys())
        row["max_corr"] = float(max(abs(row[a]) for a in anchors
                                      if pd.notna(row[a])) if anchors else np.nan)
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("factor").sort_values("max_corr")
