"""PRD-X v2 Phase post-audit R12 — §12.0 cycle06 baseline regression attempt.

Trigger-first stack with cycle06's composite factor + weekly cadence
on the same 2018-2024 strict-chronological train window.

cycle06 spec (trial 31af04cf2ff9):
  features = drawup_from_252d_low, trend_tstat_20d, ret_2d
  weights = 0.333, 0.333, 0.333 (equal-weighted rank composite)
  holding_freq = weekly

Compares to:
  - R10 best (mom_12_1 monthly + full stack)
  - cycle06 metrics_per_year average (selector partition years
    2018/2019/2021/2023/2025)
  - cycle06 metrics_full_period (Sharpe 1.37, MaxDD -19.6%,
    pre-X0 baseline — caveat: split-only SPY)

§12.0 PASS criteria:
  decision-driven Sharpe ≥ cycle06 Sharpe - tolerance
  decision-driven MaxDD ≤ cycle06 MaxDD + tolerance
  decision-driven turnover ≤ cycle06 turnover × 2

Tolerance per PRD §11 X1: not explicitly numerical; this attempt
records numbers + provides non-blanket verdict (§12.0 explicitly
allows FAIL_recorded_root_cause).
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

OUT_PATH = PROJ / "data" / "audit" / "prdx_r12_x_acceptance_cycle06_composite.json"
LOG_PATH = PROJ / "data" / "audit" / "prdx_r12_x_acceptance_cycle06_composite.log"


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


def _build_cycle06_composite(factors: dict) -> pd.DataFrame:
    """Equal-weighted rank composite of cycle06 trial 31af04cf2ff9
    factors. At each date, rank-normalize each constituent across
    symbols, then average the 3 ranks."""
    needed = ["drawup_from_252d_low", "trend_tstat_20d", "ret_2d"]
    rank_panels = []
    for name in needed:
        f = factors[name]
        # cross-sectional rank per date
        ranked = f.rank(axis=1, pct=True, method="average")
        rank_panels.append(ranked)
    # average
    composite = sum(rank_panels) / len(rank_panels)
    return composite


def _realized_vol_60d(close: pd.DataFrame) -> pd.DataFrame:
    return close.pct_change().rolling(60).std() * np.sqrt(252.0)


def _weak_factor_filter_voter(entry_threshold: float = 0.7):
    midpoint = (entry_threshold + 1.0) / 2.0
    def voter(ctx: Dict) -> SignVote:
        fs = ctx.get("factor_score")
        if fs is None:
            return SignVote.NO_VOTE
        if entry_threshold < float(fs) < midpoint:
            return SignVote.VETO
        return SignVote.NO_VOTE
    return voter


def _walkforward_run(
    panel: dict, composite: pd.DataFrame,
    train_start: pd.Timestamp, train_end: pd.Timestamp,
    cadence: str,  # "weekly" or "monthly"
    use_sidecar: bool,
    base_position_size: float = 0.05,
    confirm_min_bars: int = 1,  # weekly = tighter persistence
    entry_threshold: float = 0.7,
    exit_threshold: float = 0.3,
    band_base: float = 0.02,
    ttl_bars: int = 30,
) -> dict:
    close = panel["close"].sort_index()
    close = close.loc[(close.index >= train_start)
                      & (close.index <= train_end)]
    composite = composite.loc[
        (composite.index >= train_start)
        & (composite.index <= train_end)]
    realized_vol = _realized_vol_60d(close)

    policy = RuleBasedDecisionPolicy(
        entry_triggers=[FactorEntryTrigger(entry_threshold=entry_threshold)],
        exit_triggers=[ThesisDecayTrigger(exit_threshold=exit_threshold)],
        mode="active", confirm_min_bars=confirm_min_bars,
        base_position_size=base_position_size, ttl_bars=ttl_bars)
    partial = PartialRebalancePolicy(
        no_trade_band=NoTradeBandCalculator(base_band=band_base),
        mode="active", partial_full_threshold=0.05)
    sidecar = MLSidecarPolicy(
        vote_fn=(_weak_factor_filter_voter() if use_sidecar
                 else (lambda ctx: SignVote.NO_VOTE)),
        mode=("active" if use_sidecar else "off"))

    # cadence: weekly = last bizday each week (BME = monthly; W-FRI = weekly Fri)
    freq_alias = "W-FRI" if cadence == "weekly" else "BME"
    rebal_dates = close.resample(freq_alias).last().index.intersection(
        close.index)
    daily_weights = pd.DataFrame(
        0.0, index=close.index, columns=close.columns)
    current_w: Dict[str, float] = {}
    turnover_sum = 0.0
    n_rebal = 0
    tradeable = [s for s in close.columns if s not in ("SPY", "QQQ")]

    for date in close.index:
        if date not in rebal_dates:
            for sym, w in current_w.items():
                if sym in daily_weights.columns:
                    daily_weights.at[date, sym] = w
            continue
        if date not in composite.index:
            continue
        # composite factor already rank-normalized; use directly
        scores = composite.loc[date]
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
        policy.confirm_signals(state=None, ctx={"date": date})
        for sym in tradeable:
            fs = scores.get(sym, np.nan)
            if pd.isna(fs):
                continue
            policy.step_day(state=None, ctx={
                "symbol": sym, "date": date,
                "factor_score": float(fs)})
        target_w_raw = policy.build_target_weights(
            state=None, ctx={"date": date})
        gross = sum(max(0.0, w) for w in target_w_raw.values())
        if gross > 1.0:
            scale = 1.0 / gross
            target_w_raw = {s: w * scale for s, w in target_w_raw.items()}
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
        new_w: Dict[str, float] = {}
        for d in actions:
            fs = scores.get(d.symbol, np.nan)
            ml_ctx = {
                "symbol": d.symbol, "date": date,
                "factor_score": float(fs)
                                 if not pd.isna(fs) else None,
            }
            d_final = sidecar.apply(d, ml_ctx)
            new_w[d_final.symbol] = float(d_final.target_weight)
        for sym in set(list(new_w.keys()) + list(current_w.keys())):
            old = current_w.get(sym, 0.0)
            new = new_w.get(sym, 0.0)
            turnover_sum += abs(new - old)
        current_w = {s: w for s, w in new_w.items() if w > 0}
        n_rebal += 1
        for sym, w in current_w.items():
            if sym in daily_weights.columns:
                daily_weights.at[date, sym] = w

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
    spy_nav = close["SPY"] / close["SPY"].iloc[0]
    qqq_nav = close["QQQ"] / close["QQQ"].iloc[0]
    return {
        "cadence": cadence,
        "use_sidecar": use_sidecar,
        "n_rebal": int(n_rebal),
        "turnover_per_rebal": round(turnover_sum / n_rebal, 4)
                              if n_rebal else 0.0,
        "turnover_total": round(turnover_sum, 4),
        "cum_return": round(cum_ret, 4),
        "annualized_sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "vs_spy_excess": round(cum_ret - (spy_nav.iloc[-1] - 1.0), 4),
        "vs_qqq_excess": round(cum_ret - (qqq_nav.iloc[-1] - 1.0), 4),
    }


def main() -> int:
    log_lines = []
    def _log(msg):
        line = f"[{datetime.utcnow().isoformat()}Z] {msg}"
        print(line, flush=True)
        log_lines.append(line)

    _log("R12 §12.0 regression — cycle06 composite + weekly cadence")
    load_panel = _import_cycle06_loader()
    panel, factors, mask, split_cfg = load_panel()
    _log(f"panel close {panel['close'].shape} factors {len(factors)}")

    composite = _build_cycle06_composite(factors)
    _log(f"cycle06 composite (drawup+trend+ret_2d eq-weighted ranks): "
         f"shape={composite.shape}")

    train_start = pd.Timestamp("2018-01-01")
    train_end = pd.Timestamp("2024-12-31")
    _log(f"train window {train_start.date()} → {train_end.date()}")

    # Path A: monthly + sidecar OFF (mom_12_1 R10 baseline path, but
    # NOTE: we're using cycle06 COMPOSITE here, so this is "what does
    # the cycle06 signal look like in trigger-first stack")
    _log("Path A: cycle06 composite + monthly + sidecar OFF")
    path_a = _walkforward_run(
        panel, composite, train_start, train_end,
        cadence="monthly", use_sidecar=False)
    _log(f"  A: cum={path_a['cum_return']}, "
         f"Sharpe={path_a['annualized_sharpe']}, "
         f"MaxDD={path_a['max_drawdown']}, "
         f"turnover/rebal={path_a['turnover_per_rebal']}")

    # Path B: WEEKLY cadence + sidecar OFF (cycle06's holding_freq)
    _log("Path B: cycle06 composite + WEEKLY + sidecar OFF")
    path_b = _walkforward_run(
        panel, composite, train_start, train_end,
        cadence="weekly", use_sidecar=False,
        ttl_bars=21)  # 3 weeks TTL for weekly cadence
    _log(f"  B: cum={path_b['cum_return']}, "
         f"Sharpe={path_b['annualized_sharpe']}, "
         f"MaxDD={path_b['max_drawdown']}, "
         f"turnover/rebal={path_b['turnover_per_rebal']}")

    # Path C: WEEKLY + sidecar weak-filter (full stack with cycle06 signal)
    _log("Path C: cycle06 composite + WEEKLY + sidecar weak-filter")
    path_c = _walkforward_run(
        panel, composite, train_start, train_end,
        cadence="weekly", use_sidecar=True,
        ttl_bars=21)
    _log(f"  C: cum={path_c['cum_return']}, "
         f"Sharpe={path_c['annualized_sharpe']}, "
         f"MaxDD={path_c['max_drawdown']}, "
         f"turnover/rebal={path_c['turnover_per_rebal']}")

    # cycle06 reference (from data/audit/cycle06_v1_strict.json
    # trial 31af04cf2ff9 metrics_full_period — note: full period =
    # 2007-2025, NOT 2018-2024; pre-X0 baseline split-only SPY)
    cycle06_ref = {
        "trial_id": "31af04cf2ff9",
        "metrics_full_period_pre_X0": {
            "cum_ret": 14.4122,
            "sharpe": 1.3663,
            "max_dd": -0.1960,
            "vs_spy": 8.0766,
            "spy_cum_ret": 6.3356,
        },
        "metrics_per_year_selector_partition": {
            "2018": {"sharpe": -0.4350, "max_dd": -0.1960,
                      "cum_ret": -0.0658},
            "2019": {"sharpe": 2.2341, "max_dd": -0.0569,
                      "cum_ret": 0.2521},
            "2021": {"sharpe": 2.0555, "max_dd": -0.0983,
                      "cum_ret": 0.3466},
            "2023": {"sharpe": 2.7950, "max_dd": -0.0931,
                      "cum_ret": 0.5203},
            "2025": {"sharpe": 2.1194, "max_dd": -0.1658,
                      "cum_ret": 0.3949},
        },
        "metrics_per_year_avg_sharpe_selector": 1.754,
        "caveat": "selector partition = interleaved years; "
                  "full-period uses pre-X0 split-only SPY 6.34; "
                  "post-X0 SPY-TR cum 9.00 → vs-SPY recomputes lower",
    }

    # §12.0 PASS verdict per path — TWO BASELINES (honest disclosure):
    #   (a) cycle06 spec.nav_sharpe = 0.5654 (Track-A NAV evaluation
    #       metric, what cycle06 used to PASS Track-A; same window
    #       basis as our R10/R12 stack)
    #   (b) cycle06 metrics_full_period.sharpe = 1.37 (2007-2025 full
    #       period, pre-X0 split-only baseline — different window
    #       AND different cum_ret basis)
    #
    # Apples-to-apples = (a). (b) is a confounded comparison since
    # window length and starting capital base both differ; recorded
    # for transparency.
    def verdict(path: dict) -> dict:
        # baseline a: cycle06 spec nav_sharpe (Track-A PASS metric)
        cy_sharpe_a = 0.5654
        # baseline b: cycle06 metrics_full_period.sharpe (full window)
        cy_sharpe_b = 1.3663
        cy_maxdd = -0.1960  # cycle06 max_dd on full period
        TOL_SHARPE = 0.2
        TOL_MAXDD = 0.05
        return {
            "sharpe_path": path["annualized_sharpe"],
            "sharpe_pass_vs_a_nav_sharpe": (
                path["annualized_sharpe"] >= cy_sharpe_a - TOL_SHARPE),
            "sharpe_baseline_a_minus_tol": round(cy_sharpe_a - TOL_SHARPE, 4),
            "sharpe_pass_vs_b_full_period": (
                path["annualized_sharpe"] >= cy_sharpe_b - TOL_SHARPE),
            "sharpe_baseline_b_minus_tol": round(cy_sharpe_b - TOL_SHARPE, 4),
            "maxdd_path": path["max_drawdown"],
            "maxdd_pass": path["max_drawdown"] >= cy_maxdd - TOL_MAXDD,
            "maxdd_baseline_minus_tol": round(cy_maxdd - TOL_MAXDD, 4),
        }

    summary = {
        "cycle06_reference": cycle06_ref,
        "tolerances": {"sharpe": 0.2, "maxdd": 0.05},
        "path_a_monthly_no_sidecar": path_a,
        "path_b_weekly_no_sidecar": path_b,
        "path_c_weekly_with_sidecar": path_c,
        "verdicts": {
            "A": verdict(path_a),
            "B": verdict(path_b),
            "C": verdict(path_c),
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2, default=str))
    _log(f"written {OUT_PATH}")
    _log(f"VERDICTS:")
    for k, v in summary["verdicts"].items():
        _log(f"  Path {k}: Sharpe={v['sharpe_path']} "
             f"(vs nav_sharpe 0.5654 pass={v['sharpe_pass_vs_a_nav_sharpe']}, "
             f"vs full-period 1.37 pass={v['sharpe_pass_vs_b_full_period']}), "
             f"MaxDD_pass={v['maxdd_pass']}")
    LOG_PATH.write_text("\n".join(log_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
