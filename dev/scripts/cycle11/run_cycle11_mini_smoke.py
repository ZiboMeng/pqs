"""T2b cycle11 mini-mining smoke — 20-trial Optuna over simplified signal-driven search.

NOT the full cycle11 mining run (PRD §6 estimates ~1-1.5 weeks for full).
This is a feasibility smoke: pick best of {Faber, Donchian, Connors} × max_hold,
compute Sharpe per trial, archive top trial's metrics.

Stop rule per PRD §7: if best trial Sharpe << SPY Sharpe → cycle11 likely
won't produce Track A nominee → recommend defer to T2c ML Phase 2.
If best > SPY Sharpe → recommend full 200-trial authorize.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJ = Path("/home/zibo/Documents/projects/pqs")
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestResult
from core.backtest.signal_driven_runner import SignalDrivenBacktest
from core.data.bar_store import BarStore
from core.execution.cost_model import CostModel
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig


def _load_universe():
    import yaml
    with open(PROJ / "config/universe.yaml") as f:
        u = yaml.safe_load(f)
    return sorted([s for s in u.get("seed_pool", [])
                   if s not in ("SPY", "QQQ", "GLD", "TQQQ", "SOXL", "SQQQ", "SOXS")])


def _build_panels(symbols, start="2017-01-02", end="2025-12-31"):
    store = BarStore()
    closes = {}
    for sym in symbols:
        try:
            df = store.load(sym, freq="1d", adjusted=True).sort_index()
            df = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
            if not df.empty:
                closes[sym] = df["close"]
        except Exception:
            continue
    return pd.DataFrame(closes).sort_index()


def _entry_signals(close_df, seed: str, lookback: int):
    """Build entry_signals DataFrame per seed."""
    if seed == "faber":
        # Above 200-SMA AND prior bar below = breakout up
        sma200 = close_df.rolling(200, min_periods=50).mean()
        cur = close_df > sma200
        prev = close_df.shift(1) <= sma200.shift(1)
        return (cur & prev).fillna(False)
    elif seed == "donchian":
        # Close > N-day rolling max (shifted to prevent same-bar peek)
        rmax = close_df.rolling(lookback, min_periods=lookback).max().shift(1)
        return (close_df > rmax).fillna(False)
    elif seed == "connors_rsi2":
        # RSI(2) < 5 above 200-SMA
        delta = close_df.diff()
        up = delta.clip(lower=0).rolling(2).mean()
        down = (-delta.clip(upper=0)).rolling(2).mean().replace(0, np.nan)
        rs = up / down
        rsi2 = 100 - 100 / (1 + rs)
        sma200 = close_df.rolling(200, min_periods=50).mean()
        return ((rsi2 < 5) & (close_df > sma200)).fillna(False)
    else:
        raise ValueError(f"unknown seed: {seed}")


def _exit_signals(close_df, entry_signals, max_hold: int):
    """Max-hold approximation."""
    return entry_signals.shift(max_hold).fillna(False)


def _annualized_sharpe(returns: pd.Series) -> float:
    if returns.std() == 0 or len(returns) < 2:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(252))


def _run_trial(seed: str, lookback: int, max_hold: int, top_n: int,
               close_df, cost) -> dict:
    """Run one signal-driven backtest, return metrics."""
    entry = _entry_signals(close_df, seed, lookback)
    exit_ = _exit_signals(close_df, entry, max_hold)
    if entry.values.sum() == 0:
        return {"sharpe": 0.0, "cagr": 0.0, "max_dd": 0.0, "n_trades": 0,
                "final_equity": 10_000.0}
    try:
        bt = SignalDrivenBacktest(
            entry_signals=entry, exit_signals=exit_,
            price_df=close_df,
            ttl_bars=0,  # immediate confirm
            top_n=top_n,
            cost_model=cost,
            initial_capital=10_000.0,
            execution_delay_bars=1,
        )
        result = bt.run()
    except Exception as e:
        return {"sharpe": 0.0, "cagr": 0.0, "max_dd": 0.0, "n_trades": 0,
                "final_equity": 10_000.0, "error": str(e)[:80]}

    nav = result.equity_curve
    daily_ret = nav.pct_change().dropna()
    sharpe = _annualized_sharpe(daily_ret)
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1/years) - 1 if years > 0 else 0
    peak = nav.cummax()
    max_dd = float(((nav - peak) / peak.replace(0, np.nan)).min())
    n_trades = len(result.trades) if result.trades is not None else 0
    return {
        "sharpe": sharpe, "cagr": cagr, "max_dd": max_dd,
        "n_trades": n_trades, "final_equity": float(nav.iloc[-1]),
    }


def main():
    print("=== cycle11 mini-mining smoke (20 trials) ===")
    universe = _load_universe()
    print(f"Universe: {len(universe)} stocks")
    close_df = _build_panels(universe)
    print(f"Panel: {close_df.shape}, range {close_df.index.min().date()} → {close_df.index.max().date()}")

    cost = CostModel(CostModelConfig(
        tiers={"default": CostTierConfig(
            symbols=[], commission_bps=1.0,
            slippage_interday_bps=5.0, slippage_intraday_bps=10.0,
        )}
    ))

    # 20-trial smoke grid (deterministic, not Optuna for speed):
    # 3 seeds × ~7 configs each
    trials = []
    trial_id = 0
    rng = np.random.default_rng(42)
    seed_configs = [
        ("faber",         {"lookback": 200, "max_hold": 60, "top_n": 5}),
        ("faber",         {"lookback": 200, "max_hold": 30, "top_n": 5}),
        ("faber",         {"lookback": 200, "max_hold": 90, "top_n": 5}),
        ("donchian",      {"lookback": 20,  "max_hold": 21, "top_n": 5}),
        ("donchian",      {"lookback": 55,  "max_hold": 21, "top_n": 5}),
        ("donchian",      {"lookback": 20,  "max_hold": 10, "top_n": 5}),
        ("donchian",      {"lookback": 20,  "max_hold": 5,  "top_n": 5}),
        ("donchian",      {"lookback": 55,  "max_hold": 60, "top_n": 5}),
        ("donchian",      {"lookback": 55,  "max_hold": 60, "top_n": 10}),
        ("donchian",      {"lookback": 55,  "max_hold": 60, "top_n": 3}),
        ("connors_rsi2",  {"lookback": 2,   "max_hold": 5,  "top_n": 5}),
        ("connors_rsi2",  {"lookback": 2,   "max_hold": 10, "top_n": 5}),
        ("connors_rsi2",  {"lookback": 2,   "max_hold": 21, "top_n": 5}),
        ("connors_rsi2",  {"lookback": 2,   "max_hold": 5,  "top_n": 3}),
        ("connors_rsi2",  {"lookback": 2,   "max_hold": 5,  "top_n": 10}),
        ("donchian",      {"lookback": 100, "max_hold": 60, "top_n": 5}),
        ("donchian",      {"lookback": 252, "max_hold": 60, "top_n": 5}),
        ("faber",         {"lookback": 200, "max_hold": 252,"top_n": 5}),
        ("connors_rsi2",  {"lookback": 2,   "max_hold": 3,  "top_n": 5}),
        ("donchian",      {"lookback": 20,  "max_hold": 252,"top_n": 5}),
    ]

    print(f"\nRunning {len(seed_configs)} trials...")
    for i, (seed, cfg) in enumerate(seed_configs):
        result = _run_trial(seed, cfg["lookback"], cfg["max_hold"],
                            cfg["top_n"], close_df, cost)
        result.update({"trial_id": i, "seed": seed, **cfg})
        trials.append(result)
        err = f" [ERR: {result.get('error', '')}]" if "error" in result else ""
        print(f"  trial {i:2d}: {seed:14s} lookback={cfg['lookback']:3d} "
              f"hold={cfg['max_hold']:3d} top_n={cfg['top_n']} → "
              f"Sharpe={result['sharpe']:+.3f} CAGR={result['cagr']*100:+.2f}% "
              f"MaxDD={result['max_dd']*100:+.2f}% n_trades={result['n_trades']}{err}")

    # SPY baseline for comparison
    spy = BarStore().load("SPY", freq="1d", adjusted=True).sort_index()
    spy = spy[(spy.index >= pd.Timestamp("2017-01-02")) & (spy.index <= pd.Timestamp("2025-12-31"))]
    spy_ret = spy["close"].pct_change().dropna()
    spy_sharpe = _annualized_sharpe(spy_ret)
    spy_years = (spy.index[-1] - spy.index[0]).days / 365.25
    spy_cagr = (spy["close"].iloc[-1] / spy["close"].iloc[0]) ** (1/spy_years) - 1

    print(f"\n=== SPY baseline ===")
    print(f"  Sharpe={spy_sharpe:+.3f} CAGR={spy_cagr*100:+.2f}%")

    # Top by Sharpe
    valid = [t for t in trials if "error" not in t and t["sharpe"] > 0]
    top_sharpe = sorted(valid, key=lambda x: -x["sharpe"])[:5]
    print(f"\n=== Top 5 by Sharpe ===")
    for t in top_sharpe:
        beat_spy = "✓" if t["sharpe"] > spy_sharpe else "✗"
        print(f"  {beat_spy} trial {t['trial_id']:2d}: {t['seed']:14s} "
              f"hold={t['max_hold']:3d} → Sharpe={t['sharpe']:+.3f} "
              f"CAGR={t['cagr']*100:+.2f}%")

    # Save
    out = PROJ / "data/audit/cycle11_mini_smoke.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "lineage": "track-c-cycle-2026-05-14-11-signal-driven-smoke",
        "n_trials": len(trials),
        "spy_baseline": {"sharpe": spy_sharpe, "cagr": float(spy_cagr)},
        "trials": trials,
        "top_5_by_sharpe": top_sharpe,
    }
    out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nSaved: {out}")

    # Verdict
    if top_sharpe and top_sharpe[0]["sharpe"] > spy_sharpe:
        print(f"\nVERDICT: at least 1 trial beat SPY Sharpe. Full 200-trial mining likely worthwhile.")
    else:
        print(f"\nVERDICT: 0 trials beat SPY Sharpe ({spy_sharpe:+.3f}). cycle11 mini-mining suggests")
        print(f"  full 200-trial unlikely to produce Track-A-passing nominee. Recommend defer to T2c.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
