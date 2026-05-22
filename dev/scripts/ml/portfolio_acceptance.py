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
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "dev/scripts/ml"))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from walk_forward_rank_sign import _load_panel  # noqa: E402
from core.research.ml.rank_model import (  # noqa: E402
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
from core.research.allocation.score_to_weight import (  # noqa: E402
    score_panel_to_weights,
)
from core.research.allocation.portfolio_metrics import (  # noqa: E402
    portfolio_metrics,
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
    args = ap.parse_args()

    alloc = yaml.safe_load((PROJ / "config/ml_allocation.yaml").read_text())
    default_mode = alloc["default_mapping_mode"]
    mode_a = args.mode_a or default_mode
    mode_d = args.mode_d or default_mode
    top_k = int(alloc["mapping_modes"][default_mode]["top_k"])
    cap = float(alloc["constraints"]["max_single_name_weight"])

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
    rank_d_parts = []
    for fold in iter_folds(wf, DEFAULT_SEALED_YEARS):
        tr_feats = {f: p.loc[(p.index >= fold.train_start)
                             & (p.index <= fold.train_end)]
                    for f, p in feats.items()}
        tr_labels = labels.loc[(labels.index >= fold.train_start)
                               & (labels.index <= fold.train_end)]
        va_feats = {f: p.loc[(p.index >= fold.val_start)
                             & (p.index <= fold.val_end)]
                    for f, p in feats.items()}
        model = XGBRankerRankModel(objective="rank:ndcg", n_estimators=50,
                                   max_depth=4, random_state=args.seed)
        model.fit(tr_feats, tr_labels)
        rank_d_parts.append(model.predict_rank(va_feats))
    if not rank_d_parts:
        raise RuntimeError("no walk-forward folds — widen the window")
    rank_d = pd.concat(rank_d_parts).sort_index()
    n_folds = len(rank_d_parts)

    # path A composite over the SAME concatenated OOS dates (apples-to-apples)
    rank_a = _stage1_composite_rank(factors, CYCLE06).reindex(rank_d.index)
    oos = f"{rank_d.index[0].date()}..{rank_d.index[-1].date()}"
    print(f"  {n_folds} walk-forward folds; concatenated OOS {oos}")

    # realized-vol panel (annualized 60d) — needed by score_vol_scaled
    vol_df = close.pct_change().rolling(60, min_periods=20).std() * (252 ** 0.5)

    def _weights(rank, m):
        vd = vol_df if m == "score_vol_scaled" else None
        return _rebalance(score_panel_to_weights(
            rank, mode=m, top_k=top_k, max_single_weight=cap, vol_df=vd),
            args.rebalance_days)

    weights_a = _weights(rank_a, mode_a)
    weights_d = _weights(rank_d, mode_d)

    # cost-sensitivity: 0 / 30 / 60 bps per-unit-turnover
    paths = {}
    for label, w in (("path_A_non_ml_composite", weights_a),
                     ("path_D_xgb_ranker_ndcg", weights_d)):
        paths[label] = {
            f"cost_{c}bps": portfolio_metrics(
                w, close, benchmark=spy, cost_bps=float(c))
            for c in (0, 30, 60)}

    # verdict at the realistic 30bps cost — net Sharpe AND MaxDD
    a30 = paths["path_A_non_ml_composite"]["cost_30bps"]
    d30 = paths["path_D_xgb_ranker_ndcg"]["cost_30bps"]
    sharpe_beat = d30["annualized_sharpe"] >= a30["annualized_sharpe"]
    maxdd_beat = abs(d30["max_drawdown"]) <= abs(a30["max_drawdown"])
    verdict = "PASS" if (sharpe_beat and maxdd_beat) else "FAIL"

    out = {
        "prd": "docs/prd/20260521-rerisk-and-ml-training-audit-prd.md §9 P4",
        "window": f"{args.start_year}-{args.end_year} (train-only)",
        "n_walk_forward_folds": n_folds,
        "concatenated_oos": oos,
        "mode_a": mode_a, "mode_d": mode_d,
        "top_k": top_k, "single_name_cap": cap,
        "rebalance_days": args.rebalance_days,
        "cost_levels_bps": [0, 30, 60],
        "paths": paths,
        "verdict": verdict,
        "verdict_basis": ("path D vs A on net Sharpe AND MaxDD at 30bps "
                          "cost. Multi-fold walk-forward, train-only "
                          "window. §9.6 DSR/PBO is the next step."),
        "sharpe_beat": bool(sharpe_beat), "maxdd_beat": bool(maxdd_beat),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    }
    out_path = (PROJ / args.out_dir
                / f"ml_rank_portfolio_acceptance_{out['generated_utc']}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    for label in ("path_A_non_ml_composite", "path_D_xgb_ranker_ndcg"):
        m = paths[label]["cost_30bps"]
        print(f"  {label} @30bps: Sharpe={m['annualized_sharpe']} "
              f"MaxDD={m['max_drawdown']} cum={m['cum_return']} "
              f"turnover={m['turnover_mean']}")
    print(f"  verdict={verdict} (sharpe_beat={sharpe_beat} "
          f"maxdd_beat={maxdd_beat})")
    print(f"  → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
