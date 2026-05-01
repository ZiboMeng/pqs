"""Step 0 retro NAV-level beta-cap sanity check on RCMv1 paper NAV.

Purpose: cheap (<1 day) upper-bound estimate of whether C-3 beta-controlled
construction (Cycle #02 candidate axis) can meaningfully decorrelate the
candidate's realized NAV from SPY.

What this is NOT:
  - A real backtest (RCMv1's actual realized weights were chosen WITHOUT
    a beta cap; applying a cap retro is hindsight bias).
  - A proof that C-3 will work in forward.
  - A substitute for the per-trial harness (Step 1).

What this IS:
  - For each day with active RCMv1 positions, compute the realized
    portfolio_beta_to_spy from the ACTUAL paper weights × ROLLING-60D
    per-symbol beta_to_spy.
  - Apply hindsight cap: if portfolio_beta > BETA_CAP, scale all weights
    by (BETA_CAP / portfolio_beta), residual → cash.
  - Recompute the daily return series from the capped weights.
  - Compare capped NAV vs unconstrained NAV vs SPY: cum_ret, daily-return
    correlation, max drawdown, beta-time-series.

Decision criteria (per Step 0 plan):
  - If corr(capped_daily_ret, SPY) drops > 0.20 vs corr(unconstrained_daily_ret, SPY)
    → C-3 has alpha potential, proceed to Step 1 (harness).
  - If drop < 0.10 → C-3 unlikely to break sibling collapse,
    reconsider direction before investing in harness + cycle #02.
  - 0.10-0.20 → marginal; weigh against Step 1 cost.
"""
from __future__ import annotations

import json
from pathlib import Path
import argparse

import numpy as np
import pandas as pd


PROJ = Path("/home/zibo/Documents/projects/pqs")


def _load_paper_cell(cell_dir: Path) -> dict:
    """Load one RCMv1 paper run cell. Returns dict of dataframes."""
    out = {}
    for fname, key in [
        ("target_portfolio_daily.csv", "weights"),
        ("live_like_pnl.csv", "pnl"),
        ("run_meta.json", "meta"),
    ]:
        p = cell_dir / fname
        if fname.endswith(".json"):
            out[key] = json.loads(p.read_text())
        else:
            df = pd.read_csv(p, parse_dates=["date"]).set_index("date")
            out[key] = df
    return out


def _load_returns_panel(symbols: list[str], start: pd.Timestamp,
                       end: pd.Timestamp) -> pd.DataFrame:
    """Load daily close returns for the given symbols, indexed by date.

    Uses BarStore.load(adjusted=True) to apply the splits.parquet cascade
    at read time. The raw daily/*.parquet files contain heterogeneous
    split adjustment from cross-source merging (polygon + yfinance +
    trades_backfill — see CLAUDE.md §1m Bar Pipeline + Trades Backfill);
    raw close-to-close returns therefore have ALTERNATING scale
    artifacts (LRCX, NVDA, TQQQ, XLK observed in 2022 cell). The
    canonical read path is BarStore.load(..., adjusted=True) which
    applies the splits cascade and yields a consistent post-most-recent-
    split price series.
    """
    import sys as _sys
    _sys.path.insert(0, str(PROJ))
    from core.data.bar_store import BarStore

    store = BarStore(root=PROJ / "data")
    rets = {}
    buffer_start = start - pd.Timedelta(days=120)
    for s in symbols:
        try:
            df = store.load(s, "1d", adjusted=True)
        except Exception:
            continue
        if df is None or df.empty or "close" not in df.columns:
            continue
        s_ret = df["close"].pct_change()
        s_ret = s_ret[(s_ret.index >= buffer_start) & (s_ret.index <= end)]
        rets[s] = s_ret
    return pd.DataFrame(rets).sort_index()


def _rolling_beta(symbol_rets: pd.DataFrame, spy_rets: pd.Series,
                  window: int = 60) -> pd.DataFrame:
    """Per-symbol rolling beta-to-SPY over `window` days."""
    spy_var = spy_rets.rolling(window).var()
    beta_panel = pd.DataFrame(index=symbol_rets.index, columns=symbol_rets.columns,
                              dtype=float)
    for s in symbol_rets.columns:
        cov = symbol_rets[s].rolling(window).cov(spy_rets)
        beta_panel[s] = cov / spy_var
    return beta_panel


def _portfolio_beta(weights_row: pd.Series, beta_row: pd.Series) -> float:
    """Compute ∑ w_i × β_i for the day, ignoring NaN betas."""
    valid = (~beta_row.isna()) & (weights_row.abs() > 1e-9)
    if valid.sum() == 0:
        return float("nan")
    w = weights_row[valid]
    b = beta_row[valid]
    # Weights might not sum to 1 in target_portfolio (some cash). Keep raw.
    return float((w * b).sum())


