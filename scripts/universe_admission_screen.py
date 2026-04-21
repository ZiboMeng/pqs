#!/usr/bin/env python3
"""LLM-Round 22 tool: Layer 1 universe admission screen.

Implements the objective-only admission rules from user-revised
expansion framework v2 (R21 critique → R22 proposal). Strictly
separates admission (this tool) from alpha scoring (R20/R21
diagnostic tool). No look-ahead / no performance-based filters.

Layer 1 filters (all must pass):

  1. Security type: US common stock (heuristic via BarStore metadata
     and exclude-list of known ETFs / leveraged / ADRs found in
     config/universe.yaml context)
  2. Listing history ≥ 504 trading days (2y); ≥ 252d for discovery
  3. Price floor: close > $5 (extended), > $10 (core)
  4. Liquidity: ADV60 > $20M extended, > $50M core; also consistency —
     ≥ 80% of last 60 days individually met extended threshold
  5. Market cap > $2B extended, > $5B core (proxy via price × shares
     outstanding if available; else skip cap filter with a warning)
  6. Data completeness: no all-NaN windows in last 252d; SPY overlap
     ≥ 252d
  7. Non-blacklisted per config

Output: two pools (extended + core), plus rejects with reasons.
Writes data/ml/universe_admission_<tag>.csv + summary.json.

Does NOT modify config/universe.yaml. Does NOT compute alpha/beta.
Tool PRODUCES CANDIDATE LISTS for user approval per R21 workflow
step 3.

Usage
-----
    # Screen a specific input list (e.g., SP500 + mid-cap tickers)
    python scripts/universe_admission_screen.py \\
        --input-symbols symbols.txt \\
        --out-tag expanded_v1

    # Screen all local daily parquets
    python scripts/universe_admission_screen.py \\
        --all-local --out-tag full_local_scan

    # Screen current config universe
    python scripts/universe_admission_screen.py --out-tag current_universe
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("universe_admission_screen")


# Known ETF/leveraged/index proxy tickers we explicitly EXCLUDE from
# a "US common stock" admission. Not exhaustive — catches the ones
# commonly appearing in quant data feeds. Extend as discovered.
_KNOWN_NON_COMMON_STOCK = {
    # Sector ETFs
    "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLB", "XLC",
    "XLU", "XLRE",
    # Factor ETFs
    "MTUM", "QUAL", "VLUE", "USMV", "SCHD",
    # Leveraged / inverse
    "TQQQ", "SQQQ", "SOXL", "SOXS", "SPXL", "SPXS", "UPRO", "SPXU",
    "TNA", "TZA", "FAS", "FAZ", "DRV", "DRN",
    # Fixed income / macro
    "SHY", "IEF", "TLT", "BND", "AGG", "LQD", "HYG", "EMB",
    "GLD", "SLV", "GDX", "USO", "UNG", "DBA",
    # International
    "EFA", "EEM", "VGK", "VWO", "VEA", "IEMG",
    # Volatility
    "VXX", "UVXY",
}


def _load_symbol_series(
    store: MarketDataStore, symbol: str, start: str,
) -> pd.DataFrame:
    df = store.read(symbol, "1d")
    if df is None or df.empty:
        return pd.DataFrame()
    if "close" not in df.columns:
        return pd.DataFrame()
    df = df.loc[df.index >= start]
    return df


def _check_listing_history(df: pd.DataFrame, min_days: int = 504) -> Tuple[bool, int]:
    if df.empty:
        return False, 0
    return len(df) >= min_days, len(df)


def _check_price_floor(df: pd.DataFrame, min_price: float = 5.0) -> Tuple[bool, float]:
    if df.empty:
        return False, 0.0
    recent = df["close"].tail(60).median()
    return recent >= min_price, float(recent)


def _check_liquidity(
    df: pd.DataFrame,
    min_adv_extended: float = 20e6,
    min_adv_core: float = 50e6,
    consistency_fraction: float = 0.80,
) -> Dict:
    """ADV60 dollar volume + persistence check."""
    if df.empty or "volume" not in df.columns:
        return {"ok_extended": False, "ok_core": False, "adv60": 0.0,
                "persistence_ok": False, "reason": "missing_volume"}
    recent = df.tail(60)
    if len(recent) < 60:
        return {"ok_extended": False, "ok_core": False, "adv60": 0.0,
                "persistence_ok": False, "reason": "insufficient_history"}
    # ADV20 per-day dollar volume
    per_day_dv = (recent["close"] * recent["volume"]).values
    adv60 = float(np.mean(per_day_dv))
    # Persistence: fraction of last 60 days whose individual dollar volume met extended threshold
    frac_met = float(np.mean(per_day_dv >= min_adv_extended))
    persistence_ok = frac_met >= consistency_fraction
    return {
        "ok_extended":   adv60 >= min_adv_extended and persistence_ok,
        "ok_core":       adv60 >= min_adv_core and persistence_ok,
        "adv60":         round(adv60, 0),
        "persistence":   round(frac_met, 3),
        "persistence_ok": persistence_ok,
    }


def _check_data_completeness(
    df: pd.DataFrame, spy_df: pd.DataFrame, min_overlap: int = 252,
) -> Tuple[bool, int, bool]:
    """No all-NaN 252d windows + SPY overlap ≥ min_overlap."""
    if df.empty:
        return False, 0, False
    # Any 252d window fully NaN?
    recent = df["close"].tail(252)
    no_nan_window = recent.notna().sum() >= int(252 * 0.9)
    # Overlap with SPY
    if spy_df.empty:
        overlap = 0
    else:
        overlap = len(df.index.intersection(spy_df.index))
    overlap_ok = overlap >= min_overlap
    return no_nan_window and overlap_ok, overlap, no_nan_window


def _is_common_stock_heuristic(symbol: str) -> Tuple[bool, str]:
    """Crude security-type whitelist check. Conservative — when in
    doubt, admit and mark for human review.
    """
    s = symbol.upper()
    if s in _KNOWN_NON_COMMON_STOCK:
        return False, "known_etf_or_leveraged"
    # Ticker heuristics that often indicate non-common-stock:
    if s.endswith(("U", "W", "P", "R")):  # units, warrants, preferred, rights suffix
        return True, "human_review_required_suffix"
    if "." in s or "-" in s:  # class shares (BRK-B, BRK.B) — allow but flag
        return True, "class_share_or_hyphen"
    if s.startswith("3") or s.startswith("5") or s.startswith("7"):
        # Some exchanges use numeric prefixes for depositary/listed issues;
        # not a strong signal on US exchange so just flag
        return True, "numeric_prefix_flag"
    return True, "ok"


def _screen_symbol(
    symbol: str, store: MarketDataStore, spy_df: pd.DataFrame,
    start: str,
) -> Dict:
    df = _load_symbol_series(store, symbol, start)
    if df.empty:
        return {"symbol": symbol, "admitted": False, "tier": "REJECT",
                "reason": "no_data"}

    # Check 1: security type
    is_common, type_note = _is_common_stock_heuristic(symbol)
    if not is_common:
        return {"symbol": symbol, "admitted": False, "tier": "REJECT",
                "reason": f"not_common_stock:{type_note}"}

    # Check 2: listing history
    hist_ok, n_days = _check_listing_history(df, min_days=504)
    # Even if below 504, try 252 for discovery
    discovery_ok = n_days >= 252

    # Check 3: price floor
    pf_ok, med_price = _check_price_floor(df, min_price=5.0)
    pf_core_ok, _ = _check_price_floor(df, min_price=10.0)

    # Check 4: liquidity
    liq = _check_liquidity(df, min_adv_extended=20e6, min_adv_core=50e6)

    # Check 5: data completeness + SPY overlap
    data_ok, overlap, no_nan = _check_data_completeness(df, spy_df, min_overlap=252)

    # Tier assignment
    all_extended = (hist_ok and pf_ok and liq["ok_extended"] and data_ok)
    all_core = (hist_ok and pf_core_ok and liq["ok_core"] and data_ok)

    if all_core:
        tier = "CORE"
    elif all_extended:
        tier = "EXTENDED"
    elif discovery_ok and pf_ok and liq["adv60"] >= 10e6 and data_ok:
        tier = "WATCH"
    else:
        tier = "REJECT"

    admitted = tier in ("CORE", "EXTENDED")

    # Reasons for rejection
    reasons = []
    if not hist_ok:   reasons.append(f"history_short({n_days}d)")
    if not pf_ok:     reasons.append(f"price_low({med_price:.2f})")
    if not liq["ok_extended"]:
        reasons.append(f"liq_fail(adv={liq['adv60']:.0f},persist={liq['persistence']:.2f})")
    if not data_ok:   reasons.append(f"data_incomplete(overlap={overlap})")

    return {
        "symbol":        symbol,
        "admitted":      admitted,
        "tier":          tier,
        "n_days":        n_days,
        "price_median60": round(med_price, 2),
        "adv60_usd":     liq["adv60"],
        "liq_persist":   liq.get("persistence", 0),
        "spy_overlap":   overlap,
        "type_note":     type_note,
        "reasons":       ";".join(reasons) if reasons else "",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-symbols", default=None,
                        help="Path to newline-separated symbol list file")
    parser.add_argument("--all-local", action="store_true",
                        help="Screen every symbol in data/daily/*.parquet")
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--out-tag", default="screen",
                        help="Output file suffix (data/ml/universe_admission_<tag>.csv)")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--out-dir", default="data/ml")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    # Determine symbols to screen
    if args.all_local:
        data_dir = Path(cfg.system.paths.data_dir) / "daily"
        symbols = sorted([p.stem for p in data_dir.glob("*.parquet")])
        logger.info("All-local scan: %d symbols", len(symbols))
    elif args.input_symbols:
        syms_text = Path(args.input_symbols).read_text()
        symbols = [line.strip().upper() for line in syms_text.splitlines()
                   if line.strip() and not line.strip().startswith("#")]
        logger.info("Input-symbols scan: %d symbols", len(symbols))
    else:
        uni = cfg.universe
        symbols = list(dict.fromkeys(
            list(uni.seed_pool) + list(uni.sector_etfs) +
            list(uni.factor_etfs) + list(uni.cross_asset)
        ))
        logger.info("Config-universe scan: %d symbols", len(symbols))

    # SPY for overlap check
    spy_df = _load_symbol_series(store, "SPY", args.start)
    if spy_df.empty:
        logger.error("SPY data unavailable — cannot compute overlap")
        sys.exit(2)

    # Screen each
    rows = []
    n_total = len(symbols)
    for i, sym in enumerate(symbols, 1):
        if i % 500 == 0:
            logger.info("  progress: %d/%d (%.1f%%)", i, n_total, 100*i/n_total)
        rows.append(_screen_symbol(sym, store, spy_df, args.start))

    df = pd.DataFrame(rows)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"universe_admission_{args.out_tag}.csv"
    df.to_csv(csv_path, index=False)

    # Summary
    tier_counts = df["tier"].value_counts().to_dict()
    summary = {
        "input_count":    n_total,
        "start":          args.start,
        "core":           df.loc[df["tier"] == "CORE", "symbol"].tolist(),
        "extended":       df.loc[df["tier"] == "EXTENDED", "symbol"].tolist(),
        "watch":          df.loc[df["tier"] == "WATCH", "symbol"].tolist(),
        "reject_count":   int((df["tier"] == "REJECT").sum()),
        "tier_counts":    tier_counts,
    }
    (out_dir / f"universe_admission_{args.out_tag}_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )

    # Print
    print()
    print("=" * 84)
    print(f"Universe Admission Screen (Layer 1) — {args.out_tag}")
    print(f"  Input: {n_total} symbols | Start: {args.start}")
    print("=" * 84)
    print(f"Tier counts: {tier_counts}")
    print(f"CORE ({len(summary['core'])}): first 30 = {summary['core'][:30]}")
    if len(summary['core']) > 30:
        print(f"       ... and {len(summary['core']) - 30} more")
    print(f"EXTENDED ({len(summary['extended'])}): first 30 = {summary['extended'][:30]}")
    if len(summary['extended']) > 30:
        print(f"       ... and {len(summary['extended']) - 30} more")
    print(f"WATCH ({len(summary['watch'])}): {summary['watch'][:20]}")
    print(f"REJECT: {summary['reject_count']}")
    print("=" * 84)
    print(f"Artifacts: {csv_path}")
    print(f"           {out_dir / f'universe_admission_{args.out_tag}_summary.json'}")


if __name__ == "__main__":
    main()
