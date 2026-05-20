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
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from core.config.loader import load_config
from core.config.production_strategy import (
    DEFAULT_CONFIG_PATH as PS_YAML_DEFAULT,
    load_production_strategy,
    build_strategy_from_config,
    ProductionStrategyError,
)
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

# PRD-X v2 P2-1 (2026-05-20): opt-in decision-stack overlay. Default
# legacy path (MultiFactorStrategy → PortfolioConstructor → engine)
# unchanged; --decision-stack trigger-first applies
# PartialRebalancePolicy + MLSidecarPolicy as a thin overlay on the
# strategy's weight panel before engine.run. M11 parity preserved
# (engine.run main path untouched). Status flip in
# production_strategy.yaml to "active" remains directional (user
# explicit-go required) per /loop discipline.
from core.regime.regime_detector import RegimeState as _RegimeState
from core.research.decision import ActionType as _ActionType
from core.research.decision.ml_sidecar import (
    MLSidecarPolicy as _MLSidecarPolicy,
    SignVote as _SignVote,
)
from core.research.decision.ml_voters import (
    no_op_voter as _no_op_voter,
    weak_factor_filter_voter as _weak_factor_filter_voter,
    classifier_voter as _classifier_voter,
    binary_classifier_voter as _binary_classifier_voter,
)
from core.research.decision.no_trade_band import (
    NoTradeBandCalculator as _NoTradeBandCalculator,
)
from core.research.decision.partial_rebalance import (
    PartialRebalancePolicy as _PartialRebalancePolicy,
)


def _resolve_voter_from_config(ml_sidecar_cfg):
    """P1-3-runtime fix (auditor F5+F8 closure): map config
    voter_kind → vote_fn factory. Returns None for disabled.
    Raises ValueError on unknown voter_kind so misconfigured
    yaml fails fast at startup (not silently no-op).
    """
    if not getattr(ml_sidecar_cfg, "enabled", False):
        return None
    kind = getattr(ml_sidecar_cfg, "voter_kind", "no_op")
    params = dict(getattr(ml_sidecar_cfg, "voter_params", {}) or {})
    if kind == "no_op":
        return _no_op_voter()
    if kind == "weak_factor_filter":
        # voter_params may carry entry_threshold override
        return _weak_factor_filter_voter(**params)
    if kind in ("classifier_voter", "binary_classifier_voter"):
        # classifier wiring requires user-supplied artifact path
        # + feature extractor — out of scope for default config
        # consumption; raise with hint so users know what to do.
        raise ValueError(
            f"voter_kind={kind!r} requires explicit classifier "
            f"artifact + feature_extractor wiring; not currently "
            f"supported via yaml-only config. Use programmatic "
            f"injection via run_strategy(..., sidecar_voter=...).")
    raise ValueError(
        f"unknown voter_kind={kind!r}; expected one of "
        f"{{no_op, weak_factor_filter, classifier_voter, "
        f"binary_classifier_voter}}")

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


def build_strategies(cfg, price_df: pd.DataFrame, risk_syms: list, def_syms: list,
                     production_strategy_path: str = PS_YAML_DEFAULT) -> dict:
    """构建默认策略集合 + Mining 晋升策略。

    PRD M1: `multi_factor` baseline 从 config/production_strategy.yaml 读取，
    不再硬编码 factor_weights。运行时加载失败会 WARN 并 fallback 到 null
    baseline（dual_momentum / trend_following / cross_asset_rotation 仍注册）。
    """
    strategies = {
        "dual_momentum":        DualMomentumStrategy(universe=risk_syms),
        "trend_following":      TrendFollowingStrategy(symbols=risk_syms),
        "cross_asset_rotation": CrossAssetRotationStrategy(
            risk_assets=risk_syms, defensive_assets=def_syms
        ),
    }

    # multi_factor baseline — single source of truth from artifact
    try:
        ps_cfg = load_production_strategy(production_strategy_path)
        strategies["multi_factor"] = build_strategy_from_config(
            ps_cfg, cfg.risk, risk_syms
        )
    except ProductionStrategyError as exc:
        logger.warning(
            "Could not load production strategy from %s: %s. "
            "multi_factor baseline will be SKIPPED (other strategies still run).",
            production_strategy_path, exc,
        )

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


