"""Path B: single-name VRP / IV scan via yfinance current chains.

Free path can only give a SNAPSHOT (current chain IV) since historical
single-name options chains are paid. But a snapshot of:
  - IV / RV ratio (current vs trailing 21d realized) per ticker
  - Skew structure (5 / 8 / 10 pct OTM put IV vs ATM IV)
  - Premium yield vs SPY
is enough to TRIAGE which single names are worth paying for chain
data on.

Tickers scanned: NVDA TSLA META AMD COIN AAPL MSFT GOOG (high-vol
single names; AAPL/MSFT/GOOG as lower-vol controls).

Output:
  data/options/analysis/single_name_vrp_snapshot.json
  stdout markdown digest with ranking
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

PROJ = Path(__file__).resolve().parents[3]
ANAL_DIR = PROJ / "data" / "options" / "analysis"

TICKERS = ["NVDA", "TSLA", "META", "AMD", "COIN", "AAPL", "MSFT", "GOOG"]
RV_WINDOW = 21


def _trailing_rv(close: pd.Series, window: int = RV_WINDOW) -> float:
    """Annualized 21d realized vol in vol points."""
    log_ret = np.log(close / close.shift(1)).dropna()
    if len(log_ret) < window:
        return float("nan")
    return float(log_ret.iloc[-window:].std() * np.sqrt(252) * 100.0)


def _scan_ticker(symbol: str, vix_now: float) -> dict | None:
    print(f"[scan] {symbol} ...")
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(period="3mo")
        if hist.empty:
            return None
        spot = float(hist["Close"].iloc[-1])
        rv_21 = _trailing_rv(hist["Close"], RV_WINDOW)

        exps = tk.options
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
            return None

        chain = tk.option_chain(best_exp)
        puts = chain.puts
        calls = chain.calls

        # ATM IV (use closest-to-spot strike, average put + call)
        atm_put = puts.iloc[(puts["strike"] - spot).abs().argsort()[:1]]
        atm_call = calls.iloc[(calls["strike"] - spot).abs().argsort()[:1]]
        atm_iv = (float(atm_put["impliedVolatility"].iloc[0])
                  + float(atm_call["impliedVolatility"].iloc[0])) / 2.0 * 100

        # 5 / 8 / 10 pct OTM put IV
        otm_puts = {}
        for otm in [0.05, 0.08, 0.10]:
            target = spot * (1 - otm)
            row = puts.iloc[(puts["strike"] - target).abs().argsort()[:1]]
            otm_puts[f"{int(otm*100)}pct"] = {
                "strike": float(row["strike"].iloc[0]),
                "iv_pct": float(row["impliedVolatility"].iloc[0]) * 100,
            }

        vrp = atm_iv - rv_21
        return {
            "symbol": symbol, "spot": spot, "expiration": best_exp,
            "rv_21d_pct": rv_21, "atm_iv_pct": atm_iv, "vrp_pct": vrp,
            "atm_iv_over_vix": atm_iv / vix_now,
            "atm_iv_over_rv": atm_iv / rv_21 if rv_21 > 0 else float("nan"),
            "otm_puts": otm_puts,
            "skew_5pct_put_over_atm": otm_puts["5pct"]["iv_pct"] / atm_iv,
            "skew_8pct_put_over_atm": otm_puts["8pct"]["iv_pct"] / atm_iv,
        }
    except Exception as e:
        print(f"  [error] {symbol}: {e}")
        return None


def main() -> int:
    ANAL_DIR.mkdir(parents=True, exist_ok=True)
    vix_now = float(yf.Ticker("^VIX").history(period="1d")["Close"].iloc[-1])
    print(f"VIX now: {vix_now:.2f}")

    spy = yf.Ticker("SPY").history(period="3mo")
    spy_rv = _trailing_rv(spy["Close"])
    print(f"SPY 21d RV: {spy_rv:.2f} vol pts; VRP = {vix_now - spy_rv:+.2f}\n")

    results = {"vix_now": vix_now, "spy_rv_21d": spy_rv,
               "spy_vrp_now": vix_now - spy_rv,
               "tickers": {}}
    for sym in TICKERS:
        r = _scan_ticker(sym, vix_now)
        if r:
            results["tickers"][sym] = r

    out = ANAL_DIR / "single_name_vrp_snapshot.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nWrote {out}\n")

    # Render summary table
    print("# Single-name VRP / skew snapshot")
    print()
    print(f"VIX baseline: {vix_now:.1f} | SPY 21d RV: {spy_rv:.1f} | "
          f"SPY VRP: {vix_now - spy_rv:+.1f}\n")
    print("| Ticker | Spot | RV21 | ATM IV | VRP | IV/VIX | IV/RV | "
          "5otmP IV | 8otmP IV | Skew5/ATM | Skew8/ATM |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    rows = sorted(results["tickers"].values(), key=lambda x: -x["vrp_pct"])
    for r in rows:
        print(f"| {r['symbol']} | ${r['spot']:.0f} | {r['rv_21d_pct']:.1f} | "
              f"{r['atm_iv_pct']:.1f} | **{r['vrp_pct']:+.1f}** | "
              f"{r['atm_iv_over_vix']:.2f} | {r['atm_iv_over_rv']:.2f} | "
              f"{r['otm_puts']['5pct']['iv_pct']:.1f} | "
              f"{r['otm_puts']['8pct']['iv_pct']:.1f} | "
              f"{r['skew_5pct_put_over_atm']:.2f} | "
              f"{r['skew_8pct_put_over_atm']:.2f} |")

    print("\n## Implications")
    spy_vrp = vix_now - spy_rv
    high_vrp = [r for r in rows if r["vrp_pct"] > spy_vrp * 1.5]
    if high_vrp:
        print(f"\nTickers with VRP > 1.5× SPY's ({spy_vrp:.1f}):")
        for r in high_vrp:
            ratio = r["vrp_pct"] / spy_vrp if spy_vrp > 0 else float("nan")
            print(f"  - {r['symbol']}: VRP {r['vrp_pct']:+.1f} ({ratio:.1f}× SPY)")
    else:
        print("\nNo ticker shows VRP > 1.5× SPY's right now (low-vol regime).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
