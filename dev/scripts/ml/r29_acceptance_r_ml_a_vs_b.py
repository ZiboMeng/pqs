"""PRD #4 P4.5 sub-step B (Round 29) — R-ML-A vs R-ML-B real backtest.

Reuses R10 acceptance walk-forward pattern. Compares:
  Path A (R-ML-A): trigger-first stack + weak_factor_filter_voter
                   (R10 Path C baseline reproduce)
  Path B (R-ML-B): trigger-first stack + trained XGBSignClassifier
                   (Stage 1 cycle06 rank panel + Stage 2 binary classifier)

§9.0: trained classifier produces 0/1 → mapped to VETO/NO_VOTE in
panel-backed voter. NO continuous magnitude scaling.

AC (PRD #4 P4.5):
  - At least one of R-ML-B/C/D beats R-ML-A on Sharpe AND MaxDD
  - §9.0 invariant verified
  - Reproducible via seeded pipeline

Per `feedback_no_blanket_failure_verdict`: if R-ML-B FAILS to beat A,
record per-path verdict + root cause (not "ML doesn't work").
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Any

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from core.regime.regime_detector import RegimeState  # noqa: E402
from core.research.decision.ml_sidecar import MLSidecarPolicy, SignVote  # noqa: E402
from core.research.decision.no_trade_band import NoTradeBandCalculator  # noqa: E402
from core.research.decision.partial_rebalance import PartialRebalancePolicy  # noqa: E402
from core.research.decision.rule_based_policy import RuleBasedDecisionPolicy  # noqa: E402
from core.research.decision.entry_triggers import FactorEntryTrigger  # noqa: E402
from core.research.decision.exit_triggers import ThesisDecayTrigger  # noqa: E402
from core.research.ml.artifact import load_artifact  # noqa: E402
from core.research.ml.context_features import extract_feature_bundle  # noqa: E402
from core.research.ml.rank_model import _cross_sectional_rank, _cross_sectional_standardize  # noqa: E402


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


def _build_stage1_rank(factors, feature_names):
    standardized = [_cross_sectional_standardize(factors[n]) for n in feature_names]
    avg = sum(standardized) / len(standardized)
    return _cross_sectional_rank(avg)


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


def _trained_classifier_voter(
    model, stage1_rank: pd.DataFrame,
    context_panels: Dict[str, pd.DataFrame],
):
    """Panel-backed voter for trained XGB sign classifier.

    Looks up (date, symbol) in pre-computed Stage 1 rank + context
    panels to build [stage1_rank, *sorted(context)] vector, predicts,
    maps 0/1 → VETO/NO_VOTE per §9.0.
    """
    ctx_names = sorted(context_panels.keys())

    def voter(ctx: Dict) -> SignVote:
        sym = ctx.get("symbol")
        date = ctx.get("date")
        if sym is None or date is None:
            return SignVote.NO_VOTE
        if (date not in stage1_rank.index
                or sym not in stage1_rank.columns):
            return SignVote.NO_VOTE
        rank = stage1_rank.at[date, sym]
        if pd.isna(rank):
            return SignVote.NO_VOTE
        feats = [float(rank)]
        for name in ctx_names:
            panel = context_panels[name]
            if date not in panel.index or sym not in panel.columns:
                return SignVote.NO_VOTE
            v = panel.at[date, sym]
            if pd.isna(v):
                return SignVote.NO_VOTE
            feats.append(float(v))
        try:
            X = np.asarray(feats, dtype=float).reshape(1, -1)
            pred = int(np.asarray(model.predict(X)).flatten()[0])
        except Exception:
            return SignVote.NO_VOTE
        if pred == 0:
            return SignVote.VETO
        return SignVote.NO_VOTE
    return voter


def _walkforward_run(
    panel, factors, train_start, train_end,
    ml_mode: str, vote_fn,
    factor_name: str = "mom_12_1",
    factor_panel_override: Optional[pd.DataFrame] = None,
    entry_threshold: float = 0.7,
    exit_threshold: float = 0.3,
    band_base: float = 0.02,
    base_position_size: float = 0.05,
    confirm_min_bars: int = 2,
) -> dict:
    """Walk-forward with optional custom factor_panel (overrides
    ``factor_name`` lookup). R-ML-C uses stage1_rank as the factor
    signal — pass it via ``factor_panel_override``.
    """
    close = panel["close"].sort_index()
    close = close.loc[(close.index >= train_start)
                      & (close.index <= train_end)]
    if factor_panel_override is not None:
        factor_src = factor_panel_override
    else:
        factor_src = factors[factor_name]
    factor = factor_src.loc[(factor_src.index >= train_start)
                            & (factor_src.index <= train_end)]
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

    rebal_dates = close.resample("BME").last().index.intersection(close.index)
    daily_weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    current_w: Dict[str, float] = {}
    turnover_sum = 0.0
    n_rebal = 0
    veto_count = no_vote_count = confirm_count = 0
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
        target_w_raw = policy.build_target_weights(state=None, ctx={"date": date})
        gross = sum(max(0.0, w) for w in target_w_raw.values())
        if gross > 1.0:
            scale = 1.0 / gross
            target_w_raw = {s: w * scale for s, w in target_w_raw.items()}
        all_syms = set(target_w_raw.keys()) | set(current_w.keys())
        target_union = {s: float(target_w_raw.get(s, 0.0)) for s in all_syms}
        current_union = {s: float(current_w.get(s, 0.0)) for s in all_syms}
        spy_vol = (float(realized_vol.loc[date, "SPY"])
                   if "SPY" in realized_vol.columns
                       and not pd.isna(realized_vol.loc[date, "SPY"])
                   else 0.15)
        rebal_ctx = {"date": date, "regime": RegimeState.NEUTRAL,
                     "realized_vol": spy_vol}
        actions = partial.compute_actions(
            target_weights=target_union, current_weights=current_union,
            ctx=rebal_ctx)
        new_w: Dict[str, float] = {}
        for d in actions:
            ml_ctx = {
                "symbol": d.symbol, "date": date,
                "factor_score": (float(scores.get(d.symbol, np.nan))
                                  if not pd.isna(scores.get(d.symbol, np.nan))
                                  else None),
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
    # SPY benchmark return on same window
    spy_ret = panel["close"]["SPY"].loc[(panel["close"].index >= train_start)
                                        & (panel["close"].index <= train_end)]
    spy_cum = float(spy_ret.iloc[-1] / spy_ret.iloc[0] - 1.0)
    return {
        "ml_mode": ml_mode,
        "n_rebal": int(n_rebal),
        "turnover_per_rebal": round(turnover_sum / max(n_rebal, 1), 4),
        "cum_return": round(float(cum_ret), 4),
        "annualized_sharpe": round(float(sharpe), 4),
        "max_drawdown": round(float(max_dd), 4),
        "vs_spy_excess_cum": round(float(cum_ret) - spy_cum, 4),
        "vote_counts": {
            "VETO": int(veto_count), "NO_VOTE": int(no_vote_count),
            "CONFIRM": int(confirm_count),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PRD #4 P4.5 sub-step B: R-ML-A vs R-ML-B real backtest")
    parser.add_argument("--classifier-artifact", required=True,
                        help="Path to trained sign classifier .pkl artifact "
                             "(base path without extension, OR .pkl suffix)")
    parser.add_argument("--backtest-start", default="2018-01-01")
    parser.add_argument("--backtest-end", default="2024-12-31")
    parser.add_argument("--context-bundle", default="regime_state")
    parser.add_argument("--out-dir", default="data/audit")
    parser.add_argument("--include-r-ml-c", action="store_true",
                        help="Also run R-ML-C (Stage 1 rank as factor_score "
                             "instead of mom_12_1) + trained classifier")
    args = parser.parse_args()

    print(f"=== R29 P4.5 sub-step B: R-ML-A vs R-ML-B real backtest ===")
    print(f"classifier artifact: {args.classifier_artifact}")
    print(f"window: {args.backtest_start} → {args.backtest_end}")
    print(f"context bundle: {args.context_bundle}")

    print(f"\n[1/5] Load cycle06 panel + factors...")
    load_panel = _import_cycle06_loader()
    panel, factors, mask, split_cfg = load_panel()
    print(f"  close {panel['close'].shape} factors {len(factors)}")

    print(f"\n[2/5] Load trained sign classifier artifact...")
    artifact = load_artifact(args.classifier_artifact)
    print(f"  lineage: {artifact.metadata.lineage_tag}")
    print(f"  spec_id: {artifact.metadata.spec_id[:16]}...")
    print(f"  output_type: {artifact.metadata.output_type}  "
          f"features: {artifact.metadata.feature_columns}")
    if artifact.metadata.output_type != "sign":
        print(f"ERROR: artifact output_type must be 'sign'", file=sys.stderr)
        return 2

    print(f"\n[3/5] Pre-compute Stage 1 rank panel (cycle06 3-factor zscore-rank)...")
    cycle06_feats = ("drawup_from_252d_low", "trend_tstat_20d", "ret_2d")
    stage1_rank = _build_stage1_rank(factors, cycle06_feats)
    print(f"  stage1_rank shape {stage1_rank.shape}")

    print(f"\n[4/5] Extract context bundle: {args.context_bundle}...")
    context = extract_feature_bundle(factors, args.context_bundle)
    print(f"  {len(context)} context features")

    print(f"\n[5/5] Run walk-forward two paths...")
    train_start = pd.Timestamp(args.backtest_start)
    train_end = pd.Timestamp(args.backtest_end)

    print(f"\nPath A (R-ML-A): weak_factor_filter heuristic baseline")
    path_a = _walkforward_run(
        panel, factors, train_start, train_end,
        ml_mode="active", vote_fn=_weak_factor_filter_voter())
    print(f"  cum={path_a['cum_return']}  Sharpe={path_a['annualized_sharpe']}  "
          f"MaxDD={path_a['max_drawdown']}  turnover={path_a['turnover_per_rebal']}")
    print(f"  vetos={path_a['vote_counts']['VETO']}  "
          f"vs_SPY_excess_cum={path_a['vs_spy_excess_cum']}")

    print(f"\nPath B (R-ML-B): trained XGB sign classifier panel-backed voter")
    trained_voter = _trained_classifier_voter(
        artifact.model, stage1_rank, context)
    path_b = _walkforward_run(
        panel, factors, train_start, train_end,
        ml_mode="active", vote_fn=trained_voter)
    print(f"  cum={path_b['cum_return']}  Sharpe={path_b['annualized_sharpe']}  "
          f"MaxDD={path_b['max_drawdown']}  turnover={path_b['turnover_per_rebal']}")
    print(f"  vetos={path_b['vote_counts']['VETO']}  "
          f"vs_SPY_excess_cum={path_b['vs_spy_excess_cum']}")

    path_c: Optional[Dict[str, Any]] = None
    if args.include_r_ml_c:
        print(f"\nPath C (R-ML-C): Stage 1 rank as factor_score + trained classifier")
        path_c = _walkforward_run(
            panel, factors, train_start, train_end,
            ml_mode="active", vote_fn=trained_voter,
            factor_panel_override=stage1_rank)
        print(f"  cum={path_c['cum_return']}  Sharpe={path_c['annualized_sharpe']}  "
              f"MaxDD={path_c['max_drawdown']}  turnover={path_c['turnover_per_rebal']}")
        print(f"  vetos={path_c['vote_counts']['VETO']}  "
              f"vs_SPY_excess_cum={path_c['vs_spy_excess_cum']}")

    # AC verdict
    sharpe_beat = path_b["annualized_sharpe"] > path_a["annualized_sharpe"]
    maxdd_beat = path_b["max_drawdown"] > path_a["max_drawdown"]   # less negative = better
    p45_ac_pass = sharpe_beat and maxdd_beat

    c_sharpe_beat = c_maxdd_beat = c_ac_pass = None
    if path_c is not None:
        c_sharpe_beat = path_c["annualized_sharpe"] > path_a["annualized_sharpe"]
        c_maxdd_beat = path_c["max_drawdown"] > path_a["max_drawdown"]
        c_ac_pass = c_sharpe_beat and c_maxdd_beat

    print(f"\n=== Verdict ===")
    print(f"  Sharpe diff (B - A):  {path_b['annualized_sharpe'] - path_a['annualized_sharpe']:+.4f}  "
          f"{'BEAT' if sharpe_beat else 'FAIL'}")
    print(f"  MaxDD  diff (B - A):  {path_b['max_drawdown'] - path_a['max_drawdown']:+.4f}  "
          f"{'BEAT (less DD)' if maxdd_beat else 'FAIL'}")
    print(f"  cum    diff (B - A):  {path_b['cum_return'] - path_a['cum_return']:+.4f}")
    print(f"  PRD #4 P4.5 AC (B beats A on Sharpe AND MaxDD): "
          f"{'✅ PASS' if p45_ac_pass else '❌ FAIL (non-blanket — record root cause)'}")
    if path_c is not None:
        print(f"  Sharpe diff (C - A):  {path_c['annualized_sharpe'] - path_a['annualized_sharpe']:+.4f}  "
              f"{'BEAT' if c_sharpe_beat else 'FAIL'}")
        print(f"  MaxDD  diff (C - A):  {path_c['max_drawdown'] - path_a['max_drawdown']:+.4f}  "
              f"{'BEAT (less DD)' if c_maxdd_beat else 'FAIL'}")
        print(f"  cum    diff (C - A):  {path_c['cum_return'] - path_a['cum_return']:+.4f}")
        print(f"  PRD #4 P4.5 AC (C beats A on Sharpe AND MaxDD): "
              f"{'✅ PASS' if c_ac_pass else '❌ FAIL (non-blanket)'}")
        any_ac_pass = p45_ac_pass or c_ac_pass
        print(f"\n  P4.5 binding AC (B OR C beats A on both): "
              f"{'✅ PASS' if any_ac_pass else '❌ FAIL'}")

    out_dir = PROJ / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    trained_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary: Dict[str, Any] = {
        "R_ML_A_weak_factor_filter": path_a,
        "R_ML_B_trained_xgb_classifier": path_b,
    }
    if path_c is not None:
        summary["R_ML_C_stage1_rank_factor_plus_classifier"] = path_c
        summary["diff_C_minus_A"] = {
            "sharpe": round(path_c["annualized_sharpe"] - path_a["annualized_sharpe"], 4),
            "max_dd": round(path_c["max_drawdown"] - path_a["max_drawdown"], 4),
            "cum_return": round(path_c["cum_return"] - path_a["cum_return"], 4),
        }
        summary["p45_ac_pass_C"] = c_ac_pass
    summary["diff_B_minus_A"] = {
        "sharpe": round(path_b["annualized_sharpe"] - path_a["annualized_sharpe"], 4),
        "max_dd": round(path_b["max_drawdown"] - path_a["max_drawdown"], 4),
        "cum_return": round(path_b["cum_return"] - path_a["cum_return"], 4),
        "vs_spy_excess_cum": round(
            path_b["vs_spy_excess_cum"] - path_a["vs_spy_excess_cum"], 4),
    }
    summary["p45_ac_pass_B"] = p45_ac_pass
    summary["config"] = {
        "classifier_artifact": str(args.classifier_artifact),
        "classifier_lineage": artifact.metadata.lineage_tag,
        "classifier_spec_id": artifact.metadata.spec_id,
        "backtest_start": args.backtest_start,
        "backtest_end": args.backtest_end,
        "context_bundle": args.context_bundle,
        "include_r_ml_c": args.include_r_ml_c,
    }
    summary["trained_at_utc"] = trained_at
    out_path = out_dir / f"r29_r_ml_a_vs_b_{trained_at}.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nsummary → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
