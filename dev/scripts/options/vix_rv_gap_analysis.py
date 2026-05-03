"""VIX vs SPY realized volatility gap (VRP) historical analysis.

Phase 1.2 of `pqs-options-v1-2026-05-02` branch. Free-path foundational
check: does the volatility risk premium (VRP) exist AND survive black
swans, justifying further options buildout?

VRP definition (used here):
    VRP_t = VIX_t (annualized %) - RV_t (annualized %, from SPY)
where RV_t = sqrt(252) * std(log_return_SPY[t-20:t]) * 100
(21-trading-day trailing realized vol of SPY log returns, annualized).

Positive VRP_t => implied vol > realized vol => option SELLERS earn
the spread on average. This is the structural alpha source for
cash-secured put, covered call, and wheel strategies.

Tail check: Feb 2018 (volmageddon), Mar 2020 (COVID), Sep 2022 (rate
hikes), Oct 2008 (GFC) — periods where realized blew through implied
and VRP collapsed deeply negative. A viable VRP harvest strategy must
either tolerate or avoid those periods.

Outputs (under data/options/, NOT touching stock workstream):
- data/options/snapshots/vix_history.parquet          (raw ^VIX)
- data/options/snapshots/spy_history.parquet          (raw SPY)
- data/options/analysis/vix_rv_gap.parquet            (daily series)
- data/options/analysis/vix_rv_gap_summary.json       (aggregate)
- stdout: markdown summary

Run:
    python dev/scripts/options/vix_rv_gap_analysis.py
    python dev/scripts/options/vix_rv_gap_analysis.py --no-refetch  # use cached
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


PROJ = Path(__file__).resolve().parents[3]
SNAP_DIR = PROJ / "data" / "options" / "snapshots"
ANAL_DIR = PROJ / "data" / "options" / "analysis"

VIX_PARQUET = SNAP_DIR / "vix_history.parquet"
SPY_PARQUET = SNAP_DIR / "spy_history.parquet"
GAP_PARQUET = ANAL_DIR / "vix_rv_gap.parquet"
SUMMARY_JSON = ANAL_DIR / "vix_rv_gap_summary.json"

RV_WINDOW = 21  # ~1 trading month
TRADING_DAYS = 252

# Tail periods to flag for analysis
TAIL_PERIODS = [
    ("gfc_2008",      "2008-09-01", "2009-03-31"),
    ("euro_2011",     "2011-08-01", "2011-12-31"),
    ("china_2015",    "2015-08-01", "2015-10-31"),
    ("volmageddon_2018", "2018-02-01", "2018-02-28"),
    ("q4_2018",       "2018-10-01", "2018-12-31"),
    ("covid_2020",    "2020-02-15", "2020-04-30"),
    ("rate_hike_2022","2022-01-01", "2022-12-31"),
    ("svb_2023",      "2023-03-01", "2023-04-30"),
]


def fetch_yf(ticker: str, start: str = "1990-01-01") -> pd.DataFrame:
    """Fetch full history from yfinance. Auto-adjusted for SPY (split + div)."""
    print(f"[fetch] {ticker} from {start} ...")
    auto_adjust = ticker.upper() != "^VIX"  # VIX is an index, no adjustment
    df = yf.Ticker(ticker).history(start=start, auto_adjust=auto_adjust)
    if df.empty:
        raise RuntimeError(f"yfinance returned empty for {ticker}")
    df.index = df.index.tz_localize(None)
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    df.columns = [c.lower() for c in df.columns]
    print(f"[fetch] {ticker}: {len(df)} rows, {df.index.min().date()} → {df.index.max().date()}")
    return df


def compute_rv(spy_close: pd.Series, window: int = RV_WINDOW) -> pd.Series:
    """Annualized realized vol from SPY closes (% units, e.g. 15.3)."""
    log_ret = np.log(spy_close / spy_close.shift(1))
    rv = log_ret.rolling(window=window, min_periods=window).std() * np.sqrt(TRADING_DAYS) * 100.0
    return rv.rename("rv_21d_pct")


def build_gap_frame(vix_df: pd.DataFrame, spy_df: pd.DataFrame) -> pd.DataFrame:
    """Daily VIX | RV | VRP frame; aligned on intersection of dates."""
    vix = vix_df["close"].rename("vix_pct")
    rv = compute_rv(spy_df["close"])
    df = pd.concat([vix, rv], axis=1, join="inner").dropna()
    df["vrp_pct"] = df["vix_pct"] - df["rv_21d_pct"]
    df["vrp_positive"] = (df["vrp_pct"] > 0).astype(int)
    df["year"] = df.index.year
    df["month"] = df.index.to_period("M").astype(str)
    return df


def _stats_block(s: pd.Series) -> dict[str, float]:
    return {
        "n": int(s.notna().sum()),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "std": float(s.std()),
        "min": float(s.min()),
        "p05": float(s.quantile(0.05)),
        "p25": float(s.quantile(0.25)),
        "p75": float(s.quantile(0.75)),
        "p95": float(s.quantile(0.95)),
        "max": float(s.max()),
        "positive_pct": float((s > 0).mean() * 100.0),
    }


def summarize(df: pd.DataFrame) -> dict[str, Any]:
    """Aggregate VRP statistics: full period, per-year, per-tail, VIX-stratified."""
    out: dict[str, Any] = {}
    out["window"] = {
        "start": str(df.index.min().date()),
        "end": str(df.index.max().date()),
        "n_trading_days": int(len(df)),
    }
    out["full_period_vrp_pct"] = _stats_block(df["vrp_pct"])
    out["full_period_vix_pct"] = _stats_block(df["vix_pct"])
    out["full_period_rv_21d_pct"] = _stats_block(df["rv_21d_pct"])

    # Per-year breakdown
    per_year = {}
    for year, sub in df.groupby("year"):
        per_year[int(year)] = {
            "n": int(len(sub)),
            "vrp_mean": float(sub["vrp_pct"].mean()),
            "vrp_median": float(sub["vrp_pct"].median()),
            "vrp_min": float(sub["vrp_pct"].min()),
            "vrp_positive_pct": float((sub["vrp_pct"] > 0).mean() * 100.0),
            "vix_mean": float(sub["vix_pct"].mean()),
            "rv_mean": float(sub["rv_21d_pct"].mean()),
        }
    out["per_year"] = per_year

    # Per-month VRP positive % (for "65% of months positive" acceptance)
    monthly = df.groupby("month")["vrp_pct"].mean()
    out["monthly_vrp_positive_pct"] = float((monthly > 0).mean() * 100.0)
    out["monthly_n"] = int(len(monthly))
    out["monthly_worst_5"] = {
        str(idx): float(val) for idx, val in monthly.nsmallest(5).items()
    }
    out["monthly_best_5"] = {
        str(idx): float(val) for idx, val in monthly.nlargest(5).items()
    }

    # Tail period focused
    per_tail = {}
    for label, start, end in TAIL_PERIODS:
        sub = df.loc[start:end]
        if sub.empty:
            per_tail[label] = {"window": [start, end], "n": 0}
            continue
        per_tail[label] = {
            "window": [start, end],
            "n": int(len(sub)),
            "vix_max": float(sub["vix_pct"].max()),
            "rv_max": float(sub["rv_21d_pct"].max()),
            "vrp_min": float(sub["vrp_pct"].min()),
            "vrp_min_date": str(sub["vrp_pct"].idxmin().date()),
            "vrp_mean": float(sub["vrp_pct"].mean()),
            "days_vrp_negative": int((sub["vrp_pct"] < 0).sum()),
        }
    out["tail_periods"] = per_tail

    # VIX-tier stratification (selling regime conditioning)
    bins = [0, 12, 16, 20, 25, 30, 40, 100]
    labels = ["<12", "12-16", "16-20", "20-25", "25-30", "30-40", ">=40"]
    df_strat = df.assign(vix_tier=pd.cut(df["vix_pct"], bins=bins, labels=labels, right=False))
    per_vix = {}
    for tier, sub in df_strat.groupby("vix_tier", observed=True):
        per_vix[str(tier)] = {
            "n": int(len(sub)),
            "vrp_mean": float(sub["vrp_pct"].mean()),
            "vrp_positive_pct": float((sub["vrp_pct"] > 0).mean() * 100.0),
            "rv_mean": float(sub["rv_21d_pct"].mean()),
        }
    out["per_vix_tier"] = per_vix

    return out


def render_markdown(summary: dict[str, Any]) -> str:
    """Stdout-friendly markdown digest."""
    w = summary["window"]
    fp = summary["full_period_vrp_pct"]
    lines = [
        "# VIX vs SPY-RV gap (VRP) — historical viability check",
        "",
        f"**Window**: {w['start']} → {w['end']} ({w['n_trading_days']} trading days)",
        "",
        "## Full-period VRP (vol points, e.g. 3.5 = 350 bps annualized)",
        f"- mean: {fp['mean']:+.2f}",
        f"- median: {fp['median']:+.2f}",
        f"- std: {fp['std']:.2f}",
        f"- p05 (worst tail): {fp['p05']:+.2f}",
        f"- min: {fp['min']:+.2f}",
        f"- positive%: {fp['positive_pct']:.1f}% of trading days",
        f"- monthly positive%: {summary['monthly_vrp_positive_pct']:.1f}% of {summary['monthly_n']} months",
        "",
        "## Per-tail-period stress (VRP collapse during black swans)",
        "",
        "| Period | Window | VIX max | RV max | VRP min | Days VRP<0 |",
        "|---|---|---|---|---|---|",
    ]
    for label, blk in summary["tail_periods"].items():
        if blk.get("n", 0) == 0:
            continue
        lines.append(
            f"| {label} | {blk['window'][0]}…{blk['window'][1]} | "
            f"{blk['vix_max']:.1f} | {blk['rv_max']:.1f} | "
            f"**{blk['vrp_min']:+.2f}** ({blk['vrp_min_date']}) | "
            f"{blk['days_vrp_negative']} |"
        )
    lines += [
        "",
        "## VIX-tier conditional VRP (selling regime)",
        "",
        "| VIX tier | n | VRP mean | VRP positive% | RV mean |",
        "|---|---|---|---|---|",
    ]
    for tier, blk in summary["per_vix_tier"].items():
        lines.append(
            f"| {tier} | {blk['n']} | {blk['vrp_mean']:+.2f} | "
            f"{blk['vrp_positive_pct']:.1f}% | {blk['rv_mean']:.1f} |"
        )
    lines += [
        "",
        "## Per-year VRP (cycle visibility)",
        "",
        "| Year | n | VRP mean | VRP min | VRP pos% | VIX mean | RV mean |",
        "|---|---|---|---|---|---|---|",
    ]
    for year, blk in summary["per_year"].items():
        lines.append(
            f"| {year} | {blk['n']} | {blk['vrp_mean']:+.2f} | "
            f"{blk['vrp_min']:+.2f} | {blk['vrp_positive_pct']:.1f}% | "
            f"{blk['vix_mean']:.1f} | {blk['rv_mean']:.1f} |"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-refetch", action="store_true",
                    help="Reuse cached snapshots if present (faster reruns).")
    ap.add_argument("--start", default="1990-01-01",
                    help="History start date (default 1990-01-01).")
    args = ap.parse_args()

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    ANAL_DIR.mkdir(parents=True, exist_ok=True)

    if args.no_refetch and VIX_PARQUET.exists() and SPY_PARQUET.exists():
        print(f"[cache] reading {VIX_PARQUET} + {SPY_PARQUET}")
        vix_df = pd.read_parquet(VIX_PARQUET)
        spy_df = pd.read_parquet(SPY_PARQUET)
    else:
        vix_df = fetch_yf("^VIX", start=args.start)
        spy_df = fetch_yf("SPY",  start=args.start)
        vix_df.to_parquet(VIX_PARQUET)
        spy_df.to_parquet(SPY_PARQUET)
        print(f"[snap] wrote {VIX_PARQUET} ({len(vix_df)} rows)")
        print(f"[snap] wrote {SPY_PARQUET} ({len(spy_df)} rows)")

    gap = build_gap_frame(vix_df, spy_df)
    gap.to_parquet(GAP_PARQUET)
    print(f"[gap] wrote {GAP_PARQUET} ({len(gap)} rows, "
          f"{gap.index.min().date()} → {gap.index.max().date()})")

    summary = summarize(gap)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2, default=str))
    print(f"[summary] wrote {SUMMARY_JSON}")

    print()
    print(render_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