def _build_ohlcv_frames(store, symbols: list) -> dict:
    """Load OHLCV DataFrames per symbol for cross-ticker DSL context."""
    frames = {}
    for sym in symbols:
        df = store.read(sym, "1d")
        if df is not None and not df.empty:
            cols = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
            if cols:
                frames[sym] = df[cols]
    return frames


def _apply_decision_stack_overlay(
    weights: pd.DataFrame,
    regime_series: pd.Series,
    band_base: float = 0.02,
    use_sidecar: bool = True,
    sidecar_voter=None,
    partial_full_threshold: float = 0.05,
) -> pd.DataFrame:
    """PRD-X v2 P2-1: opt-in thin overlay on a weight panel.

    Routes the legacy strategy's weight panel through:
      - PartialRebalancePolicy(active, vol/regime no-trade band)
      - MLSidecarPolicy(active, default = no-op CONFIRM voter)
    one rebalance row at a time, then re-emits a filtered panel.

    **R17 (auditor F5/F8 closure)**: parameters can be config-driven
    via `_apply_decision_stack_overlay_from_config()` wrapper which
    reads them from `production_strategy.yaml::decision_stack`.
    Direct callers may still pass explicit kwargs; defaults match
    the prior hardcoded values to preserve R14 acceptance numbers.

    Bit-identical to legacy IF all bands are 0 (degenerate);
    materially different IF NoTradeBandCalculator gates small
    deltas. ML sidecar default voter is NO_VOTE = pass-through
    per §9.0 (no continuous magnitude scaling).

    Skip rebalance days where target ≈ current within bands →
    weights row stays at prior values (HOLD).
    """
    band = _NoTradeBandCalculator(base_band=band_base)
    partial = _PartialRebalancePolicy(
        no_trade_band=band, mode="active",
        partial_full_threshold=partial_full_threshold)
    voter = sidecar_voter or (lambda ctx: _SignVote.NO_VOTE)
    sidecar = _MLSidecarPolicy(
        vote_fn=voter,
        mode=("active" if use_sidecar else "off"))

    out = pd.DataFrame(0.0, index=weights.index, columns=weights.columns)
    current: dict = {}
    # build per-day realized vol on the panel (60d rolling on row-sums
    # — proxy; per-symbol vol context preferred but row-sum is
    # cheap-and-correct-direction for the band scaling)
    weights_nonzero_count = (weights != 0).sum(axis=1)
    last_rebal_signature = None
    for date in weights.index:
        target_row = weights.loc[date]
        # detect rebalance: row differs from last seen by > epsilon
        sig = tuple(round(float(x), 6) for x in target_row.fillna(0).values)
        is_rebal = (last_rebal_signature is None or
                    sig != last_rebal_signature)
        last_rebal_signature = sig
        if not is_rebal:
            # carry current
            for s, w in current.items():
                if s in out.columns:
                    out.at[date, s] = w
            continue
        # target dict for active symbols (positive weight only;
        # long-only invariant)
        target = {s: float(target_row[s])
                  for s in target_row.index
                  if not pd.isna(target_row[s]) and target_row[s] > 0}
        all_syms = set(target.keys()) | set(current.keys())
        target_union = {s: target.get(s, 0.0) for s in all_syms}
        current_union = {s: current.get(s, 0.0) for s in all_syms}
        regime = (regime_series.get(date) if regime_series is not None
                  else None)
        regime_state = _RegimeState.NEUTRAL
        if regime is not None and not pd.isna(regime):
            try:
                regime_state = _RegimeState(regime)
            except ValueError:
                regime_state = _RegimeState.NEUTRAL
        ctx_partial = {"date": date, "regime": regime_state,
                       "realized_vol": 0.15}  # anchor proxy
        actions = partial.compute_actions(
            target_weights=target_union,
            current_weights=current_union,
            ctx=ctx_partial)
        new_w: dict = {}
        for d in actions:
            ml_ctx = {"symbol": d.symbol, "date": date}
            d_final = sidecar.apply(d, ml_ctx)
            if d_final.target_weight > 0:
                new_w[d_final.symbol] = float(d_final.target_weight)
        current = new_w
        for s, w in current.items():
            if s in out.columns:
                out.at[date, s] = w
    return out