def _apply_beta_cap(weights_row: pd.Series, port_beta: float,
                    beta_cap: float) -> pd.Series:
    """If portfolio_beta > beta_cap, scale all weights by (cap / port_beta)
    and put the residual in cash (return weights of length N).

    If portfolio_beta <= beta_cap, return weights unchanged."""
    if not np.isfinite(port_beta) or port_beta <= beta_cap:
        return weights_row.copy()
    scale = beta_cap / port_beta
    return weights_row * scale


def _daily_return_from_weights(weights: pd.DataFrame,
                              symbol_rets: pd.DataFrame) -> pd.Series:
    """Compute daily portfolio return from weights × per-symbol returns.

    Convention: weights[t] is the post-rebalance held weight FOR day t+1's
    return. Standard T+1 execution. For paper-run target_portfolio_daily,
    weights[t] is the target as of EOD t; the next day's return uses it.

    For a directional sanity check we use lag-1: return[t] uses
    weights[t-1].
    """
    # Reindex returns to the union dates
    common_dates = weights.index.intersection(symbol_rets.index)
    weights = weights.reindex(common_dates)
    symbol_rets = symbol_rets.reindex(common_dates)
    # Lag weights by 1 day
    weights_lag = weights.shift(1)
    # Per-symbol contribution
    contrib = (weights_lag * symbol_rets).fillna(0.0)
    # Drop any symbols (columns) with no overlap
    return contrib.sum(axis=1)


