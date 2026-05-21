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
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from core.config.loader import load_config
from core.data.factory import create_default_store
from core.execution.cost_model import CostModel
from core.regime.regime_detector import RegimeDetector
from core.portfolio.constructor import PortfolioConstructor
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.pnl_tracker import PnLTracker
from core.risk.kill_switch import KillSwitch, KillSwitchConfig
from core.diagnostics.detectors import DiagnosticSuite
from core.logging_setup import setup_logging, get_logger

setup_logging()
logger = get_logger("run_paper")


def apply_kill_switch_to_target(
    engine: PaperTradingEngine,
    target: dict,
) -> tuple[dict, object | None]:
    """Evaluate kill switch against the engine's equity history and apply the
    resulting state to `target` weights.

    - SUSPENDED → returns empty dict (force full liquidation to cash next fill)
    - DEGRADED  → scales every weight by `position_multiplier` (e.g. 0.5)
    - NORMAL    → returns target unchanged

    Returns (adjusted_target, KillSwitchResult or None).

    Design note: both live and replay flows MUST go through this helper so that
    DEGRADED actually reduces position size (previously only SUSPENDED was
    honoured, and only by breaking the replay loop — DEGRADED was silently
    ignored, undermining the 2-tier risk gate).
    """
    ks = getattr(engine, "kill_switch", None)
    if ks is None:
        return target, None
    records = getattr(engine, "_tracker", None)
    if records is not None and records._records:
        eq_values = [r["equity"] for r in records._records]
    else:
        eq_values = [engine._initial_capital]
    result = ks.evaluate(pd.Series(eq_values))
    if result.state == "SUSPENDED":
        logger.warning("Kill switch SUSPENDED → 清空目标权重 (force cash). "
                       "rules=%s", ",".join(result.active_rules))
        return {}, result
    if result.state == "DEGRADED":
        mult = result.position_multiplier
        logger.warning("Kill switch DEGRADED → 目标权重 × %.2f. rules=%s",
                       mult, ",".join(result.active_rules))
        return {s: w * mult for s, w in target.items()}, result
    return target, result


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


def _rth_filter_day_bars(day_bars: dict) -> dict:
    """Keep only RTH (09:30-16:00 ET) bars for each symbol."""
    out = {}
    for sym, df in day_bars.items():
        if df is None or df.empty:
            continue
        mins = df.index.hour * 60 + df.index.minute
        rth = df.loc[(mins > 9 * 60 + 30) & (mins <= 16 * 60)]
        if not rth.empty:
            out[sym] = rth
    return out


def _execute_day_bar_by_bar(
    engine:          PaperTradingEngine,
    run_id:          str,
    date_ts:         pd.Timestamp,
    day_bars:        dict,
    target:          dict,
    timing_provider = None,
) -> object | None:
    """Dispatch one day's bar-by-bar execution via the shared intraday
    runtime. Used by both replay and live. Returns DayResult or None.

    Idempotency is handled inside run_day_intraday (has_fill_for_bar per
    bar), so calling this on a day already processed is safe.

    If `timing_provider` is passed (the output of
    `multi_timescale.make_timing_target_provider`), per-bar targets
    flow through the multi-TF timing layer.
    """
    day_bars = _rth_filter_day_bars(day_bars)
    if not day_bars:
        logger.debug("[%s] no RTH bars available", date_ts.date())
        return None
    try:
        return engine.run_day_intraday(
            run_id=run_id, date=date_ts,
            day_bars=day_bars, target_wts=target,
            timing_provider=timing_provider,
        )
    except Exception as exc:
        logger.error("[%s] intraday 执行失败: %s", date_ts.date(), exc, exc_info=True)
        return None


