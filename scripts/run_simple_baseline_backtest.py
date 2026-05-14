#!/usr/bin/env python3
"""
scripts/run_simple_baseline_backtest.py — Simple baseline backtest.

Strategy: 70% MTUM + 30% TQQQ-200SMA-or-BIL, monthly rebalance.

Discipline (CLAUDE.md temporal_split.yaml):
  - Strategy is FORMULA-only (no fitted parameter); design lives outside data.
  - Backtest computed on full daily series 2015-11-27 (MTUM inception) → 2024-12-31.
  - Metrics REPORTED only for train years: 2016, 2017, 2020, 2022, 2024.
  - Validation years (2018/19/21/23/25) and sealed year (2026): skipped from
    headline metrics per holdout discipline.

Execution convention: weights at end-of-day T → realized in close-to-close
return T+1 → T+2 (1-day lag). This mirrors PQS production T+1-open execution
spirit at daily granularity. Slightly conservative.

Outputs:
  - data/baseline_simple/nav.parquet  — daily NAV + benchmark NAVs
  - data/baseline_simple/report.json  — train-year metrics
  - data/baseline_simple/report.md    — human-readable summary
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.signals.strategies.simple_baseline import SimpleBaselineStrategy

OUT_DIR = Path("data/baseline_simple")
OUT_DIR.mkdir(parents=True, exist_ok=True)

TRAIN_YEARS = [2016, 2017, 2020, 2022, 2024]
START_DATE = "2015-01-02"
END_DATE = "2024-12-31"     # last train year end (strict ≤2024 per CLAUDE.md)


def _load_panel() -> pd.DataFrame:
    """Load panel via yfinance (PQS canonical BarStore has sparse MTUM 2015-17
    data; yfinance fallback allowed per CLAUDE.md ETF rule). All symbols
    use yfinance for consistency. STRICT END_DATE = 2024-12-31 — no 2025
    (validation) or 2026 (sealed) data loaded.
    """
    import yfinance as yf

    symbols = ["MTUM", "TQQQ", "BIL", "QQQ", "SPY"]
    closes = {}
    for sym in symbols:
        df = yf.download(sym, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        closes[sym] = df["Close"]
    # VIX (^VIX, no adjustment)
    vix_df = yf.download("^VIX", start=START_DATE, end=END_DATE, auto_adjust=False, progress=False)
    if isinstance(vix_df.columns, pd.MultiIndex):
        vix_df.columns = vix_df.columns.droplevel(1)
    closes["VIX"] = vix_df["Close"]

    panel = pd.DataFrame(closes).sort_index()
    panel.index.name = "date"
    # Drop rows where any required col is NaN (all need to be present)
    panel = panel.dropna()
    return panel


def _simulate(weights: pd.DataFrame, prices: pd.DataFrame) -> pd.Series:
    """T+1 close-to-close NAV simulation.

    weights[T] → realized in return[T+1 → T+2]. Shift weights forward 1 day.
    """
    # Daily returns (close-to-close)
    returns = prices.pct_change().fillna(0.0)
    # Align weights with returns (shift +1 day)
    aligned_weights = weights.shift(1).reindex(returns.index).fillna(0.0)
    # Portfolio daily return = sum(w * r) over assets that strategy uses
    cols_used = ["MTUM", "TQQQ", "BIL"]
    port_ret = (aligned_weights[cols_used] * returns[cols_used]).sum(axis=1)
    nav = (1.0 + port_ret).cumprod()
    nav.iloc[0] = 1.0  # starting NAV
    return nav


def _benchmark_nav(prices: pd.DataFrame, symbol: str) -> pd.Series:
    """Buy-and-hold NAV for benchmark."""
    returns = prices[symbol].pct_change().fillna(0.0)
    nav = (1.0 + returns).cumprod()
    nav.iloc[0] = 1.0
    return nav


def _metrics(nav: pd.Series, benchmark: pd.Series) -> dict:
    """Compute CAGR / Sharpe / MaxDD / vs benchmark over the input range."""
    if len(nav) < 2:
        return {}
    ret = nav.pct_change().dropna()
    n_days = len(ret)
    years = n_days / 252.0
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1) if years > 0 else 0.0
    bench_cagr = float((benchmark.iloc[-1] / benchmark.iloc[0]) ** (1 / years) - 1) if years > 0 else 0.0
    sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0
    # MaxDD
    running_max = nav.cummax()
    dd = (nav / running_max) - 1.0
    max_dd = float(dd.min())
    return {
        "n_days": n_days,
        "cagr": round(cagr, 4),
        "sharpe": round(sharpe, 3),
        "max_dd": round(max_dd, 4),
        "benchmark_cagr": round(bench_cagr, 4),
        "vs_benchmark_cagr": round(cagr - bench_cagr, 4),
        "cum_return": round(float(nav.iloc[-1] / nav.iloc[0] - 1), 4),
        "benchmark_cum_return": round(float(benchmark.iloc[-1] / benchmark.iloc[0] - 1), 4),
    }


def main() -> None:
    print("Loading panel...")
    panel = _load_panel()
    print(f"  Panel: {panel.index.min().date()} → {panel.index.max().date()} (n={len(panel)})")

    print("Generating strategy weights...")
    # Newfound "Protect & Participate" partial-defense pattern:
    # mtum_risk_off_weight=0.35 keeps some equity for rebound trades,
    # avoids the GTAA whipsaw cost while still cutting drawdown.
    strat = SimpleBaselineStrategy(mtum_risk_off_weight=0.25)
    weights = strat.generate(panel)
    # Sanity: post warmup, weights should sum near 1
    post_warmup = weights.iloc[300:]
    sums = post_warmup.sum(axis=1)
    print(f"  Post-warmup weight sums: mean={sums.mean():.4f}, min={sums.min():.4f}, max={sums.max():.4f}")

    print("Simulating NAV...")
    strat_nav = _simulate(weights, panel)
    spy_nav = _benchmark_nav(panel, "SPY")
    qqq_nav = _benchmark_nav(panel, "QQQ")

    # ── Train-year-only metrics ─────────────────────────────────────────
    print("\nTrain-year metrics (2016/2017/2020/2022/2024):")
    train_mask = pd.Series(panel.index.year, index=panel.index).isin(TRAIN_YEARS)
    # Concat train-year-only NAV by re-normalizing within each year
    by_year = {}
    cum_compounded = 1.0
    train_dates = []
    train_strat_ret = []
    train_spy_ret = []
    train_qqq_ret = []
    for year in TRAIN_YEARS:
        year_mask = panel.index.year == year
        if not year_mask.any():
            continue
        year_strat = strat_nav.loc[year_mask]
        year_spy = spy_nav.loc[year_mask]
        year_qqq = qqq_nav.loc[year_mask]
        # Renormalize per-year start = 1.0
        ystrat = year_strat / year_strat.iloc[0]
        yspy = year_spy / year_spy.iloc[0]
        yqqq = year_qqq / year_qqq.iloc[0]
        m_spy = _metrics(ystrat, yspy)
        m_qqq = _metrics(ystrat, yqqq)
        m = {
            "year": year,
            "n_days": m_spy["n_days"],
            "cum_return": m_spy["cum_return"],
            "sharpe": m_spy["sharpe"],
            "max_dd": m_spy["max_dd"],
            "vs_spy": m_spy["vs_benchmark_cagr"],
            "vs_qqq": m_qqq["vs_benchmark_cagr"],
            "spy_cum_return": m_spy["benchmark_cum_return"],
            "qqq_cum_return": m_qqq["benchmark_cum_return"],
        }
        by_year[year] = m
        cum_compounded *= (1.0 + m["cum_return"])
        train_strat_ret.append(ystrat.pct_change().fillna(0.0))
        train_spy_ret.append(yspy.pct_change().fillna(0.0))
        train_qqq_ret.append(yqqq.pct_change().fillna(0.0))
        print(f"  {year}: cum_ret={m['cum_return']:+.2%}, Sharpe={m['sharpe']:.2f}, "
              f"MaxDD={m['max_dd']:+.2%}, vs_SPY={m['vs_spy']:+.2%}, vs_QQQ={m['vs_qqq']:+.2%}")

    # Aggregate stats over train years
    all_strat = pd.concat(train_strat_ret)
    all_spy = pd.concat(train_spy_ret)
    all_qqq = pd.concat(train_qqq_ret)
    n_train_days = len(all_strat)
    train_years_n = n_train_days / 252.0
    train_cagr = float((1.0 + all_strat).prod() ** (1.0 / train_years_n) - 1)
    train_sharpe = float(all_strat.mean() / all_strat.std() * np.sqrt(252)) if all_strat.std() > 0 else 0.0
    train_spy_cagr = float((1.0 + all_spy).prod() ** (1.0 / train_years_n) - 1)
    train_qqq_cagr = float((1.0 + all_qqq).prod() ** (1.0 / train_years_n) - 1)
    # MaxDD over concatenated returns
    concat_nav = (1.0 + all_strat).cumprod()
    concat_dd = (concat_nav / concat_nav.cummax()) - 1.0
    train_maxdd = float(concat_dd.min())

    train_summary = {
        "train_years": TRAIN_YEARS,
        "n_train_days": n_train_days,
        "train_years_equivalent": round(train_years_n, 2),
        "cagr": round(train_cagr, 4),
        "sharpe": round(train_sharpe, 3),
        "max_dd": round(train_maxdd, 4),
        "spy_cagr": round(train_spy_cagr, 4),
        "qqq_cagr": round(train_qqq_cagr, 4),
        "cagr_vs_spy": round(train_cagr - train_spy_cagr, 4),
        "cagr_vs_qqq": round(train_cagr - train_qqq_cagr, 4),
    }

    print(f"\nTrain-years aggregate (concat NAV):")
    print(f"  CAGR={train_cagr:+.2%} vs SPY {train_spy_cagr:+.2%} (Δ {train_summary['cagr_vs_spy']:+.2%})")
    print(f"  CAGR vs QQQ {train_qqq_cagr:+.2%} (Δ {train_summary['cagr_vs_qqq']:+.2%})")
    print(f"  Sharpe={train_sharpe:.2f}, MaxDD={train_maxdd:+.2%}")

    # ── Save outputs ────────────────────────────────────────────────────────
    nav_df = pd.DataFrame({
        "strategy_nav": strat_nav,
        "spy_nav": spy_nav,
        "qqq_nav": qqq_nav,
    })
    nav_path = OUT_DIR / "nav.parquet"
    nav_df.to_parquet(nav_path)
    print(f"\nSaved NAV: {nav_path}")

    report = {
        "strategy": "SimpleBaselineStrategy",
        "spec": {
            "mtum_weight": 0.70,
            "leveraged_weight": 0.30,
            "leveraged_symbol": "TQQQ",
            "cash_symbol": "BIL",
            "trend_signal_symbol": "QQQ",
            "sma_window": 200,
            "rebalance_monthly": True,
        },
        "data_window": {
            "start": str(panel.index.min().date()),
            "end": str(panel.index.max().date()),
            "n_days": len(panel),
        },
        "by_train_year": by_year,
        "train_aggregate": train_summary,
        "discipline_note": (
            "Train years = 2016/2017/2020/2022/2024 only. Validation years "
            "(2018/19/21/23/25) and sealed (2026) skipped per "
            "config/temporal_split.yaml holdout discipline."
        ),
    }
    report_path = OUT_DIR / "report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"Saved report: {report_path}")


if __name__ == "__main__":
    main()
