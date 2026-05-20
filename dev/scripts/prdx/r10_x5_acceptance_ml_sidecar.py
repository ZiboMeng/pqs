"""PRD-X v2 Phase X5 R10 — acceptance experiment for MLSidecarPolicy.

Compares 3 paths on the same cycle06 panel + same RuleBasedDecisionPolicy
+ same train window:

  Path A: ML sidecar OFF (= R9 active baseline,bit-identical to
          PartialRebalancePolicy active-mode R5e v2 reproduce)
  Path B: ML sidecar ACTIVE + RANDOM_VETO 20% (1-in-5 entry vetoed
          via deterministic seeded RNG; baseline noise floor)
  Path C: ML sidecar ACTIVE + WEAK_FACTOR_FILTER (veto when factor
          score is in the LOWER half of the entry-eligible band,
          i.e. just barely above entry_threshold = noisy edge)

AC (PRD §11 X5 + §9.0 post-fix):
  - All 3 paths bit-identical baseline (off-mode reproduces R9 active)
  - Random VETO 20% should hurt cum_ret and Sharpe (random costs)
  - WEAK_FACTOR_FILTER should retain higher-strength entries; expect
    Sharpe ≥ off-mode (or comparable; small N noise dominates)
  - §9.0 invariant verified: vote_fn returns SignVote enum;
    sidecar never produces continuous magnitude scaling

Verdict RECORDED non-blanket per `feedback_no_blanket_failure_verdict`.
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

OUT_PATH = PROJ / "data" / "audit" / "prdx_r10_x5_acceptance.json"
LOG_PATH = PROJ / "data" / "audit" / "prdx_r10_x5_acceptance.log"


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


# ── vote_fn variants (§9.0 — all return SignVote, never float) ──────
def _make_random_veto_voter(seed: int, veto_rate: float = 0.2):
    """20% of ctx evaluations get VETO; deterministic via seeded RNG."""
    rng = np.random.default_rng(seed)
    def voter(ctx: Dict) -> SignVote:
        u = rng.uniform()
        return SignVote.VETO if u < veto_rate else SignVote.NO_VOTE
    return voter


def _weak_factor_filter_voter(entry_threshold: float = 0.7):
    """VETO when factor_score is in the lower half of the
    entry-eligible band (i.e. between entry_threshold and the
    midpoint to 1.0). Higher strength = stronger signal.

    This is a DISCRETE classifier-style rule (§9.0 compliant).
    """
    midpoint = (entry_threshold + 1.0) / 2.0
    def voter(ctx: Dict) -> SignVote:
        fs = ctx.get("factor_score")
        if fs is None:
            return SignVote.NO_VOTE
        # Only vote on entry-eligible decisions (factor_score above
        # entry threshold by construction); VETO weak edges.
        if entry_threshold < float(fs) < midpoint:
            return SignVote.VETO
        return SignVote.NO_VOTE
    return voter


def _walkforward_run(
    panel: dict,
    factors: dict,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    ml_mode: str,
    vote_fn,
    factor_name: str = "mom_12_1",
    base_position_size: float = 0.05,
    confirm_min_bars: int = 2,
    entry_threshold: float = 0.7,
    exit_threshold: float = 0.3,
    band_base: float = 0.02,
) -> dict:
    close = panel["close"].sort_index()
    close = close.loc[(close.index >= train_start)
                      & (close.index <= train_end)]
    factor = factors[factor_name].loc[
        (factors[factor_name].index >= train_start)
        & (factors[factor_name].index <= train_end)]
    realized_vol = _realized_vol_60d(close)

    policy = RuleBasedDecisionPolicy(
        entry_triggers=[FactorEntryTrigger(entry_threshold=entry_threshold)],
        exit_triggers=[ThesisDecayTrigger(exit_threshold=exit_threshold)],
        mode="active", confirm_min_bars=confirm_min_bars,
        base_position_size=base_position_size, ttl_bars=90)
    partial = PartialRebalancePolicy(
        no_trade_band=NoTradeBandCalculator(base_band=band_base),
        mode="active", partial_full_threshold=0.05)
    sidecar = MLSidecarPolicy(vote_fn=vote_fn, mode=ml_mode)

    rebal_dates = close.resample("BME").last().index.intersection(
        close.index)
    daily_weights = pd.DataFrame(
        0.0, index=close.index, columns=close.columns)
    current_w: Dict[str, float] = {}
    turnover_sum = 0.0
    n_rebal = 0
    veto_count = 0
    no_vote_count = 0
    confirm_count = 0
    tradeable = [s for s in close.columns if s not in ("SPY", "QQQ")]

    for date in close.index:
        if date not in rebal_dates:
            for sym, w in current_w.items():
                if sym in daily_weights.columns:
                    daily_weights.at[date, sym] = w
            continue
        scores = _normalize_rank(factor.loc[date])
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
        rebal_ctx = {"date": date, "regime": RegimeState.NEUTRAL,
                     "realized_vol": spy_vol}
        actions = partial.compute_actions(
            target_weights=target_union,
            current_weights=current_union, ctx=rebal_ctx)
        # APPLY ML SIDECAR overlay per-symbol
        new_w: Dict[str, float] = {}
        for d in actions:
            ml_ctx = {
                "symbol": d.symbol, "date": date,
                "factor_score": float(scores.get(d.symbol, np.nan))
                                 if not pd.isna(scores.get(d.symbol, np.nan))
                                 else None,
            }
            v = sidecar.vote(ml_ctx)
            if v == SignVote.VETO:
                veto_count += 1
            elif v == SignVote.CONFIRM:
                confirm_count += 1
            else:
                no_vote_count += 1
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
    return {
        "ml_mode": ml_mode,
        "n_rebal": int(n_rebal),
        "turnover_per_rebal": round(turnover_sum / n_rebal, 4)
                              if n_rebal else 0.0,
        "cum_return": round(cum_ret, 4),
        "annualized_sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "vote_counts": {
            "VETO": int(veto_count),
            "NO_VOTE": int(no_vote_count),
            "CONFIRM": int(confirm_count),
        },
    }


def main() -> int:
    log_lines = []
    def _log(msg):
        line = f"[{datetime.utcnow().isoformat()}Z] {msg}"
        print(line, flush=True)
        log_lines.append(line)

    _log("R10 X5 acceptance — start (3-path comparison)")
    load_panel = _import_cycle06_loader()
    panel, factors, mask, split_cfg = load_panel()
    _log(f"panel close {panel['close'].shape} factors {len(factors)}")

    train_start = pd.Timestamp("2018-01-01")
    train_end = pd.Timestamp("2024-12-31")
    _log(f"train window {train_start.date()} → {train_end.date()}")

    # Path A: sidecar OFF
    _log("Path A: ML sidecar OFF (R9-active baseline reproduce)")
    path_a = _walkforward_run(
        panel, factors, train_start, train_end,
        ml_mode="off", vote_fn=lambda ctx: SignVote.NO_VOTE)
    _log(f"  A: cum={path_a['cum_return']}, "
         f"Sharpe={path_a['annualized_sharpe']}, "
         f"MaxDD={path_a['max_drawdown']}, "
         f"turnover={path_a['turnover_per_rebal']}")

    # Path B: random VETO 20% (noise floor)
    _log("Path B: ML sidecar ACTIVE + RANDOM_VETO 20%")
    path_b = _walkforward_run(
        panel, factors, train_start, train_end,
        ml_mode="active", vote_fn=_make_random_veto_voter(seed=42))
    _log(f"  B: cum={path_b['cum_return']}, "
         f"Sharpe={path_b['annualized_sharpe']}, "
         f"MaxDD={path_b['max_drawdown']}, "
         f"turnover={path_b['turnover_per_rebal']}, "
         f"vetos={path_b['vote_counts']['VETO']}")

    # Path C: WEAK_FACTOR_FILTER (discriminative)
    _log("Path C: ML sidecar ACTIVE + WEAK_FACTOR_FILTER")
    path_c = _walkforward_run(
        panel, factors, train_start, train_end,
        ml_mode="active", vote_fn=_weak_factor_filter_voter())
    _log(f"  C: cum={path_c['cum_return']}, "
         f"Sharpe={path_c['annualized_sharpe']}, "
         f"MaxDD={path_c['max_drawdown']}, "
         f"turnover={path_c['turnover_per_rebal']}, "
         f"vetos={path_c['vote_counts']['VETO']}")

    summary = {
        "path_a_off": path_a,
        "path_b_random_veto_20pct": path_b,
        "path_c_weak_factor_filter": path_c,
        "diffs": {
            "B_vs_A": {
                "cum_ret_diff": round(
                    path_b["cum_return"] - path_a["cum_return"], 4),
                "sharpe_diff": round(
                    path_b["annualized_sharpe"]
                    - path_a["annualized_sharpe"], 4),
                "maxdd_diff": round(
                    path_b["max_drawdown"] - path_a["max_drawdown"], 4),
            },
            "C_vs_A": {
                "cum_ret_diff": round(
                    path_c["cum_return"] - path_a["cum_return"], 4),
                "sharpe_diff": round(
                    path_c["annualized_sharpe"]
                    - path_a["annualized_sharpe"], 4),
                "maxdd_diff": round(
                    path_c["max_drawdown"] - path_a["max_drawdown"], 4),
            },
        },
        "config": {
            "factor_name": "mom_12_1",
            "entry_threshold": 0.7,
            "exit_threshold": 0.3,
            "band_base": 0.02,
            "weak_filter_midpoint": 0.85,
            "random_veto_rate": 0.2,
            "random_seed": 42,
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