def run_replay(
    engine:         PaperTradingEngine,
    price_df_1d:    pd.DataFrame,
    open_df_1d:     pd.DataFrame,
    price_df_60m:   dict,
    regime:         pd.Series,
    strategy,
    constructor:    PortfolioConstructor,
    diagnostics:    DiagnosticSuite,
    spy_benchmark:  pd.Series,
    from_date:      str,
    to_date:        str = None,
    run_id:         str = None,
    decision_stack: str = "legacy",
    decision_stack_cfg=None,
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

    # PRD M10: apply cross-ticker DSL rules on production weight matrix
    try:
        from core.signals.cross_ticker_wrapper import apply_rules_to_weight_matrix
        # Build OHLCV frames on-the-fly from price_df_1d (close-only);
        # DSL rules referencing high/low/open/volume will degrade gracefully
        ohlcv_frames = {
            sym: pd.DataFrame({"close": price_df_1d[sym]}).dropna()
            for sym in price_df_1d.columns
        }
        weights, ct_stats = apply_rules_to_weight_matrix(
            weights, regime, ohlcv_frames,
        )
        if ct_stats.get("applied"):
            logger.info("Cross-ticker DSL replay stats: %s", ct_stats)
    except Exception as exc:
        logger.warning("Cross-ticker DSL wrapper failed (non-fatal): %s", exc)

    # PRD-X v2 P2-* (2026-05-20): opt-in decision-stack overlay on
    # paper replay weight panel. Default legacy bit-identical;
    # trigger-first applies PartialRebalance + MLSidecar between the
    # constructor-built weights and the per-day PaperTradingEngine
    # iteration. M11 parity preserved (no change to engine.run_day_*).
    # R17 (auditor F5/F8): config-driven parameters when available.
    if decision_stack == "trigger-first":
        from scripts.run_backtest import (
            _apply_decision_stack_overlay,
            _apply_decision_stack_overlay_from_config,
        )
        if decision_stack_cfg is not None:
            logger.info(
                "paper-replay: applying PRD-X trigger-first overlay "
                "from config (band_base=%s, sidecar.enabled=%s, "
                "voter_kind=%s, per-symbol-vol=yes)",
                decision_stack_cfg.partial_rebalance.band_base,
                decision_stack_cfg.ml_sidecar.enabled,
                decision_stack_cfg.ml_sidecar.voter_kind)
            weights = _apply_decision_stack_overlay_from_config(
                weights, regime, decision_stack_cfg,
                price_df=price_df_1d)
        else:
            logger.warning(
                "paper-replay: --decision-stack trigger-first BUT "
                "no decision_stack_cfg — fallback to hardcoded "
                "defaults (auditor F5: prefer config wiring)")
            weights = _apply_decision_stack_overlay(
                weights, regime, band_base=0.02, use_sidecar=True,
                price_df=price_df_1d)
    elif decision_stack != "legacy":
        raise ValueError(
            f"unknown decision_stack={decision_stack!r}; expected "
            f"'legacy' or 'trigger-first'")

    if run_id is None:
        import uuid
        run_id = str(uuid.uuid4())[:8]
    logger.info("Replay run_id: %s", run_id)

    for i, date in enumerate(dates):
        date_ts = pd.Timestamp(date)

        if date_ts not in weights.index:
            continue

        day_wts = weights.loc[date_ts]
        target = {s: float(v) for s, v in day_wts.items() if v > 0.001}

        target, ks_result = apply_kill_switch_to_target(engine, target)
        if ks_result is not None and ks_result.state == "SUSPENDED":
            logger.warning("[%s] Kill switch SUSPENDED，停止回放", date.date())

        day_bars_60m = price_df_60m.get(str(date.date()))

        if day_bars_60m and isinstance(day_bars_60m, dict) and len(day_bars_60m) > 0:
            result = _execute_day_bar_by_bar(
                engine, run_id, date_ts, day_bars_60m, target,
            )
            if result is not None:
                engine.reconcile(date_ts, result)
        else:
            # Daily fallback — only when NO intraday bars exist for the day.
            # Pricing semantics (M11b fix, 2026-04-24):
            #   * date_ts   = T (signal day)
            #   * next_date = T+1 (execution day, also row index)
            #   * prev_close (T close)  → SOD mark / current-weight calc
            #   * exec_open (T+1 open)  → fill price
            #   * eod_close (T+1 close) → EOD equity mark
            # Pre-fix this path passed only T-close as `prices` for both
            # SOD and EOD valuation, producing a 1-day-stale equity.
            next_idx = i + 1
            if next_idx >= len(dates):
                break
            next_date = dates[next_idx]
            prev_close: Dict[str, float] = {}
            exec_open: Dict[str, float] = {}
            eod_close: Dict[str, float] = {}
            for sym in price_df_1d.columns:
                if date_ts in price_df_1d.index:
                    p = price_df_1d.loc[date_ts, sym]
                    if not pd.isna(p):
                        prev_close[sym] = float(p)
                if next_date in open_df_1d.index and sym in open_df_1d.columns:
                    o = open_df_1d.loc[next_date, sym]
                    if not pd.isna(o):
                        exec_open[sym] = float(o)
                if next_date in price_df_1d.index:
                    # NOTE (audit 2026-05-21): no exec_open fallback to
                    # T+1 close. A missing T+1 open = no execution bar;
                    # per CLAUDE.md pricing spec ("Symbol has no bar
                    # today → Do NOT generate new orders") the symbol
                    # must be skipped (fail-closed), not filled at a
                    # substitute price. _generate_orders' NaN guard
                    # already drops symbols absent from exec_open; the
                    # position is held and marked at last valid close.
                    c = price_df_1d.loc[next_date, sym]
                    if not pd.isna(c):
                        eod_close[sym] = float(c)
            if not prev_close or not exec_open:
                continue
            # Diagnostic: surface (do not silently absorb) any target
            # symbol whose T+1 open is missing — its order is skipped.
            missing_open = sorted(s for s in target if s not in exec_open)
            if missing_open:
                logger.warning(
                    "[%s] T+1 open missing for %d target symbol(s): %s — "
                    "orders skipped (fail-closed per pricing spec; "
                    "positions held + marked at last valid close)",
                    next_date.date(), len(missing_open), missing_open,
                )
            try:
                result = engine.run_day_daily(
                    exec_date=next_date,
                    target_wts=target,
                    prev_close=prev_close,
                    exec_open=exec_open,
                    eod_close=eod_close,
                )
                engine.reconcile(next_date, result)
            except Exception as exc:
                logger.error("[%s] Daily 执行失败: %s", date.date(), exc)

        if ks_result is not None and ks_result.state == "SUSPENDED":
            break

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
    parser.add_argument("--ignore-alignment-check", action="store_true",
                        help="Skip PRD M3 runtime alignment check. In live "
                             "mode, only use this if you know what you're "
                             "doing — the check is designed to catch silent "
                             "strategy/universe drift.")
    parser.add_argument(
        "--decision-stack",
        choices=["legacy", "trigger-first"],
        default="legacy",
        help=("PRD-X v2 opt-in for paper-replay overlay. "
              "Default legacy = bit-identical paper-backtest "
              "consistency (M11 path preserved). 'trigger-first' "
              "applies PartialRebalancePolicy + MLSidecarPolicy "
              "overlay on the constructor's weight panel before "
              "the per-day PaperTradingEngine loop. Status flip in "
              "production_strategy.yaml to 'active' remains a "
              "directional decision."),
    )
    parser.add_argument("--use-timing", action="store_true",
                        help="Route per-bar targets through the multi-TF "
                             "timing layer (decide_timing). Loads 60m+30m"
                             "+15m bars for timing decisions. Off by default "
                             "because current timing research shows ~neutral "
                             "value; only enable with explicit intent.")
    args = parser.parse_args()

    cfg   = load_config(Path(args.config_dir))
    store = create_default_store(cfg)

    # PRD M3/M13: runtime alignment check (mode from config/system.yaml;
    # FAIL mode in paper live blocks startup on hash mismatch)
    if args.mode != "status":
        from core.alignment import check_alignment, write_alignment_report, AlignmentMode
        ac = cfg.system.alignment
        # Paper trading (live + replay) respects fail mode directly
        mode = AlignmentMode.FAIL if ac.mode == "fail" else AlignmentMode.WARN
        alignment = check_alignment(
            Path(__file__).resolve().parent.parent,
            mode=mode,
            ignore=args.ignore_alignment_check,
        )
        logger.info(alignment.summary_line())
        try:
            write_alignment_report(alignment)
        except Exception as exc:
            logger.warning("Could not write alignment artifact: %s", exc)

    # ── 初始化 PaperTradingEngine ─────────────────────────────────────────────
    cost_model  = CostModel(cfg.cost_model)
    initial_cap = cfg.system.account.initial_capital_usd
    pnl_tracker = PnLTracker(initial_capital=initial_cap)
    halt_pct = cfg.risk.drawdown_limits.halt_pct if hasattr(cfg.risk, 'drawdown_limits') else 0.25
    ks_cfg = KillSwitchConfig(
        max_drawdown=-halt_pct,
        degrade_dd_ratio=0.70,
        suspend_dd_ratio=1.00,
    )
    kill_switch = KillSwitch(ks_cfg)
    # Share mode: config/risk.yaml::position_limits.allow_fractional_shares
    # is the single source of truth (P0.5). Prior behavior relied on
    # per-engine defaults happening to match — fragile under future
    # default flips.
    integer_shares = not cfg.risk.position_limits.allow_fractional_shares
    engine = PaperTradingEngine(
        cost_model      = cost_model,
        pnl_tracker     = pnl_tracker,
        db_path         = args.db_path,
        initial_capital = cfg.system.account.initial_capital_usd,
        kill_switch     = kill_switch,
        integer_shares  = integer_shares,
    )

    if args.mode == "status":
        show_status(engine)
        return

    # ── 加载价格数据 ──────────────────────────────────────────────────────────
    uni      = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    def_syms = [s for s in ["TLT", "IEF", "GLD", "SHY"] if s in all_syms]

    # P0-A F4: paper-sim daily prices MUST be split-adjusted (was
    # store.read = MarketDataStore raw → grand-audit P0-A). R3-verified
    # NOT on the live forward-evidence path (that runs via
    # forward.observe → attention_report BarStore-adjusted; run_paper
    # writes no forward/evidence manifest) → correctness fix for the
    # run_all.sh daily/replay paper loop, not a live-soak mutation.
    # 60m reads below stay raw (intraday, separate — like run_mining).
    from core.data.price_access import load_adjusted
    frames = {}
    open_frames = {}
    for sym in all_syms:
        try:
            df = load_adjusted(sym, store.data_dir, "1d")
            if df is not None and not df.empty:
                if "close" in df.columns:
                    frames[sym] = df["close"]
                if "open" in df.columns:
                    open_frames[sym] = df["open"]
        except Exception:
            pass
    price_df_1d = pd.DataFrame(frames).sort_index() if frames else pd.DataFrame()
    open_df_1d = pd.DataFrame(open_frames).sort_index() if open_frames else pd.DataFrame()

    # Regime. VIX mode depends on what we're doing: live/paper must
    # fail-closed if VIX is missing (trading against a 20.0 stub in a
    # black-swan day would mis-size catastrophically); replay/status
    # can stay lenient (historical gaps are bounded and diagnostic).
    from core.data.vix_loader import load_vix_series, VixDataMissingError
    vix_mode = "strict" if args.mode == "live" else "lenient"
    spy_close = price_df_1d.get("SPY", pd.Series(dtype=float))
    detector  = RegimeDetector(cfg.regime)
    try:
        vix_for_regime = load_vix_series(
            store, spy_close.index, mode=vix_mode,
        )
    except VixDataMissingError as exc:
        logger.error("Refusing to run live without fresh VIX: %s", exc)
        return
    regime = detector.classify_series(spy_close, vix_for_regime)

    # Strategy
    all_tradeable = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    risk_syms = [s for s in all_tradeable if s not in def_syms
                 and s not in ["TQQQ", "SOXL"] and s not in uni.blacklist]

    constructor = PortfolioConstructor(use_vol_parity=False)
    # PRD M1: strategy loaded from config/production_strategy.yaml (single
    # source of truth). Paper trading does NOT accept --override-production
    # — if the artifact is misconfigured, fail loud rather than fall back
    # to a hardcoded default (which was exactly the drift M1 fixes).
    from core.config.production_strategy import load_production_strategy, build_strategy_from_config
    ps_cfg = load_production_strategy()
    strategy = build_strategy_from_config(ps_cfg, cfg.risk, risk_syms)
    diagnostics = DiagnosticSuite()

    if args.mode == "replay":
        # 加载 60m K 线——按日期分组，每日一个 multi-symbol DataFrame
        intraday_by_sym = {}
        for sym in all_tradeable:
            try:
                df = store.read(sym, "60m")
                if df is not None and not df.empty:
                    intraday_by_sym[sym] = df
            except Exception:
                pass

        # price_df_60m: date_str → Dict[symbol → DataFrame]  (multi-asset per day)
        price_df_60m = {}
        if intraday_by_sym:
            all_dates = set()
            for df in intraday_by_sym.values():
                all_dates.update(df.index.date)
            for d in sorted(all_dates):
                day_frames = {}
                for sym, df in intraday_by_sym.items():
                    mask = df.index.date == d
                    if mask.any():
                        day_frames[sym] = df[mask]
                if day_frames:
                    price_df_60m[str(d)] = day_frames

        # R17 (auditor F5/F8 closure): load decision_stack config from
        # production_strategy.yaml for runtime parameters.
        decision_stack_cfg = None
        if args.decision_stack == "trigger-first":
            try:
                from core.config.production_strategy import (
                    load_production_strategy,
                )
                _ps = load_production_strategy("config/production_strategy.yaml")
                decision_stack_cfg = _ps.decision_stack
                logger.info(
                    "paper-replay decision_stack config loaded: "
                    "mode=%s, band_base=%s, sidecar.enabled=%s, "
                    "voter_kind=%s",
                    decision_stack_cfg.mode,
                    decision_stack_cfg.partial_rebalance.band_base,
                    decision_stack_cfg.ml_sidecar.enabled,
                    decision_stack_cfg.ml_sidecar.voter_kind)
            except Exception as exc:
                logger.warning(
                    "decision_stack config load FAILED (%s); "
                    "fallback to hardcoded defaults", exc)

        run_replay(
            engine         = engine,
            price_df_1d    = price_df_1d,
            open_df_1d     = open_df_1d,
            price_df_60m   = price_df_60m,
            regime         = regime,
            strategy       = strategy,
            constructor    = constructor,
            diagnostics    = diagnostics,
            spy_benchmark  = spy_close,
            from_date      = args.from_date,
            to_date        = args.to_date,
            decision_stack = args.decision_stack,
            decision_stack_cfg = decision_stack_cfg,
        )

    elif args.mode == "live":
        logger.info("Live 模式：bar-by-bar intraday runtime ...")

        # Load intraday 60m bars for all tradeable symbols. Live path MUST
        # process whichever bars are already closed — never fall back to
        # daily run_day_daily (that would collapse the bar loop).
        intraday_by_sym: dict = {}
        for sym in all_tradeable:
            try:
                df = store.read(sym, "60m")
                if df is not None and not df.empty:
                    intraday_by_sym[sym] = df
            except Exception:
                pass
        if not intraday_by_sym:
            logger.error("无 60m 行情数据；live 模式必须有 intraday bars")
            show_status(engine)
            return

        # Determine the "live day" — latest date present in intraday data
        # that is ≤ today. In production this will be today as of each
        # call. Using the store's latest date lets live run on cached
        # historical EOD data until a real-time feed arrives.
        all_dates = set()
        for df in intraday_by_sym.values():
            all_dates.update(df.index.normalize().unique())
        today = pd.Timestamp.today().normalize()
        live_date_candidates = sorted(d for d in all_dates if d <= today)
        if not live_date_candidates:
            logger.error("无 today≤ 的 intraday bars")
            show_status(engine)
            return
        live_date = live_date_candidates[-1]
        logger.info("Live day resolved to %s", live_date.date())

        # Target weights come from the daily MFS decided on the PRIOR close
        # (no look-ahead: bars closing today use signals generated at the
        # previous daily close).
        signals = strategy.generate(price_df_1d, regime)
        weights = constructor.build(
            raw_signals   = signals,
            price_df      = price_df_1d,
            regime_series = regime,
        )

        # PRD #4 P4.5 audit close (Round 31, 2026-05-20): live parity gap
        # — replay path applies decision_stack overlay (loaded from
        # production_strategy.yaml::decision_stack at line 521-557 above),
        # but live path historically went strategy→constructor→target
        # directly, bypassing the trigger-first overlay. This block mirrors
        # the replay wiring so live === replay === backtest decision chain
        # when --decision-stack trigger-first.
        if args.decision_stack == "trigger-first":
            try:
                from core.config.production_strategy import (
                    load_production_strategy,
                )
                from scripts.run_backtest import (
                    _apply_decision_stack_overlay_from_config,
                )
                _ps_live = load_production_strategy(
                    "config/production_strategy.yaml")
                _ds_live = _ps_live.decision_stack
                logger.info(
                    "paper-live decision_stack overlay: mode=%s, "
                    "band_base=%s, sidecar.enabled=%s, voter_kind=%s",
                    _ds_live.mode,
                    _ds_live.partial_rebalance.band_base,
                    _ds_live.ml_sidecar.enabled,
                    _ds_live.ml_sidecar.voter_kind)
                weights = _apply_decision_stack_overlay_from_config(
                    weights, regime, _ds_live, price_df=price_df_1d,
                )
            except Exception as exc:
                logger.warning(
                    "live decision_stack overlay FAILED (%s); falling "
                    "back to legacy weights — live ≠ replay parity is "
                    "BROKEN this run.", exc)

        # PRD M10: cross-ticker DSL on live weights
        try:
            from core.signals.cross_ticker_wrapper import apply_rules_to_weight_matrix
            ohlcv_frames = {
                sym: pd.DataFrame({"close": price_df_1d[sym]}).dropna()
                for sym in price_df_1d.columns
            }
            weights, ct_stats = apply_rules_to_weight_matrix(
                weights, regime, ohlcv_frames,
            )
            if ct_stats.get("applied"):
                logger.info("Cross-ticker DSL live stats: %s", ct_stats)
        except Exception as exc:
            logger.warning("Cross-ticker DSL wrapper failed (non-fatal): %s", exc)
        daily_idx = price_df_1d.index[price_df_1d.index < live_date]
        if daily_idx.empty or daily_idx[-1] not in weights.index:
            logger.warning("无足够历史信号 (live_date=%s)", live_date.date())
            show_status(engine)
            return
        signal_date = daily_idx[-1]
        day_wts = weights.loc[signal_date]
        target = {s: float(v) for s, v in day_wts.items() if v > 0.001}
        logger.info("目标权重 (源自 %s 收盘信号):\n%s", signal_date.date(),
                    pd.Series(target).sort_values(ascending=False).to_string()
                    if target else "(empty)")

        target, ks_result = apply_kill_switch_to_target(engine, target)
        if ks_result is not None and ks_result.state != "NORMAL":
            logger.info("KS 调整后目标权重:\n%s",
                        pd.Series(target).sort_values(ascending=False).to_string()
                        if target else "(空 — 全部转现金)")

        # Build day_bars dict for live_date (one DataFrame per symbol).
        day_bars = {}
        for sym, df in intraday_by_sym.items():
            mask = df.index.normalize() == live_date
            if mask.any():
                day_bars[sym] = df.loc[mask]

        # run_id scheme: deterministic per (YYYY-MM-DD live) so that a
        # restarted `--mode live` on the same day resumes from checkpoint
        # instead of double-filling.
        run_id = f"live-{live_date.date().isoformat()}"
        logger.info("Live run_id=%s bars available for %d symbols",
                    run_id, len(day_bars))

        # Optional multi-TF timing provider. Loads higher/lower TFs and
        # returns a closure that computes per-bar timed targets.
        timing_provider = None
        if args.use_timing:
            from core.intraday.multi_timescale import (
                load_multi_timescale_bars, make_timing_target_provider,
                TimingThresholds,
            )
            # Timing needs bars across TFs for the full live day.
            mt_bars = load_multi_timescale_bars(
                store, list(target.keys()),
                freqs=["60m", "30m", "15m"],
            )
            # Slice to live_date for the timing provider's context
            # lookups (build_context walks each TF's full history but
            # timing on a single day needs only that day's per-symbol
            # bars across TFs).
            mt_bars_today = {}
            for freq, sym_map in mt_bars.items():
                mt_bars_today[freq] = {}
                for sym, df in sym_map.items():
                    day_mask = df.index.normalize() == live_date
                    if day_mask.any():
                        mt_bars_today[freq][sym] = df.loc[day_mask]
            th = TimingThresholds.from_config(cfg.risk.intraday_timing)
            timing_provider = make_timing_target_provider(
                mt_bars_today, target, thresholds=th,
            )
            logger.info("Timing provider enabled (TFs: %s, threshold=%.2f)",
                        sorted(mt_bars_today.keys()), th.execute_threshold)

        result = _execute_day_bar_by_bar(
            engine, run_id, live_date, day_bars, target,
            timing_provider=timing_provider,
        )
        if result is not None:
            engine.reconcile(live_date, result)

        show_status(engine)


if __name__ == "__main__":
    main()
