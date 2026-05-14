#!/usr/bin/env python3
"""B9 smoke: NAV-residualized mining target on real data (≤2024 train).

Validates B7 module on real PQS data, not just synthetic. Discipline: only
2018-2024 train-period dates used (RCMv1 + Trial9 NAV available; Cand-2
train-only file ends 2017 so excluded from smoke — full 3-member fleet
will be available post-backcast in B10).

Output: stats on β + residual variance + IC ranking shift vs raw.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np
import pandas as pd

from core.mining.nav_residualized_evaluator import (
    build_fleet_forward_returns_from_nav,
    compute_residual_forward_returns,
    compute_rolling_beta,
)

# ── 1. Load fleet NAV from existing parquet (2018-2024 train-only slice) ────
TRAIN_END = pd.Timestamp("2024-12-31")
FLEET_PATHS = {
    "rcm_v1": "data/sr_validation/rcmv1_arm_A_baseline_nav.parquet",
    "trial9": "data/sr_validation/trial9_arm_A_baseline_nav.parquet",
}


def load_fleet_returns() -> pd.DataFrame:
    """Load fleet daily returns (overlap period only, sliced to ≤2024)."""
    fleet_nav = {}
    for name, path in FLEET_PATHS.items():
        df = pd.read_parquet(path)
        nav = df["equity"]
        nav = nav.loc[:TRAIN_END]
        fleet_nav[name] = nav
    fleet_df = pd.DataFrame(fleet_nav).dropna()
    fleet_ret = fleet_df.pct_change().dropna()
    return fleet_df, fleet_ret


def load_stock_returns() -> pd.DataFrame:
    """Load daily close → returns for ~10 stocks (≤2024 train).
    Uses yfinance for consistent 2009-2024 coverage (BarStore has gaps).
    """
    import yfinance as yf
    syms = ["AAPL", "MSFT", "NVDA", "META", "JNJ", "WMT", "JPM", "XOM", "CAT", "BA"]
    closes = {}
    for sym in syms:
        df = yf.download(sym, start="2014-01-01", end="2024-12-31",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        if df.empty:
            continue
        closes[sym] = df["Close"]
    panel = pd.DataFrame(closes).sort_index().dropna()
    return panel.pct_change().dropna()


def main() -> None:
    print("=" * 60)
    print("B9 smoke: NAV-residualized mining target on real data (≤2024)")
    print("=" * 60)

    print("\n[1] Loading fleet NAV...")
    fleet_nav, fleet_ret = load_fleet_returns()
    print(f"  Fleet date range: {fleet_ret.index.min().date()} → {fleet_ret.index.max().date()}")
    print(f"  Fleet members: {list(fleet_ret.columns)}, n={len(fleet_ret)} days")

    print("\n[2] Loading stock returns...")
    stock_ret = load_stock_returns()
    print(f"  Stocks: {list(stock_ret.columns)}, n={len(stock_ret)} days")

    # Align dates
    common_idx = fleet_ret.index.intersection(stock_ret.index)
    fleet_ret = fleet_ret.loc[common_idx]
    stock_ret = stock_ret.loc[common_idx]
    print(f"  Common period: {common_idx.min().date()} → {common_idx.max().date()} ({len(common_idx)} days)")

    print("\n[3] Computing 36m rolling β (multi-factor OLS)...")
    beta = compute_rolling_beta(stock_ret, fleet_ret, window_months=36)
    for sym in list(beta.keys())[:3]:
        b = beta[sym].dropna()
        if len(b) > 0:
            print(f"  {sym}: β_rcm_v1={b['rcm_v1'].median():+.3f} "
                  f"(median over {len(b)} post-warmup dates), "
                  f"β_trial9={b['trial9'].median():+.3f}")

    print("\n[4] Computing 21-day forward returns...")
    fwd_stock = (1.0 + stock_ret).rolling(21).apply(np.prod, raw=True) - 1.0
    fwd_stock = fwd_stock.shift(-21)
    fwd_fleet_nav = fleet_nav.loc[common_idx]
    fwd_fleet = build_fleet_forward_returns_from_nav(fwd_fleet_nav, horizon_days=21)

    print("\n[5] Computing residual forward returns...")
    resid_fwd = compute_residual_forward_returns(fwd_stock, fwd_fleet, beta)

    print("\n[6] Comparison stats:")
    raw_var = fwd_stock.dropna(how="any").var().mean()
    resid_var = resid_fwd.dropna(how="any").var().mean()
    print(f"  Avg raw fwd_ret variance:     {raw_var:.6f}")
    print(f"  Avg residual fwd_ret variance: {resid_var:.6f}")
    print(f"  Variance ratio (resid/raw):   {resid_var/raw_var:.3f}")
    print(f"  → residualization explains {1 - resid_var/raw_var:.1%} of fwd-return variance")

    print("\n[7] IC-ranking shift sanity check:")
    # Pick an arbitrary "factor": 60-day momentum
    mom60 = (1.0 + stock_ret).rolling(60).apply(np.prod, raw=True) - 1.0
    mom60 = mom60.loc[common_idx]
    # Compute IC on raw vs residual fwd_ret
    raw_ic = []
    resid_ic = []
    for t in mom60.index:
        if t not in fwd_stock.index or fwd_stock.loc[t].isna().all():
            continue
        if t not in resid_fwd.index or resid_fwd.loc[t].isna().all():
            continue
        score = mom60.loc[t]
        # Cross-sectional Spearman rank corr
        raw_target = fwd_stock.loc[t]
        resid_target = resid_fwd.loc[t]
        common = score.dropna().index.intersection(raw_target.dropna().index)
        if len(common) < 3:
            continue
        # Use both pairs of common indices
        s = score.loc[common]
        r_raw = raw_target.loc[common]
        if t in resid_fwd.index:
            r_resid = resid_target.dropna()
            common_r = s.index.intersection(r_resid.index)
            if len(common_r) >= 3:
                ic_r_raw = s.rank().corr(r_raw.rank())
                ic_r_resid = s.loc[common_r].rank().corr(r_resid.loc[common_r].rank())
                if not (np.isnan(ic_r_raw) or np.isnan(ic_r_resid)):
                    raw_ic.append(ic_r_raw)
                    resid_ic.append(ic_r_resid)
    raw_ic_mean = np.mean(raw_ic) if raw_ic else np.nan
    resid_ic_mean = np.mean(resid_ic) if resid_ic else np.nan
    print(f"  mom60 IC vs raw fwd_ret:       {raw_ic_mean:+.4f}  (n={len(raw_ic)} dates)")
    print(f"  mom60 IC vs residual fwd_ret:  {resid_ic_mean:+.4f}  (n={len(resid_ic)} dates)")
    if not np.isnan(raw_ic_mean) and not np.isnan(resid_ic_mean):
        diff = abs(resid_ic_mean - raw_ic_mean)
        print(f"  |Δ IC| = {diff:.4f} → {'meaningful shift' if diff > 0.005 else 'minimal shift'}")

    print("\n[8] Verdict:")
    if resid_var < raw_var * 0.95:
        print("  ✓ Residualization meaningfully reduces fwd-return variance")
        print("  ✓ Pipeline integrates with real fleet NAV + stock data")
        print("  → B9 SMOKE PASS")
    else:
        print("  ✗ Residual variance not materially below raw")
        print("  → Investigate: are fleet members orthogonal to stock universe?")

if __name__ == "__main__":
    main()
