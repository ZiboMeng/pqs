"""Free-path validation of the skew assumption from Path C.

Path C used skew_uplift = 1.20-1.40 (literature-justified) to model
real put-side IV / VIX ratio. This script measures the LIVE ratio
from yfinance current SPY options chain — confirms or disconfirms
the academic literature range without paid data.

Methodology:
  1. Pull SPY current ATM IV (from VIX or from SPY ATM chain)
  2. Pull SPY 5%-OTM put + 5%-OTM call IV from chain
  3. Compute ratios: put_5otm_iv / vix, call_5otm_iv / vix
  4. Report

Output: stdout summary + data/options/analysis/skew_validation.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

PROJ = Path(__file__).resolve().parents[3]
ANAL_DIR = PROJ / "data" / "options" / "analysis"


def main() -> int:
    ANAL_DIR.mkdir(parents=True, exist_ok=True)
    spy = yf.Ticker("SPY")
    vix = yf.Ticker("^VIX")
    spot = float(spy.history(period="1d")["Close"].iloc[-1])
    vix_now = float(vix.history(period="1d")["Close"].iloc[-1])
    print(f"SPY spot: ${spot:.2f}")
    print(f"VIX: {vix_now:.2f}")

    # Find expiration ~30 calendar days out
    exps = spy.options
    today = datetime.now().date()
    target_dte = 30
    best_exp = None
    best_diff = 1e9
    for exp_str in exps:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = (exp_date - today).days
        if 20 <= dte <= 45 and abs(dte - target_dte) < best_diff:
            best_exp = exp_str
            best_diff = abs(dte - target_dte)
    if not best_exp:
        print(f"No expiration in 20-45 DTE window. Available: {exps[:10]}")
        return 1
    print(f"Expiration chosen: {best_exp} (~{30+best_diff} DTE)")

    chain = spy.option_chain(best_exp)
    puts = chain.puts.copy()
    calls = chain.calls.copy()

    # 5% OTM levels
    otm_pct_grid = [0.02, 0.05, 0.08, 0.10]

    results = {"spot": spot, "vix": vix_now, "expiration": best_exp,
               "ratios": {}}
    print()
    print(f"{'Strike':>10} {'OTM%':>6} {'Put IV':>10} {'Call IV':>10} "
          f"{'Put/VIX':>10} {'Call/VIX':>10}")
    for otm in otm_pct_grid:
        # Put OTM = strike < spot
        put_strike_target = spot * (1 - otm)
        put_row = puts.iloc[(puts["strike"] - put_strike_target).abs().argsort()[:1]]
        put_iv = float(put_row["impliedVolatility"].iloc[0]) * 100  # to vol pts
        put_strike = float(put_row["strike"].iloc[0])

        call_strike_target = spot * (1 + otm)
        call_row = calls.iloc[(calls["strike"] - call_strike_target).abs().argsort()[:1]]
        call_iv = float(call_row["impliedVolatility"].iloc[0]) * 100
        call_strike = float(call_row["strike"].iloc[0])

        put_ratio = put_iv / vix_now
        call_ratio = call_iv / vix_now
        results["ratios"][f"otm_{int(otm*100)}pct"] = {
            "put_strike": put_strike, "call_strike": call_strike,
            "put_iv_pct": put_iv, "call_iv_pct": call_iv,
            "put_iv_over_vix": put_ratio, "call_iv_over_vix": call_ratio,
        }
        print(f"  {put_strike:>8.0f}/{call_strike:<.0f}  {otm*100:>4.0f}%   "
              f"{put_iv:>8.2f}   {call_iv:>8.2f}   "
              f"{put_ratio:>8.3f}   {call_ratio:>8.3f}")

    print()
    print("Path C assumption (skew=1.30) was: ATM IV * 1.30 used UNIFORMLY")
    print("Empirical (above): put-side ratio is what we needed to measure.")

    out = ANAL_DIR / "skew_validation.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
