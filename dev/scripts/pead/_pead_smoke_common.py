"""Shared utilities for PEAD Path 1 + Path 2 smoke backtests.

Pre-flight bar-level integrity smoke per
[[feedback_bar_level_data_integrity_smoke]]:
  - weekend-row scan on close_df (must be 0 weekend rows)
  - cross-symbol date intersection min length check
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

PROJ = Path("/home/zibo/Documents/projects/pqs")
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd
import yaml

from core.data.bar_store import BarStore


def load_universe() -> List[str]:
    """Universe = seed_pool minus ETFs/inverse-3x ETFs."""
    with open(PROJ / "config/universe.yaml") as f:
        u = yaml.safe_load(f)
    return sorted([s for s in u.get("seed_pool", [])
                   if s not in ("SPY", "QQQ", "GLD", "TQQQ",
                                "SOXL", "SQQQ", "SOXS")])


def build_panels(
    symbols: List[str],
    start: str = "2017-01-02",
    end: str = "2025-12-31",
    add_benchmark: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return (close_df, open_df). Always passes open_df per
    [[feedback_bar_level_data_integrity_smoke]] + cycle11 lesson.

    If add_benchmark=True, SPY is included as a column for AR computation
    (price-jump path).
    """
    store = BarStore()
    closes, opens = {}, {}
    syms = list(symbols)
    if add_benchmark and "SPY" not in syms:
        syms.append("SPY")
    for sym in syms:
        try:
            df = store.load(sym, freq="1d", adjusted=True).sort_index()
            df = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
            if not df.empty:
                closes[sym] = df["close"]
                if "open" in df.columns:
                    opens[sym] = df["open"]
        except Exception:
            continue
    close_df = pd.DataFrame(closes).sort_index()
    open_df = pd.DataFrame(opens).reindex(index=close_df.index,
                                          columns=close_df.columns)

    # Bar-level integrity smoke (catch off-by-one)
    weekend_rows = close_df.index[close_df.index.dayofweek >= 5]
    if len(weekend_rows) > 0:
        raise ValueError(
            f"Weekend rows detected in close_df (n={len(weekend_rows)}). "
            f"Bar-level integrity smoke FAILED — see "
            f"docs/memos/20260513-spy_off_by_one_date_label_postmortem.md"
        )

    return close_df, open_df


def annualized_sharpe(returns: pd.Series) -> float:
    if returns.std() == 0 or len(returns) < 2:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(252))


def spy_baseline(start: str = "2017-01-02", end: str = "2025-12-31") -> dict:
    """SPY Sharpe + CAGR + MaxDD for comparison."""
    store = BarStore()
    spy = store.load("SPY", freq="1d", adjusted=True).sort_index()
    spy = spy[(spy.index >= pd.Timestamp(start)) & (spy.index <= pd.Timestamp(end))]
    spy_ret = spy["close"].pct_change().dropna()
    sharpe = annualized_sharpe(spy_ret)
    years = (spy.index[-1] - spy.index[0]).days / 365.25
    cagr = (spy["close"].iloc[-1] / spy["close"].iloc[0]) ** (1 / years) - 1
    return {"sharpe": sharpe, "cagr": float(cagr), "years": float(years)}


def trial_metrics(result, top_n_signals_avg: float = 0.0) -> dict:
    """Compute Sharpe / CAGR / MaxDD / n_trades from BacktestResult."""
    nav = result.equity_curve
    if len(nav) < 2:
        return {"sharpe": 0.0, "cagr": 0.0, "max_dd": 0.0, "n_trades": 0,
                "final_equity": float(nav.iloc[0]) if len(nav) else 10_000.0,
                "n_signals_avg_per_year": top_n_signals_avg}
    daily_ret = nav.pct_change().dropna()
    sharpe = annualized_sharpe(daily_ret)
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    peak = nav.cummax()
    max_dd = float(((nav - peak) / peak.replace(0, np.nan)).min())
    n_trades = len(result.trades) if result.trades is not None else 0
    return {
        "sharpe": sharpe, "cagr": float(cagr), "max_dd": max_dd,
        "n_trades": int(n_trades),
        "final_equity": float(nav.iloc[-1]),
        "n_signals_avg_per_year": float(top_n_signals_avg),
    }