def _apply_decision_stack_overlay_from_config(
    weights: pd.DataFrame,
    regime_series: pd.Series,
    ds_cfg,
):
    """R17 (auditor F5/F8 closure): config-driven overlay invocation.

    Reads `decision_stack` section from production_strategy.yaml
    (parsed into DecisionStackConfig) and routes parameters into
    `_apply_decision_stack_overlay()`. Voter selection from
    `ml_sidecar.voter_kind` via `_resolve_voter_from_config()`.

    This is the SoT→runtime bridge. Without it, yaml schema is
    placebo (auditor F5 finding).
    """
    voter = _resolve_voter_from_config(ds_cfg.ml_sidecar)
    use_sidecar = ds_cfg.ml_sidecar.enabled and (voter is not None)
    return _apply_decision_stack_overlay(
        weights=weights,
        regime_series=regime_series,
        band_base=ds_cfg.partial_rebalance.band_base,
        partial_full_threshold=ds_cfg.partial_rebalance.partial_full_threshold,
        use_sidecar=use_sidecar,
        sidecar_voter=voter,
    )


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
    qqq_series:       pd.Series = None,
    open_df:          pd.DataFrame = None,
    ohlcv_frames:     Optional[dict] = None,
    enable_cross_ticker_rules: bool = True,
    decision_stack:   str = "legacy",
    decision_stack_cfg=None,
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

    # PRD M10: cross-ticker DSL applied to production weight matrix
    # (skip if disabled by --no-cross-ticker-rules or if ohlcv_frames
    # not available, e.g. for non-MFS strategies tested without OHLCV).
    cross_ticker_stats = {"applied": False, "reason": "not requested"}
    if enable_cross_ticker_rules and ohlcv_frames is not None:
        from core.signals.cross_ticker_wrapper import apply_rules_to_weight_matrix
        weights, cross_ticker_stats = apply_rules_to_weight_matrix(
            weights, regime_series, ohlcv_frames,
        )

    # PRD-X v2 P2-1 (opt-in, default legacy bit-identical): decision-
    # stack overlay applied AFTER cross-ticker rules and BEFORE
    # engine.run. M11 main path untouched. R17 (auditor F5/F8):
    # parameters now config-driven via decision_stack_cfg (parsed
    # from production_strategy.yaml::decision_stack section).
    if decision_stack == "trigger-first":
        if decision_stack_cfg is None:
            logger.warning(
                "%s: --decision-stack trigger-first BUT no "
                "decision_stack_cfg provided — falling back to "
                "hardcoded defaults (band_base=0.02, sidecar=NO_VOTE). "
                "Auditor F5: prefer wiring decision_stack_cfg from "
                "production_strategy.yaml.", name)
            weights = _apply_decision_stack_overlay(
                weights, regime_series, band_base=0.02,
                use_sidecar=True)
        else:
            logger.info(
                "%s: applying PRD-X trigger-first overlay from config "
                "(band_base=%s, sidecar_enabled=%s, voter_kind=%s)",
                name,
                decision_stack_cfg.partial_rebalance.band_base,
                decision_stack_cfg.ml_sidecar.enabled,
                decision_stack_cfg.ml_sidecar.voter_kind,
            )
            weights = _apply_decision_stack_overlay_from_config(
                weights, regime_series, decision_stack_cfg)
    elif decision_stack != "legacy":
        raise ValueError(
            f"unknown decision_stack={decision_stack!r}; "
            f"expected 'legacy' or 'trigger-first'")

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
        analyzer   = WindowAnalyzer(engine=engine, thresholds=cfg.acceptance)
        wf_windows = analyzer.walk_forward(
            signals_df = weights,
            price_df   = price_df,
            benchmark  = benchmark_series,
        )
        if wf_windows:
            oos_check = WindowAnalyzer.oos_consistency_check(
                wf_windows, thresholds=cfg.acceptance,
            )
            logger.info("%s OOS consistency: %s", name, oos_check)
            acceptance = analyzer.acceptance_check(
                bt_result, benchmark_series,
                qqq_benchmark=qqq_series,
            )
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
    parser.add_argument("--universe", choices=["executable", "expanded_v1", "expanded_v2"],
                        default="executable",
                        help="symbol universe (default executable = the "
                             "config/universe.yaml-derived set, byte-for-byte "
                             "unchanged for D6/P4-A2; expanded_v1 = Phase-4 "
                             "expanded via resolve_universe). P4-A1 "
                             "propagation: backtest on the same universe a "
                             "candidate was mined on.")
    parser.add_argument("--output-dir",      default="reports/backtests")
    parser.add_argument("--production-strategy",
                        default=PS_YAML_DEFAULT,
                        help="Path to production_strategy.yaml (PRD M1 "
                             "single source of truth). Override for research "
                             "/ ad-hoc exploration; do NOT point at uncommitted "
                             "files in shared repos.")
    parser.add_argument("--ignore-alignment-check", action="store_true",
                        help="Skip PRD M3 runtime alignment check. Use only "
                             "for explicit research runs where you know the "
                             "yaml fingerprint will not match.")
    parser.add_argument(
        "--decision-stack",
        choices=["legacy", "trigger-first"],
        default="legacy",
        help=("PRD-X v2 opt-in (default legacy = unchanged from "
              "M11a/M11b baseline). 'trigger-first' applies "
              "PartialRebalancePolicy + MLSidecarPolicy as a thin "
              "overlay on the strategy's weight panel before "
              "engine.run. Status flip in production_strategy.yaml "
              "to 'active' remains a directional decision."),
    )
    parser.add_argument("--no-cross-ticker-rules", action="store_true",
                        help="Disable PRD M10 cross-ticker DSL wrapper. "
                             "Overrides config/cross_ticker_rules.yaml::enabled. "
                             "Use for clean strategy-only backtest.")
    args = parser.parse_args()

    cfg       = load_config(Path(args.config_dir))
    store     = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    artifacts = ArtifactManager(reports_dir=Path(args.output_dir))

    # PRD M3/M13: runtime alignment check (mode from config/system.yaml)
    # Backtest is never blocked by FAIL mode (live_only_fail=True default);
    # research/backtest always use WARN regardless of yaml mode.
    from core.alignment import check_alignment, write_alignment_report, AlignmentMode
    ac = cfg.system.alignment
    # Backtest semantic: always WARN; FAIL applies only to live paper
    mode = AlignmentMode.FAIL if (ac.mode == "fail" and not ac.live_only_fail) else AlignmentMode.WARN
    alignment = check_alignment(
        Path(__file__).resolve().parent.parent,
        mode=mode,
        ignore=args.ignore_alignment_check,
    )
    logger.info(alignment.summary_line())
    try:
        write_alignment_report(alignment)
    except Exception as exc:  # never block startup on artifact write
        logger.warning("Could not write alignment artifact: %s", exc)

    # ── 收集所有 symbol ──────────────────────────────────────────────────────
    uni     = cfg.universe
    if getattr(args, "universe", "executable") == "expanded_v1":
        from core.universe.universe_resolver import resolve_universe
        all_tradeable = list(resolve_universe(
            "expanded_v1", config_dir=Path(args.config_dir)))
    else:
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
    # Backtest is research context — lenient mode is acceptable
    # (long history; occasional gaps diagnostic-logged). Live path
    # uses strict mode in run_paper.py.
    from core.data.vix_loader import load_vix_series

    spy_df    = store.read("SPY", "1d")
    spy_close = spy_df["close"].reindex(price_df.index, method="ffill") if spy_df is not None and not spy_df.empty else price_df.get("SPY")
    qqq_df    = store.read("QQQ", "1d")
    qqq_close = qqq_df["close"].reindex(price_df.index, method="ffill") if qqq_df is not None and not qqq_df.empty else price_df.get("QQQ")

    # ── Regime ────────────────────────────────────────────────────────────────
    logger.info("计算 regime 序列...")
    detector = RegimeDetector(cfg.regime)
    spy_for_regime = price_df.get("SPY", pd.Series(dtype=float))
    vix_for_regime = load_vix_series(
        store, spy_for_regime.index, mode="lenient",
    )
    regime_series  = detector.classify_series(spy_for_regime, vix_for_regime)
    logger.info("Regime 分布:\n%s", regime_series.value_counts().to_string())

    # ── BacktestEngine ────────────────────────────────────────────────────────
    cost_model  = CostModel(cfg.cost_model)
    # Share mode: config is source of truth (P0.5). BacktestEngine's own
    # default was `integer_shares=False` (fractional), which contradicted
    # config/risk.yaml::allow_fractional_shares=false and silently drifted
    # results vs paper.
    integer_shares = not cfg.risk.position_limits.allow_fractional_shares
    engine      = BacktestEngine(
        cost_model      = cost_model,
        initial_capital = cfg.system.account.initial_capital_usd,
        integer_shares  = integer_shares,
    )
    constructor = PortfolioConstructor()

    # ── 策略集合 ──────────────────────────────────────────────────────────────
    strategies = build_strategies(
        cfg, price_df, risk_syms, def_syms,
        production_strategy_path=args.production_strategy,
    )
    if args.strategy:
        strategies = {k: v for k, v in strategies.items() if args.strategy in k}

    # PRD M10: preload OHLCV frames for cross-ticker DSL context (once,
    # outside the per-strategy loop)
    ohlcv_frames = _build_ohlcv_frames(store, all_tradeable)

    # R17 (auditor F5/F8 closure): load production_strategy.yaml
    # decision_stack section for runtime parameter resolution. Failure
    # to load → fall back to hardcoded defaults inside overlay (logged
    # warning, NOT silent — auditor F5 finding was the silent drift).
    decision_stack_cfg = None
    if args.decision_stack == "trigger-first":
        try:
            _ps_for_ds = load_production_strategy(
                args.production_strategy)
            decision_stack_cfg = _ps_for_ds.decision_stack
            logger.info(
                "decision_stack config loaded from %s: mode=%s, "
                "band_base=%s, sidecar.enabled=%s, voter_kind=%s",
                args.production_strategy,
                decision_stack_cfg.mode,
                decision_stack_cfg.partial_rebalance.band_base,
                decision_stack_cfg.ml_sidecar.enabled,
                decision_stack_cfg.ml_sidecar.voter_kind)
        except Exception as exc:
            logger.warning(
                "decision_stack config load FAILED (%s); overlay "
                "will fall back to hardcoded defaults", exc)

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
            qqq_series       = qqq_close,  # closeout 2026-04-20: QQQ gate
            ohlcv_frames     = ohlcv_frames,
            enable_cross_ticker_rules = not args.no_cross_ticker_rules,
            decision_stack   = args.decision_stack,
            decision_stack_cfg = decision_stack_cfg,
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
