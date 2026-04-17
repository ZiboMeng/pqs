#!/usr/bin/env python3
"""
scripts/run_backtest.py — 端到端全量回测 + 报告生成。

流程
----
  1. 加载配置
  2. 从 MarketDataStore 读取历史价格（日线 + VIX）
  3. 运行 RegimeDetector 计算 regime 序列
  4. 运行已注册的活跃策略（Mining 晋升 + 默认基线）
  5. PortfolioConstructor 构建组合权重
  6. BacktestEngine 执行回测（SPY/QQQ benchmark 对比）
  7. WindowAnalyzer walk-forward OOS 验证
  8. 生成 MasterReport

用法
----
    python scripts/run_backtest.py
    python scripts/run_backtest.py --strategy dual_momentum  # 只跑一个
    python scripts/run_backtest.py --start 2018-01-01 --end 2024-12-31
    python scripts/run_backtest.py --no-walk-forward         # 快速跑，跳过 OOS
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
from core.signals.strategies.dual_momentum import DualMomentumStrategy
from core.signals.strategies.trend_following import TrendFollowingStrategy
from core.signals.strategies.cross_asset_rotation import CrossAssetRotationStrategy
from core.signals.strategies.multi_factor import MultiFactorStrategy
from core.portfolio.constructor import PortfolioConstructor
from core.backtest.backtest_engine import BacktestEngine, compute_metrics
from core.backtest.window_analyzer import WindowAnalyzer
from core.reporting.master_report_builder import MasterReportBuilder
from core.storage.artifact_manager import ArtifactManager
from core.logging_setup import setup_logging, get_logger
from core.mining.archive import MiningArchive

setup_logging()
logger = get_logger("run_backtest")


def load_prices(store: MarketDataStore, symbols: list, freq: str = "1d") -> pd.DataFrame:
    """加载多个 symbol 的收盘价矩阵。"""
    frames = {}
    for sym in symbols:
        try:
            df = store.read(sym, freq)
            if df is not None and not df.empty and "close" in df.columns:
                frames[sym] = df["close"]
        except Exception as exc:
            logger.warning("加载 %s 失败: %s", sym, exc)
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames).sort_index()


def load_open_prices(store: MarketDataStore, symbols: list) -> pd.DataFrame:
    """加载多个 symbol 的开盘价矩阵（用于 T+1 成交）。"""
    frames = {}
    for sym in symbols:
        try:
            df = store.read(sym, "1d")
            if df is not None and not df.empty and "open" in df.columns:
                frames[sym] = df["open"]
        except Exception:
            pass
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames).sort_index()


def build_strategies(cfg, price_df: pd.DataFrame, risk_syms: list, def_syms: list) -> dict:
    """构建默认策略集合 + Mining 晋升策略。"""
    strategies = {
        "dual_momentum":        DualMomentumStrategy(universe=risk_syms),
        "trend_following":      TrendFollowingStrategy(symbols=risk_syms),
        "cross_asset_rotation": CrossAssetRotationStrategy(
            risk_assets=risk_syms, defensive_assets=def_syms
        ),
        "multi_factor":         MultiFactorStrategy(
            symbols=risk_syms, top_n=4, rebalance_monthly=False, score_weighted=True,
            factor_weights={"low_vol": 0.0, "momentum": 0.30, "quality": 0.25,
                            "pv_div": 0.05, "rel_strength": 0.30, "market_trend": 0.10},
            min_holding_days=3, lookback_mom=189, lookback_quality=189, lookback_vol=84,
        ),
    }

    # 从 Mining 存档加载晋升策略
    mining_cfg  = cfg.backtest.mining or {}
    archive_db  = mining_cfg.get("archive_db", "data/mining/archive.db")
    if Path(archive_db).exists():
        try:
            from core.mining.strategy_space import instantiate_strategy, StrategySpec
            archive = MiningArchive(db_path=archive_db)
            for p in archive.get_promoted():
                spec  = StrategySpec.from_dict(p["strategy_type"], p["params"])
                strat = instantiate_strategy(spec, risk_syms, def_syms)
                key   = f"mined_{p['strategy_type']}_{p['spec_id'][:6]}"
                strategies[key] = strat
                logger.info("加载已挖掘策略: %s (tier=%s)", key, p["tier"])
        except Exception as exc:
            logger.warning("加载 Mining 存档失败: %s", exc)

    return strategies


def run_strategy(
    name:             str,
    strategy,
    price_df:         pd.DataFrame,
    regime_series:    pd.Series,
    benchmark_series: pd.Series,
    cfg,
    engine:           BacktestEngine,
    constructor:      PortfolioConstructor,
    walk_forward:     bool = True,
    open_df:          pd.DataFrame = None,
) -> dict:
    """运行单个策略回测，返回结果字典。"""
    logger.info("=== 回测策略: %s ===", name)

    signals = strategy.generate(price_df, regime_series)
    use_vp = not isinstance(strategy, MultiFactorStrategy)
    actual_constructor = constructor if use_vp else PortfolioConstructor(use_vol_parity=False)
    weights = actual_constructor.build(
        raw_signals   = signals,
        price_df      = price_df,
        regime_series = regime_series,
    )

    bt_result = engine.run(
        signals_df       = weights,
        price_df         = price_df,
        open_df          = open_df,
        regime_series    = regime_series,
        benchmark_series = benchmark_series,
    )
    logger.info("%s: %s", name, bt_result)

    wf_windows = []
    if walk_forward and len(price_df) >= 756 + 126:
        analyzer   = WindowAnalyzer(engine=engine)
        wf_windows = analyzer.walk_forward(
            signals_df = weights,
            price_df   = price_df,
            benchmark  = benchmark_series,
        )
        if wf_windows:
            oos_check = WindowAnalyzer.oos_consistency_check(wf_windows)
            logger.info("%s OOS consistency: %s", name, oos_check)
            acceptance = analyzer.acceptance_check(bt_result, benchmark_series)
            logger.info("%s Tier D: %s", name, acceptance)

    return {
        "name":       name,
        "result":     bt_result,
        "wf_windows": wf_windows,
        "signals":    signals,
        "weights":    weights,
    }


def main():
    parser = argparse.ArgumentParser(description="PQS 回测运行器")
    parser.add_argument("--strategy",        help="只跑指定策略名")
    parser.add_argument("--start",           default=None, help="回测起始日期 YYYY-MM-DD")
    parser.add_argument("--end",             default=None, help="回测结束日期 YYYY-MM-DD")
    parser.add_argument("--no-walk-forward", action="store_true")
    parser.add_argument("--config-dir",      default="config")
    parser.add_argument("--output-dir",      default="reports/backtests")
    args = parser.parse_args()

    cfg       = load_config(Path(args.config_dir))
    store     = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    artifacts = ArtifactManager(reports_dir=Path(args.output_dir))

    # ── 收集所有 symbol ──────────────────────────────────────────────────────
    uni     = cfg.universe
    seed    = list(uni.seed_pool)
    sectors = list(uni.sector_etfs)
    factors = list(uni.factor_etfs)
    cross   = list(uni.cross_asset)
    all_tradeable = list(dict.fromkeys(seed + sectors + factors + cross))
    def_syms  = [s for s in ["TLT", "IEF", "GLD", "SHY"] if s in all_tradeable]
    risk_syms = [s for s in all_tradeable if s not in def_syms and s not in ["TQQQ", "SOXL"]]

    # ── 加载价格 ─────────────────────────────────────────────────────────────
    logger.info("加载价格数据...")
    price_df = load_prices(store, all_tradeable)
    open_df = load_open_prices(store, all_tradeable)
    if price_df.empty:
        logger.error("价格数据为空，请先运行 fetch_data.py")
        sys.exit(1)

    start = args.start or cfg.backtest.start_date or "2013-01-02"
    end   = args.end
    if start:
        price_df = price_df[price_df.index >= start]
        if not open_df.empty:
            open_df = open_df[open_df.index >= start]
    if end:
        price_df = price_df[price_df.index <= end]
        if not open_df.empty:
            open_df = open_df[open_df.index <= end]

    logger.info("价格矩阵: %d 行 × %d 列 (%s ~ %s)",
                len(price_df), len(price_df.columns),
                price_df.index[0].date(), price_df.index[-1].date())

    # ── VIX & benchmark ───────────────────────────────────────────────────────
    vix_df     = store.read("^VIX", "1d") if store.get_last_date("^VIX", "1d") is not None else None
    vix_series = vix_df["close"].reindex(price_df.index, method="ffill") if vix_df is not None and not vix_df.empty else None

    spy_df    = store.read("SPY", "1d")
    spy_close = spy_df["close"].reindex(price_df.index, method="ffill") if spy_df is not None and not spy_df.empty else price_df.get("SPY")
    qqq_df    = store.read("QQQ", "1d")
    qqq_close = qqq_df["close"].reindex(price_df.index, method="ffill") if qqq_df is not None and not qqq_df.empty else price_df.get("QQQ")

    # ── Regime ────────────────────────────────────────────────────────────────
    logger.info("计算 regime 序列...")
    detector = RegimeDetector(cfg.regime)
    spy_for_regime = price_df.get("SPY", pd.Series(dtype=float))
    vix_for_regime = vix_series if vix_series is not None else pd.Series(20.0, index=spy_for_regime.index)
    regime_series  = detector.classify_series(spy_for_regime, vix_for_regime)
    logger.info("Regime 分布:\n%s", regime_series.value_counts().to_string())

    # ── BacktestEngine ────────────────────────────────────────────────────────
    cost_model  = CostModel(cfg.cost_model)
    engine      = BacktestEngine(
        cost_model      = cost_model,
        initial_capital = cfg.system.account.initial_capital_usd,
    )
    constructor = PortfolioConstructor()

    # ── 策略集合 ──────────────────────────────────────────────────────────────
    strategies = build_strategies(cfg, price_df, risk_syms, def_syms)
    if args.strategy:
        strategies = {k: v for k, v in strategies.items() if args.strategy in k}

    # ── 逐策略回测 ────────────────────────────────────────────────────────────
    all_runs = {}
    for name, strategy in strategies.items():
        run = run_strategy(
            name             = name,
            strategy         = strategy,
            price_df         = price_df,
            regime_series    = regime_series,
            benchmark_series = spy_close,
            cfg              = cfg,
            engine           = engine,
            constructor      = constructor,
            walk_forward     = not args.no_walk_forward,
            open_df          = open_df if not open_df.empty else None,
        )
        all_runs[name] = run

    # ── 生成主报告 ────────────────────────────────────────────────────────────
    logger.info("生成 MasterReport...")
    run_ctx = artifacts.create_run("backtest")
    builder = MasterReportBuilder()

    primary_name   = next(iter(all_runs))
    primary_result = all_runs[primary_name]["result"]
    primary_wf     = all_runs[primary_name].get("wf_windows", [])

    builder.set_backtest(primary_result)
    if primary_wf:
        builder.set_rolling_windows(primary_wf)

    # Regime-stratified performance
    if not primary_result.equity_curve.empty and spy_close is not None:
        builder.set_regime_performance(
            equity_curve=primary_result.equity_curve,
            regime_series=regime_series,
            benchmark_series=spy_close,
            qqq_series=qqq_close,
        )

    # Strategy-level attribution
    if len(all_runs) > 1:
        builder.set_strategy_attribution(all_runs)

    report = builder.build()
    report_path = run_ctx.path("master_report.md")
    report.save(str(report_path))
    logger.info("报告已保存: %s", report_path)

    # 输出所有策略对比摘要
    logger.info("\n=== 策略对比摘要 ===")
    for name, run in all_runs.items():
        m = run["result"].metrics
        logger.info(
            "%-35s | Sharpe=%.2f | CAGR=%.1f%% | MaxDD=%.1f%% | IR=%.2f",
            name,
            m.get("sharpe", float("nan")),
            m.get("cagr", float("nan")) * 100,
            m.get("max_drawdown", float("nan")) * 100,
            m.get("ir", float("nan")),
        )

    # SPY benchmark 参考
    if spy_close is not None and not spy_close.empty:
        spy_metrics = compute_metrics(spy_close.loc[price_df.index[0]:])
        logger.info(
            "%-35s | Sharpe=%.2f | CAGR=%.1f%% | MaxDD=%.1f%%",
            "SPY (benchmark)",
            spy_metrics.get("sharpe", float("nan")),
            spy_metrics.get("cagr", float("nan")) * 100,
            spy_metrics.get("max_drawdown", float("nan")) * 100,
        )

    artifacts.update_latest(run_ctx)
    logger.info("回测完成。")


if __name__ == "__main__":
    main()
