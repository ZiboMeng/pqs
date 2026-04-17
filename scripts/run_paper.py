#!/usr/bin/env python3
"""
scripts/run_paper.py — 内部模拟盘（Paper Trading）日常运行入口。

模式
----
  live    : 运行当日（需要已有当日行情数据）
  replay  : 从历史日期开始回放（构建伪 track record，会附加 bias 警告）
  status  : 查看当前持仓、权益曲线、risk 状态

用法
----
    python scripts/run_paper.py --mode live              # 当日模拟盘
    python scripts/run_paper.py --mode replay --from-date 2024-01-02  # 历史回放
    python scripts/run_paper.py --mode status            # 查看状态

注意事项
--------
  - replay 模式产生的历史记录带有 bias 风险标注，不代表真实 OOS 绩效
  - live 模式在 EOD 后运行，使用当日 60m K 线作为输入
  - kill switch 自动生效（阈值来自 config/risk.yaml）
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
from core.signals.strategies.multi_factor import MultiFactorStrategy
from core.portfolio.constructor import PortfolioConstructor
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.pnl_tracker import PnLTracker
from core.risk.kill_switch import KillSwitch, KillSwitchConfig
from core.diagnostics.detectors import DiagnosticSuite
from core.logging_setup import setup_logging, get_logger

setup_logging()
logger = get_logger("run_paper")


def show_status(engine: PaperTradingEngine) -> None:
    """打印模拟盘当前状态。"""
    summary = engine.get_pnl_summary()
    print("\n=== 模拟盘状态 ===")
    print(f"  当前权益:   ${engine.get_equity():,.2f}")
    print(f"  当前现金:   ${engine.get_cash():,.2f}")
    print(f"  总收益率:   {summary.get('total_return', 0):.2%}")
    print(f"  最大回撤:   {summary.get('max_drawdown', 0):.2%}")
    print(f"  Sharpe:     {summary.get('sharpe', float('nan')):.2f}")
    ks = engine.kill_switch if hasattr(engine, 'kill_switch') else None
    ks_state = ks.state if ks else "UNKNOWN"
    ks_mult = ks.position_multiplier if ks else 1.0
    print(f"  Kill Switch: {ks_state} (position mult={ks_mult:.0%})")

    pos = engine.get_positions()
    if pos:
        print("\n  当前持仓:")
        for sym, qty in pos.items():
            print(f"    {sym}: {qty:.2f} 股")
    else:
        print("\n  当前无持仓（全仓现金）")


def run_replay(
    engine:         PaperTradingEngine,
    price_df_1d:    pd.DataFrame,
    price_df_60m:   dict,
    regime:         pd.Series,
    strategy,
    constructor:    PortfolioConstructor,
    diagnostics:    DiagnosticSuite,
    spy_benchmark:  pd.Series,
    from_date:      str,
    to_date:        str = None,
) -> None:
    """
    历史数据回放（伪 track record）。

    ⚠️ BIAS 警告：策略和参数基于完整历史数据选择，回放结果存在前视偏差，
    不等同于真实 OOS 绩效。仅用于测试执行一致性和发现系统性 bug。
    """
    logger.warning("=" * 60)
    logger.warning("REPLAY 模式 — 存在 LOOK-AHEAD BIAS")
    logger.warning("策略/参数已基于完整历史数据选择，结果不代表真实 OOS 绩效")
    logger.warning("=" * 60)

    dates = price_df_1d.index
    dates = dates[dates >= from_date]
    if to_date:
        dates = dates[dates <= to_date]

    if dates.empty:
        logger.error("指定日期范围内无数据")
        return

    logger.info("开始回放: %s ~ %s (%d 个交易日)", dates[0].date(), dates[-1].date(), len(dates))

    # 生成全期信号（在 replay 模式下无法避免前视 bias）
    signals = strategy.generate(price_df_1d, regime)
    weights = constructor.build(
        raw_signals   = signals,
        price_df      = price_df_1d,
        regime_series = regime,
    )

    for date in dates:
        date_ts = pd.Timestamp(date)

        if engine.is_kill_switch_triggered:
            logger.warning("[%s] Kill switch 触发，停止回放", date.date())
            break

        # 获取当日 60m K 线
        day_bars = price_df_60m.get(str(date.date()))
        if day_bars is None or (isinstance(day_bars, pd.DataFrame) and day_bars.empty):
            logger.debug("[%s] 无 60m 数据，跳过", date.date())
            continue

        # 当日信号
        if date_ts not in weights.index:
            continue
        day_sigs = weights.loc[[date_ts]]

        try:
            result = engine.run_day(
                date     = date_ts,
                day_bars = day_bars,
                day_sigs = day_sigs,
            )
            engine.reconcile(date_ts, result)
        except Exception as exc:
            logger.error("[%s] 执行失败: %s", date.date(), exc)

    # Run diagnostics
    equity = engine.get_equity_curve() if hasattr(engine, 'get_equity_curve') else pd.Series(dtype=float)
    if not equity.empty and spy_benchmark is not None:
        diag_results = diagnostics.run_all(
            strategy_equity=equity,
            benchmark_equity=spy_benchmark.reindex(equity.index, method="ffill"),
        )
        print("\n=== 诊断结果 ===")
        for d in diag_results:
            print(f"  {d}")
        if diagnostics.any_triggered(diag_results):
            logger.warning("诊断发现异常，请检查策略状态")

    show_status(engine)


def main():
    parser = argparse.ArgumentParser(description="PQS 模拟盘运行器")
    parser.add_argument("--mode",       choices=["live", "replay", "status"], default="status")
    parser.add_argument("--from-date",  default="2024-01-02", help="replay 起始日期")
    parser.add_argument("--to-date",    default=None,         help="replay 结束日期")
    parser.add_argument("--db-path",    default="data/paper_trading/pt.db")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    cfg   = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    # ── 初始化 PaperTradingEngine ─────────────────────────────────────────────
    cost_model  = CostModel(cfg.cost_model)
    pnl_tracker = PnLTracker()
    kill_switch = KillSwitch(KillSwitchConfig())
    engine = PaperTradingEngine(
        cost_model      = cost_model,
        pnl_tracker     = pnl_tracker,
        db_path         = args.db_path,
        initial_capital = cfg.system.account.initial_capital_usd,
        kill_switch     = kill_switch,
    )

    if args.mode == "status":
        show_status(engine)
        return

    # ── 加载价格数据 ──────────────────────────────────────────────────────────
    uni      = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.cross_asset)
    ))
    def_syms = [s for s in ["TLT", "IEF", "GLD"] if s in all_syms]

    frames = {}
    for sym in all_syms:
        try:
            df = store.read(sym, "1d")
            if df is not None and not df.empty and "close" in df.columns:
                frames[sym] = df["close"]
        except Exception:
            pass
    price_df_1d = pd.DataFrame(frames).sort_index() if frames else pd.DataFrame()

    # Regime
    vix_df     = store.read("^VIX", "1d") if store.get_last_date("^VIX", "1d") is not None else None
    vix_series = vix_df["close"].reindex(price_df_1d.index, method="ffill") if vix_df is not None and not vix_df.empty else None
    spy_close      = price_df_1d.get("SPY", pd.Series(dtype=float))
    detector       = RegimeDetector(cfg.regime)
    vix_for_regime = vix_series if vix_series is not None else pd.Series(20.0, index=spy_close.index)
    regime         = detector.classify_series(spy_close, vix_for_regime)

    # Strategy
    all_tradeable = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    risk_syms = [s for s in all_tradeable if s not in def_syms
                 and s not in ["TQQQ", "SOXL"] and s not in uni.blacklist]

    constructor = PortfolioConstructor(use_vol_parity=False)
    strategy    = MultiFactorStrategy(
        symbols=risk_syms, top_n=4, rebalance_monthly=False,
        factor_weights={"low_vol": 0.05, "momentum": 0.15, "quality": 0.20,
                        "pv_div": 0.25, "rel_strength": 0.30},
        min_holding_days=3,
    )
    diagnostics = DiagnosticSuite()

    if args.mode == "replay":
        # 加载 60m K 线（按日期索引）
        price_df_60m = {}
        for sym in all_syms:
            try:
                df = store.read(sym, "60m")
                if df is not None and not df.empty:
                    for date, group in df.groupby(df.index.date):
                        key = str(date)
                        if key not in price_df_60m:
                            price_df_60m[key] = group
            except Exception:
                pass

        run_replay(
            engine         = engine,
            price_df_1d    = price_df_1d,
            price_df_60m   = price_df_60m,
            regime         = regime,
            strategy       = strategy,
            constructor    = constructor,
            diagnostics    = diagnostics,
            spy_benchmark  = spy_close,
            from_date      = args.from_date,
            to_date        = args.to_date,
        )

    elif args.mode == "live":
        logger.info("Live 模式：运行当日模拟盘...")
        today = pd.Timestamp.today().normalize()

        signals = strategy.generate(price_df_1d, regime)
        weights = constructor.build(
            raw_signals   = signals,
            price_df      = price_df_1d,
            regime_series = regime,
        )

        if today not in weights.index:
            logger.warning("当日 (%s) 无信号数据，请确认行情已更新", today.date())
        else:
            day_sigs = weights.loc[[today]]
            logger.info("当日目标权重:\n%s", day_sigs.T.to_string())
            logger.info("（完整日内执行需要 60m 行情数据）")

        show_status(engine)


if __name__ == "__main__":
    main()
