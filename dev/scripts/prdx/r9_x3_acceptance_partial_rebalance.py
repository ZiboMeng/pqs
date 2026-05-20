"""PRD-X v2 Phase X3 R9 — acceptance experiment for PartialRebalancePolicy.

Compares mode='off' (legacy bit-identical, X4-precedent) vs
mode='active' (band-gated delta-to-trade) on the same cycle06
panel + same RuleBasedDecisionPolicy entry/exit triggers + same
train window. Verdict: does the band-gated path materially reduce
turnover without sacrificing Sharpe/MaxDD?

AC (PRD §11 X3 + §6.3 4-action discipline):
  - Both paths run on identical input (deterministic)
  - mode='off' result must be ≈ baseline R5e (Round 6)
  - mode='active' must reduce turnover_per_rebal vs mode='off'
  - mode='active' must not catastrophically worsen Sharpe/MaxDD
    (some Sharpe sacrifice expected if band is too tight; need
    to assess actual numbers, NOT a hard gate)

The verdict is RECORDED — non-blanket per
feedback_no_blanket_failure_verdict. Tuning is X3 follow-up; this
is the wiring-correctness + magnitude-of-effect smoke.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.regime.regime_detector import RegimeState  # noqa: E402
from core.research.decision import ActionType  # noqa: E402
from core.research.decision.entry_triggers import (  # noqa: E402
    FactorEntryTrigger,
)
from core.research.decision.exit_triggers import (  # noqa: E402
    ThesisDecayTrigger,
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

OUT_PATH = PROJ / "data" / "audit" / "prdx_r9_x3_acceptance.json"
LOG_PATH = PROJ / "data" / "audit" / "prdx_r9_x3_acceptance.log"


def _import_cycle06_loader():
    spec = importlib.util.spec_from_file_location(
        "cycle06_track_a_eval",
        PROJ / "dev" / "scripts" / "cycle06" / "cycle06_track_a_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._load_panel


def _normalize_rank(series: pd.Series) -> pd.Series:
    s = series.copy()
    if s.dropna().empty:
        return pd.Series(np.nan, index=s.index)
    return s.rank(pct=True, method="average")


def _realized_vol_60d(close: pd.DataFrame) -> pd.DataFrame:
    ret = close.pct_change()
    return ret.rolling(60).std() * np.sqrt(252.0)


def _walkforward_run(
    panel: dict,
    factors: dict,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    partial_rebalance_mode: str,
    factor_name: str = "mom_12_1",
    base_position_size: float = 0.05,
    confirm_min_bars: int = 2,
    entry_threshold: float = 0.7,
    exit_threshold: float = 0.3,
    band_base: float = 0.02,
) -> dict:
    """Run walk-forward with optional band-gated partial rebalance.

    partial_rebalance_mode: 'off' = legacy bit-identical (direct
    target assignment, R5e v2 path). 'active' = band-gated
    delta-to-trade via PartialRebalancePolicy.
    """
    close = panel["close"].sort_index()
    close = close.loc[(close.index >= train_start)
                      & (close.index <= train_end)]
    factor = factors[factor_name]
    factor = factor.loc[(factor.index >= train_start)
                        & (factor.index <= train_end)]
    realized_vol = _realized_vol_60d(close)

    entry_t = FactorEntryTrigger(entry_threshold=entry_threshold)
    exit_t = ThesisDecayTrigger(exit_threshold=exit_threshold)
    policy = RuleBasedDecisionPolicy(
        entry_triggers=[entry_t], exit_triggers=[exit_t],
        mode="active", confirm_min_bars=confirm_min_bars,
        base_position_size=base_position_size, ttl_bars=90,
    )
    band = NoTradeBandCalculator(base_band=band_base)
    partial = PartialRebalancePolicy(
        no_trade_band=band, mode=partial_rebalance_mode,
        partial_full_threshold=0.05)

    rebal_dates = close.resample("BME").last().index.intersection(
        close.index)
    daily_weights = pd.DataFrame(
        0.0, index=close.index, columns=close.columns)
    current_w: Dict[str, float] = {}
    turnover_sum = 0.0
    n_rebal = 0
    n_hold = 0
    n_no_trade = 0
    n_enter_full = 0
    n_enter_partial = 0
    n_add = 0
    n_trim = 0
    n_exit = 0
    state_log = []

    tradeable = [s for s in close.columns if s not in ("SPY", "QQQ")]

    for date in close.index:
        if date not in rebal_dates:
            for sym, w in current_w.items():
                if sym in daily_weights.columns:
                    daily_weights.at[date, sym] = w
            continue
        scores = _normalize_rank(factor.loc[date])
        # Phase 1: detect for ALL symbols
        for sym in tradeable:
            fs = scores.get(sym, np.nan)
            if pd.isna(fs):
                continue
            rv = (realized_vol.loc[date, sym]
                  if sym in realized_vol.columns else 0.15)
            if pd.isna(rv):
                rv = 0.15
            ctx_sym = {
                "symbol": sym, "date": date,
                "factor_score": float(fs),
                "regime": RegimeState.NEUTRAL,
                "realized_vol": float(rv),
            }
            policy.detect_setups(state=None, ctx=ctx_sym)
        # Phase 2: confirm globally
        policy.confirm_signals(state=None, ctx={"date": date})
        # Phase 3: step_day per-symbol (exit triggers)
        for sym in tradeable:
            fs = scores.get(sym, np.nan)
            if pd.isna(fs):
                continue
            policy.step_day(state=None, ctx={
                "symbol": sym, "date": date,
                "factor_score": float(fs)})
        # Phase 4: build target weights once
        target_w_raw = policy.build_target_weights(
            state=None, ctx={"date": date})
        # normalize gross to ≤ 1.0 (long-only cap)
        gross = sum(max(0.0, w) for w in target_w_raw.values())
        if gross > 1.0:
            scale = 1.0 / gross
            target_w_raw = {s: w * scale for s, w in target_w_raw.items()}
        # Phase 5: partial rebalance OR pass-through
        #   PartialRebalancePolicy needs symbols in BOTH dicts;
        #   union them so EXIT can be triggered for dropped symbols
        all_syms = set(target_w_raw.keys()) | set(current_w.keys())
        target_union = {s: float(target_w_raw.get(s, 0.0))
                         for s in all_syms}
        current_union = {s: float(current_w.get(s, 0.0))
                          for s in all_syms}
        # Use SPY's realized vol as a fleet-level proxy for ctx
        spy_vol = (float(realized_vol.loc[date, "SPY"])
                   if "SPY" in realized_vol.columns
                       and not pd.isna(realized_vol.loc[date, "SPY"])
                   else 0.15)
        rebal_ctx = {
            "date": date,
            "regime": RegimeState.NEUTRAL,
            "realized_vol": spy_vol,
        }
        actions = partial.compute_actions(
            target_weights=target_union,
            current_weights=current_union,
            ctx=rebal_ctx)
        # Materialize actions into new_w
        new_w: Dict[str, float] = {}
        for d in actions:
            new_w[d.symbol] = float(d.target_weight)
            # action counters
            if d.action == ActionType.HOLD:
                n_hold += 1
            elif d.action == ActionType.NO_TRADE:
                n_no_trade += 1
            elif d.action == ActionType.ENTER_FULL:
                n_enter_full += 1
            elif d.action == ActionType.ENTER_PARTIAL:
                n_enter_partial += 1
            elif d.action == ActionType.ADD:
                n_add += 1
            elif d.action == ActionType.TRIM:
                n_trim += 1
            elif d.action == ActionType.EXIT:
                n_exit += 1
        # turnover
        for sym in set(list(new_w.keys()) + list(current_w.keys())):
            old = current_w.get(sym, 0.0)
            new = new_w.get(sym, 0.0)
            turnover_sum += abs(new - old)
        current_w = {s: w for s, w in new_w.items() if w > 0}
        n_rebal += 1
        if len(state_log) < 5:
            state_log.append({
                "date": str(date.date()),
                "n_held": sum(1 for w in current_w.values() if w > 0),
                "gross": round(sum(current_w.values()), 4),
                "top": [(s, round(w, 3))
                         for s, w in sorted(current_w.items(),
                                            key=lambda kv: -kv[1])
                         if w > 0][:5],
            })
        for sym, w in current_w.items():
            if sym in daily_weights.columns:
                daily_weights.at[date, sym] = w

    # NAV (T+1 shifted weights × close-to-close returns)
    rets = close.pct_change().fillna(0.0)
    shifted_w = daily_weights.shift(1).fillna(0.0)
    port_ret = (shifted_w * rets[shifted_w.columns]).sum(axis=1)
    nav = (1.0 + port_ret).cumprod()
    ann_ret = port_ret.mean() * 252.0
    ann_vol = port_ret.std() * np.sqrt(252.0)
    sharpe = (ann_ret / ann_vol) if ann_vol > 0 else 0.0
    cum_ret = nav.iloc[-1] - 1.0
    dd = (nav - nav.cummax()) / nav.cummax()
    max_dd = dd.min()
    spy_nav = (close["SPY"] / close["SPY"].iloc[0]) if "SPY" in close else None
    qqq_nav = (close["QQQ"] / close["QQQ"].iloc[0]) if "QQQ" in close else None
    return {
        "mode": partial_rebalance_mode,
        "n_rebal": int(n_rebal),
        "turnover_total": round(turnover_sum, 4),
        "turnover_per_rebal": (
            round(turnover_sum / n_rebal, 4) if n_rebal else 0.0),
        "cum_return": round(cum_ret, 4),
        "annualized_sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "vs_spy_excess": (
            round(cum_ret - (spy_nav.iloc[-1] - 1.0), 4)
            if spy_nav is not None else None),
        "vs_qqq_excess": (
            round(cum_ret - (qqq_nav.iloc[-1] - 1.0), 4)
            if qqq_nav is not None else None),
        "action_counts": {
            "ENTER_FULL": n_enter_full,
            "ENTER_PARTIAL": n_enter_partial,
            "ADD": n_add,
            "HOLD": n_hold,
            "TRIM": n_trim,
            "EXIT": n_exit,
            "NO_TRADE": n_no_trade,
        },
        "state_log_first5": state_log,
        "policy_config": {
            "factor_name": factor_name,
            "entry_threshold": entry_threshold,
            "exit_threshold": exit_threshold,
            "confirm_min_bars": confirm_min_bars,
            "base_position_size": base_position_size,
            "ttl_bars": 90,
            "band_base": band_base,
            "partial_full_threshold": 0.05,
            "regime_placeholder": "NEUTRAL_constant_R9",
        },
    }


def main() -> int:
    log_lines = []
    def _log(msg):
        line = f"[{datetime.utcnow().isoformat()}Z] {msg}"
        print(line, flush=True)
        log_lines.append(line)

    _log("R9 X3 acceptance — start (off vs active comparison)")
    load_panel = _import_cycle06_loader()
    panel, factors, mask, split_cfg = load_panel()
    _log(f"panel close {panel['close'].shape} factors {len(factors)}")

    train_start = pd.Timestamp("2018-01-01")
    train_end = pd.Timestamp("2024-12-31")
    _log(f"train window {train_start.date()} → {train_end.date()} "
         f"(strict-chronological; sealed 2026 永不读)")

    _log("Running mode='off' (legacy bit-identical baseline)...")
    res_off = _walkforward_run(
        panel, factors, train_start, train_end,
        partial_rebalance_mode="off")
    _log(f"OFF: cum_ret={res_off['cum_return']}, "
         f"Sharpe={res_off['annualized_sharpe']}, "
         f"MaxDD={res_off['max_drawdown']}, "
         f"turnover/rebal={res_off['turnover_per_rebal']}")

    _log("Running mode='active' (band-gated partial rebalance)...")
    res_active = _walkforward_run(
        panel, factors, train_start, train_end,
        partial_rebalance_mode="active")
    _log(f"ACTIVE: cum_ret={res_active['cum_return']}, "
         f"Sharpe={res_active['annualized_sharpe']}, "
         f"MaxDD={res_active['max_drawdown']}, "
         f"turnover/rebal={res_active['turnover_per_rebal']}")

    # Diff
    turnover_reduction = (
        (res_off["turnover_per_rebal"] - res_active["turnover_per_rebal"])
        / res_off["turnover_per_rebal"]
        if res_off["turnover_per_rebal"] > 0 else 0.0
    )
    sharpe_diff = (res_active["annualized_sharpe"]
                   - res_off["annualized_sharpe"])
    maxdd_diff = (res_active["max_drawdown"]
                  - res_off["max_drawdown"])
    _log(f"DIFF: turnover_reduction={turnover_reduction:.1%}, "
         f"sharpe_diff={sharpe_diff:+.4f}, "
         f"maxdd_diff={maxdd_diff:+.4f}")

    summary = {
        "off_mode": res_off,
        "active_mode": res_active,
        "diff": {
            "turnover_reduction_pct": round(turnover_reduction * 100, 2),
            "sharpe_diff": round(sharpe_diff, 4),
            "maxdd_diff": round(maxdd_diff, 4),
            "cum_ret_diff": round(
                res_active["cum_return"] - res_off["cum_return"], 4),
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2, default=str))
    _log(f"written {OUT_PATH}")
    LOG_PATH.write_text("\n".join(log_lines))
    _log(f"written {LOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
