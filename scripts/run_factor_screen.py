#!/usr/bin/env python3
"""
scripts/run_factor_screen.py — 因子生成 + IC 筛选 + 报告。

流程
----
  1. 加载日线价格数据
  2. 自动生成候选因子（momentum/reversal/vol/quality/volume）
  3. 计算前向收益（5d/10d/21d）
  4. 对每个因子计算 Rank IC → IR → 统计显著性
  5. 输出排行榜（按 IR 排序）

用法
----
    python scripts/run_factor_screen.py
    python scripts/run_factor_screen.py --horizon 5    # 只看 5 日前向收益
    python scripts/run_factor_screen.py --top 10       # 只看 Top 10
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.data.market_data_store import MarketDataStore
from core.factors.factor_generator import generate_all_factors, compute_forward_returns
from core.factors.factor_engine import FactorEngine
from core.logging_setup import setup_logging, get_logger


def _load_backfill_tickers(symbols) -> set:
    """Intersect BarStore daily-provenance backfill set with universe."""
    try:
        backfill = BarStore().list_backfill_tickers(freq="daily")
    except Exception:
        return set()
    return set(symbols) & backfill

setup_logging()
logger = get_logger("run_factor_screen")


def load_price_volume(store, symbols, start_date):
    price_frames, vol_frames = {}, {}
    for sym in symbols:
        df = store.read(sym, "1d")
        if df is not None and not df.empty:
            if "close" in df.columns:
                price_frames[sym] = df["close"]
            if "volume" in df.columns:
                vol_frames[sym] = df["volume"]
    price_df = pd.DataFrame(price_frames).sort_index()
    vol_df = pd.DataFrame(vol_frames).sort_index() if vol_frames else None
    if start_date:
        price_df = price_df[price_df.index >= start_date]
        if vol_df is not None:
            vol_df = vol_df[vol_df.index >= start_date]
    return price_df, vol_df


def main():
    parser = argparse.ArgumentParser(description="PQS 因子筛选")
    parser.add_argument("--horizon", type=int, nargs="*", default=[5, 10, 21])
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--universe", choices=["executable", "expanded_v1"],
                        default="executable",
                        help="symbol universe (default executable = the "
                             "config/universe.yaml-derived set, byte-for-byte "
                             "unchanged for D6/P4-A2; expanded_v1 = Phase-4 "
                             "expanded via resolve_universe). P4-A1.")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    uni = cfg.universe
    if args.universe == "expanded_v1":
        from core.universe.universe_resolver import resolve_universe
        all_syms = list(resolve_universe(
            "expanded_v1", config_dir=Path(args.config_dir)))
    else:
        all_syms = list(dict.fromkeys(
            list(uni.seed_pool) + list(uni.sector_etfs) +
            list(uni.factor_etfs) + list(uni.cross_asset)
        ))
    tradeable = [s for s in all_syms if s not in uni.blacklist and s not in uni.macro_reference]

    start = cfg.backtest.start_date or "2007-01-02"
    logger.info("加载价格数据...")
    price_df, vol_df = load_price_volume(store, tradeable, start)
    logger.info("价格矩阵: %d 行 × %d 列", len(price_df), len(price_df.columns))

    logger.info("生成候选因子...")
    backfill_tickers = _load_backfill_tickers(price_df.columns)
    if backfill_tickers:
        logger.info("data sensitivity guard: %d backfill tickers will get NaN "
                    "for volume-sensitive factors", len(backfill_tickers))
    factors = generate_all_factors(price_df, vol_df,
                                    backfill_tickers=backfill_tickers)
    logger.info("生成 %d 个候选因子", len(factors))

    logger.info("计算前向收益...")
    fwd_returns = compute_forward_returns(price_df, args.horizon)

    engine = FactorEngine()
    all_stats = []

    for fname, fdf in factors.items():
        for h, rdf in fwd_returns.items():
            try:
                ic = engine.compute_rank_ic(fdf, rdf)
                stats = engine.compute_factor_stats(ic, factor_name=fname, horizon=h)
                all_stats.append(stats)
            except Exception as exc:
                logger.debug("Factor %s H%d failed: %s", fname, h, exc)

    if not all_stats:
        logger.error("没有因子通过计算")
        return

    rows = []
    for s in all_stats:
        rows.append({
            "factor": s.factor_name,
            "horizon": s.horizon,
            "mean_ic": s.mean_ic,
            "ir": s.ir,
            "t_stat": s.t_stat,
            "p_value": s.p_value,
            "ic_pos%": s.ic_positive_ratio,
            "n": s.n_periods,
            "sig": "***" if s.is_significant else "",
        })

    df = pd.DataFrame(rows).sort_values("ir", ascending=False, key=abs)

    print(f"\n=== 因子筛选排行榜 (Top {args.top}) ===\n")
    sig_df = df[df["sig"] == "***"]
    if not sig_df.empty:
        print(f"显著因子 (IR>0.3, p<0.05): {len(sig_df)} / {len(df)}\n")
        print(sig_df.head(args.top).to_string(index=False))
    else:
        print("无显著因子。Top candidates:\n")
        print(df.head(args.top).to_string(index=False))

    print(f"\n=== 全部 {len(df)} 个因子-horizon 组合 ===\n")
    print(df.head(args.top).to_string(index=False))


if __name__ == "__main__":
    main()
