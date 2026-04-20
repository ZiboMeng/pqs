#!/usr/bin/env python3
"""
scripts/validate_combo_costs.py — multi-TF combo cost & turnover stress.

For each combo in validate_combo_tfs.py, applies cost stress at multiple
levels and computes:
  - Gross Sharpe / CAGR
  - Net Sharpe / CAGR after intraday slippage + commission
  - Avg holding bars (1 / flip_frac)
  - Annualized turnover (round-trips per year)
  - Breakeven cost multiplier (the cost mult at which net Sharpe ≈ 0)

Cost model: uses config/cost_model.yaml `default` tier
  bps_per_trade = commission_bps + slippage_intraday_bps
At default config that is roughly 13bps per side = 26bps round-trip.

Purpose
-------
Prove (or refute) that the lower-TF combos can survive trading costs.
Given #10 finding that lower TFs reduce GROSS Sharpe, this confirms
they cannot be saved by execution timing — they're already sub-baseline
before cost.

Usage
-----
    python scripts/validate_combo_costs.py
    python scripts/validate_combo_costs.py --symbols SPY QQQ AAPL
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.logging_setup import setup_logging, get_logger

# Reuse helpers from the combo validation script
from scripts.validate_combo_tfs import (
    _COMBOS, _BARS_PER_YEAR, _load_tf, _combo_signal_per_sym,
)

setup_logging()
logger = get_logger("validate_combo_costs")

_COST_MULTS = [0.0, 0.5, 1.0, 2.0, 3.0, 5.0]


def _backtest_combo_cost(
    bars_per_tf: dict, symbols: list, combo: list, cost_bps_per_trade: float,
) -> dict:
    """Same as validate_combo_tfs._backtest_combo, but applies a per-flip
    cost in bps. Cost is applied to the bar where the signal flips
    (entry or exit), proportional to |delta_weight| (0 or 1)."""
    fine = combo[-1]
    per_sym_rets, per_sym_flips = [], []

    for sym in symbols:
        close, sig = _combo_signal_per_sym(bars_per_tf, sym, combo)
        if close is None or sig is None or len(close) < 20:
            continue
        fwd = close.pct_change().shift(-1)
        mask = fwd.notna() & sig.notna()
        if mask.sum() < 20:
            continue

        sig_vals = sig[mask].values
        fwd_vals = fwd[mask].values
        gross = sig_vals * fwd_vals

        # Cost: apply to bar where sig differs from previous bar
        delta = np.zeros_like(sig_vals)
        delta[1:] = np.abs(sig_vals[1:] - sig_vals[:-1])
        cost = delta * (cost_bps_per_trade / 10000.0)
        net = gross - cost

        per_sym_rets.append(pd.Series(net, index=close.index[mask], name=sym))
        per_sym_flips.append(int(delta.sum()))

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

    avg_flips = float(np.mean(per_sym_flips))
    avg_flips_per_year = avg_flips / max(n_years, 0.001)

    return {
        "sharpe": sharpe,
        "cagr": cagr * 100.0,
        "max_dd": float(dd) * 100.0,
        "vol_ann": std * np.sqrt(bpy) * 100.0,
        "flips_per_year": avg_flips_per_year,
        "n_bars": len(port_ret),
    }


def _find_breakeven(rows_for_combo: list) -> float | None:
    """Return cost multiplier at which net Sharpe crosses zero
    (linear interp). None if never crosses."""
    pts = sorted([(r["cost_mult"], r["sharpe"]) for r in rows_for_combo])
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        if y1 > 0 >= y2:
            # Linear interpolation
            return x1 + (x2 - x1) * y1 / (y1 - y2) if y1 != y2 else x2
    if all(s > 0 for _, s in pts):
        return float("inf")
    if all(s <= 0 for _, s in pts):
        return 0.0
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--max-symbols", type=int, default=25)
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    default_tier = cfg.cost_model.tiers["default"]
    bps_base = float(default_tier.commission_bps + default_tier.slippage_intraday_bps)
    print(f"Using cost_model 'default' tier: {bps_base:.1f} bps per trade")
    print(f"  (commission={default_tier.commission_bps} + "
          f"slippage_intraday={default_tier.slippage_intraday_bps})")

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

    bars_per_tf = {}
    for tf in ["60m", "30m", "15m", "5m"]:
        bars_per_tf[tf] = _load_tf(store, symbols, tf)
        logger.info("%s: loaded %d symbols", tf, len(bars_per_tf[tf]))

    print(f"\nCost stress on up to {len(symbols)} symbols × {len(_COMBOS)} combos")

    all_rows = []
    for combo in _COMBOS:
        combo_label = "+".join(combo)
        logger.info("Combo: %s", combo_label)
        for mult in _COST_MULTS:
            r = _backtest_combo_cost(bars_per_tf, symbols, combo,
                                      cost_bps_per_trade=bps_base * mult)
            if not r:
                continue
            r["combo"] = combo_label
            r["cost_mult"] = mult
            r["bps_per_trade"] = round(bps_base * mult, 2)
            all_rows.append(r)

    if not all_rows:
        print("(no results)")
        return

    df = pd.DataFrame(all_rows)
    cols = ["cost_mult", "bps_per_trade", "sharpe", "cagr",
            "max_dd", "flips_per_year"]

    print("\n=== Per-combo cost stress ===")
    for combo_label in df["combo"].unique():
        sub = df[df["combo"] == combo_label].sort_values("cost_mult")
        print(f"\n  Combo: {combo_label}")
        print(sub[cols].to_string(index=False,
              float_format=lambda v: f"{v:+.3f}"))

    print("\n=== Breakeven cost multiplier per combo ===")
    print("(cost mult at which net Sharpe crosses zero)")
    for combo_label in df["combo"].unique():
        sub = df[df["combo"] == combo_label].to_dict("records")
        be = _find_breakeven(sub)
        if be is None:
            be_str = "n/a"
        elif be == float("inf"):
            be_str = ">5x (survives all tested levels)"
        else:
            be_str = f"{be:.2f}x  ({be * bps_base:.1f} bps/trade)"
        print(f"  {combo_label:<25} breakeven = {be_str}")

    print("\n=== Holding period (bars) and annual turnover ===")
    print("  At cost_mult=1.0 (base cost):")
    base = df[df["cost_mult"] == 1.0].set_index("combo")
    for combo_label in base.index:
        flips = base.loc[combo_label, "flips_per_year"]
        # Each round-trip = 2 flips (entry + exit)
        roundtrips = flips / 2.0
        avg_hold_bars = base.loc[combo_label, "n_bars"] / max(flips, 1)
        print(f"  {combo_label:<25} ~{roundtrips:.0f} round-trips/yr/sym, "
              f"avg holding ≈ {avg_hold_bars:.1f} bars")


if __name__ == "__main__":
    main()
