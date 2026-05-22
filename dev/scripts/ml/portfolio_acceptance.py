#!/usr/bin/env python
"""P4 — portfolio acceptance harness (PRD 20260521 §9 / §12.3).

Proves whether a forecast creates a useful PORTFOLIO, not just a good
rank-IC. Compares, on one held-out window, long-only portfolios built
the same way (score → score_to_weight → backtest):

  path A  — non-ML Stage-1 cycle06 composite rank (the baseline)
  path D  — XGBRanker (rank:ndcg) ranker-to-portfolio

(paths B/C — the sign-veto sidecar — are covered by
`r29_acceptance_r_ml_a_vs_b.py`; this harness adds the new ranker path.)

Reuses: `_load_panel` (walk_forward_rank_sign), `score_panel_to_weights`
+ `portfolio_metrics` (core/research/allocation), `XGBRankerRankModel`.

temporal_split: the default 2012-2017 window is train-only — no
validation/sealed consumed.

Output: data/audit/ml_rank_portfolio_acceptance_<ts>.json

Usage: python dev/scripts/ml/portfolio_acceptance.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "dev/scripts/ml"))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from walk_forward_rank_sign import _load_panel  # noqa: E402
from core.research.ml.rank_model import (  # noqa: E402
    LinearBaselineRankModel,
    _cross_sectional_rank,
    _cross_sectional_standardize,
)
from core.research.ml.labels import make_forward_return_labels  # noqa: E402
from core.research.ml.pipeline import (  # noqa: E402
    DEFAULT_SEALED_YEARS,
    WalkForwardConfig,
    iter_folds,
)
from core.research.ml.xgb_rank_model import XGBRankerRankModel  # noqa: E402
from core.research.ml.lgbm_rank_model import LGBMRankerRankModel  # noqa: E402
from core.research.allocation.score_to_weight import (  # noqa: E402
    score_panel_to_weights,
)
from core.research.allocation.portfolio_metrics import (  # noqa: E402
    portfolio_metrics,
)
from core.research.allocation.constraints import (  # noqa: E402
    apply_turnover_cap,
)
from core.research.allocation.exit_policy import (  # noqa: E402
    apply_signal_decay_exit,
    apply_turnover_band,
)
from core.research.ml.artifact import (  # noqa: E402
    ArtifactGovernance,
    validate_artifact_governance,
)
from core.research.allocation.vol_target import (  # noqa: E402
    apply_vol_target_overlay,
)

CYCLE06 = ("drawup_from_252d_low", "trend_tstat_20d", "ret_2d")


def _stage1_composite_rank(factors: dict, names) -> pd.DataFrame:
    """Equal-weight zscore-average cross-sectional rank ∈ [0,1]."""
    std = [_cross_sectional_standardize(factors[n]) for n in names]
    return _cross_sectional_rank(sum(std) / len(std))


def _rebalance(w: pd.DataFrame, step: int) -> pd.DataFrame:
    """Hold weights between rebalances: only every `step`-th date
    carries a fresh target; the rest forward-fill. Without this the
    harness implicitly rebalances DAILY and the cost-sensitivity is
    dominated by an unrealistic turnover-cost artifact (~37%/yr at
    30bps with daily churn)."""
    if step <= 1:
        return w
    return w.iloc[::step].reindex(w.index).ffill().fillna(0.0)


def _port_ret(weights: pd.DataFrame, close: pd.DataFrame) -> pd.Series:
    """Daily portfolio return (weight set at T earned over T+1)."""
    cols = [c for c in weights.columns if c in close.columns]
    rets = close[cols].reindex(weights.index).pct_change().fillna(0.0)
    return (weights[cols].shift(1).fillna(0.0) * rets).sum(axis=1)


# NOTE — min-edge gate (S4 R12, 2026-05-22): a per-bar gate driven by a
# trailing-realized edge proxy was prototyped and REVERTED — a lagging
# proxy + hard cash/no-trade gate whipsaws (it cashes out *after* a weak
# stretch and re-enters *after* a strong one), turning path A Sharpe
# +0.73 → -0.46 on the 2015-2017 smoke. The gate FUNCTION
# (constraints.apply_min_edge_gate) is correct and kept; a non-whipsaw
# production edge proxy is a research sub-problem → `min_edge_to_trade`
# is marked `roadmap` in ml_allocation.yaml, not wired here.


def _overfit_control(sweep: dict, close: pd.DataFrame,
                     n_trials: int) -> dict:
    """PRD §9.6 — DSR-deflate the promoted path (D_xgb) OOS return for
    the acceptance trial count, plus a PBO check over the FULL config
    sweep. PBO via CSCV needs a genuine multi-config sweep — feeding it
    just 2 paths is degenerate; `sweep` carries the composite baseline +
    3 genuinely-different model families (XGB / Linear / LGBM), so the
    PBO matrix is model-DIVERSE, not cosmetic re-skins (supplement S5).
    Reuses the project's overfit-control modules — never re-implements."""
    from core.research.overfit_metrics import deflated_sharpe_ratio
    from core.research.mining_pbo import compute_mining_pbo
    daily = {name: _port_ret(w, close) for name, w in sweep.items()}
    monthly = {name: (1 + r).resample("ME").prod() - 1
               for name, r in daily.items()}
    out = {"n_trials": int(n_trials),
           "sweep_configs": list(sweep.keys()),
           "selection": "P4 acceptance config sweep → promoted = D_xgb"}
    try:
        out["dsr_promoted_D_xgb"] = deflated_sharpe_ratio(
            daily["D_xgb"].tolist(), n_trials=int(n_trials))
    except Exception as exc:  # noqa: BLE001
        out["dsr_promoted_D_xgb"] = {"error": f"{type(exc).__name__}: {exc}"}
    # PBO — (months × n_configs) monthly-return matrix via CSCV
    M = pd.concat([monthly[n] for n in sweep], axis=1).dropna().to_numpy()
    out["pbo"] = compute_mining_pbo(M)
    return out


