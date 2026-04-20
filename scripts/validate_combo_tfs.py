#!/usr/bin/env python3
"""
scripts/validate_combo_tfs.py — multi-timeframe combo incremental validation.

Tests combos:
    60m only
    60m + 30m
    60m + 30m + 15m
    60m + 30m + 15m + 5m

For each combo:
  - Decision cadence = finest TF in the combo
  - Higher TFs are backward-aligned onto the finest timeline (latest
    completed bar's direction)
  - Combined direction = equal-weighted sum of each TF's direction sign
    (-1/0/+1), thresholded at 0.5 → long=1 else 0
  - Long-only equal-weight portfolio, same as validate_single_tf

Purpose
-------
Establishes whether combining TFs produces incremental value over the
best single TF (60m baseline Sharpe +0.47 from validate_single_tf.py).

Incremental value requires: combo Sharpe > best single-TF Sharpe, AND
not obtained through mechanical volatility reduction (i.e., risk-
adjusted gain must exceed cost of higher turnover).

Usage
-----
    python scripts/validate_combo_tfs.py
    python scripts/validate_combo_tfs.py --symbols SPY QQQ AAPL
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
logger = get_logger("validate_combo_tfs")

_BARS_PER_YEAR = {"60m": 252 * 7, "30m": 252 * 13,
                  "15m": 252 * 26, "5m": 252 * 78}

_COMBOS = [
    ["60m"],
    ["60m", "30m"],
    ["60m", "30m", "15m"],
    ["60m", "30m", "15m", "5m"],
]


def _filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    mins = df.index.hour * 60 + df.index.minute
    return df.loc[(mins > 9 * 60 + 30) & (mins <= 16 * 60)]


def _bar_direction(df: pd.DataFrame) -> pd.Series:
    c = df["close"].astype(float)
    o = df["open"].astype(float)
    return pd.Series(
        np.where(c > o * 1.001, 1.0, np.where(c < o * 0.999, -1.0, 0.0)),
        index=df.index,
    )


def _align_backward(higher_dir: pd.Series, fine_index: pd.DatetimeIndex) -> pd.Series:
    """For each timestamp in fine_index, return the latest-available higher_dir
    value whose timestamp <= fine timestamp. Right-label convention: a higher
    bar closing at T becomes available at T."""
    # reindex with method='pad' uses last-known value; valid because
    # higher_dir is sorted and right-labeled.
    return higher_dir.reindex(
        higher_dir.index.union(fine_index)
    ).sort_index().ffill().reindex(fine_index)


def _load_tf(store: MarketDataStore, symbols, freq: str) -> dict:
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


def _combo_signal_per_sym(
    bars_per_tf: dict, sym: str, combo: list,
) -> tuple[pd.Series, pd.Series] | tuple[None, None]:
    """Build combined signal on the FINE-TF timeline for one symbol.

    Returns (fine_close_series, combined_signal_series) or (None, None).
    """
    fine = combo[-1]
    if sym not in bars_per_tf.get(fine, {}):
        return None, None

    fine_df = bars_per_tf[fine][sym]
    fine_idx = fine_df.index
    fine_dir = _bar_direction(fine_df)

    total = fine_dir.copy()
    n_active = pd.Series(1.0, index=fine_idx)

    for tf in combo[:-1]:
        if sym not in bars_per_tf.get(tf, {}):
            continue
        higher_dir = _bar_direction(bars_per_tf[tf][sym])
        aligned = _align_backward(higher_dir, fine_idx)
        valid = aligned.notna()
        total = total + aligned.fillna(0.0)
        n_active = n_active + valid.astype(float)

    # Equal-weighted mean of directions across all active TFs
    combined_score = total / n_active
    # Long-only gate: enter if combined score > 0.5 (majority bullish)
    long_sig = (combined_score > 0.5).astype(float)
    return fine_df["close"].astype(float), long_sig


def _backtest_combo(bars_per_tf: dict, symbols: list, combo: list) -> dict:
    fine = combo[-1]
    per_sym_rets = []
    per_sym_flip_frac = []
    per_sym_hit = []
    ic_per_sym = []  # IC of combined score vs next-bar return

    for sym in symbols:
        close, sig = _combo_signal_per_sym(bars_per_tf, sym, combo)
        if close is None or sig is None or len(close) < 20:
            continue

        fwd = close.pct_change().shift(-1)
        mask = fwd.notna() & sig.notna()
        if mask.sum() < 20:
            continue

        strat_ret = (sig * fwd)[mask]
        per_sym_rets.append(pd.Series(strat_ret.values, index=close.index[mask], name=sym))

        sig_vals = sig[mask].values
        flips = int(np.sum(np.abs(np.diff(sig_vals)) > 0.5))
        per_sym_flip_frac.append(flips / max(len(sig_vals), 1))

        active = sig_vals > 0.5
        if active.any():
            per_sym_hit.append((fwd[mask].values[active] > 0).mean())

        # IC: use the actual sign-weighted long_sig here
        rho = spearmanr(sig_vals, fwd[mask].values).correlation
        if not np.isnan(rho):
            ic_per_sym.append(rho)

    if not per_sym_rets:
        return {}

    port_df = pd.concat(per_sym_rets, axis=1, sort=True)
    port_ret = port_df.mean(axis=1, skipna=True).dropna()
    if len(port_ret) < 20:
        return {}

    bpy = _BARS_PER_YEAR[fine]
    mean = float(port_ret.mean())
    std = float(port_ret.std(ddof=1))
    sharpe = (mean / std) * np.sqrt(bpy) if std > 1e-12 else 0.0
    total = float((1.0 + port_ret).prod() - 1.0)
    n_years = len(port_ret) / bpy
    cagr = ((1.0 + total) ** (1.0 / n_years) - 1.0) if n_years > 0.05 else 0.0

    equity = (1.0 + port_ret).cumprod()
    dd = (equity / equity.cummax() - 1.0).min()

    return {
        "combo": "+".join(combo),
        "fine_tf": fine,
        "n_symbols": len(per_sym_rets),
        "n_bars": len(port_ret),
        "n_years": n_years,
        "sharpe": sharpe,
        "cagr": cagr,
        "max_dd": float(dd),
        "vol_ann": std * np.sqrt(bpy),
        "avg_flip_frac": float(np.mean(per_sym_flip_frac)) if per_sym_flip_frac else 0.0,
        "avg_hit_rate": float(np.mean(per_sym_hit)) if per_sym_hit else 0.0,
        "mean_ic": float(np.mean(ic_per_sym)) if ic_per_sym else np.nan,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--max-symbols", type=int, default=25)
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

    # Pre-load all 4 TFs once
    bars_per_tf = {}
    for tf in ["60m", "30m", "15m", "5m"]:
        bars_per_tf[tf] = _load_tf(store, symbols, tf)
        logger.info("%s: loaded %d symbols", tf, len(bars_per_tf[tf]))

    print(f"\nCombo incremental validation on up to {len(symbols)} symbols")
    print("Signal: majority-bullish gate on equal-weighted sum of per-TF bar direction")

    rows = []
    for combo in _COMBOS:
        logger.info("Running combo: %s", "+".join(combo))
        r = _backtest_combo(bars_per_tf, symbols, combo)
        if r:
            rows.append(r)

    if not rows:
        print("(no results)")
        return

    df = pd.DataFrame(rows).set_index("combo")
    print("\n=== Combo incremental table ===")
    cols = ["fine_tf", "n_symbols", "n_bars", "sharpe", "cagr",
            "max_dd", "vol_ann", "avg_flip_frac", "avg_hit_rate", "mean_ic"]
    disp = df[cols].copy()
    disp["cagr"] = (disp["cagr"] * 100)
    disp["max_dd"] = (disp["max_dd"] * 100)
    disp["vol_ann"] = (disp["vol_ann"] * 100)
    disp["avg_hit_rate"] = (disp["avg_hit_rate"] * 100)
    print(disp.to_string(float_format=lambda v: f"{v:+.3f}"))

    # Incremental delta vs shorter combo
    print("\n=== Incremental ΔSharpe vs previous combo ===")
    combos = df.index.tolist()
    prev_s = None
    for c in combos:
        s = df.loc[c, "sharpe"]
        delta = "--" if prev_s is None else f"{s - prev_s:+.3f}"
        print(f"  {c:<30} Sharpe={s:+.3f}   Δ={delta}")
        prev_s = s

    best_combo = df["sharpe"].idxmax()
    best_sharpe = df.loc[best_combo, "sharpe"]
    base_60m = df.loc["60m", "sharpe"] if "60m" in df.index else None
    print(f"\nBest combo (Sharpe): {best_combo}  Sharpe={best_sharpe:+.3f}")
    if base_60m is not None:
        delta = best_sharpe - base_60m
        print(f"Delta vs 60m-only baseline: {delta:+.3f}")
        if delta > 0.05:
            print("→ Incremental value detected.")
        elif delta > -0.05:
            print("→ No meaningful incremental value — combo ~= 60m baseline.")
        else:
            print("→ Negative incremental value — lower TFs hurt performance.")


if __name__ == "__main__":
    main()
