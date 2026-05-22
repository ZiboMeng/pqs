#!/usr/bin/env python
"""S6 — ranking-baseline real out-of-sample validation
(supplement PRD 20260522 §2 S6; the §12.6 deferred-model unlock gate).

All prior P4 acceptance ran on a TRAIN-ONLY smoke window. S6 runs the
ranker-to-portfolio path on the `config/temporal_split.yaml` VALIDATION
partition (2018/2019/2021/2023/2025) — genuine out-of-sample.

Per validation year vy: the XGBRanker (rank:ndcg) is trained ONLY on
train_years strictly before vy (purged `horizon` trading bars at the
boundary — audit C1), then predicts on vy; the path-D portfolio +
path-A non-ML composite are scored on vy. Per-year net Sharpe / MaxDD /
vs-SPY are reported, plus the §9.6 DSR/PBO on the concatenated
validation result.

temporal_split discipline: validation_years are the holdout designated
for exactly this — evaluating on them is their purpose. Sealed 2026 is
NEVER touched.

Output: data/audit/ml_s6_oos_validation_<ts>.json

Usage: python dev/scripts/ml/s6_oos_validation.py
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from walk_forward_rank_sign import _load_panel  # noqa: E402
from portfolio_acceptance import _stage1_composite_rank, _rebalance  # noqa: E402
from core.research.ml.labels import make_forward_return_labels  # noqa: E402
from core.research.ml.xgb_rank_model import XGBRankerRankModel  # noqa: E402
from core.research.ml.lgbm_rank_model import LGBMRankerRankModel  # noqa: E402
from core.research.ml.rank_model import LinearBaselineRankModel  # noqa: E402
from core.research.allocation.score_to_weight import score_panel_to_weights  # noqa: E402
from core.research.allocation.portfolio_metrics import portfolio_metrics  # noqa: E402
from core.research.allocation.constraints import apply_turnover_cap  # noqa: E402
from core.research.allocation.exit_policy import (  # noqa: E402
    apply_signal_decay_exit, apply_turnover_band,
)
from core.research.overfit_metrics import deflated_sharpe_ratio  # noqa: E402
from core.research.mining_pbo import compute_mining_pbo  # noqa: E402

CYCLE06 = ("drawup_from_252d_low", "trend_tstat_20d", "ret_2d")
SEALED_YEAR = 2026


def _partition():
    d = yaml.safe_load(
        (PROJ / "config/temporal_split.yaml").read_text())["partition"]
    ty = []
    for e in d["train_years"]:
        if "range" in e:
            ty += list(range(e["range"][0], e["range"][1] + 1))
        else:
            ty.append(e["year"])
    vy = sorted(e["year"] for e in d["validation_years"])
    return sorted(ty), vy


def main() -> int:
    ap = argparse.ArgumentParser(description="S6 ranking-baseline OOS validation")
    ap.add_argument("--horizon-days", type=int, default=21)
    ap.add_argument("--rebalance-days", type=int, default=21)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", default="data/audit")
    args = ap.parse_args()

    train_years, val_years = _partition()
    assert SEALED_YEAR not in val_years, "sealed 2026 must not be validated"
    alloc = yaml.safe_load((PROJ / "config/ml_allocation.yaml").read_text())
    top_k = int(alloc["mapping_modes"][alloc["default_mapping_mode"]]["top_k"])
    cap = float(alloc["constraints"]["max_single_name_weight"])
    turnover_cap = float(alloc["constraints"]["turnover_cap_daily"])
    decay = float(alloc["exit_policy"]["signal_decay"]["exit_when_rank_below"])
    band = float(alloc["exit_policy"]["turnover_band"]["rebalance_band"])

    print(f"=== S6 ranking-baseline OOS validation ===")
    print(f"  train_years={train_years}")
    print(f"  validation_years={val_years}  (sealed {SEALED_YEAR} untouched)")
    panel, factors, _ = _load_panel()
    close = panel["close"]
    spy = close.get("SPY")
    feats = {f: factors[f] for f in CYCLE06}
    labels = make_forward_return_labels(close, args.horizon_days)
    composite = _stage1_composite_rank(factors, CYCLE06)

    def _weights(rank):
        w = _rebalance(score_panel_to_weights(
            rank, mode="top_k_capped", top_k=top_k, max_single_weight=cap),
            args.rebalance_days)
        w = apply_turnover_cap(w, turnover_cap)
        w = apply_signal_decay_exit(w, rank, exit_threshold=decay)
        w = apply_turnover_band(w, band)
        return w

    def _rankers():
        return {
            "xgb": XGBRankerRankModel(objective="rank:ndcg", n_estimators=50,
                                      max_depth=4, random_state=args.seed),
            "linear": LinearBaselineRankModel(),
            "lgbm": LGBMRankerRankModel(n_estimators=50, max_depth=4,
                                        random_state=args.seed),
        }

    per_year = {}
    d_ret_parts, a_ret_parts = [], []
    # model-diverse return parts for a non-degenerate §9.6 PBO sweep
    sweep_ret = {"A_composite": [], "D_xgb": [], "D_linear": [], "D_lgbm": []}
    for vy in val_years:
        vy_s = pd.Timestamp(f"{vy}-01-01")
        vy_e = pd.Timestamp(f"{vy}-12-31")
        # train years strictly before vy; purge `horizon` trading bars
        # off the train tail so a train label cannot reach into vy.
        tr_years = [y for y in train_years if y < vy]
        pre = close.index[close.index < vy_s]
        purge_end = (pre[-(args.horizon_days + 1)]
                     if len(pre) > args.horizon_days else pre[-1])
        tr_dates = close.index[(close.index.year.isin(tr_years))
                               & (close.index <= purge_end)]
        va_dates = close.index[(close.index >= vy_s) & (close.index <= vy_e)]
        if len(va_dates) < 20:
            per_year[vy] = {"error": "validation-year data missing"}
            continue
        tr_feats = {f: p.loc[tr_dates] for f, p in feats.items()}
        tr_labels = labels.loc[tr_dates]
        va_feats = {f: p.loc[va_dates] for f, p in feats.items()}
        # train 3 model families on this vy's train slice
        ranks = {}
        for nm, mdl in _rankers().items():
            mdl.fit(tr_feats, tr_labels)
            ranks[nm] = mdl.predict_rank(va_feats)
        rank_d = ranks["xgb"]                    # the promoted ranker
        rank_a = composite.reindex(index=rank_d.index)
        wd, wa = _weights(rank_d), _weights(rank_a)
        md = portfolio_metrics(wd, close, benchmark=spy, cost_bps=30.0)
        ma = portfolio_metrics(wa, close, benchmark=spy, cost_bps=30.0)
        per_year[vy] = {
            "train_years_used": tr_years,
            "path_D": md, "path_A": ma,
        }
        # concatenated daily returns for the §9.6 stats
        rets = close.reindex(wd.index).pct_change().fillna(0.0)
        cols = [c for c in wd.columns if c in rets.columns]

        def _dret(w):
            return (w[cols].shift(1).fillna(0.0) * rets[cols]).sum(axis=1)
        d_ret_parts.append(_dret(wd))
        a_ret_parts.append(_dret(wa))
        # model-diverse sweep for PBO (composite + 3 model families)
        sweep_ret["A_composite"].append(_dret(wa))
        sweep_ret["D_xgb"].append(_dret(wd))
        sweep_ret["D_linear"].append(_dret(_weights(ranks["linear"])))
        sweep_ret["D_lgbm"].append(_dret(_weights(ranks["lgbm"])))
        print(f"  {vy}: path_D Sharpe={md['annualized_sharpe']} "
              f"MaxDD={md['max_drawdown']} | path_A Sharpe="
              f"{ma['annualized_sharpe']} MaxDD={ma['max_drawdown']}")

    ok_years = [y for y in val_years if "error" not in per_year[y]]
    d_sharpes = [per_year[y]["path_D"]["annualized_sharpe"] for y in ok_years]
    a_sharpes = [per_year[y]["path_A"]["annualized_sharpe"] for y in ok_years]
    d_maxdds = [per_year[y]["path_D"]["max_drawdown"] for y in ok_years]
    mean_d, mean_a = float(np.mean(d_sharpes)), float(np.mean(a_sharpes))
    worst_maxdd = float(min(d_maxdds))           # most negative

    # §9.6 — DSR on the concatenated validation daily return; PBO over
    # the (month × {A, D}) matrix.
    d_ret = pd.concat(d_ret_parts).sort_index()
    a_ret = pd.concat(a_ret_parts).sort_index()
    ledger = json.loads(
        (PROJ / "data/audit/ml_trial_ledger.json").read_text())
    n_trials = len(ledger["trials"])
    try:
        dsr = deflated_sharpe_ratio(d_ret.tolist(), n_trials=n_trials)
    except Exception as exc:  # noqa: BLE001
        dsr = {"error": f"{type(exc).__name__}: {exc}"}
    # PBO over a model-DIVERSE sweep (composite + 3 model families) —
    # a 2-column (A,D) matrix is degenerate (see P4 R17).
    sweep_monthly = []
    for nm in ("A_composite", "D_xgb", "D_linear", "D_lgbm"):
        r = pd.concat(sweep_ret[nm]).sort_index()
        sweep_monthly.append((1 + r).resample("ME").prod() - 1)
    pbo = compute_mining_pbo(
        pd.concat(sweep_monthly, axis=1).dropna().to_numpy())

    sharpe_beat = mean_d >= mean_a
    maxdd_ok = all(abs(x) <= 0.20 for x in d_maxdds)
    verdict = "PASS" if (sharpe_beat and maxdd_ok) else "FAIL"

    out = {
        "prd": "supplement 20260522 §2 S6 — ranking-baseline OOS validation",
        "train_years": train_years,
        "validation_years": val_years,
        "per_validation_year": per_year,
        "aggregate": {
            "mean_path_D_sharpe": round(mean_d, 4),
            "mean_path_A_sharpe": round(mean_a, 4),
            "worst_path_D_maxdd": round(worst_maxdd, 4),
            "per_year_maxdd_all_within_20pct": bool(maxdd_ok),
        },
        "overfit_control": {
            "n_trials": n_trials,
            "dsr": dsr,
            "pbo": pbo,
        },
        "verdict": verdict,
        "verdict_basis": ("path-D mean net Sharpe ≥ path-A AND every "
                          "validation-year MaxDD ≤ 20% invariant. "
                          "Stress-slice MaxDD is a separate check (S6b)."),
        "sharpe_beat": bool(sharpe_beat),
        "maxdd_within_invariant": bool(maxdd_ok),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    }
    out_path = (PROJ / args.out_dir
                / f"ml_s6_oos_validation_{out['generated_utc']}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n  aggregate: mean path-D Sharpe={mean_d:.4f} vs path-A "
          f"{mean_a:.4f}; worst path-D MaxDD={worst_maxdd:.4f}")
    print(f"  §9.6: n_trials={n_trials} "
          f"dsr={dsr.get('deflated_sharpe') if isinstance(dsr, dict) else dsr} "
          f"pbo={pbo.get('pbo')}")
    print(f"  VERDICT = {verdict} (sharpe_beat={sharpe_beat} "
          f"maxdd_within_invariant={maxdd_ok})")
    print(f"  → {out_path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