def _acceptance_governance(args, mode_d, top_k, cap, overfit,
                           acceptance_path) -> ArtifactGovernance:
    """PRD §10.2 ArtifactGovernance for the portfolio-acceptance artifact
    (supplement S2). Portfolio-tier fields populated — this IS a
    portfolio-level artifact, so target-weight / risk-scaling /
    constraint-set / cost-model / execution-assumption ids are required.
    """
    h = hashlib.sha256()
    for rel in ("config/ml_sources.yaml", "config/ml_labeling.yaml",
                "config/ml_allocation.yaml", "config/temporal_split.yaml"):
        h.update((PROJ / rel).read_bytes())
    dsr = (overfit.get("dsr_promoted_D_xgb") or {}).get("deflated_sharpe")
    pbo = (overfit.get("pbo") or {}).get("pbo")
    vt = args.vol_target
    return ArtifactGovernance(
        task_family="rank_to_portfolio",
        source_tiers=("A_market_data",),
        label_mode="forward_return",
        sample_weight_mode="uniform",
        purge_embargo={"embargo_days": args.horizon_days,
                       "unit": "trading_bars"},
        context_bundle="none",
        training_universe="executable",
        model_family="XGBRankerRankModel",
        objective="rank:ndcg",
        config_hash=h.hexdigest()[:16],
        trial_count=int(overfit["n_trials"]),  # S5: from trial ledger
        dsr=dsr, pbo=pbo,
        score_to_weight_mode=mode_d,
        exit_policy_mode="none",
        reused_native_components=True,
        portfolio_acceptance_path=acceptance_path,
        target_weight_mode=mode_d,
        risk_scaling_mode=(f"vol_target_{vt}" if vt > 0 else "none"),
        constraint_set_id="ml_allocation.yaml",
        cost_model_id="per_unit_turnover_bps",
        execution_assumption_id="tplus1_close_shift",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="P4 portfolio acceptance harness")
    ap.add_argument("--start-year", type=int, default=2012)
    ap.add_argument("--end-year", type=int, default=2017,
                    help="< 2018 keeps the window train-only")
    ap.add_argument("--horizon-days", type=int, default=21)
    ap.add_argument("--rebalance-days", type=int, default=21,
                    help="hold weights between rebalances (default 21 = "
                         "monthly); 1 = daily (unrealistic cost)")
    ap.add_argument("--out-dir", default="data/audit")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--mode-a", default=None,
                    help="path-A mapping mode (default = config default)")
    ap.add_argument("--mode-d", default=None,
                    help="path-D mapping mode; score_vol_scaled tames "
                         "drawdown (P4 verdict Option B, user 2026-05-22)")
    ap.add_argument("--vol-target", type=float, default=0.0,
                    help="annualized vol-target exposure overlay on path D "
                         "(0 = off; P4 Option B attempt 2 — the systematic-"
                         "drawdown lever)")
    ap.add_argument("--n-trials", type=int, default=None,
                    help="§9.6 DSR trial count. Default None → sourced "
                         "from the persisted trial ledger "
                         "data/audit/ml_trial_ledger.json (supplement S5 "
                         "fix — no longer a hardcoded CLI default).")
    args = ap.parse_args()

    # S5: n_trials sourced from the persisted trial ledger, not a CLI
    # default — the ledger is the honest record of configs examined.
    if args.n_trials is not None:
        n_trials = int(args.n_trials)
    else:
        _ledger = json.loads(
            (PROJ / "data/audit/ml_trial_ledger.json").read_text())
        n_trials = len(_ledger["trials"])

    alloc = yaml.safe_load((PROJ / "config/ml_allocation.yaml").read_text())
    default_mode = alloc["default_mapping_mode"]
    mode_a = args.mode_a or default_mode
    mode_d = args.mode_d or default_mode
    top_k = int(alloc["mapping_modes"][default_mode]["top_k"])
    cap = float(alloc["constraints"]["max_single_name_weight"])
    turnover_cap = float(alloc["constraints"]["turnover_cap_daily"])
    _ep = alloc["exit_policy"]
    decay_thr = float(_ep["signal_decay"]["exit_when_rank_below"])
    rebal_band = float(_ep["turnover_band"]["rebalance_band"])

    print(f"=== P4 portfolio acceptance  {args.start_year}-{args.end_year}"
          f"  mode_a={mode_a} mode_d={mode_d} top_k={top_k} ===")
    panel, factors, _ = _load_panel()
    start = pd.Timestamp(f"{args.start_year}-01-01")
    end = pd.Timestamp(f"{args.end_year}-12-31")
    close = panel["close"].loc[(panel["close"].index >= start)
                               & (panel["close"].index <= end)]
    factors = {k: v.loc[(v.index >= start) & (v.index <= end)]
               for k, v in factors.items() if not v.empty}
    missing = [f for f in CYCLE06 if f not in factors]
    if missing:
        raise RuntimeError(f"cycle06 factors missing: {missing}")

    spy = close.get("SPY")
    feats = {f: factors[f] for f in CYCLE06}
    labels = make_forward_return_labels(close, args.horizon_days)

    # --- path D: multi-fold walk-forward; concatenated OOS rank panel -----
    wf = WalkForwardConfig(
        start_year=args.start_year, end_year=args.end_year,
        train_window_years=3, val_window_years=1, step_years=1,
        embargo_days=args.horizon_days)   # P1 §8.2 purge+embargo
    # S5: train 3 genuinely-different model families per fold — XGB is
    # the promoted ranker; Linear + LGBM make the §9.6 PBO sweep
    # model-DIVERSE (the prior sweep was 4 cosmetic XGB-mapping re-skins
    # → collinear → optimistic PBO).
    def _rankers():
        return {
            "xgb": XGBRankerRankModel(objective="rank:ndcg",
                                      n_estimators=50, max_depth=4,
                                      random_state=args.seed),
            "linear": LinearBaselineRankModel(),
            "lgbm": LGBMRankerRankModel(n_estimators=50, max_depth=4,
                                        random_state=args.seed),
        }
    rank_parts: dict = {k: [] for k in _rankers()}
    for fold in iter_folds(wf, DEFAULT_SEALED_YEARS,
                           trading_index=close.index):  # audit C1: exact embargo
        tr_feats = {f: p.loc[(p.index >= fold.train_start)
                             & (p.index <= fold.train_end)]
                    for f, p in feats.items()}
        tr_labels = labels.loc[(labels.index >= fold.train_start)
                               & (labels.index <= fold.train_end)]
        va_feats = {f: p.loc[(p.index >= fold.val_start)
                             & (p.index <= fold.val_end)]
                    for f, p in feats.items()}
        for name, model in _rankers().items():
            model.fit(tr_feats, tr_labels)
            rank_parts[name].append(model.predict_rank(va_feats))
    if not rank_parts["xgb"]:
        raise RuntimeError("no walk-forward folds — widen the window")
    ranks = {k: pd.concat(v).sort_index() for k, v in rank_parts.items()}
    rank_d = ranks["xgb"]               # the promoted ranker
    n_folds = len(rank_parts["xgb"])

    # path A composite over the SAME concatenated OOS dates (apples-to-apples)
    rank_a = _stage1_composite_rank(factors, CYCLE06).reindex(rank_d.index)
    oos = f"{rank_d.index[0].date()}..{rank_d.index[-1].date()}"
    print(f"  {n_folds} walk-forward folds; concatenated OOS {oos}")

    # realized-vol panel (annualized 60d) — needed by score_vol_scaled
    vol_df = close.pct_change().rolling(60, min_periods=20).std() * (252 ** 0.5)

    def _weights(rank, m, vt=0.0):
        vd = vol_df if m == "score_vol_scaled" else None
        w = _rebalance(score_panel_to_weights(
            rank, mode=m, top_k=top_k, max_single_weight=cap, vol_df=vd),
            args.rebalance_days)
        # S4: turnover cap (ml_allocation.yaml constraints.turnover_cap_daily)
        w = apply_turnover_cap(w, turnover_cap)
        # S4: exit_policy — signal-decay exit (held name's rank decays
        # below the threshold) + turnover no-trade band.
        w = apply_signal_decay_exit(w, rank, exit_threshold=decay_thr)
        w = apply_turnover_band(w, rebal_band)
        # min-edge gate intentionally NOT wired — see NOTE above.
        if vt > 0.0:
            w = apply_vol_target_overlay(w, close, target_vol=vt)
        return w

    weights_a = _weights(rank_a, mode_a)
    weights_d = _weights(rank_d, mode_d, args.vol_target)
    # §9.6 PBO needs the full config sweep explored to land on path D
    # S5: model-DIVERSE PBO sweep — composite + 3 genuinely-different
    # model families (not 4 cosmetic XGB-mapping re-skins).
    sweep = {
        "A_composite": _weights(rank_a, "top_k_capped"),
        "D_xgb": _weights(ranks["xgb"], "top_k_capped"),
        "D_linear": _weights(ranks["linear"], "top_k_capped"),
        "D_lgbm": _weights(ranks["lgbm"], "top_k_capped"),
    }

    # cost-sensitivity: 0 / 30 / 60 bps per-unit-turnover
    paths = {}
    for label, w in (("path_A_non_ml_composite", weights_a),
                     ("path_D_xgb_ranker_ndcg", weights_d)):
        paths[label] = {
            f"cost_{c}bps": portfolio_metrics(
                w, close, benchmark=spy, cost_bps=float(c))
            for c in (0, 30, 60)}

    # verdict at the realistic 30bps cost.
    # Gate (user 2026-05-22, prompt §〇 #5): path D beats baseline on net
    # Sharpe AND path D's MaxDD is within the 15-20% invariant band —
    # the strict "MaxDD beats baseline" half was relaxed to "MaxDD < 20%".
    a30 = paths["path_A_non_ml_composite"]["cost_30bps"]
    d30 = paths["path_D_xgb_ranker_ndcg"]["cost_30bps"]
    sharpe_beat = d30["annualized_sharpe"] >= a30["annualized_sharpe"]
    maxdd_within_invariant = abs(d30["max_drawdown"]) <= 0.20
    verdict = "PASS" if (sharpe_beat and maxdd_within_invariant) else "FAIL"
    overfit = _overfit_control(sweep, close, n_trials)

    out = {
        "prd": "docs/prd/20260521-rerisk-and-ml-training-audit-prd.md §9 P4",
        "window": f"{args.start_year}-{args.end_year} (train-only)",
        "n_walk_forward_folds": n_folds,
        "concatenated_oos": oos,
        "mode_a": mode_a, "mode_d": mode_d,
        "top_k": top_k, "single_name_cap": cap,
        "rebalance_days": args.rebalance_days,
        "path_d_vol_target": args.vol_target,
        "cost_levels_bps": [0, 30, 60],
        "paths": paths,
        "overfit_control": overfit,
        "verdict": verdict,
        "verdict_basis": ("path D beats baseline on net Sharpe AND path "
                          "D MaxDD within the 15-20% invariant (gate per "
                          "user 2026-05-22, prompt §〇 #5). Multi-fold "
                          "walk-forward, train-only window, 30bps cost."),
        "sharpe_beat": bool(sharpe_beat),
        "maxdd_within_invariant": bool(maxdd_within_invariant),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    }
    out_path = (PROJ / args.out_dir
                / f"ml_rank_portfolio_acceptance_{out['generated_utc']}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # §10.2 governance (supplement S2) — portfolio-tier; fail-closed.
    governance = _acceptance_governance(
        args, mode_d, top_k, cap, overfit,
        str(out_path.relative_to(PROJ)))
    validate_artifact_governance(governance, is_portfolio=True)
    out["governance"] = asdict(governance)
    out_path.write_text(json.dumps(out, indent=2))
    for label in ("path_A_non_ml_composite", "path_D_xgb_ranker_ndcg"):
        m = paths[label]["cost_30bps"]
        print(f"  {label} @30bps: Sharpe={m['annualized_sharpe']} "
              f"MaxDD={m['max_drawdown']} cum={m['cum_return']} "
              f"turnover={m['turnover_mean']}")
    dsr = overfit.get("dsr_promoted_D_xgb", {})
    print(f"  verdict={verdict} (sharpe_beat={sharpe_beat} "
          f"maxdd_within_invariant={maxdd_within_invariant})")
    print(f"  §9.6: n_trials={overfit['n_trials']} "
          f"dsr(D_xgb)={dsr.get('deflated_sharpe')} "
          f"pbo(sweep×{len(overfit['sweep_configs'])})="
          f"{overfit['pbo'].get('pbo')}")
    print(f"  → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
