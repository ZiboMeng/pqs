"""PRD-X v2 Phase X2 R5e — acceptance smoke experiment.

Smoke (not full regression): verify the R5 RuleBasedDecisionPolicy
end-to-end can drive a monthly-rebalanced long-only portfolio on
the cycle06 panel without crashing, and produce sane NAV / Sharpe
/ MaxDD numbers in the 2018-2024 strict-chronological train window.

Compares to cycle06 baseline NAV (split-only and TR-adjusted) for
sanity orientation, NOT a hard regression — that's the full R5f
phase. This is the build-side smoke that proves the policy wires
up correctly.

Inputs:
  - cycle06 panel via importlib reuse of cycle06_track_a_eval._load_panel
  - factor source: "mom_12_1" (12-month minus 1-month momentum)
  - regime: NEUTRAL (placeholder; real regime detector R5f)
  - vol: 60-day realized stddev of daily log returns
Outputs (JSON):
  - daily NAV path
  - 4 metrics (cum_return, annualized_sharpe, max_drawdown, turnover)
  - 3-way comparison: trigger-policy vs SPY (TR) vs QQQ (TR)
  - per-symbol position-state history sample (first 5 dates)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.regime.regime_detector import RegimeState  # noqa: E402
from core.research.decision.entry_triggers import (  # noqa: E402
    FactorEntryTrigger,
    RegimeEntryTrigger,
)
from core.research.decision.exit_triggers import (  # noqa: E402
    ThesisDecayTrigger,
)
from core.research.decision.rule_based_policy import (  # noqa: E402
    RuleBasedDecisionPolicy,
)

OUT_PATH = (PROJ / "data" / "audit" / "prdx_r5e_acceptance_smoke.json")
LOG_PATH = (PROJ / "data" / "audit" / "prdx_r5e_acceptance_smoke.log")


def _import_cycle06_loader():
    spec = importlib.util.spec_from_file_location(
        "cycle06_track_a_eval",
        PROJ / "dev" / "scripts" / "cycle06" / "cycle06_track_a_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._load_panel


def _normalize_rank(series: pd.Series) -> pd.Series:
    """Cross-sectional rank → [0, 1] normalized score."""
    s = series.copy()
    if s.dropna().empty:
        return pd.Series(np.nan, index=s.index)
    r = s.rank(pct=True, method="average")
    return r


def _realized_vol_60d(close: pd.DataFrame) -> pd.DataFrame:
    """Per-symbol 60-day annualized realized vol from daily returns."""
    ret = close.pct_change()
    vol = ret.rolling(60).std() * np.sqrt(252.0)
    return vol


def _walkforward_run(panel, factors, train_start, train_end,
                      factor_name="mom_12_1",
                      base_position_size=0.05,
                      confirm_min_bars=2,
                      entry_threshold=0.7,
                      exit_threshold=0.3):
    """Run policy day-by-day; rebalance monthly (last bizday of month)."""
    close = panel["close"].sort_index()
    close = close.loc[(close.index >= train_start)
                      & (close.index <= train_end)]
    factor = factors.get(factor_name)
    if factor is None:
        raise SystemExit(f"factor {factor_name!r} not in cycle06 factors; "
                         f"available: {list(factors.keys())[:10]}…")
    factor = factor.loc[(factor.index >= train_start)
                        & (factor.index <= train_end)]
    realized_vol = _realized_vol_60d(close)

    # build policy
    entry_factor = FactorEntryTrigger(entry_threshold=entry_threshold)
    entry_regime = RegimeEntryTrigger()  # default long-friendly
    exit_decay = ThesisDecayTrigger(exit_threshold=exit_threshold)
    policy = RuleBasedDecisionPolicy(
        entry_triggers=[entry_factor],  # OR-first wins
        exit_triggers=[exit_decay],
        mode="active",
        confirm_min_bars=confirm_min_bars,
        base_position_size=base_position_size,
        # R5e ROOT CAUSE: ttl_bars actually impl'd as days in
        # step_day. For monthly cadence (~30d), ttl_bars=10 expires
        # ARMED before second-fire chance. Set 90 = 3 months window
        # so monthly cadence has 2 retries.
        ttl_bars=90,
    )

    # rebalance dates: last business day of each month
    rebal_dates = close.resample("BME").last().index.intersection(
        close.index)

    daily_weights = pd.DataFrame(
        0.0, index=close.index, columns=close.columns)
    current_w: dict = {}
    turnover_sum = 0.0
    n_rebal = 0
    state_log = []

    # R5e ROOT CAUSE fix (R3 self-audit, first smoke n_held=0):
    # The inner loop must be phase-separated, not nested per-symbol.
    # step_day's global TTL loop expires OTHER symbols' ARMED records
    # when called per-symbol mid-iteration. Phase-separated order:
    #   (1) detect_setups for ALL symbols first (build/refresh tracker)
    #   (2) confirm_signals ONCE (promote ARMED→CONFIRMED globally)
    #   (3) step_day per-symbol for exit triggers (TTL is monthly-aware
    #       because rebal cadence > TTL only AFTER confirm has run)
    #   (4) build_target_weights ONCE
    # Plus: TTL converted from days→rebal-ticks-equivalent by setting
    # ttl_bars=90 (≈3 months) so monthly cadence has 2 chances to
    # re-fire before EXPIRED.
    tradeable = [s for s in close.columns if s not in ("SPY", "QQQ")]

    for date in close.index:
        if date in rebal_dates:
            scores = _normalize_rank(factor.loc[date])
            # Phase 1: detect_setups for all symbols (refresh tracker)
            for sym in tradeable:
                fs = scores.get(sym, np.nan)
                if pd.isna(fs):
                    continue
                rv = (realized_vol.loc[date, sym]
                      if sym in realized_vol.columns else 0.15)
                if pd.isna(rv):
                    rv = 0.15
                ctx = {
                    "symbol": sym,
                    "date": date,
                    "factor_score": float(fs),
                    "regime": RegimeState.NEUTRAL,
                    "realized_vol": float(rv),
                }
                policy.detect_setups(state=None, ctx=ctx)
            # Phase 2: confirm_signals once (global)
            policy.confirm_signals(state=None, ctx={"date": date})
            # Phase 3: step_day per-symbol for exit triggers
            for sym in tradeable:
                fs = scores.get(sym, np.nan)
                if pd.isna(fs):
                    continue
                ctx = {
                    "symbol": sym,
                    "date": date,
                    "factor_score": float(fs),
                }
                policy.step_day(state=None, ctx=ctx)
            # Phase 4: build target weights once
            new_w_all = policy.build_target_weights(state=None,
                                                     ctx={"date": date})
            # normalize gross to ≤ 1.0 cap (long-only)
            gross = sum(max(0.0, w) for w in new_w_all.values())
            if gross > 1.0:
                scale = 1.0 / gross
                new_w_all = {s: w * scale for s, w in new_w_all.items()}
            # turnover
            for sym in set(list(new_w_all.keys()) + list(current_w.keys())):
                old = current_w.get(sym, 0.0)
                new = new_w_all.get(sym, 0.0)
                turnover_sum += abs(new - old)
            current_w = dict(new_w_all)
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
        # propagate current weights to daily_weights row
        for sym, w in current_w.items():
            if sym in daily_weights.columns:
                daily_weights.at[date, sym] = w

    # NAV: daily simple returns weighted by previous-day target
    rets = close.pct_change().fillna(0.0)
    # shift weights forward by 1 day (T+1 execution)
    shifted_w = daily_weights.shift(1).fillna(0.0)
    port_ret = (shifted_w * rets[shifted_w.columns]).sum(axis=1)
    # add cash residue (1-gross at risk-free 0 simplification)
    nav = (1.0 + port_ret).cumprod()

    # metrics
    ann_ret = port_ret.mean() * 252.0
    ann_vol = port_ret.std() * np.sqrt(252.0)
    sharpe = (ann_ret / ann_vol) if ann_vol > 0 else 0.0
    cum_ret = nav.iloc[-1] - 1.0
    running_max = nav.cummax()
    dd = (nav - running_max) / running_max
    max_dd = dd.min()

    # benchmarks (already TR-adjusted via cycle06 atr=True flip)
    spy_nav = (close["SPY"] / close["SPY"].iloc[0]) if "SPY" in close else None
    qqq_nav = (close["QQQ"] / close["QQQ"].iloc[0]) if "QQQ" in close else None

    return {
        "factor": factor_name,
        "train_start": str(train_start.date()),
        "train_end": str(train_end.date()),
        "n_rebal_dates": int(n_rebal),
        "turnover_total": round(turnover_sum, 4),
        "turnover_per_rebal_avg": (
            round(turnover_sum / n_rebal, 4) if n_rebal else 0.0),
        "cum_return": round(cum_ret, 4),
        "annualized_sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "benchmark_spy_cum_return": (
            round(spy_nav.iloc[-1] - 1.0, 4) if spy_nav is not None else None),
        "benchmark_qqq_cum_return": (
            round(qqq_nav.iloc[-1] - 1.0, 4) if qqq_nav is not None else None),
        "vs_spy_excess": (
            round(cum_ret - (spy_nav.iloc[-1] - 1.0), 4)
            if spy_nav is not None else None),
        "vs_qqq_excess": (
            round(cum_ret - (qqq_nav.iloc[-1] - 1.0), 4)
            if qqq_nav is not None else None),
        "state_log_first5": state_log,
        "policy_config": {
            "factor_name": factor_name,
            "entry_threshold": entry_threshold,
            "exit_threshold": exit_threshold,
            "confirm_min_bars": confirm_min_bars,
            "base_position_size": base_position_size,
            "ttl_bars": 90,
            "regime_placeholder": "NEUTRAL_constant_R5e_smoke",
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def main() -> int:
    log_lines = []
    def _log(msg):
        line = f"[{datetime.utcnow().isoformat()}Z] {msg}"
        print(line, flush=True)
        log_lines.append(line)

    _log("R5e X2 acceptance smoke — start")
    _log("loading cycle06 panel (TR-adjusted, atr=True post-X0)")
    load_panel = _import_cycle06_loader()
    panel, factors, mask, split_cfg = load_panel()
    _log(f"panel close shape = {panel['close'].shape}, "
         f"factors n = {len(factors)}, factor names sample = "
         f"{list(factors.keys())[:5]}")

    # cycle06 selector partition = train_start/train_end already
    train_start = pd.Timestamp("2018-01-01")
    train_end = pd.Timestamp("2024-12-31")
    _log(f"train window: {train_start.date()} → {train_end.date()} "
         f"(strict-chronological; sealed 2026 永不读)")

    # pick a factor that exists; mom-style preferred
    factor_pref = ["mom_12_1", "mom_6_1", "mom_252", "mom_120",
                   "mom_60", "mom_12m"]
    factor_choice = None
    for f in factor_pref:
        if f in factors:
            factor_choice = f
            break
    if factor_choice is None:
        # fall back: first factor that has 2018+ data
        for fname, fpanel in factors.items():
            if fpanel is not None and not fpanel.empty:
                if fpanel.index.max() >= train_start:
                    factor_choice = fname
                    break
    _log(f"factor choice = {factor_choice!r}")

    res = _walkforward_run(panel, factors, train_start, train_end,
                            factor_name=factor_choice)
    _log(f"result: cum_ret={res['cum_return']}, "
         f"sharpe={res['annualized_sharpe']}, "
         f"max_dd={res['max_drawdown']}, "
         f"n_rebal={res['n_rebal_dates']}, "
         f"turnover_per_rebal={res['turnover_per_rebal_avg']}")
    _log(f"vs SPY (TR): {res['vs_spy_excess']}, "
         f"vs QQQ (TR): {res['vs_qqq_excess']}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(res, indent=2, default=str))
    _log(f"written {OUT_PATH}")
    LOG_PATH.write_text("\n".join(log_lines))
    _log(f"written {LOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
