#!/usr/bin/env python
"""AUDIT — quantify the P4 walk-forward embargo leak (2026-05-22).

Audit finding C1: `core/research/ml/pipeline.py::iter_folds` trims the
train window by `embargo_days` CALENDAR days, but the label horizon is
counted in TRADING days. A 21-trading-day forward label spans ~28-31
calendar days, so trimming only 21 calendar days leaves ~5 trading days
of train labels whose forward window reaches into the validation
window — a real lookahead leak.

This script runs the SAME P4 path-D pipeline twice and compares:
  - buggy   : embargo = horizon CALENDAR days (current production code)
  - correct : embargo = horizon TRADING days (trim by index position)

A material drop in path-D Sharpe under the correct embargo means the
P4 "PASS" verdict was partly leak-supported.

Audit only — does not modify any production module.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "dev/scripts/ml"))

import pandas as pd  # noqa: E402

from walk_forward_rank_sign import _load_panel  # noqa: E402
from portfolio_acceptance import (  # noqa: E402
    CYCLE06, _stage1_composite_rank, _rebalance,
)
from core.research.ml.labels import make_forward_return_labels  # noqa: E402
from core.research.ml.xgb_rank_model import XGBRankerRankModel  # noqa: E402
from core.research.allocation.score_to_weight import score_panel_to_weights  # noqa: E402
from core.research.allocation.portfolio_metrics import portfolio_metrics  # noqa: E402

START_Y, END_Y = 2012, 2017
TRAIN_WIN, VAL_WIN = 3, 1
HORIZON = 21
SEED = 42


def _folds(close_index):
    """Yield (train_start, train_end_buggy, train_end_correct, val_start,
    val_end) for each rolling fold."""
    k = 0
    while True:
        tr_s_y = START_Y + k
        tr_e_y = tr_s_y + TRAIN_WIN - 1
        va_s_y = tr_e_y + 1
        va_e_y = va_s_y + VAL_WIN - 1
        if va_e_y > END_Y:
            break
        val_start = pd.Timestamp(f"{va_s_y}-01-01")
        # buggy: Dec-31 minus HORIZON calendar days (production iter_folds)
        te_buggy = pd.Timestamp(f"{tr_e_y}-12-31") - pd.Timedelta(days=HORIZON)
        # correct: drop the last HORIZON trading days before val_start
        pre_val = close_index[close_index < val_start]
        te_correct = pre_val[-(HORIZON + 1)]
        yield (pd.Timestamp(f"{tr_s_y}-01-01"), te_buggy, te_correct,
               val_start, pd.Timestamp(f"{va_e_y}-12-31"))
        k += 1


def _run(mode: str, panel, factors, close, spy) -> dict:
    feats = {f: factors[f] for f in CYCLE06}
    labels = make_forward_return_labels(close, HORIZON)
    rank_parts = []
    fold_log = []
    for tr_s, te_buggy, te_correct, va_s, va_e in _folds(close.index):
        train_end = te_buggy if mode == "buggy" else te_correct
        tr_feats = {f: p.loc[(p.index >= tr_s) & (p.index <= train_end)]
                    for f, p in feats.items()}
        tr_labels = labels.loc[(labels.index >= tr_s)
                               & (labels.index <= train_end)]
        va_feats = {f: p.loc[(p.index >= va_s) & (p.index <= va_e)]
                    for f, p in feats.items()}
        m = XGBRankerRankModel(objective="rank:ndcg", n_estimators=50,
                               max_depth=4, random_state=SEED)
        m.fit(tr_feats, tr_labels)
        rank_parts.append(m.predict_rank(va_feats))
        fold_log.append(f"{tr_s.date()}..{train_end.date()} -> "
                        f"{va_s.date()}..{va_e.date()}")
    rank_d = pd.concat(rank_parts).sort_index()
    w = _rebalance(score_panel_to_weights(rank_d, mode="top_k_capped",
                                          top_k=10, max_single_weight=0.40),
                   21)
    return {"folds": fold_log,
            "metrics_30bps": portfolio_metrics(w, close, benchmark=spy,
                                               cost_bps=30.0)}


def main() -> int:
    print("=== AUDIT: P4 embargo-leak quantification ===")
    panel, factors, _ = _load_panel()
    start = pd.Timestamp(f"{START_Y}-01-01")
    end = pd.Timestamp(f"{END_Y}-12-31")
    close = panel["close"].loc[(panel["close"].index >= start)
                               & (panel["close"].index <= end)]
    factors = {k: v.loc[(v.index >= start) & (v.index <= end)]
               for k, v in factors.items() if not v.empty}
    spy = close.get("SPY")

    buggy = _run("buggy", panel, factors, close, spy)
    correct = _run("correct", panel, factors, close, spy)

    b, c = buggy["metrics_30bps"], correct["metrics_30bps"]
    print("\n  fold train_end (buggy calendar-day embargo):")
    for f in buggy["folds"]:
        print(f"    {f}")
    print("  fold train_end (correct trading-day embargo):")
    for f in correct["folds"]:
        print(f"    {f}")
    print(f"\n  path-D @30bps  buggy   : Sharpe={b['annualized_sharpe']} "
          f"MaxDD={b['max_drawdown']} cum={b['cum_return']}")
    print(f"  path-D @30bps  correct : Sharpe={c['annualized_sharpe']} "
          f"MaxDD={c['max_drawdown']} cum={c['cum_return']}")
    d_sharpe = round(b["annualized_sharpe"] - c["annualized_sharpe"], 4)
    print(f"\n  leak impact on Sharpe = {d_sharpe} "
          f"({'leak-supported' if d_sharpe > 0.1 else 'small'})")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {
        "audit": "C1 embargo-leak quantification",
        "horizon_days": HORIZON,
        "buggy_calendar_embargo": buggy,
        "correct_trading_embargo": correct,
        "sharpe_leak_delta": d_sharpe,
        "generated_utc": ts,
    }
    path = PROJ / f"data/audit/embargo_leak_quant_{ts}.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(f"  -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
