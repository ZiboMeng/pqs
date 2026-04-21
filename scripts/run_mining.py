#!/usr/bin/env python3
"""
scripts/run_mining.py — 策略循环挖掘主入口。

功能
----
  1. 加载历史价格数据
  2. 计算 regime 序列
  3. 启动 StrategyMiner：对 DualMomentum / TrendFollowing / CrossAssetRotation
     三种类型进行 Optuna 驱动的参数搜索
  4. 多阶段筛选（quick → OOS → robustness → diversity）
  5. 晋升最优策略到活跃池（持久化到 SQLite）
  6. 打印排行榜

用法
----
    python scripts/run_mining.py                    # 标准挖掘（每类 80 trials，1h 预算）
    python scripts/run_mining.py --trials 200       # 更多试验
    python scripts/run_mining.py --budget 7200      # 更长时间预算（秒）
    python scripts/run_mining.py --type dual_momentum  # 只挖一种策略类型
    python scripts/run_mining.py --leaderboard      # 只打印排行榜，不运行新挖掘
    python scripts/run_mining.py --reset-archive    # ⚠️ 清空存档重新开始

注意事项
--------
  - 每次运行会从上次 Optuna study 断点续跑（Bayesian 优化持续积累）
  - 运行时间越长，Optuna TPE 采样越精准
  - Mining 结果自动被 run_backtest.py 加载用于对比回测
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.execution.cost_model import CostModel
from core.regime.regime_detector import RegimeDetector
from core.mining.strategy_space import ALL_SPACES
from core.mining.evaluator import MiningEvaluator
from core.mining.archive import MiningArchive
from core.mining.miner import StrategyMiner
from core.logging_setup import setup_logging, get_logger

setup_logging()
logger = get_logger("run_mining")


def load_prices(store: MarketDataStore, symbols: list) -> pd.DataFrame:
    frames = {}
    for sym in symbols:
        try:
            df = store.read(sym, "1d")
            if df is not None and not df.empty and "close" in df.columns:
                frames[sym] = df["close"]
        except Exception as exc:
            logger.warning("加载 %s 失败: %s", sym, exc)
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames).sort_index()


def main():
    parser = argparse.ArgumentParser(description="PQS 策略挖掘循环")
    parser.add_argument("--trials",         type=int,   default=80,     help="每种策略类型的 Optuna 试验数")
    parser.add_argument("--budget",         type=float, default=3600.0, help="总时间预算（秒）")
    parser.add_argument("--type",           help="只挖指定类型 (dual_momentum/trend_following/cross_asset_rotation)")
    parser.add_argument("--leaderboard",    action="store_true", help="只打印排行榜")
    parser.add_argument("--reset-archive",  action="store_true", help="清空 Mining 存档重新开始")
    parser.add_argument("--start",          default=None, help="数据起始日期")
    parser.add_argument("--config-dir",     default="config")
    parser.add_argument("--lineage-tag",    default="post-2026-04-20-closeout",
                        help="Stamps every archived trial/promotion "
                             "with this tag. Pre-closeout rows default "
                             "to 'pre-2026-04-20' and should not be mixed.")
    parser.add_argument("--lineage-filter", default=None,
                        help="When used with --leaderboard, only show "
                             "trials with this lineage_tag. Omit to "
                             "show all lineages (leaderboard will "
                             "display a 'lineage' column so mixing "
                             "is visible).")
    args = parser.parse_args()

    cfg   = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    # ── 获取 mining 配置 ──────────────────────────────────────────────────────
    mining_cfg = cfg.backtest.mining or {}
    archive_db = mining_cfg.get("archive_db",        "data/mining/archive.db")
    optuna_db  = mining_cfg.get("optuna_db",          "data/mining/optuna.db")
    ec_dir     = mining_cfg.get("equity_curve_dir",   "data/mining/equity_curves")
    archive    = MiningArchive(db_path=archive_db, equity_curve_dir=ec_dir,
                                lineage_tag=args.lineage_tag)
    logger.info("Archive lineage_tag=%s", args.lineage_tag)

    # ── 只打印排行榜 ──────────────────────────────────────────────────────────
    if args.leaderboard:
        lb = archive.leaderboard(n=30, lineage_tag=args.lineage_filter)
        if lb.empty:
            if args.lineage_filter:
                logger.info("指定 lineage_tag='%s' 无记录。", args.lineage_filter)
            else:
                logger.info("存档为空，请先运行挖掘。")
        else:
            header = (
                f"策略挖掘排行榜 Top 30"
                + (f"（lineage={args.lineage_filter}）" if args.lineage_filter else "")
            )
            print(f"\n=== {header} ===")
            # 新增列: lineage_tag + QQQ 门槛相关（Round 2 Topic B，closeout
            # 2026-04-20）。之前 CLI 只显示 8 列，隐藏了 QQQ gate 字段和
            # lineage_tag，导致混 lineage 看不出来，gate 状态看不出来。
            lb_disp = lb.copy()
            lb_disp["qqq_full"]    = lb_disp["qqq_full_period_excess"]
            lb_disp["qqq_holdout"] = lb_disp["qqq_holdout_excess"]
            lb_disp["qqq_oos"]     = lb_disp["qqq_oos_avg_excess"]
            lb_disp["qqq_ok"]      = lb_disp["passed_qqq_gate"].map(
                {1: "✓", 0: "✗"}
            )
            cols = [
                "spec_id", "strategy_type", "tier", "composite_score",
                "quick_sharpe", "oos_ir", "oos_pass_rate", "quick_max_dd",
                "qqq_ok", "qqq_full", "qqq_holdout", "qqq_oos",
                "lineage_tag",
            ]
            print(lb_disp[cols].to_string(index=False))

        # Per-lineage 汇总 —— 暴露跨 lineage 混合状态, 帮诊断 OOS/QQQ gate 分层
        ls = archive.lineage_summary()
        if not ls.empty:
            print("\n=== 按 Lineage 分组汇总 ===")
            ls_disp = ls.copy()
            for c in ("avg_quick_sharpe", "worst_oos_ir", "best_oos_ir"):
                ls_disp[c] = ls_disp[c].round(3)
            print(ls_disp.to_string(index=False))

        stats = archive.stats()
        print(f"\n存档统计（跨所有 lineage）: {stats}")
        return

    # ── 重置存档 ──────────────────────────────────────────────────────────────
    if args.reset_archive:
        confirm = input("⚠️  确认清空 Mining 存档？这将删除所有已挖掘结果。(yes/no): ")
        if confirm.lower() != "yes":
            logger.info("取消。")
            return
        import sqlite3
        conn = sqlite3.connect(archive_db)
        conn.execute("DELETE FROM trials")
        conn.execute("DELETE FROM promotions")
        conn.commit()
        conn.close()
        logger.info("存档已清空。")

    # ── 收集 symbol ───────────────────────────────────────────────────────────
    uni      = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool)
        + list(uni.sector_etfs)
        + list(uni.factor_etfs)
        + list(uni.cross_asset)
    ))
    def_syms  = [s for s in ["TLT", "IEF", "GLD", "SHY"] if s in all_syms]
    risk_syms = [s for s in all_syms if s not in def_syms and s not in ["TQQQ", "SOXL"]]

    # ── 加载价格 ──────────────────────────────────────────────────────────────
    logger.info("加载价格数据...")
    price_df = load_prices(store, all_syms)
    if price_df.empty:
        logger.error("价格数据为空，请先运行 fetch_data.py")
        sys.exit(1)

    # Load open prices for realistic T+1 execution
    open_frames = {}
    for sym in all_syms:
        try:
            df = store.read(sym, "1d")
            if df is not None and not df.empty and "open" in df.columns:
                open_frames[sym] = df["open"]
        except Exception:
            pass
    open_df = pd.DataFrame(open_frames).sort_index() if open_frames else None

    start = args.start or cfg.backtest.start_date or "2013-01-02"
    if start:
        price_df = price_df[price_df.index >= start]
        if open_df is not None:
            open_df = open_df[open_df.index >= start]

    logger.info("价格矩阵: %d 行 × %d 列 (%s ~ %s)",
                len(price_df), len(price_df.columns),
                price_df.index[0].date(), price_df.index[-1].date())

    # ── VIX & Regime ──────────────────────────────────────────────────────────
    # Mining is research context — lenient mode (logs warning on any
    # fallback fill). Live path uses strict mode in run_paper.py.
    from core.data.vix_loader import load_vix_series

    spy_close      = price_df.get("SPY", pd.Series(dtype=float))
    detector       = RegimeDetector(cfg.regime)
    vix_for_regime = load_vix_series(store, spy_close.index, mode="lenient")
    regime         = detector.classify_series(spy_close, vix_for_regime)

    spy_prices = price_df.get("SPY", pd.Series(dtype=float))

    # ── 初始化 Evaluator & Miner ──────────────────────────────────────────────
    cost_model = CostModel(cfg.cost_model)
    evaluator  = MiningEvaluator(
        cost_model          = cost_model,
        initial_capital     = cfg.system.account.initial_capital_usd,
        quick_min_sharpe    = mining_cfg.get("quick_min_sharpe",    0.30),
        quick_max_dd        = mining_cfg.get("quick_max_drawdown",  0.40),
        quick_min_cagr      = mining_cfg.get("quick_min_cagr",      0.02),
        oos_min_pass_rate   = mining_cfg.get("oos_min_pass_rate",   0.60),
        oos_min_ir          = mining_cfg.get("oos_min_ir_vs_benchmark", 0.30),
        oos_min_excess_ret  = mining_cfg.get("oos_min_excess_return", 0.03),
        regime_robust_n     = mining_cfg.get("regime_robust_min_regimes", 2),
        cost_multiplier     = mining_cfg.get("cost_robust_multiplier", 2.0),
        param_max_change    = mining_cfg.get("param_robust_max_sharpe_change", 0.50),
        diversity_max_corr  = mining_cfg.get("diversity_max_correlation", 0.70),
        score_weights       = mining_cfg.get("score_weights"),
        holdout_bars        = mining_cfg.get("holdout_bars", 252),
        quick_data_fraction = mining_cfg.get("quick_data_fraction", 0.70),
        stress_periods      = mining_cfg.get("stress_periods", []),
        crisis_dd_vs_spy    = mining_cfg.get("crisis_dd_vs_spy_multiplier", 1.0),
        wf_test_bars_by_type = mining_cfg.get("walk_forward_test_bars_by_type", {}),
        min_oos_is_sharpe_ratio = mining_cfg.get("min_oos_is_sharpe_ratio", 0.50),
        defensive_window_dd_mult = mining_cfg.get("defensive_window_dd_multiplier", 1.3),
        # QQQ hard gate (P0.4) — defaults to 0.0 meaning "must match QQQ"
        min_cagr_excess_vs_qqq     = mining_cfg.get("min_cagr_excess_vs_qqq", 0.0),
        min_holdout_excess_vs_qqq  = mining_cfg.get("min_holdout_excess_vs_qqq", 0.0),
        min_avg_oos_excess_vs_qqq  = mining_cfg.get("min_avg_oos_excess_vs_qqq", 0.0),
        # Share mode (P0.5): config is source of truth
        integer_shares             = not cfg.risk.position_limits.allow_fractional_shares,
    )
    if open_df is not None:
        evaluator.set_open_df(open_df)
        logger.info("Mining evaluator 使用真实 open price")

    # 过滤策略类型
    spaces = ALL_SPACES
    if args.type:
        spaces = [s for s in ALL_SPACES if s.strategy_type == args.type]
        if not spaces:
            logger.error("未知策略类型: %s", args.type)
            sys.exit(1)

    miner = StrategyMiner(
        evaluator      = evaluator,
        archive        = archive,
        spaces         = spaces,
        optuna_storage = optuna_db,
    )

    # ── 启动挖掘 ─────────────────────────────────────────────────────────────
    logger.info("启动策略挖掘循环 (trials=%d, budget=%.0fs)...", args.trials, args.budget)
    # QQQ series for the hard gate. Load from store alongside SPY.
    qqq_df = store.read("QQQ", "1d")
    qqq_series = (qqq_df["close"].reindex(price_df.index, method="ffill")
                  if qqq_df is not None and not qqq_df.empty else None)
    if qqq_series is None:
        logger.warning("QQQ data missing — hard gate will be disabled "
                       "(all strategies bypass QQQ check). Expected to be "
                       "available via store.read('QQQ', '1d').")

    run_result = miner.run(
        price_df         = price_df,
        regime_series    = regime,
        benchmark_series = spy_prices,
        risk_universe    = risk_syms,
        def_universe     = def_syms,
        n_trials         = args.trials,
        time_budget      = args.budget,
        verbose          = True,
        qqq_series       = qqq_series,
    )

    # ── 打印结果 ──────────────────────────────────────────────────────────────
    logger.info("\n=== 挖掘结果 ===")
    logger.info("评估总数: %d  | 耗时: %.1f秒", run_result.n_evaluated, run_result.elapsed_seconds)
    logger.info("存档统计: %s",  run_result.archive_stats)

    print("\n=== 晋升策略 ===")
    for r in run_result.promoted_strategies:
        print(f"  {r.strategy_type} | tier={r.tier} | score={r.composite_score:.3f} | {r.spec_id}")

    if not run_result.leaderboard.empty:
        print("\n=== Top 20 排行榜 ===")
        lb = run_result.leaderboard.head(20)
        print(lb[["spec_id", "strategy_type", "tier", "composite_score",
                   "quick_sharpe", "oos_ir", "oos_pass_rate"]].to_string(index=False))

    logger.info("Mining 完成。")


if __name__ == "__main__":
    main()