def run_one_cell(cell_dir: Path, beta_cap: float = 0.75,
                window: int = 60) -> dict:
    """Run the retro for one RCMv1 paper cell. Returns metrics dict."""
    cell = _load_paper_cell(cell_dir)
    weights = cell["weights"].drop(columns=["cash"], errors="ignore")
    # Filter out symbols that are 100% zero across the cell
    nonzero_cols = weights.loc[:, (weights.abs() > 1e-9).any(axis=0)].columns
    weights = weights[list(nonzero_cols)]

    start = weights.index.min()
    end = weights.index.max()

    # Load returns for these symbols + SPY (for beta + comparison)
    symbols = sorted(set(weights.columns) | {"SPY"})
    rets = _load_returns_panel(symbols, start, end)
    if "SPY" not in rets.columns:
        raise RuntimeError("SPY return panel not found")
    spy_rets = rets["SPY"]
    sym_rets = rets[[c for c in weights.columns if c in rets.columns]]

    # Rolling 60d beta vs SPY
    beta_panel = _rolling_beta(sym_rets, spy_rets, window=window)
    # Filter to cell window
    beta_panel = beta_panel.loc[start:end]
    weights = weights.loc[start:end, sym_rets.columns]

    # Compute per-day portfolio beta + capped weights
    port_beta_unc = []
    port_beta_capped = []
    capped_weights = weights.copy()
    for dt in weights.index:
        wr = weights.loc[dt]
        br = beta_panel.loc[dt] if dt in beta_panel.index else pd.Series(
            np.nan, index=weights.columns
        )
        pb = _portfolio_beta(wr, br)
        port_beta_unc.append(pb)
        capped = _apply_beta_cap(wr, pb, beta_cap)
        capped_weights.loc[dt] = capped
        # Recompute capped beta for diagnostic (should be ≤ cap)
        port_beta_capped.append(_portfolio_beta(capped, br))

    port_beta_unc = pd.Series(port_beta_unc, index=weights.index)
    port_beta_capped = pd.Series(port_beta_capped, index=weights.index)

    # Compute daily portfolio returns: unconstrained vs capped
    unc_daily = _daily_return_from_weights(weights, sym_rets)
    cap_daily = _daily_return_from_weights(capped_weights, sym_rets)
    spy_daily = spy_rets.reindex(unc_daily.index)

    # Drop the warm-up day (first row has NaN due to weight lag)
    unc_daily = unc_daily.iloc[1:]
    cap_daily = cap_daily.iloc[1:]
    spy_daily = spy_daily.iloc[1:]

    # Cum ret series
    unc_cum = (1 + unc_daily).cumprod() - 1
    cap_cum = (1 + cap_daily).cumprod() - 1
    spy_cum = (1 + spy_daily).cumprod() - 1

    # Correlations
    corr_unc_spy = float(unc_daily.corr(spy_daily))
    corr_cap_spy = float(cap_daily.corr(spy_daily))
    corr_unc_cap = float(unc_daily.corr(cap_daily))

    # Final cum_ret
    final_unc = float(unc_cum.iloc[-1])
    final_cap = float(cap_cum.iloc[-1])
    final_spy = float(spy_cum.iloc[-1])

    # Max drawdown
    def _max_dd(cum_series: pd.Series) -> float:
        nav = 1 + cum_series
        peak = nav.cummax()
        dd = (nav - peak) / peak
        return float(dd.min())

    return {
        "cell": cell_dir.name,
        "start": str(start.date()),
        "end": str(end.date()),
        "n_days": int(len(weights)),
        "n_symbols_active": int(len([c for c in weights.columns
                                     if (weights[c].abs() > 1e-9).any()])),
        "beta_cap": beta_cap,
        "port_beta_unc": {
            "mean": float(port_beta_unc.mean()),
            "median": float(port_beta_unc.median()),
            "max": float(port_beta_unc.max()),
            "min": float(port_beta_unc.min()),
            "n_days_above_cap": int((port_beta_unc > beta_cap).sum()),
            "frac_days_above_cap": float((port_beta_unc > beta_cap).mean()),
        },
        "port_beta_capped": {
            "mean": float(port_beta_capped.mean()),
            "median": float(port_beta_capped.median()),
            "max": float(port_beta_capped.max()),
        },
        "cum_ret": {
            "unconstrained": final_unc,
            "capped": final_cap,
            "spy": final_spy,
        },
        "max_dd": {
            "unconstrained": _max_dd(unc_cum),
            "capped": _max_dd(cap_cum),
            "spy": _max_dd(spy_cum),
        },
        "corr_daily_returns": {
            "unconstrained_vs_spy": corr_unc_spy,
            "capped_vs_spy": corr_cap_spy,
            "unconstrained_vs_capped": corr_unc_cap,
            "drop_capped_minus_unc_vs_spy": corr_cap_spy - corr_unc_spy,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Step 0: RCMv1 retro NAV-level beta-cap sanity check"
    )
    ap.add_argument("--beta-cap", type=float, default=0.75,
                    help="Hindsight portfolio beta cap (default 0.75)")
    ap.add_argument("--window", type=int, default=60,
                    help="Rolling beta window in days (default 60)")
    ap.add_argument("--cells", nargs="+", default=[
        "data/paper_runs/rcm_v1_defensive_composite_01/20260425T041403Z",  # 2022 cell
        "data/paper_runs/rcm_v1_defensive_composite_01/20260425T041358Z",  # 2024 cell
    ])
    args = ap.parse_args()

    results = []
    for cell in args.cells:
        cell_path = PROJ / cell if not Path(cell).is_absolute() else Path(cell)
        print(f"Running cell: {cell_path.name}", flush=True)
        r = run_one_cell(cell_path, beta_cap=args.beta_cap, window=args.window)
        results.append(r)
        print(json.dumps(r, indent=2))
        print()

    # Summary across cells
    print("=" * 70)
    print("SUMMARY (cell-by-cell)")
    print("=" * 70)
    print(
        f"{'cell':>30s} {'corr_unc_spy':>13s} {'corr_cap_spy':>13s} "
        f"{'drop':>7s} {'cum_unc':>9s} {'cum_cap':>9s} {'cum_spy':>9s} "
        f"{'beta_unc_med':>13s} {'frac_>_cap':>11s}"
    )
    for r in results:
        c = r["cell"][:28]
        print(
            f"{c:>30s} "
            f"{r['corr_daily_returns']['unconstrained_vs_spy']:>13.4f} "
            f"{r['corr_daily_returns']['capped_vs_spy']:>13.4f} "
            f"{r['corr_daily_returns']['drop_capped_minus_unc_vs_spy']:>+7.4f} "
            f"{r['cum_ret']['unconstrained']:>+9.2%} "
            f"{r['cum_ret']['capped']:>+9.2%} "
            f"{r['cum_ret']['spy']:>+9.2%} "
            f"{r['port_beta_unc']['median']:>13.4f} "
            f"{r['port_beta_unc']['frac_days_above_cap']:>11.2%}"
        )

    # Decision banner
    drops = [r["corr_daily_returns"]["drop_capped_minus_unc_vs_spy"]
             for r in results]
    avg_drop = sum(drops) / len(drops) if drops else 0.0
    print()
    print(f"Average drop in (capped vs SPY) - (unconstrained vs SPY) "
          f"correlation: {avg_drop:+.4f}")
    if abs(avg_drop) > 0.20:
        verdict = "C-3 has alpha potential — PROCEED to Step 1 harness."
    elif abs(avg_drop) > 0.10:
        verdict = "MARGINAL — weigh harness cost; consider reduced cap or alt axis."
    else:
        verdict = "C-3 UNLIKELY to break sibling collapse — RECONSIDER direction."
    print(f"Step 0 decision: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
