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


def main() -> int:
    ap = argparse.ArgumentParser(description="P4 portfolio acceptance harness")
    ap.add_argument("--start-year", type=int, default=2012)
    ap.add_argument("--end-year", type=int, default=2017,
                    help="< 2018 keeps the window train-only")
    ap.add_argument("--horizon-days", type=int, default=21)
    ap.add_argument("--out-dir", default="data/audit")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    alloc = yaml.safe_load((PROJ / "config/ml_allocation.yaml").read_text())
    mode = alloc["default_mapping_mode"]
    top_k = int(alloc["mapping_modes"][mode]["top_k"])
    cap = float(alloc["constraints"]["max_single_name_weight"])

    print(f"=== P4 portfolio acceptance  {args.start_year}-{args.end_year}"
          f"  mode={mode} top_k={top_k} ===")
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

    dates = close.index
    mid = dates[int(len(dates) * 0.6)]   # 60% train / 40% held-out test
    spy = close.get("SPY")
    print(f"  train [{dates[0].date()}..{mid.date()}]  "
          f"test [{mid.date()}..{dates[-1].date()}]")

    # --- path A: non-ML Stage-1 cycle06 composite -------------------------
    rank_a = _stage1_composite_rank(factors, CYCLE06)
    rank_a_test = rank_a.loc[rank_a.index > mid]
    weights_a = score_panel_to_weights(
        rank_a_test, mode=mode, top_k=top_k, max_single_weight=cap)
    metrics_a = portfolio_metrics(weights_a, close, benchmark=spy)

    # --- path D: XGBRanker (rank:ndcg) ranker-to-portfolio ----------------
    feats = {f: factors[f] for f in CYCLE06}
    labels = make_forward_return_labels(close, args.horizon_days)
    train_feats = {f: p.loc[p.index <= mid] for f, p in feats.items()}
    train_labels = labels.loc[labels.index <= mid]
    model = XGBRankerRankModel(objective="rank:ndcg", n_estimators=50,
                               max_depth=4, random_state=args.seed)
    model.fit(train_feats, train_labels)
    test_feats = {f: p.loc[p.index > mid] for f, p in feats.items()}
    rank_d = model.predict_rank(test_feats)
    weights_d = score_panel_to_weights(
        rank_d, mode=mode, top_k=top_k, max_single_weight=cap)
    metrics_d = portfolio_metrics(weights_d, close, benchmark=spy)

    # --- verdict ----------------------------------------------------------
    a, d = metrics_a, metrics_d
    sharpe_beat = d["annualized_sharpe"] >= a["annualized_sharpe"]
    maxdd_beat = abs(d["max_drawdown"]) <= abs(a["max_drawdown"])
    verdict = "PASS" if (sharpe_beat and maxdd_beat) else "FAIL"

    out = {
        "prd": "docs/prd/20260521-rerisk-and-ml-training-audit-prd.md §9 P4",
        "window": f"{args.start_year}-{args.end_year} (train-only)",
        "test_window": f"{mid.date()}..{dates[-1].date()}",
        "allocation_mode": mode, "top_k": top_k, "single_name_cap": cap,
        "path_A_non_ml_composite": a,
        "path_D_xgb_ranker_ndcg": d,
        "verdict": verdict,
        "verdict_basis": ("path D vs A on Sharpe AND MaxDD — single "
                          "train/test split smoke; full multi-fold "
                          "walk-forward + DSR/PBO is the next step"),
        "sharpe_beat": bool(sharpe_beat), "maxdd_beat": bool(maxdd_beat),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    }
    out_path = (PROJ / args.out_dir
                / f"ml_rank_portfolio_acceptance_{out['generated_utc']}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"  path A: Sharpe={a['annualized_sharpe']} MaxDD={a['max_drawdown']}"
          f" cum={a['cum_return']} turnover={a['turnover_mean']}")
    print(f"  path D: Sharpe={d['annualized_sharpe']} MaxDD={d['max_drawdown']}"
          f" cum={d['cum_return']} turnover={d['turnover_mean']}")
    print(f"  verdict={verdict} (sharpe_beat={sharpe_beat} "
          f"maxdd_beat={maxdd_beat})")
    print(f"  → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
