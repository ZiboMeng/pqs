#!/usr/bin/env python3
"""Daily forward observation for SimpleBaselineStrategy paper-trading.

Run after NYSE close (after 16:15 ET) to record today's TD observation.

Workflow:
  1. Load spec.yaml + manifest.json + verify spec_hash
  2. Fetch yfinance data through observation_date
  3. Compute strategy weights for observation_date
  4. Evolve NAV from prior TD using actual price returns
  5. Apply rebalance if month-end OR if weights diverged > threshold
  6. Append new TD to manifest + daily_nav.csv

Usage:
  python dev/scripts/baseline/observe_simple_baseline.py
  python dev/scripts/baseline/observe_simple_baseline.py --observation-date 2026-05-13
  python dev/scripts/baseline/observe_simple_baseline.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np
import pandas as pd
import yaml

from core.signals.strategies.simple_baseline import SimpleBaselineStrategy

CANDIDATE_DIR = Path("data/baseline_simple/paper_runs/simple_baseline_v1")
SPEC_PATH = CANDIDATE_DIR / "spec.yaml"
MANIFEST_PATH = CANDIDATE_DIR / "manifest.json"
NAV_CSV_PATH = CANDIDATE_DIR / "daily_nav.csv"


def _spec_hash(spec_text: str) -> str:
    data = yaml.safe_load(spec_text)
    canon = yaml.safe_dump(data, sort_keys=True, default_flow_style=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _fetch_panel(symbols: list[str], end_date: pd.Timestamp) -> pd.DataFrame:
    """Fetch yfinance data through end_date (inclusive)."""
    import yfinance as yf

    # Need >= 200 trading days of QQQ for SMA + several days of MTUM/TQQQ
    start = end_date - pd.Timedelta(days=400)
    closes = {}
    for sym in symbols:
        sym_yf = sym if sym != "VIX" else "^VIX"
        auto_adj = sym != "VIX"  # VIX is an index, no adjustment
        df = yf.download(
            sym_yf, start=start.strftime("%Y-%m-%d"),
            end=(end_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            auto_adjust=auto_adj, progress=False,
        )
        if df.empty:
            raise RuntimeError(f"yfinance returned empty for {sym_yf}")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        closes[sym] = df["Close"]
    panel = pd.DataFrame(closes).sort_index()
    panel.index.name = "date"
    panel = panel.dropna()
    return panel


def _is_month_end(d: pd.Timestamp, trading_days: pd.DatetimeIndex) -> bool:
    """True if d is the last trading day of its month per the trading calendar."""
    same_month = trading_days[(trading_days.year == d.year) & (trading_days.month == d.month)]
    return len(same_month) > 0 and same_month.max() == d


def main() -> None:
    parser = argparse.ArgumentParser(description="Observe simple_baseline_v1")
    parser.add_argument("--observation-date", type=str, default=None,
                        help="YYYY-MM-DD; defaults to today")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute but don't write")
    args = parser.parse_args()

    if not SPEC_PATH.exists() or not MANIFEST_PATH.exists():
        sys.exit("[FAIL] spec or manifest missing. Run init script first.")

    spec_text = SPEC_PATH.read_text()
    spec = yaml.safe_load(spec_text)
    spec_sha_computed = _spec_hash(spec_text)
    manifest = json.loads(MANIFEST_PATH.read_text())
    if manifest["spec_hash"] != spec_sha_computed:
        sys.exit(
            f"[FAIL] spec_hash drift!\n"
            f"  manifest: {manifest['spec_hash'][:16]}…\n"
            f"  current : {spec_sha_computed[:16]}…\n"
            f"  Spec modified post-init — investigation required."
        )

    obs_date = (
        pd.Timestamp(args.observation_date) if args.observation_date
        else pd.Timestamp(date.today())
    )

    # ── Fetch data ─────────────────────────────────────────────────────────
    required = spec["paper_config"]["required_symbols"] + ["VIX"]
    panel = _fetch_panel(required, obs_date)
    trading_days = panel.index
    if obs_date not in trading_days:
        # Use latest trading day <= obs_date
        valid = trading_days[trading_days <= obs_date]
        if len(valid) == 0:
            sys.exit(f"[FAIL] no trading data ≤ {obs_date.date()}")
        actual_obs = valid.max()
        print(f"[INFO] {obs_date.date()} is not a trading day; using {actual_obs.date()}")
        obs_date = actual_obs

    # ── Compute target weights ─────────────────────────────────────────────
    strat = SimpleBaselineStrategy(**spec["strategy_params"])
    weights = strat.generate(panel)
    target_w = weights.loc[obs_date]

    # State diagnostics
    qqq_close = float(panel.loc[obs_date, "QQQ"])
    vix_close = float(panel.loc[obs_date, "VIX"])
    qqq_sma200 = float(panel["QQQ"].rolling(200).mean().loc[obs_date])
    qqq_above_sma = qqq_close > qqq_sma200
    if target_w["TQQQ"] > 0.01:
        regime = "risk_on"
    elif target_w["MTUM"] < spec["strategy_params"]["mtum_weight"] - 1e-6:
        regime = "risk_off"
    else:
        regime = "risk_on"

    # ── NAV evolution ──────────────────────────────────────────────────────
    prior_runs = manifest["forward_runs"]
    initial_nav = float(spec["paper_config"]["initial_nav_usd"])

    if not prior_runs:
        # TD001: initialize positions at target weights
        td_number = 1
        nav_prev = initial_nav
        prev_positions: Dict[str, float] = {}
        is_rebalance = True
    else:
        last = prior_runs[-1]
        td_number = last["td_number"] + 1
        prev_obs_date = pd.Timestamp(last["observation_date"])
        prev_positions = last["positions_shares"]
        # Compute NAV change from prior date to current
        nav_value = 0.0
        for sym, shares in prev_positions.items():
            cur_px = float(panel.loc[obs_date, sym])
            nav_value += shares * cur_px
        # Cash adds prior cash (no interest modeling at retail in v1)
        cash = last.get("cash_usd", 0.0)
        nav_prev = nav_value + cash
        # Determine rebalance: month-end of trading calendar
        is_rebalance = _is_month_end(obs_date, trading_days) or _is_month_end(prev_obs_date, trading_days)
        # If month-end was crossed BETWEEN prev and current, rebalance now
        if not is_rebalance:
            # Check if any month-end occurred strictly between prev and obs
            between = trading_days[(trading_days > prev_obs_date) & (trading_days < obs_date)]
            for d in between:
                if _is_month_end(d, trading_days):
                    is_rebalance = True
                    break

    nav_current = nav_prev

    # ── Apply rebalance if needed ─────────────────────────────────────────
    if is_rebalance:
        new_positions: Dict[str, float] = {}
        cash_remaining = nav_current
        for sym in ["MTUM", "TQQQ", "BIL"]:
            w = float(target_w[sym])
            if w > 0:
                px = float(panel.loc[obs_date, sym])
                # No fractional shares for paper
                shares = int((nav_current * w) // px) if px > 0 else 0
                new_positions[sym] = shares
                cash_remaining -= shares * px
            else:
                new_positions[sym] = 0
        # Subtract rough trading cost (5 bps per trade)
        if prior_runs:
            cost_bps = float(spec["paper_config"]["cost_bps_per_trade"])
            traded_value = sum(
                abs(new_positions[s] - prev_positions.get(s, 0)) * float(panel.loc[obs_date, s])
                for s in new_positions
            )
            cost = traded_value * (cost_bps / 10000.0)
            cash_remaining -= cost
    else:
        # Hold previous positions; cash unchanged
        new_positions = dict(prev_positions)
        cash_remaining = prior_runs[-1].get("cash_usd", 0.0)
        cost = 0.0

    # Recompute NAV from new positions + cash (mark-to-market at obs_date)
    nav_current = sum(
        new_positions[s] * float(panel.loc[obs_date, s])
        for s in new_positions
    ) + cash_remaining

    # ── Sleeve values for reporting ────────────────────────────────────────
    sleeve_values = {
        s: new_positions[s] * float(panel.loc[obs_date, s])
        for s in new_positions
    }

    # ── Build TD entry ─────────────────────────────────────────────────────
    td_entry = {
        "td_number": td_number,
        "observation_date": str(obs_date.date()),
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "nav_usd": round(nav_current, 4),
        "cash_usd": round(cash_remaining, 4),
        "is_rebalance_day": bool(is_rebalance),
        "positions_shares": new_positions,
        "sleeve_values_usd": {k: round(v, 4) for k, v in sleeve_values.items()},
        "target_weights": {k: round(float(target_w[k]), 6) for k in ["MTUM", "TQQQ", "BIL"]},
        "regime": regime,
        "diagnostics": {
            "vix_close": round(vix_close, 4),
            "qqq_close": round(qqq_close, 4),
            "qqq_sma200": round(qqq_sma200, 4),
            "qqq_above_sma200": bool(qqq_above_sma),
            "spy_close": round(float(panel.loc[obs_date, "SPY"]), 4),
        },
    }

    # ── Update manifest ────────────────────────────────────────────────────
    manifest["forward_runs"].append(td_entry)
    manifest["n_observe_days"] = td_number
    manifest["last_observe_date"] = str(obs_date.date())
    manifest["current_nav_usd"] = round(nav_current, 4)
    manifest["current_cash_usd"] = round(cash_remaining, 4)
    manifest["current_positions"] = new_positions
    manifest["target_weights"] = td_entry["target_weights"]
    manifest["regime"] = regime
    manifest["vix_close"] = round(vix_close, 4)
    manifest["qqq_close"] = round(qqq_close, 4)
    manifest["qqq_above_sma200"] = bool(qqq_above_sma)
    manifest["high_water_nav_usd"] = max(manifest["high_water_nav_usd"], nav_current)
    manifest["current_status"] = "in_progress"

    if args.dry_run:
        print(f"\n[DRY RUN] TD{td_number:03d} computed but NOT saved:")
        print(json.dumps(td_entry, indent=2))
        return

    # Persist
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    # Append to NAV CSV
    row = pd.DataFrame([{
        "date": str(obs_date.date()),
        "td_number": td_number,
        "nav_usd": round(nav_current, 4),
        "cash_usd": round(cash_remaining, 4),
        "mtum_value": round(sleeve_values.get("MTUM", 0.0), 4),
        "tqqq_value": round(sleeve_values.get("TQQQ", 0.0), 4),
        "bil_value": round(sleeve_values.get("BIL", 0.0), 4),
        "regime": regime,
        "vix_close": round(vix_close, 4),
        "qqq_close": round(qqq_close, 4),
        "qqq_above_sma200": bool(qqq_above_sma),
    }])
    existing_csv = pd.read_csv(NAV_CSV_PATH) if NAV_CSV_PATH.exists() and NAV_CSV_PATH.stat().st_size > 0 else None
    if existing_csv is None or existing_csv.empty:
        row.to_csv(NAV_CSV_PATH, index=False)
    else:
        row.to_csv(NAV_CSV_PATH, mode="a", header=False, index=False)

    print(f"[OK] TD{td_number:03d} recorded: {obs_date.date()}")
    print(f"     NAV: ${nav_current:,.2f}  (regime={regime})")
    print(f"     MTUM: ${sleeve_values.get('MTUM', 0):,.0f} / "
          f"TQQQ: ${sleeve_values.get('TQQQ', 0):,.0f} / "
          f"BIL: ${sleeve_values.get('BIL', 0):,.0f} / "
          f"cash: ${cash_remaining:,.2f}")
    print(f"     VIX={vix_close:.2f}, QQQ={qqq_close:.2f} (SMA200={qqq_sma200:.2f}, above={qqq_above_sma})")


if __name__ == "__main__":
    main()
