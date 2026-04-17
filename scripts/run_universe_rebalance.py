#!/usr/bin/env python3
"""
scripts/run_universe_rebalance.py — 动态 universe 重评估。

按 momentum / stability / liquidity 对候选标的打分，
输出当前推荐的交易池 top-N 和评分详情。

用法：
    python scripts/run_universe_rebalance.py
    python scripts/run_universe_rebalance.py --top 10 --as-of 2025-01-02
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.universe.universe_manager import UniverseManager
from core.logging_setup import setup_logging, get_logger

setup_logging()
logger = get_logger("universe_rebalance")


def score_symbols(price_df, volume_df, as_of_idx):
    """Score symbols cross-sectionally at a given date index."""
    scores = {}
    for sym in price_df.columns:
        p = price_df[sym].iloc[:as_of_idx + 1].dropna()
        if len(p) < 252:
            continue

        mom_252 = float(p.iloc[-1] / p.iloc[-252] - 1) if len(p) >= 252 else 0
        mom_63 = float(p.iloc[-1] / p.iloc[-63] - 1) if len(p) >= 63 else 0
        mom_21 = float(p.iloc[-1] / p.iloc[-21] - 1) if len(p) >= 21 else 0
        ret = p.pct_change().dropna()
        vol_63 = float(ret.tail(63).std() * np.sqrt(252)) if len(ret) >= 63 else 1.0

        v = None
        if volume_df is not None and sym in volume_df.columns:
            vs = volume_df[sym].iloc[:as_of_idx + 1].dropna()
            if len(vs) >= 30:
                v = float(vs.tail(30).mean())

        scores[sym] = {
            "mom_252d": mom_252,
            "mom_63d": mom_63,
            "mom_21d": mom_21,
            "vol_63d": vol_63,
            "avg_vol_30d": v or 0,
        }

    df = pd.DataFrame(scores).T
    if df.empty:
        return df

    df["mom_score"] = df["mom_252d"].rank(pct=True) * 0.5 + df["mom_63d"].rank(pct=True) * 0.3 + df["mom_21d"].rank(pct=True) * 0.2
    df["stab_score"] = 1.0 - df["vol_63d"].rank(pct=True)
    df["liq_score"] = df["avg_vol_30d"].rank(pct=True)
    df["composite"] = df["mom_score"] * 0.5 + df["stab_score"] * 0.3 + df["liq_score"] * 0.2
    return df.sort_values("composite", ascending=False)


def main():
    parser = argparse.ArgumentParser(description="PQS Universe Rebalance")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--as-of", default=None, help="评估日期 YYYY-MM-DD")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) +
        list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    tradeable = [s for s in all_syms if s not in uni.blacklist and s not in uni.macro_reference]

    pf, vf = {}, {}
    for sym in tradeable:
        df = store.read(sym, "1d")
        if df is not None and not df.empty:
            if "close" in df.columns:
                pf[sym] = df["close"]
            if "volume" in df.columns:
                vf[sym] = df["volume"]
    price_df = pd.DataFrame(pf).sort_index()
    vol_df = pd.DataFrame(vf).sort_index() if vf else None

    if args.as_of:
        as_of = pd.Timestamp(args.as_of)
        mask = price_df.index <= as_of
        as_of_idx = mask.sum() - 1
    else:
        as_of_idx = len(price_df) - 1
        as_of = price_df.index[as_of_idx]

    logger.info("Universe rebalance as of %s", as_of.date())

    scores = score_symbols(price_df, vol_df, as_of_idx)
    if scores.empty:
        logger.error("No symbols scored")
        return

    # PIT filter
    mgr = UniverseManager(config=uni, extra_watchlist=[s for s in tradeable if s not in uni.seed_pool])
    ohlcv = {}
    for sym in tradeable:
        df = store.read(sym, "1d")
        if df is not None:
            ohlcv[sym] = df.iloc[:as_of_idx + 1]
    mgr.refresh(ohlcv, as_of=as_of.date())
    eligible = set(mgr.get_candidate_symbols())

    scores["eligible"] = scores.index.isin(eligible)
    eligible_scores = scores[scores["eligible"]]

    print("\n=== Universe Rebalance (%s) ===" % as_of.date())
    print("\nTop %d eligible symbols:" % args.top)
    print(eligible_scores.head(args.top)[["composite", "mom_score", "stab_score", "liq_score", "mom_252d", "vol_63d"]].to_string())

    print("\nRecommended trading pool (%d):" % min(args.top, len(eligible_scores)))
    recommended = list(eligible_scores.head(args.top).index)
    print("  ", recommended)

    hr = [s for s in recommended if uni.is_high_risk(s)]
    if hr:
        print("  High-risk symbols in pool:", hr)


if __name__ == "__main__":
    main()
