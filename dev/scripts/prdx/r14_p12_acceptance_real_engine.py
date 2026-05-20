"""PRD-X v2 P1-2 acceptance experiment — real BacktestEngine main link.

Post-auditor F2 fix: R9/R10 used hand-rolled `shift(1) +
(weights × pct_change).sum(axis=1)` for NAV, bypassing
`BacktestEngine.run()` and its T+1 open-execution semantic /
cost model / order-generation kernel.

This R14 driver routes the SAME (RuleBased + Partial + Sidecar)
decision stack output through the real `BacktestEngine.run(
signals_df=daily_weights, price_df=close, open_df=open)` path,
then compares NAV to R10 hand-rolled NAV to surface the
fill-timing / cost-model / T+1-open-execution delta.

AC (P1-2 verdict):
  - End-to-end runs against real kernel without error
  - NAV path / cum_ret / Sharpe / MaxDD reported
  - Delta vs R10 hand-rolled NAV recorded
  - Verdict non-blanket: if real-engine NAV differs materially
    from hand-rolled, root-cause classified (cost / fill-timing /
    open-vs-close MTM / etc), NOT a blanket "X3/X5 broken"
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.backtest.backtest_engine import BacktestEngine  # noqa: E402
from core.config.schemas.cost_model import (  # noqa: E402
    CostModelConfig, CostTierConfig,
)
from core.execution.cost_model import CostModel  # noqa: E402
from core.regime.regime_detector import RegimeState  # noqa: E402
from core.research.decision import ActionType  # noqa: E402
from core.research.decision.entry_triggers import (  # noqa: E402
    FactorEntryTrigger,
)
from core.research.decision.exit_triggers import (  # noqa: E402
    ThesisDecayTrigger,
)
from core.research.decision.ml_sidecar import (  # noqa: E402
    MLSidecarPolicy, SignVote,
)
from core.research.decision.no_trade_band import (  # noqa: E402
    NoTradeBandCalculator,
)
from core.research.decision.partial_rebalance import (  # noqa: E402
    PartialRebalancePolicy,
)
from core.research.decision.rule_based_policy import (  # noqa: E402
    RuleBasedDecisionPolicy,
)

OUT_PATH = PROJ / "data" / "audit" / "prdx_r14_p12_acceptance_real_engine.json"
LOG_PATH = PROJ / "data" / "audit" / "prdx_r14_p12_acceptance_real_engine.log"


def _import_cycle06_loader():
    spec = importlib.util.spec_from_file_location(
        "cycle06_track_a_eval",
        PROJ / "dev" / "scripts" / "cycle06" / "cycle06_track_a_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._load_panel


def _normalize_rank(series):
    s = series.copy()
    if s.dropna().empty:
        return pd.Series(np.nan, index=s.index)
    return s.rank(pct=True, method="average")


def _realized_vol_60d(close):
    return close.pct_change().rolling(60).std() * np.sqrt(252.0)


def _weak_factor_filter_voter(entry_threshold=0.7):
    midpoint = (entry_threshold + 1.0) / 2.0
    def voter(ctx):
        fs = ctx.get("factor_score")
        if fs is None:
            return SignVote.NO_VOTE
        if entry_threshold < float(fs) < midpoint:
            return SignVote.VETO
        return SignVote.NO_VOTE
    return voter


def _zero_cost_model():
    return CostModel(CostModelConfig(tiers={
        "default": CostTierConfig(
            symbols=[], commission_bps=0.0,
            slippage_interday_bps=0.0, slippage_intraday_bps=0.0)
    }))


def _build_weight_panel(
    panel, train_start, train_end,
    factor_name="mom_12_1",
    use_sidecar=True,
):
    """Run the (RuleBased + Partial + Sidecar) decision stack to
    produce a daily_weights panel — same as R10 path."""
    close = panel["close"].sort_index()
    close = close.loc[(close.index >= train_start)
                      & (close.index <= train_end)]
    panel_dates = close.index
    factor = panel.get(factor_name)
    # cycle06 panel has factors in a separate dict; load it
    return panel_dates, close


def _walkforward_run(
    panel, factors, train_start, train_end, use_sidecar=True,
    factor_name="mom_12_1",
    base_position_size=0.05, confirm_min_bars=2,
    entry_threshold=0.7, exit_threshold=0.3, band_base=0.02,
):
    close = panel["close"].sort_index()
    close = close.loc[(close.index >= train_start)
                      & (close.index <= train_end)]
    open_df = panel["open"].sort_index() if "open" in panel else None
    if open_df is not None:
        open_df = open_df.loc[(open_df.index >= train_start)
                              & (open_df.index <= train_end)]
    factor = factors[factor_name].loc[
        (factors[factor_name].index >= train_start)
        & (factors[factor_name].index <= train_end)]
    realized_vol = _realized_vol_60d(close)

    policy = RuleBasedDecisionPolicy(
        entry_triggers=[FactorEntryTrigger(entry_threshold=entry_threshold)],
        exit_triggers=[ThesisDecayTrigger(exit_threshold=exit_threshold)],
        mode="active", confirm_min_bars=confirm_min_bars,
        base_position_size=base_position_size, ttl_bars=3)
    partial = PartialRebalancePolicy(
        no_trade_band=NoTradeBandCalculator(base_band=band_base),
        mode="active", partial_full_threshold=0.05)
    sidecar = MLSidecarPolicy(
        vote_fn=(_weak_factor_filter_voter() if use_sidecar
                 else (lambda ctx: SignVote.NO_VOTE)),
        mode=("active" if use_sidecar else "off"))

    rebal_dates = close.resample("BME").last().index.intersection(close.index)
    daily_weights = pd.DataFrame(
        0.0, index=close.index, columns=close.columns)
    current_w: Dict[str, float] = {}
    tradeable = [s for s in close.columns if s not in ("SPY", "QQQ")]

    for date in close.index:
        if date not in rebal_dates:
            for sym, w in current_w.items():
                if sym in daily_weights.columns:
                    daily_weights.at[date, sym] = w
            continue
        if date not in factor.index:
            continue
        scores = _normalize_rank(factor.loc[date])
        # Phase 1: detect for all symbols
        for sym in tradeable:
            fs = scores.get(sym, np.nan)
            if pd.isna(fs):
                continue
            rv = (realized_vol.loc[date, sym]
                  if sym in realized_vol.columns else 0.15)
            if pd.isna(rv):
                rv = 0.15
            policy.detect_setups(state=None, ctx={
                "symbol": sym, "date": date,
                "factor_score": float(fs),
                "regime": RegimeState.NEUTRAL,
                "realized_vol": float(rv)})
        # Phase 2: confirm once
        policy.confirm_signals(state=None, ctx={"date": date})
        # Phase 3: step_day per-symbol (bar_counter advances once
        # on first call per new date — P1-3 fix)
        for sym in tradeable:
            fs = scores.get(sym, np.nan)
            if pd.isna(fs):
                continue
            policy.step_day(state=None, ctx={
                "symbol": sym, "date": date,
                "factor_score": float(fs)})
        # Phase 4: build target weights
        target_w_raw = policy.build_target_weights(
            state=None, ctx={"date": date})
        gross = sum(max(0.0, w) for w in target_w_raw.values())
        if gross > 1.0:
            scale = 1.0 / gross
            target_w_raw = {s: w * scale for s, w in target_w_raw.items()}
        # Phase 5: partial rebalance
        all_syms = set(target_w_raw.keys()) | set(current_w.keys())
        target_union = {s: float(target_w_raw.get(s, 0.0))
                         for s in all_syms}
        current_union = {s: float(current_w.get(s, 0.0))
                          for s in all_syms}
        spy_vol = (float(realized_vol.loc[date, "SPY"])
                   if "SPY" in realized_vol.columns
                       and not pd.isna(realized_vol.loc[date, "SPY"])
                   else 0.15)
        actions = partial.compute_actions(
            target_weights=target_union,
            current_weights=current_union,
            ctx={"date": date, "regime": RegimeState.NEUTRAL,
                 "realized_vol": spy_vol})
        # Phase 6: ML sidecar
        new_w: Dict[str, float] = {}
        for d in actions:
            fs = scores.get(d.symbol, np.nan)
            ml_ctx = {"symbol": d.symbol, "date": date,
                      "factor_score": float(fs)
                                       if not pd.isna(fs) else None}
            d_final = sidecar.apply(d, ml_ctx)
            new_w[d_final.symbol] = float(d_final.target_weight)
        current_w = {s: w for s, w in new_w.items() if w > 0}
        for sym, w in current_w.items():
            if sym in daily_weights.columns:
                daily_weights.at[date, sym] = w

    return daily_weights, close, open_df


def _hand_rolled_nav(daily_weights, close):
    """R10 hand-rolled NAV path: shift(1) × close pct_change."""
    rets = close.pct_change().fillna(0.0)
    shifted_w = daily_weights.shift(1).fillna(0.0)
    port_ret = (shifted_w * rets[shifted_w.columns]).sum(axis=1)
    nav = (1.0 + port_ret).cumprod()
    ann_ret = port_ret.mean() * 252.0
    ann_vol = port_ret.std() * np.sqrt(252.0)
    sharpe = (ann_ret / ann_vol) if ann_vol > 0 else 0.0
    cum_ret = nav.iloc[-1] - 1.0
    dd = (nav - nav.cummax()) / nav.cummax()
    return {
        "method": "hand_rolled_shift1_close_pct",
        "cum_return": float(round(cum_ret, 4)),
        "annualized_sharpe": float(round(sharpe, 4)),
        "max_drawdown": float(round(dd.min(), 4)),
        "final_nav": float(round(nav.iloc[-1], 4)),
    }


def _real_engine_nav(daily_weights, close, open_df):
    """P1-2: route through BacktestEngine.run with T+1 open exec."""
    engine = BacktestEngine(
        cost_model=_zero_cost_model(),
        initial_capital=100_000.0,
        min_trade_usd=100.0,
        rebalance_threshold=0.02,  # standard 2%
        integer_shares=False,
        execution_freq="interday",
    )
    result = engine.run(
        signals_df=daily_weights,
        price_df=close,
        open_df=open_df,
    )
    # extract NAV-like metrics from BacktestResult
    equity = result.equity_curve
    if equity.empty:
        return {"method": "BacktestEngine.run", "error": "empty equity"}
    cum_ret = (equity.iloc[-1] / equity.iloc[0]) - 1.0
    daily_ret = equity.pct_change().fillna(0.0)
    ann_ret = daily_ret.mean() * 252.0
    ann_vol = daily_ret.std() * np.sqrt(252.0)
    sharpe = (ann_ret / ann_vol) if ann_vol > 0 else 0.0
    dd = (equity - equity.cummax()) / equity.cummax()
    return {
        "method": "BacktestEngine.run_T+1_open_exec_zero_cost",
        "cum_return": float(round(cum_ret, 4)),
        "annualized_sharpe": float(round(sharpe, 4)),
        "max_drawdown": float(round(dd.min(), 4)),
        "final_equity_usd": float(round(equity.iloc[-1], 2)),
        "n_bars": int(len(equity)),
    }


def main():
    log_lines = []
    def _log(msg):
        line = f"[{datetime.utcnow().isoformat()}Z] {msg}"
        print(line, flush=True)
        log_lines.append(line)

    _log("R14 P1-2 acceptance — real BacktestEngine main link")
    load_panel = _import_cycle06_loader()
    panel, factors, mask, split_cfg = load_panel()
    _log(f"panel close {panel['close'].shape} open {panel['open'].shape}")
    train_start = pd.Timestamp("2018-01-01")
    train_end = pd.Timestamp("2024-12-31")
    _log(f"train {train_start.date()} → {train_end.date()}")

    _log("Building decision-stack weight panel (RuleBased + Partial + Sidecar)...")
    daily_weights, close, open_df = _walkforward_run(
        panel, factors, train_start, train_end, use_sidecar=True)
    _log(f"daily_weights shape {daily_weights.shape}; non-zero rows "
         f"{(daily_weights.sum(axis=1) > 0).sum()}")

    _log("Path A: hand-rolled NAV (R10 baseline)")
    res_handrolled = _hand_rolled_nav(daily_weights, close)
    _log(f"  hand-rolled: cum={res_handrolled['cum_return']}, "
         f"Sharpe={res_handrolled['annualized_sharpe']}, "
         f"MaxDD={res_handrolled['max_drawdown']}")

    _log("Path B: BacktestEngine.run real main link (P1-2)")
    res_engine = _real_engine_nav(daily_weights, close, open_df)
    _log(f"  engine: cum={res_engine.get('cum_return')}, "
         f"Sharpe={res_engine.get('annualized_sharpe')}, "
         f"MaxDD={res_engine.get('max_drawdown')}")

    diff = {
        "cum_ret_diff_engine_minus_handrolled": (
            round(res_engine.get("cum_return", 0)
                  - res_handrolled.get("cum_return", 0), 4)
            if "error" not in res_engine else None),
        "sharpe_diff": (
            round(res_engine.get("annualized_sharpe", 0)
                  - res_handrolled.get("annualized_sharpe", 0), 4)
            if "error" not in res_engine else None),
        "maxdd_diff": (
            round(res_engine.get("max_drawdown", 0)
                  - res_handrolled.get("max_drawdown", 0), 4)
            if "error" not in res_engine else None),
    }
    _log(f"DIFF (engine - handrolled): {diff}")

    summary = {
        "hand_rolled": res_handrolled,
        "real_engine": res_engine,
        "diff_engine_minus_handrolled": diff,
        "context": {
            "train_window": [str(train_start.date()), str(train_end.date())],
            "decision_stack": "RuleBasedDecisionPolicy + "
                              "PartialRebalancePolicy(active, band=0.02) + "
                              "MLSidecarPolicy(weak_factor_filter)",
            "cost_model": "zero (isolating fill-timing effect)",
            "execution_freq": "interday (M11a/M11b bit-for-bit)",
            "rebalance_threshold": 0.02,
        },
        "verdict_template": "non-blanket: if cum_ret_diff materially "
                            "negative → cost model / fill-timing /"
                            "rebalance_threshold filtering; if "
                            "positive → hand-rolled was overestimating; "
                            "in both cases record-and-route per "
                            "feedback_no_blanket_failure_verdict",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2, default=str))
    LOG_PATH.write_text("\n".join(log_lines))
    _log(f"written {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
