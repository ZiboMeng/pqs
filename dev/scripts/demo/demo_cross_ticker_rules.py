#!/usr/bin/env python
"""Demo: apply `config/cross_ticker_rules.yaml` to a strategy's weights on
real data and show before/after differences.

PRD M4 demonstration. Does NOT modify production behavior; it just loads
current production strategy, generates weights, and shows how the rule
engine transforms them per bar/day across a recent window.

Usage:
  python dev/scripts/demo/demo_cross_ticker_rules.py
  python dev/scripts/demo/demo_cross_ticker_rules.py --start 2024-01-01 --end 2024-12-31
  python dev/scripts/demo/demo_cross_ticker_rules.py --rules-file config/cross_ticker_rules.yaml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.config.loader import load_config
from core.config.production_strategy import (
    build_strategy_from_config,
    load_production_strategy,
)
from core.data.market_data_store import MarketDataStore
from core.data.vix_loader import load_vix_series
from core.logging_setup import get_logger, setup_logging
from core.portfolio.constructor import PortfolioConstructor
from core.regime.regime_detector import RegimeDetector
from core.signals.cross_ticker_rules import (
    RuleContext,
    apply_rules,
    load_rules,
)

setup_logging()
logger = get_logger("demo_ctr")


def _build_weights(cfg, store, start: str, end: str):
    """Run the production strategy on a date window and return date × symbol
    weight matrix, plus the regime series and ohlcv frames."""
    uni = cfg.universe
    all_tradable = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    def_syms = [s for s in ["TLT", "IEF", "GLD", "SHY"] if s in all_tradable]
    risk_syms = [s for s in all_tradable if s not in def_syms
                 and s not in ["TQQQ", "SOXL"] and s not in uni.blacklist]

    # Load price panel
    frames, ohlcv_frames = {}, {}
    for sym in all_tradable:
        df = store.read(sym, "1d")
        if df is not None and not df.empty:
            frames[sym] = df["close"]
            if all(c in df.columns for c in ("open", "high", "low", "close")):
                ohlcv_frames[sym] = df[["open", "high", "low", "close"]]
                if "volume" in df.columns:
                    ohlcv_frames[sym]["volume"] = df["volume"]
    price_df = pd.DataFrame(frames).sort_index()

    # Slice window
    if start:
        price_df = price_df[price_df.index >= start]
        ohlcv_frames = {s: df[df.index >= start] for s, df in ohlcv_frames.items()}
    if end:
        price_df = price_df[price_df.index <= end]
        ohlcv_frames = {s: df[df.index <= end] for s, df in ohlcv_frames.items()}

    # Regime
    if "SPY" not in price_df.columns:
        raise RuntimeError("SPY not in data")
    spy = price_df["SPY"]
    vix = load_vix_series(store, spy.index, mode="lenient")
    regime = RegimeDetector(cfg.regime).classify_series(spy, vix)

    # Build strategy via M1 single source of truth
    ps_cfg = load_production_strategy()
    strat = build_strategy_from_config(ps_cfg, cfg.risk, risk_syms)
    signals = strat.generate(price_df, regime)
    constructor = PortfolioConstructor(use_vol_parity=False)
    weights = constructor.build(
        raw_signals=signals, price_df=price_df, regime_series=regime,
    )
    return weights, regime, ohlcv_frames, ps_cfg


def _apply_rules_over_window(
    weights: pd.DataFrame,
    regime: pd.Series,
    ohlcv_frames: dict,
    rules,
):
    """Walk each date, build context, apply rules, return (adjusted_weights,
    diff_summary)."""
    adjusted = weights.copy()
    n_changed_rows = 0
    n_symbols_changed = 0
    # Track per-rule application counts
    # (naive: count dates where any weight changed vs input)
    for date in weights.index:
        if not isinstance(date, pd.Timestamp):
            continue
        # Build ohlcv context: each symbol's df up to and including date
        ctx_ohlcv = {}
        for sym, df in ohlcv_frames.items():
            mask = df.index <= date
            if mask.any():
                ctx_ohlcv[sym] = df[mask].tail(252)  # last 252 bars for speed
        ctx = RuleContext(
            bar_timestamp=date,
            regime=str(regime.get(date, "NEUTRAL")),
            ohlcv=ctx_ohlcv,
        )
        before = {s: float(weights.loc[date, s]) for s in weights.columns
                  if float(weights.loc[date, s]) != 0}
        after = apply_rules(before, ctx, rules)

        # Apply changes back to matrix
        changed_this_row = False
        for sym, new_w in after.items():
            if sym not in adjusted.columns:
                adjusted[sym] = 0.0
            old_w = float(adjusted.loc[date, sym]) if sym in adjusted.columns else 0.0
            if abs(new_w - old_w) > 1e-9:
                adjusted.loc[date, sym] = new_w
                changed_this_row = True
                n_symbols_changed += 1
        # Symbols removed by rules (e.g. regime_basket override with different set)
        for sym in before:
            if sym not in after:
                adjusted.loc[date, sym] = 0.0
                changed_this_row = True
                n_symbols_changed += 1
        if changed_this_row:
            n_changed_rows += 1

    summary = {
        "n_dates": len(weights),
        "n_dates_changed": n_changed_rows,
        "pct_dates_changed": n_changed_rows / max(1, len(weights)),
        "n_symbol_changes_total": n_symbols_changed,
    }
    return adjusted, summary


def _portfolio_cagr(weights: pd.DataFrame, price_df: pd.DataFrame) -> float:
    """Simple equal-weight portfolio NAV at end of window, compute CAGR."""
    weights = weights.reindex(columns=price_df.columns, fill_value=0.0).fillna(0.0)
    rets = price_df.pct_change().fillna(0.0)
    # shift by 1 bar to avoid lookahead
    port_rets = (weights.shift(1).fillna(0.0) * rets).sum(axis=1)
    equity = (1 + port_rets).cumprod()
    if len(equity) < 2 or equity.iloc[-1] <= 0:
        return float("nan")
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1 / max(years, 0.01)) - 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo cross-ticker DSL on real data (PRD M4)")
    parser.add_argument("--start", default="2023-01-02")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--rules-file", default="config/cross_ticker_rules.yaml")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    # Load rules
    enabled, rules = load_rules(args.rules_file)
    print(f"Rules file: {args.rules_file}")
    print(f"  enabled: {enabled}")
    print(f"  rule count: {len(rules)}")
    for r in rules:
        print(f"    - {r.name} (type={type(r).__name__}, priority={r.priority})")

    if not rules:
        print("\nNo rules to apply. Edit config/cross_ticker_rules.yaml.")
        return 0

    print(f"\nWindow: {args.start} → {args.end}")
    print("Building baseline weights from production strategy...")
    weights, regime, ohlcv, ps_cfg = _build_weights(cfg, store, args.start, args.end)
    print(f"  {ps_cfg.summary_line()}")
    print(f"  Weight matrix: {len(weights)} dates × {len(weights.columns)} symbols")
    print(f"  Regime distribution over window:")
    for r, c in regime.value_counts().items():
        print(f"    {r}: {c}")

    print("\nApplying DSL rules bar-by-bar...")
    adjusted, summary = _apply_rules_over_window(weights, regime, ohlcv, rules)

    print(f"\nDiff summary:")
    for k, v in summary.items():
        if "pct" in k:
            print(f"  {k}: {v:.1%}")
        else:
            print(f"  {k}: {v}")

    # Load price df for CAGR calc
    price_df = pd.DataFrame({s: df["close"] for s, df in ohlcv.items()}).sort_index()
    cagr_before = _portfolio_cagr(weights, price_df)
    cagr_after = _portfolio_cagr(adjusted, price_df)
    print(f"\nPortfolio CAGR comparison (naive equal-weight, no costs):")
    print(f"  Baseline (no rules):  {cagr_before:+.2%}")
    print(f"  With DSL rules:       {cagr_after:+.2%}")
    print(f"  Delta:                {cagr_after - cagr_before:+.2%}")

    # Align dataframes (adjusted may have added columns from regime basket)
    all_cols = sorted(set(weights.columns) | set(adjusted.columns))
    w_aligned = weights.reindex(columns=all_cols, fill_value=0.0)
    a_aligned = adjusted.reindex(columns=all_cols, fill_value=0.0)
    diff_mask = (w_aligned - a_aligned).abs().sum(axis=1) > 1e-9
    first_diff = diff_mask.idxmax() if diff_mask.any() else None
    if first_diff is not None:
        print(f"\nFirst date with non-zero weight diff: {first_diff.date()}")
        print(f"  Regime: {regime.get(first_diff, '?')}")
        b = w_aligned.loc[first_diff]
        a = a_aligned.loc[first_diff]
        changed = [(s, float(b[s]), float(a[s])) for s in all_cols
                   if abs(float(b[s]) - float(a[s])) > 1e-6]
        for sym, bv, av in sorted(changed, key=lambda x: -abs(x[2] - x[1]))[:10]:
            print(f"    {sym:<8} {bv:+.4f} → {av:+.4f}  (Δ {av - bv:+.4f})")

    print("\nNOTE: this is a research demo. Rules are not wired into")
    print("      run_backtest.py yet — production integration is a future")
    print("      follow-up (see PRD M4 acceptance §).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
