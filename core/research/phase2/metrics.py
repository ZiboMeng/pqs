"""Uniform phase-two performance and robustness metrics."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestResult, compute_metrics


def _period_return(returns: pd.Series, frequency: str) -> pd.Series:
    return (1.0 + returns).resample(frequency).prod() - 1.0


def _average_holding_sessions(trades: Iterable[Any]) -> float:
    open_dates: dict[str, list[pd.Timestamp]] = {}
    durations: list[int] = []
    for fill in sorted(trades, key=lambda item: item.fill_date):
        symbol = str(fill.symbol)
        if str(fill.side.value) == "BUY":
            open_dates.setdefault(symbol, []).append(pd.Timestamp(fill.fill_date))
        elif open_dates.get(symbol):
            start = open_dates[symbol].pop(0)
            durations.append(max(int(np.busday_count(start.date(), pd.Timestamp(fill.fill_date).date())), 0))
    return float(np.mean(durations)) if durations else 0.0


def detailed_metrics(
    result: BacktestResult,
    *,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    benchmark: pd.Series,
) -> dict[str, Any]:
    equity = result.equity_curve.loc[start:end].dropna()
    if len(equity) < 2:
        raise ValueError("evaluation slice has fewer than two NAV observations")
    benchmark_slice = benchmark.reindex(equity.index).dropna()
    metrics: dict[str, Any] = dict(
        compute_metrics(
            equity,
            initial_capital=float(equity.iloc[0]),
            benchmark=benchmark_slice,
        )
    )
    returns = equity.pct_change().dropna()
    weekly = _period_return(returns, "W-FRI")
    monthly = _period_return(returns, "ME")
    annual = _period_return(returns, "YE")
    drawdown = equity / equity.cummax() - 1.0
    underwater = drawdown < -0.001
    positive = returns[returns > 0.0]
    negative = returns[returns < 0.0]
    fills = [fill for fill in result.trades if pd.Timestamp(start) <= fill.fill_date <= pd.Timestamp(end)]
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1.0 / 252.0)
    traded_notional = float(sum(fill.notional_usd for fill in fills))
    average_equity = float(equity.mean())
    annual_turnover = traded_notional / max(average_equity, 1e-12) / years
    weights = result.weights.reindex(equity.index).fillna(0.0)
    gross = weights.abs().sum(axis=1)
    active_days = (gross > 0.01).mean()
    positive_annual = annual[annual > 0.0]
    best_year_fraction = (
        float(positive_annual.max() / positive_annual.sum())
        if len(positive_annual) and positive_annual.sum() > 0
        else 1.0
    )
    daily_profit_factor = (
        float(positive.sum() / abs(negative.sum())) if len(negative) and negative.sum() != 0 else float("inf")
    )
    total_commission = float(sum(fill.cost_breakdown.commission_usd for fill in fills))
    total_slippage = float(sum(fill.cost_breakdown.slippage_usd for fill in fills))
    metrics.update(
        {
            "time_under_water_fraction": float(underwater.mean()),
            "worst_day": float(returns.min()),
            "worst_week": float(weekly.min()),
            "worst_month": float(monthly.min()),
            "tail_loss_5pct": float(returns[returns <= returns.quantile(0.05)].mean()),
            "daily_profit_factor": daily_profit_factor,
            "daily_expectancy": float(returns.mean()),
            "exposure": float(gross.mean()),
            "market_participation": float(active_days),
            "annual_turnover": float(annual_turnover),
            "trade_count": len(fills),
            "average_holding_sessions_proxy": _average_holding_sessions(fills),
            "transaction_cost_usd": total_commission + total_slippage,
            "commission_usd": total_commission,
            "slippage_usd": total_slippage,
            "average_trade_notional_usd": traded_notional / max(len(fills), 1),
            "max_trade_notional_usd": max((float(fill.notional_usd) for fill in fills), default=0.0),
            "capacity_fraction_of_500k_proxy": max((float(fill.notional_usd) for fill in fills), default=0.0) / 500_000.0,
            "best_year_positive_pnl_fraction": best_year_fraction,
            "monthly_returns": {str(date.date()): float(value) for date, value in monthly.items()},
            "annual_returns": {str(date.year): float(value) for date, value in annual.items()},
        }
    )
    return metrics


def annual_fold_metrics(
    equity: pd.Series,
    benchmark: pd.Series,
    start_year: int,
    end_year: int,
) -> list[dict[str, Any]]:
    folds: list[dict[str, Any]] = []
    for year in range(start_year, end_year + 1):
        nav = equity[equity.index.year == year]
        if len(nav) < 20:
            continue
        metrics = compute_metrics(
            nav,
            initial_capital=float(nav.iloc[0]),
            benchmark=benchmark.reindex(nav.index),
        )
        folds.append({"year": year, **metrics})
    return folds


def stationary_bootstrap_cagr_ci(
    returns: pd.Series,
    *,
    seed: int = 20260717,
    samples: int = 500,
    average_block: int = 20,
) -> tuple[float, float]:
    """Deterministic stationary-block bootstrap CAGR confidence interval."""
    values = returns.dropna().to_numpy(dtype=float)
    if len(values) < 20:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    cagr_samples: list[float] = []
    restart_probability = 1.0 / average_block
    for _ in range(samples):
        sample = np.empty(len(values), dtype=float)
        index = int(rng.integers(0, len(values)))
        for position in range(len(values)):
            if position == 0 or rng.random() < restart_probability:
                index = int(rng.integers(0, len(values)))
            else:
                index = (index + 1) % len(values)
            sample[position] = values[index]
        total = float(np.prod(1.0 + sample))
        cagr_samples.append(total ** (252.0 / len(sample)) - 1.0 if total > 0 else -1.0)
    low, high = np.quantile(cagr_samples, [0.025, 0.975])
    return float(low), float(high)
