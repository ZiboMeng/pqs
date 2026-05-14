"""Daily observation script for options paper trading runs.

Pulls live SPY + VIX from yfinance, runs one observe step on the
specified candidate. Idempotent (skipped if already observed today).

Usage (run after NYSE 16:15-16:30 ET close, analogous to Trial 9
forward observe ritual):
  python dev/scripts/options/observe_options_forward.py \
    --candidate-id spy_8otm_bull_put_v1
  # or all candidates in data/options/paper_runs/:
  python dev/scripts/options/observe_options_forward.py --all
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.options.paper.spec import load_spec  # noqa: E402
from core.options.paper.runner import observe, PAPER_DIR_DEFAULT  # noqa: E402


def _fetch_market_data(underlying: str = "SPY", history_days: int = 60) -> tuple[float, float, pd.Series]:
    """Return (spot, vix, spy_history_close_series).

    Defense-in-depth: yf.Ticker.history() currently returns
    America/New_York-tz-aware index, so bare tz_localize(None) happens to
    give correct ET dates. But if yfinance ever reverts to UTC tz-aware
    (which is what caused the SPY off-by-one bug postmortem'd
    2026-05-13), bare tz_localize(None) would produce +1 day labels.
    Explicit tz_convert(_ET) before tz_localize(None) is safe under both
    behaviors.
    """
    spy_hist = yf.Ticker(underlying).history(period=f"{history_days}d")
    if spy_hist.empty:
        raise RuntimeError(f"yfinance returned empty for {underlying}")
    if spy_hist.index.tz is not None:
        spy_hist.index = spy_hist.index.tz_convert("America/New_York").tz_localize(None)
    spot = float(spy_hist["Close"].iloc[-1])
    vix_hist = yf.Ticker("^VIX").history(period="5d")
    vix = float(vix_hist["Close"].iloc[-1])
    return spot, vix, spy_hist["Close"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate-id", default=None,
                    help="Specific candidate; omit to use --all")
    ap.add_argument("--all", action="store_true",
                    help="Observe all candidates in data/options/paper_runs/")
    ap.add_argument("--as-of-date", default=None,
                    help="Override observe date YYYY-MM-DD (debugging only)")
    args = ap.parse_args()

    if not args.candidate_id and not args.all:
        ap.error("Specify --candidate-id or --all")

    if args.all:
        candidate_dirs = sorted(PAPER_DIR_DEFAULT.glob("*"))
        candidate_ids = [d.name for d in candidate_dirs if (d / "spec.yaml").exists()]
    else:
        candidate_ids = [args.candidate_id]

    if not candidate_ids:
        print("No candidates found")
        return 1

    today_dt = datetime.strptime(args.as_of_date, "%Y-%m-%d") \
               if args.as_of_date else datetime.now()
    print(f"[observe] {today_dt.strftime('%Y-%m-%d %H:%M')} (UTC)")

    spot, vix, spy_history = _fetch_market_data()
    print(f"[market] SPY=${spot:.2f}  VIX={vix:.2f}")

    for cid in candidate_ids:
        spec_path = PAPER_DIR_DEFAULT / cid / "spec.yaml"
        if not spec_path.exists():
            print(f"  [skip] {cid}: no spec.yaml")
            continue
        spec = load_spec(spec_path)
        try:
            res = observe(spec, today_dt, spot, vix, spy_history,
                          base_dir=PAPER_DIR_DEFAULT)
            if res["status"] == "skipped_already_today":
                print(f"  [{cid}] already observed today; skip")
            else:
                print(f"  [{cid}] TD{res['n_observe_days']:03d}  "
                      f"NAV=${res['nav']:,.2f}  "
                      f"DD={res['rolling_dd']*100:.2f}%  "
                      f"open={res['open_positions']}  "
                      f"cum_pnl=${res['cum_pnl']:+.2f}  "
                      f"events={res['events']}")
        except Exception as e:
            print(f"  [{cid}] ERROR: {e}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
