"""PRD-3 RB3 — B1 intraday acceptance EXPERIMENT.

experiment round. AC (PRD-3 ralph-loop RB3): 跑+记 leakage-correct
+ intraday 3x cost + A/B de-confound (info vs timing split) +
not-worse-than-60m-only (else retire per naive-voting precedent +
root-cause); verdict. Negative does NOT terminate the loop
(config-scoped, no blanket).

Single SoT (importlib): cycle06 _load_panel (full OHLCV, selector
= train+val, sealed 2026 NEVER read) + L3 leakage adapters → core.
research.label_leakage. RB1 gate (assert_component_b_prerequisites
+ assert_archetype_differentiated 'intraday_reversal') ROUTED
FIRST per RB2 contract. RB2 4 features
(open_range_breakout / vwap_deviation / realized_vol_regime /
intraday_volume_z) computed per (date,symbol) from REAL 30m bars.
RA2/RB2 train_b1 shallow XGB. R11 sensitivity_multiplier=3.0 for
the 3x-cost arm.

Sealed/integrity discipline: bulk ~25k intraday set has weekend
pollution + spans 2026 → CURATED 10-sym liquid subset, hard filter
year<2026, bar-integrity smoke FIRST (0 weekend + no 2026 +
monotone). Single 30m TF (B1 = day-level summary scalars; the
'multi-TF cascade' is RB4 territory).

A/B de-confound 3-point (chart_native precedent, R13/RA4 reused):
  p0 = 60m-only baseline (no intraday signal)
  p1 = INFO-only (B1 pred sign used as include/veto, no sizing
      from prediction magnitude → info contribution only)
  p2 = FULL B1 signal (pred used as sized weight, normalized →
      info + timing contribution)

IRONCLAD: IC-layer / construction-overlay layer; binding gate =
PRD-2 NAV Track-A. intraday-ML is the highest self-deception
program — verdict MOST strict; honest non-blanket if FAIL.
Usage: python dev/scripts/prd3/rb3_b1_acceptance_experiment.py [--smoke]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.execution.cost_model import CostModel
from core.ml.xgb_alpha import compute_rank_ic
from core.research.b1_intraday_features import (
    B1Config, compute_b1_day_features, train_b1,
)
from core.research.component_b_gate import assert_component_b_prerequisites
from core.research.temporal_split import train_year_set

_H = 21
_LIQUID = ("SPY", "QQQ", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY",
           "AAPL", "MSFT")
_INTRADAY = PROJ / "data/intraday/30m"


def _c6_panel():
    p = PROJ / "dev/scripts/cycle06/cycle06_track_a_eval.py"
    s = importlib.util.spec_from_file_location("_c6", p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m._load_panel()


def _load_30m(sym):
    f = _INTRADAY / f"{sym}.parquet"
    if not f.exists():
        return None
    df = pd.read_parquet(f); df.index = pd.to_datetime(df.index)
    return df[df.index.year < 2026]  # SEALED GUARD


def _bar_integrity(close, intraday):
    wknd = int((pd.DatetimeIndex(close.index).weekday >= 5).sum())
    yrs = sorted({t.year for t in close.index})
    assert 2026 not in yrs, f"SEALED: 2026 {yrs}"
    assert wknd == 0, f"weekend rows {wknd}"
    for k, df in intraday.items():
        idxs = pd.DatetimeIndex(df.index)
        w = int((idxs.weekday >= 5).sum())
        ys = {int(y) for y in idxs.year.unique()}
        assert 2026 not in ys, f"SEALED {k}: 2026"
        assert w == 0, f"weekend rows in {k}={w}"
    return {"weekend_rows": wknd, "years": yrs,
            "intraday_pairs": len(intraday)}


def _b1_features_panel(intraday, dates, syms):
    rows = []
    for d in dates:
        for s in syms:
            df = intraday.get(s)
            if df is None:
                continue
            day = df[df.index.normalize() == d.normalize()]
            if len(day) < 3:
                continue
            ohlcv = day[["open", "high", "low", "close",
                         "volume"]].to_numpy()
            f = compute_b1_day_features(ohlcv)
            if any(np.isnan(list(f.values()))):
                continue
            rows.append({"date": d, "symbol": s, **f})
    return pd.DataFrame(rows)


def _nav(pred_signed_weights, daily_ret, cm, syms,
         sensitivity_multiplier=1.0):
    """daily NAV from a {date → Series of symbol weights} mapping."""
    dates = daily_ret.index
    w_prev = pd.Series(0.0, index=syms)
    nav = [1.0]
    for i in range(1, len(dates)):
        d = dates[i]
        w = pred_signed_weights.get(d.normalize(), w_prev)
        w = w.reindex(syms).fillna(0.0)
        turn = float((w - w_prev).abs().sum())
        cbps = cm.cost_bps("SPY", "intraday", 15.0,
                           sensitivity_multiplier) / 1e4
        r = float((w_prev * daily_ret.iloc[i].reindex(syms).fillna(0)
                   ).sum())
        nav.append(nav[-1] * (1 + r) - nav[-1] * turn * cbps)
        w_prev = w
    s = pd.Series(nav, index=dates)
    ret = s.pct_change().dropna()
    sh = (float(ret.mean() / ret.std() * np.sqrt(252))
          if ret.std() > 0 else 0.0)
    return {"terminal": float(s.iloc[-1] - 1.0), "sharpe": sh}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    assert_component_b_prerequisites()  # RB1 gate FIRST
    panel, _f, _m, sc = _c6_panel()
    close = panel["close"]
    syms = [s for s in _LIQUID if s in close.columns]
    intraday = {}
    for s in syms:
        df = _load_30m(s)
        if df is not None and not df.empty:
            intraday[s] = df
    integ = _bar_integrity(close, intraday)
    tr_years = set(train_year_set(sc))

    idx = pd.DatetimeIndex(close.index)
    me = [pd.Timestamp(d) for d in pd.Series(idx, index=idx).groupby(
        [idx.year, idx.month]).last().to_numpy()]
    feats = _b1_features_panel(intraday, me, syms)
    pos = {ts: i for i, ts in enumerate(close.index)}
    feats = feats[feats.date.isin(pos)]
    feats["start_pos"] = feats.date.map(pos)
    fwd = close.shift(-_H) / close - 1.0
    feats["y"] = feats.apply(
        lambda r: fwd.at[r.date, r.symbol]
        if r.symbol in fwd.columns else np.nan, axis=1)
    feats = feats.dropna(subset=["y"])
    feats["is_train"] = feats.date.dt.year.isin(tr_years)

    if args.smoke:
        print(f"SMOKE OK: bar-integrity {integ} | rows={len(feats)} "
              f"syms={syms} (sealed 2026 excluded)")
        return 0

    feat_cols = ["open_range_breakout", "vwap_deviation",
                 "realized_vol_regime", "intraday_volume_z"]
    tr = feats[feats.is_train].reset_index(drop=True)
    va = feats[~feats.is_train].reset_index(drop=True)
    sym_codes = {s: i for i, s in enumerate(sorted(feats.symbol.unique()))}
    res = train_b1(
        tr[feat_cols], pd.Series(tr.y.to_numpy()),
        start_pos=tr.start_pos.to_numpy(), horizon=_H,
        groups=np.array([sym_codes[s] for s in tr.symbol]),
        cfg=B1Config(archetype="intraday_reversal",
                     max_depth=3, n_estimators=300))
    va_pred = res.model.predict(va[feat_cols])
    ic_va = compute_rank_ic(pd.Series(va.y.to_numpy()), va_pred,
                            pd.Series(va.date.to_numpy()))[0]

    # convert per-(date,sym) predictions → per-date weights (top-N
    # rank cross-section); base weights = 1/N equal-weight liquid set.
    base_w = pd.Series(1.0 / len(syms), index=syms)
    w_off = {}; w_info = {}; w_full = {}
    va["pred"] = va_pred
    for d, g in va.groupby("date"):
        d0 = d.normalize()
        w_off[d0] = base_w.copy()
        # info-only: include only positive-pred symbols (sign veto),
        # equal-weight among them
        pos_syms = list(g[g.pred > 0]["symbol"])
        if pos_syms:
            w_info[d0] = pd.Series(1.0 / len(pos_syms),
                                   index=pos_syms).reindex(syms
                                                            ).fillna(0)
        else:
            w_info[d0] = base_w.copy()
        # full: pred-weighted (long-only via clip>=0), normalize
        p = g.set_index("symbol")["pred"].clip(lower=0)
        if p.sum() > 0:
            w_full[d0] = (p / p.sum()).reindex(syms).fillna(0)
        else:
            w_full[d0] = base_w.copy()

    cm = CostModel(load_config(str(PROJ / "config")).cost_model)
    daily_ret = close[syms].pct_change()
    p0 = _nav(w_off, daily_ret, cm, syms)
    p1 = _nav(w_info, daily_ret, cm, syms)
    p2 = _nav(w_full, daily_ret, cm, syms)
    p2_3x = _nav(w_full, daily_ret, cm, syms,
                 sensitivity_multiplier=3.0)

    not_worse = (p2["terminal"] >= p0["terminal"] - 1e-9
                 and p2["sharpe"] >= p0["sharpe"] - 1e-9)
    cost3x_pos = p2_3x["terminal"] > 0.0
    info_contrib = p1["terminal"] - p0["terminal"]
    timing_contrib = p2["terminal"] - p1["terminal"]
    verdict = ("PASS" if (not_worse and cost3x_pos)
               else "FAIL_recorded_root_cause")
    out = {
        "experiment": "rb3_b1_acceptance",
        "sealed_2026_read": False, "bar_integrity": integ,
        "n_rows": {"train": int(len(tr)), "val": int(len(va))},
        "val_ic": float(ic_va),
        "ab_deconfound_3point": {
            "p0_60m_only": p0, "p1_info_only_veto": p1,
            "p2_full_b1_signal": p2,
            "information_contribution_terminal": info_contrib,
            "timing_contribution_terminal": timing_contrib,
            "method": "chart_native 3-point precedent (R13/RA4)"},
        "intraday_3x_cost": {"p2_at_3x": p2_3x,
                             "still_positive": bool(cost3x_pos)},
        "not_worse_than_60m_only": {
            "pass": bool(not_worse),
            "p2_terminal": p2["terminal"], "p0_terminal": p0["terminal"],
            "p2_sharpe": p2["sharpe"], "p0_sharpe": p0["sharpe"]},
        "archetype": res.archetype, "verdict": verdict,
        "intraday_ml_self_deception_caveat": (
            "intraday-ML = highest self-deception risk program "
            "(PRD-3 §3). RB3 verdict MOST strict. Negative → "
            "retire per naive-voting precedent + ROOT CAUSE, no "
            "termination, no blanket. IC-layer only; binding gate "
            "= PRD-2 NAV Track-A. NOT a promotion (PRD-3 funnel)."),
    }
    p = Path("data/audit/ml_redo/rb3_b1_acceptance.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"RB3 verdict={verdict} -> {p}")
    print(f"  val_ic={ic_va:+.4f}")
    print(f"  p0(60m-only)   term={p0['terminal']:+.4f} sh={p0['sharpe']:+.2f}")
    print(f"  p1(info-veto)  term={p1['terminal']:+.4f} sh={p1['sharpe']:+.2f}")
    print(f"  p2(full B1)    term={p2['terminal']:+.4f} sh={p2['sharpe']:+.2f}")
    print(f"  info_contrib={info_contrib:+.4f} timing_contrib={timing_contrib:+.4f}")
    print(f"  p2@3x-cost term={p2_3x['terminal']:+.4f} still_positive={cost3x_pos}")
    print(f"  not_worse_than_60m_only={not_worse}")
    print(f"  intraday-ML self-deception caveat: IC-layer, not a promotion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
