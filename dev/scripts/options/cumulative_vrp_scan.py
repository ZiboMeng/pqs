"""Daily-cumulative single-name VRP / IV scan.

Appends one row per (date, ticker) to data/options/analysis/vrp_history.parquet
in long format. Idempotent on (snapshot_date, ticker) — re-running same day
overwrites that day's rows (so re-running after market close is safe).

Default run:
    python dev/scripts/options/cumulative_vrp_scan.py

Bootstrap from any saved snapshot JSONs (one-time, when you want to seed
history from previously committed snapshots):
    python dev/scripts/options/cumulative_vrp_scan.py --bootstrap

Output:
    data/options/analysis/vrp_history.parquet  (long format, append-only)
    stdout: today's snapshot table + rolling digest (mean/std/N per ticker)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ / "dev" / "scripts" / "options"))
from single_name_vrp_scan import _scan_ticker, _trailing_rv, TICKERS  # noqa: E402

ANAL_DIR = PROJ / "data" / "options" / "analysis"
HIST_PATH = ANAL_DIR / "vrp_history.parquet"


def _flatten(scan: dict, snapshot_date: str, snapshot_dt: str,
             vix_now: float, spy_rv: float) -> dict:
    return {
        "snapshot_date": snapshot_date,
        "snapshot_dt": snapshot_dt,
        "vix_now": vix_now,
        "spy_rv_21d": spy_rv,
        "spy_vrp": vix_now - spy_rv,
        "ticker": scan["symbol"],
        "spot": scan["spot"],
        "expiration": scan["expiration"],
        "rv_21d_pct": scan["rv_21d_pct"],
        "atm_iv_pct": scan["atm_iv_pct"],
        "vrp_pct": scan["vrp_pct"],
        "iv_over_vix": scan["atm_iv_over_vix"],
        "iv_over_rv": scan["atm_iv_over_rv"],
        "otm5p_strike": scan["otm_puts"]["5pct"]["strike"],
        "otm5p_iv_pct": scan["otm_puts"]["5pct"]["iv_pct"],
        "otm8p_strike": scan["otm_puts"]["8pct"]["strike"],
        "otm8p_iv_pct": scan["otm_puts"]["8pct"]["iv_pct"],
        "otm10p_strike": scan["otm_puts"]["10pct"]["strike"],
        "otm10p_iv_pct": scan["otm_puts"]["10pct"]["iv_pct"],
        "skew_5pct_put_over_atm": scan["skew_5pct_put_over_atm"],
        "skew_8pct_put_over_atm": scan["skew_8pct_put_over_atm"],
    }


def _bootstrap_rows() -> list[dict]:
    """Read any data/options/analysis/single_name_vrp_snapshot_YYYY-MM-DD.json
    files and flatten into rows. Date comes from filename."""
    rows: list[dict] = []
    for path in sorted(ANAL_DIR.glob("single_name_vrp_snapshot_????-??-??.json")):
        snapshot_date = path.stem.replace("single_name_vrp_snapshot_", "")
        snapshot_dt = f"{snapshot_date} 00:00:00"
        d = json.loads(path.read_text())
        vix = float(d["vix_now"])
        spy_rv = float(d["spy_rv_21d"])
        for sym, scan in d["tickers"].items():
            rows.append(_flatten(scan, snapshot_date, snapshot_dt, vix, spy_rv))
        print(f"[bootstrap] {path.name}: {len(d['tickers'])} tickers")
    return rows


def _merge(hist: pd.DataFrame | None, new_rows: list[dict]) -> pd.DataFrame:
    """Replace any existing (snapshot_date, ticker) rows that appear in new_rows."""
    new_df = pd.DataFrame(new_rows)
    if new_df.empty:
        return hist if hist is not None else new_df
    if hist is None or hist.empty:
        merged = new_df
    else:
        keys = set(zip(new_df["snapshot_date"], new_df["ticker"]))
        mask = [
            (d, t) in keys
            for d, t in zip(hist["snapshot_date"], hist["ticker"])
        ]
        hist = hist.loc[[not m for m in mask]]
        merged = pd.concat([hist, new_df], ignore_index=True)
    return merged.sort_values(["snapshot_date", "ticker"]).reset_index(drop=True)


def _classify(mean: float, std: float | None, count: int) -> str:
    if count < 5:
        return f"too few obs (N={count})"
    if std is None or pd.isna(std):
        return "single obs"
    if mean > 5 and std < 3:
        return "STABLE-RICH (candidate)"
    if mean > 5 and std >= 3:
        return "high mean but noisy (avoid)"
    if mean < 0:
        return "structurally cheap (don't sell)"
    return "neutral"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true",
                        help="Also seed from saved single_name_vrp_snapshot_*.json")
    parser.add_argument("--no-live", action="store_true",
                        help="Skip live scan (only useful with --bootstrap)")
    args = parser.parse_args()

    ANAL_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    snapshot_date = now.strftime("%Y-%m-%d")
    snapshot_dt = now.strftime("%Y-%m-%d %H:%M:%S")

    new_rows: list[dict] = []
    if args.bootstrap:
        new_rows.extend(_bootstrap_rows())

    if not args.no_live:
        vix_now = float(yf.Ticker("^VIX").history(period="1d")["Close"].iloc[-1])
        spy = yf.Ticker("SPY").history(period="3mo")
        spy_rv = _trailing_rv(spy["Close"])
        print(f"[{snapshot_dt}] VIX {vix_now:.2f} | SPY 21d RV {spy_rv:.2f} | "
              f"SPY VRP {vix_now - spy_rv:+.2f}\n")
        for sym in TICKERS:
            r = _scan_ticker(sym, vix_now)
            if r:
                new_rows.append(_flatten(r, snapshot_date, snapshot_dt, vix_now, spy_rv))

    if not new_rows:
        print("No rows produced.")
        return 1

    hist = pd.read_parquet(HIST_PATH) if HIST_PATH.exists() else None
    merged = _merge(hist, new_rows)
    merged.to_parquet(HIST_PATH, index=False)
    print(f"\nWrote {HIST_PATH}: {len(merged)} rows, "
          f"{merged['snapshot_date'].nunique()} distinct dates, "
          f"{merged['ticker'].nunique()} tickers")

    if not args.no_live:
        live = pd.DataFrame([r for r in new_rows if r["snapshot_date"] == snapshot_date])
        if not live.empty:
            print("\n# Today's snapshot")
            print("| Ticker | Spot | RV21 | ATM IV | VRP | IV/RV | Skew5 | Skew8 |")
            print("|---|---|---|---|---|---|---|---|")
            for _, r in live.sort_values("vrp_pct", ascending=False).iterrows():
                print(f"| {r['ticker']} | ${r['spot']:.0f} | {r['rv_21d_pct']:.1f} | "
                      f"{r['atm_iv_pct']:.1f} | **{r['vrp_pct']:+.1f}** | "
                      f"{r['iv_over_rv']:.2f} | {r['skew_5pct_put_over_atm']:.2f} | "
                      f"{r['skew_8pct_put_over_atm']:.2f} |")

    n_dates = merged["snapshot_date"].nunique()
    print(f"\n# Rolling history ({n_dates} snapshots)")
    if n_dates < 2:
        print("Need ≥2 snapshots for trend digest.")
        return 0

    digest = (merged.groupby("ticker")["vrp_pct"]
                    .agg(["mean", "std", "min", "max", "count"])
                    .round(2)
                    .sort_values("mean", ascending=False))
    print("\n| Ticker | Mean VRP | Std VRP | Min | Max | N |")
    print("|---|---|---|---|---|---|")
    for ticker, row in digest.iterrows():
        std_str = f"{row['std']:.2f}" if pd.notna(row["std"]) else "—"
        print(f"| {ticker} | {row['mean']:+.2f} | {std_str} | "
              f"{row['min']:+.2f} | {row['max']:+.2f} | {int(row['count'])} |")

    print("\n# Heuristic classification (preliminary; calibrate at N≥10)")
    for ticker, row in digest.iterrows():
        verdict = _classify(row["mean"], row["std"], int(row["count"]))
        std_show = row["std"] if pd.notna(row["std"]) else 0.0
        print(f"  - {ticker}: mean {row['mean']:+.2f} ± {std_show:.2f} → {verdict}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
