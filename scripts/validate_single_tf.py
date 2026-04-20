#!/usr/bin/env python3
"""
scripts/validate_single_tf.py — single-timeframe baseline validation.

For each chosen timeframe (60m / 30m / 15m / 5m), computes in isolation:
  1. Per-bar IC:
     - bar_direction  (sign of close-open) vs next-bar return
     - bar_return     (close/open - 1)      vs next-bar return
  2. A naive baseline portfolio backtest:
     - Signal at bar t = sign(close_t - open_t)
     - Long-only: weight = max(signal, 0)
     - Equal-weight across symbols where weight > 0
     - Return = sum(weight * (close[t+1]/close[t] - 1)) across symbols
  3. Trading stats: approx. #flips (≈ #trades), win rate

Purpose
-------
Establishes each TF's INDEPENDENT signal quality, so #10 (combo
validation) can demonstrate whether combining TFs produces incremental
value over the best single TF.

Usage
-----
    python scripts/validate_single_tf.py                 # all TFs
    python scripts/validate_single_tf.py --freq 60m
    python scripts/validate_single_tf.py --freq 60m 30m
    python scripts/validate_single_tf.py --symbols SPY QQQ AAPL
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.logging_setup import setup_logging, get_logger

setup_logging()
logger = get_logger("validate_single_tf")

# Bars per trading year (RTH only, 252 trading days × bars-per-day)
_BARS_PER_YEAR = {
    "60m":  252 * 7,     # 10:30..16:00 + one 09:30-10:30 edge; roughly 7 bars/day
    "30m":  252 * 13,
    "15m":  252 * 26,
    "5m":   252 * 78,
}


def _filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    """Keep bars whose close timestamp is within RTH (09:30, 16:00] ET.

    Right-labeled bars: a 60m bar at 10:30 covers (09:30, 10:30]; include.
    We treat anything strictly after 09:30 and at-or-before 16:00 as RTH.
    """
    if df.empty:
        return df
    hh = df.index.hour
    mm = df.index.minute
    mins = hh * 60 + mm
    # (09:30, 16:00] — exclude 09:30 (pre-market close), include 16:00 (RTH close)
    return df.loc[(mins > 9 * 60 + 30) & (mins <= 16 * 60)]


def _load_bars(store: MarketDataStore, symbols, freq: str) -> dict:
    out = {}
    for s in symbols:
        try:
            df = store.read(s, freq)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        df = _filter_rth(df)
        if len(df) < 50:
            continue
        out[s] = df
    return out


def _per_symbol_ic(df: pd.DataFrame) -> dict:
    """Per-symbol IC of bar_direction and bar_return vs next-bar return."""
    c = df["close"].values.astype(float)
    o = df["open"].values.astype(float)
    if len(c) < 20:
        return {}

    bar_dir = np.where(c > o * 1.001, 1.0, np.where(c < o * 0.999, -1.0, 0.0))
    bar_ret = (c - o) / np.where(o > 0, o, np.nan)
    # Next-bar close-to-close return (what a trade opened "now" earns if
    # held one bar)
    fwd = np.empty_like(c)
    fwd[:-1] = c[1:] / c[:-1] - 1.0
    fwd[-1] = np.nan

    mask = ~(np.isnan(bar_dir) | np.isnan(fwd))
    ic_dir = spearmanr(bar_dir[mask], fwd[mask]).correlation if mask.sum() > 20 else np.nan
    mask2 = ~(np.isnan(bar_ret) | np.isnan(fwd))
    ic_ret = spearmanr(bar_ret[mask2], fwd[mask2]).correlation if mask2.sum() > 20 else np.nan

    return {"ic_dir": ic_dir, "ic_ret": ic_ret, "n_bars": int(mask.sum())}


def _baseline_backtest(bars_by_sym: dict, freq: str) -> dict:
    """Pool every symbol's per-bar 'long if bar up' signal into an
    equal-weight portfolio return series. Returns annualized stats."""
    per_sym_returns = []
    per_sym_flip_frac = []  # approximation of turnover per symbol
    per_sym_hit_rate = []

    for sym, df in bars_by_sym.items():
        c = df["close"].values.astype(float)
        o = df["open"].values.astype(float)
        if len(c) < 20:
            continue
        sig = np.where(c > o * 1.001, 1.0, 0.0)  # long-only
        fwd = np.empty_like(c)
        fwd[:-1] = c[1:] / c[:-1] - 1.0
        fwd[-1] = np.nan
        # Apply sig at bar t to fwd return from t to t+1
        strat_ret = sig * fwd
        # Drop NaN tail
        strat_ret = strat_ret[:-1]
        sig_used = sig[:-1]
        fwd_used = fwd[:-1]
        if len(strat_ret) < 20:
            continue

        per_sym_returns.append(pd.Series(strat_ret, index=df.index[:-1], name=sym))

        flips = np.sum(np.abs(np.diff(sig_used)) > 0.5)
        per_sym_flip_frac.append(flips / max(len(sig_used), 1))

        active = sig_used > 0.5
        if active.any():
            hit = (fwd_used[active] > 0).mean()
            per_sym_hit_rate.append(hit)

    if not per_sym_returns:
        return {}

    # Cross-sectional equal-weight mean per bar timestamp
    port_df = pd.concat(per_sym_returns, axis=1, sort=True)
    port_ret = port_df.mean(axis=1, skipna=True).dropna()
    if len(port_ret) < 20:
        return {}

    bpy = _BARS_PER_YEAR.get(freq, 252 * 7)
    mean = float(port_ret.mean())
    std = float(port_ret.std(ddof=1))
    sharpe = (mean / std) * np.sqrt(bpy) if std > 1e-12 else 0.0
    total = float((1.0 + port_ret).prod() - 1.0)
    n_years = len(port_ret) / bpy
    cagr = ((1.0 + total) ** (1.0 / n_years) - 1.0) if n_years > 0.05 else 0.0

    equity = (1.0 + port_ret).cumprod()
    running_max = equity.cummax()
    dd = (equity / running_max - 1.0).min()

    return {
        "n_bars": int(len(port_ret)),
        "n_years": float(n_years),
        "sharpe": float(sharpe),
        "cagr": float(cagr),
        "max_dd": float(dd),
        "vol_ann": float(std * np.sqrt(bpy)),
        "avg_flip_frac": float(np.mean(per_sym_flip_frac)) if per_sym_flip_frac else 0.0,
        "avg_hit_rate": float(np.mean(per_sym_hit_rate)) if per_sym_hit_rate else 0.0,
        "n_symbols": len(per_sym_returns),
    }


def _print_tf_block(freq: str, ic_rows: list, bt: dict) -> None:
    print(f"\n=== {freq} ===")
    if not ic_rows:
        print("  (no data)")
        return

    ic_df = pd.DataFrame(ic_rows).set_index("symbol")
    mean_dir = ic_df["ic_dir"].mean(skipna=True)
    mean_ret = ic_df["ic_ret"].mean(skipna=True)
    print(f"  Symbols: {len(ic_df)}  Bars/sym avg: {ic_df['n_bars'].mean():.0f}")
    print(f"  Mean IC(bar_direction): {mean_dir:+.5f}")
    print(f"  Mean IC(bar_return)   : {mean_ret:+.5f}")

    if not bt:
        print("  (no baseline backtest)")
        return

    print(f"  Baseline (long-if-bar-up, equal weight):")
    print(f"    n_bars={bt['n_bars']}  n_years={bt['n_years']:.2f}  "
          f"symbols={bt['n_symbols']}")
    print(f"    Sharpe={bt['sharpe']:+.2f}  CAGR={bt['cagr']*100:+.2f}%  "
          f"Vol={bt['vol_ann']*100:.1f}%  MaxDD={bt['max_dd']*100:.1f}%")
    print(f"    Flip fraction/bar={bt['avg_flip_frac']:.3f}  "
          f"HitRate(active)={bt['avg_hit_rate']*100:.1f}%")


def main():
    parser = argparse.ArgumentParser(description="Single-TF baseline validation")
    parser.add_argument("--freq", nargs="*", default=["60m", "30m", "15m", "5m"])
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="Override symbol set (default: universe tradeable)")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--max-symbols", type=int, default=25,
                        help="Cap symbol count to keep runtime sane")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    if args.symbols:
        symbols = list(args.symbols)
    else:
        uni = cfg.universe
        all_syms = list(dict.fromkeys(
            list(uni.seed_pool) + list(uni.sector_etfs) +
            list(uni.factor_etfs) + list(uni.cross_asset)
        ))
        symbols = [s for s in all_syms
                   if s not in uni.blacklist and s not in uni.macro_reference]
    symbols = symbols[: args.max_symbols]
    logger.info("Using %d symbols: %s", len(symbols), symbols[:10])

    print(f"Single-TF baseline validation on {len(symbols)} symbols")
    print(f"Timeframes: {args.freq}")

    summary_rows = []
    for freq in args.freq:
        bars_by_sym = _load_bars(store, symbols, freq)
        logger.info("%s: loaded %d symbols", freq, len(bars_by_sym))

        ic_rows = []
        for sym, df in bars_by_sym.items():
            stat = _per_symbol_ic(df)
            if stat:
                ic_rows.append({"symbol": sym, **stat})

        bt = _baseline_backtest(bars_by_sym, freq)
        _print_tf_block(freq, ic_rows, bt)

        if bt:
            summary_rows.append({
                "freq": freq,
                "n_symbols": bt["n_symbols"],
                "n_bars": bt["n_bars"],
                "sharpe": bt["sharpe"],
                "cagr": bt["cagr"] * 100,
                "max_dd": bt["max_dd"] * 100,
                "flip_frac": bt["avg_flip_frac"],
                "hit_rate": bt["avg_hit_rate"] * 100,
            })

    if summary_rows:
        print("\n=== Summary across TFs ===")
        df = pd.DataFrame(summary_rows).set_index("freq")
        print(df.to_string(float_format=lambda v: f"{v:+.3f}"))
        # Identify best single TF by Sharpe (baseline for #10 to beat)
        best = df["sharpe"].idxmax()
        print(f"\nBest single-TF baseline (Sharpe): {best}  "
              f"Sharpe={df.loc[best, 'sharpe']:.2f}")


if __name__ == "__main__":
    main()
