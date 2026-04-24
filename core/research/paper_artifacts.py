"""Paper artifact writers + schema (Phase E-2 R9).

Pure functions for writing paper-run CSV artifacts. Used by
scripts/run_paper_candidate.py (R8) and read by
scripts/paper_drift_report.py (R10).

Artifact schema is documented in
docs/20260424-paper_artifact_schema.md. Keep this module's output
format in sync with that doc — drift between code and schema will
break drift-report consumption.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


__all__ = [
    "write_live_like_pnl",
    "write_benchmark_relative_paper",
    "write_turnover_log",
    "compute_benchmark_relative",
    "compute_turnover",
]


# ── Live-like PnL ───────────────────────────────────────────────────────────


def write_live_like_pnl(
    equity_curve: pd.Series,
    cash_curve: pd.Series,
    initial_capital: float,
    out_path: str | Path,
) -> Path:
    """Write `live_like_pnl.csv`.

    Schema (one row per trading date):
      date             : YYYY-MM-DD
      nav              : total portfolio value (equity_curve)
      cash             : cash balance
      ret_daily        : NAV daily pct change (0.0 on first row)
      ret_cumulative   : (nav / initial_capital) - 1
      dd               : drawdown from running max NAV (negative)
    """
    if not isinstance(equity_curve, pd.Series):
        raise TypeError("equity_curve must be a pd.Series")
    idx = equity_curve.index
    df = pd.DataFrame({
        "nav": equity_curve.values,
        "cash": cash_curve.reindex(idx).values,
    }, index=idx)
    df["ret_daily"] = df["nav"].pct_change().fillna(0.0)
    df["ret_cumulative"] = df["nav"] / float(initial_capital) - 1.0
    running_max = df["nav"].cummax()
    df["dd"] = df["nav"] / running_max - 1.0
    df.index.name = "date"
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p)
    return p


# ── Benchmark-relative PnL ──────────────────────────────────────────────────


def compute_benchmark_relative(
    equity_curve: pd.Series,
    benchmark_closes: dict[str, pd.Series],
    initial_capital: float,
) -> pd.DataFrame:
    """Compute paper NAV vs buy-and-hold benchmarks.

    Parameters
    ----------
    equity_curve      : paper NAV series (date → value)
    benchmark_closes  : {symbol: close-price Series} — e.g. SPY, QQQ
    initial_capital   : paper starting capital

    Returns DataFrame with columns:
      paper_cum_ret           : cumulative paper return
      <symbol>_cum_ret        : cumulative benchmark return (one per symbol)
      excess_vs_<symbol>_bps  : paper_cum_ret - bench_cum_ret (bps)
    """
    out = pd.DataFrame(index=equity_curve.index)
    out["paper_cum_ret"] = equity_curve / float(initial_capital) - 1.0
    for sym, close in benchmark_closes.items():
        aligned = close.reindex(equity_curve.index).ffill()
        if aligned.isna().all():
            continue
        first_valid_idx = aligned.first_valid_index()
        if first_valid_idx is None:
            continue
        base = float(aligned.loc[first_valid_idx])
        if base <= 0 or not np.isfinite(base):
            continue
        out[f"{sym}_cum_ret"] = aligned / base - 1.0
        excess = (out["paper_cum_ret"] - out[f"{sym}_cum_ret"]) * 10_000.0
        out[f"excess_vs_{sym}_bps"] = excess
    return out


def write_benchmark_relative_paper(
    equity_curve: pd.Series,
    benchmark_closes: dict[str, pd.Series],
    initial_capital: float,
    out_path: str | Path,
) -> Path:
    """Write `benchmark_relative_paper.csv`.

    Schema (one row per trading date):
      date                     : YYYY-MM-DD
      paper_cum_ret            : cumulative paper return (fractional)
      SPY_cum_ret              : cumulative SPY buy-and-hold return
      QQQ_cum_ret              : cumulative QQQ buy-and-hold return (if present)
      excess_vs_SPY_bps        : paper - SPY cum return (bps)
      excess_vs_QQQ_bps        : paper - QQQ cum return (bps) if present

    Benchmarks absent in `benchmark_closes` are silently skipped.
    """
    df = compute_benchmark_relative(
        equity_curve, benchmark_closes, initial_capital,
    )
    df.index.name = "date"
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p)
    return p


# ── Turnover log ────────────────────────────────────────────────────────────


def compute_turnover(target_wts: pd.DataFrame) -> pd.DataFrame:
    """Compute daily turnover from a target-weights panel.

    Turnover convention: sum of absolute weight changes from previous
    date, divided by 2. This is the long-only "one-way" turnover used
    across the repo (see also core/research/acceptance_helpers.py
    turnover_summary which uses a rank-stability proxy on composite
    signals).

    Returns DataFrame with columns:
      turnover        : 0.5 * sum(abs(w_t - w_{t-1}))
      n_positions     : number of non-zero weights on that date
      total_weight    : sum of absolute weights on that date
    """
    wts = target_wts.fillna(0.0)
    diff = wts.diff().abs().fillna(0.0)
    turnover = diff.sum(axis=1) / 2.0
    # First row has no prior reference; turnover should be |w_0|/2
    # (entering positions); our fillna(0.0) on diff gives 0 there
    # which understates the first-day cost. Re-stamp:
    first_idx = wts.index[0] if len(wts) else None
    if first_idx is not None:
        turnover.loc[first_idx] = wts.iloc[0].abs().sum() / 2.0
    n_pos = (wts != 0).sum(axis=1)
    total_w = wts.abs().sum(axis=1)
    return pd.DataFrame({
        "turnover": turnover,
        "n_positions": n_pos.astype(int),
        "total_weight": total_w,
    })


def write_turnover_log(
    target_wts: pd.DataFrame, out_path: str | Path,
) -> Path:
    """Write `turnover_log.csv`.

    Schema (one row per trading date):
      date          : YYYY-MM-DD
      turnover      : daily one-way turnover fraction
      n_positions   : number of non-zero weights that day
      total_weight  : sum |w_i| (gross exposure)
    """
    df = compute_turnover(target_wts)
    df.index.name = "date"
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p)
    return p
