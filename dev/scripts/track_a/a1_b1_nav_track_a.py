"""PRD-3 → PRD-2 NAV Track-A: A1 (RA1+RA2) + B1 (RB2) candidates.

binding-gate gate. AC: produce a structured acceptance verdict for
EACH of the A1 (daily-close engineered+shallow-XGB) and B1
(intraday 4-feature engineered+shallow-XGB) signal candidates,
running them through the SAME canonical NAV evaluator that
cycle06/08 use — ``core.research.harness.composite_evaluator.
evaluate_composite_spec`` — so the Track-A numbers are comparable
to historical candidates without writing any new NAV engine.

Honest scope (R4/R6/R7): evaluate_composite_spec ALREADY exists +
is the canonical NAV path (used by cycle06/08, full-period +
per-validation-year + stress-slice + vs-SPY/QQQ + concentration in
one call). DELEGATED. The genuinely-new Track-A surface:

  1. wrap each ML candidate's prediction panel as a SINGLE-feature
     ``ResearchCompositeSpec(features=("...pred",), weights=(1.0,))``
     — this is the clean adapter that requires NO new Strategy class.
  2. leakage-correct walk-forward: train on train_years only,
     predict on the full panel (training rows preserved for the
     model fit; the OOS evaluation is on val_years). Sealed 2026
     NEVER read.
  3. Track-A acceptance gates per CLAUDE.md invariants:
     - vs SPY HARD (full validation period) — strategy_excess > 0
     - per-validation-year MaxDD ≤ 20% (hard invariant)
     - 2008-equivalent stress-slice MaxDD ≤ 25% (CLAUDE.md 2026-05-02)
     - concentration: top1 ≤ 40%, top3 ≤ 70%
     - vs QQQ diagnostic only (NOT blocking; QQQ deprecated 2026-05-02)
     - 6-regime / 2x-cost robustness (evaluator-reported)

Per the PRD-3 funnel discipline: PASS here does NOT promote — it
unlocks the *next* phase (forward observation + sealed gate). FAIL
→ ROOT CAUSE which gate broke (TC? cost? regime? concentration?),
not a blanket "ML doesn't work".

Usage: python dev/scripts/track_a/a1_b1_nav_track_a.py [--smoke]
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

from core.mining.research_miner import ResearchCompositeSpec
from core.research.engineered_features import build_engineered_panel
from core.research.a1_pipeline import A1Config, train_a1
from core.research.b1_intraday_features import (
    B1Config, compute_b1_day_features, train_b1,
)
from core.research.component_b_gate import assert_component_b_prerequisites
from core.research.harness import HarnessConfig, evaluate_composite_spec
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER, make_unified_cluster_map,
)
from core.research.temporal_split import (
    train_year_set, validation_year_set,
)

_H = 21
_INTRADAY_30M = PROJ / "data/intraday/30m"


def _c6_panel():
    p = PROJ / "dev/scripts/cycle06/cycle06_track_a_eval.py"
    s = importlib.util.spec_from_file_location("_c6", p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m._load_panel()


def _bar_integrity(close):
    idx = pd.DatetimeIndex(close.index)
    wknd = int((idx.weekday >= 5).sum())
    yrs = sorted({t.year for t in idx})
    assert 2026 not in yrs, f"SEALED: 2026 {yrs}"
    assert wknd == 0, f"weekend rows {wknd}"
    return {"weekend_rows": wknd, "years": yrs}


# ── A1 prediction panel ──────────────────────────────────────────────
def _a1_pred_panel(panel, tr_years, val_years):
    """STRICT CHRONOLOGICAL year-by-year rolling walk-forward
    (R1-fixed: prior single-fit `train on all train_years` was a
    temporal-leakage bug under cycle06's INTERLEAVED selector
    partition — train_years={2009-17,20,22,24} vs val_years=
    {18,19,21,23,25} are time-interleaved; one model fit on all
    train_years would learn 2020/2022/2024 regularities and then
    "predict" earlier 2018/2019/2021 = looking-forward leakage).

    Fixed protocol: for each val_year Y in sorted ascending order,
    train a FRESH model on ``train_years ∩ {y < Y}`` only, then
    predict rows where ``year == Y``. The model fitting prediction
    for Y NEVER sees any year ≥ Y. Empty train-subset → skip Y
    (e.g. if val_years contained a year before any train year).
    """
    close = panel["close"]
    feat_map = build_engineered_panel(
        panel["open"], panel["high"], panel["low"], close,
        panel["volume"], close_windows=(20, 63), monthly_rank=False)
    feat_cols = list(feat_map.keys())
    idx = pd.DatetimeIndex(close.index)
    me = [pd.Timestamp(d) for d in pd.Series(idx, index=idx).groupby(
        [idx.year, idx.month]).last().to_numpy()]
    pos = {ts: i for i, ts in enumerate(close.index)}
    rows = []
    for d in me:
        if d not in pos or pos[d] + _H >= len(close.index):
            continue
        for sym in close.columns:
            ff = {k: v.at[d, sym] for k, v in feat_map.items()
                  if sym in v.columns}
            if any(pd.isna(list(ff.values()))):
                continue
            rows.append({"date": d, "symbol": sym,
                         "start_pos": pos[d],
                         "year": d.year, **ff})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(index=close.index, columns=close.columns)
    fwd = close.shift(-_H) / close - 1.0
    df["y"] = [float(fwd.at[r.date, r.symbol])
               if r.symbol in fwd.columns else np.nan
               for r in df.itertuples()]
    df = df.dropna(subset=["y"]).reset_index(drop=True)
    sym_codes = {s: i for i, s in enumerate(sorted(df.symbol.unique()))}
    out = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    folds = {}
    for Y in sorted(val_years):
        tr_subset = {y for y in tr_years if y < Y}
        if not tr_subset:
            folds[Y] = "skipped — no train year strictly before"
            continue
        tr = df[df.year.isin(tr_subset)].reset_index(drop=True)
        va = df[df.year == Y].reset_index(drop=True)
        if tr.empty or va.empty:
            folds[Y] = f"skipped — train={len(tr)} val={len(va)}"
            continue
        res = train_a1(
            tr[feat_cols], pd.Series(tr.y.to_numpy()),
            start_pos=tr.start_pos.to_numpy(), horizon=_H,
            groups=np.array([sym_codes[s] for s in tr.symbol]),
            cfg=A1Config(max_depth=3, n_estimators=300,
                         random_state=42))
        pred = res.model.predict(va[feat_cols])
        for r, p in zip(va.itertuples(), pred):
            out.at[r.date, r.symbol] = float(p)
        folds[Y] = f"train_years≤{Y-1} n={len(tr)} val n={len(va)}"
    print("  A1 walk-forward folds:")
    for y, s in folds.items():
        print(f"    {y}: {s}")
    return out


# ── B1 prediction panel ──────────────────────────────────────────────
def _load_30m(sym):
    f = _INTRADAY_30M / f"{sym}.parquet"
    if not f.exists():
        return None
    df = pd.read_parquet(f); df.index = pd.to_datetime(df.index)
    return df[df.index.year < 2026]  # SEALED


_LIQUID = ("SPY", "QQQ", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY",
           "AAPL", "MSFT")


def _b1_pred_panel(panel, tr_years, val_years):
    """Same STRICT CHRONOLOGICAL year-by-year rolling walk-forward
    as A1 — fresh model per val_year Y trained on
    ``train_years ∩ {y < Y} ∩ intraday-available`` only.
    """
    close = panel["close"]
    syms = [s for s in _LIQUID if s in close.columns]
    intraday = {}
    for s in syms:
        df = _load_30m(s)
        if df is not None and not df.empty:
            intraday[s] = df
    if not intraday:
        return pd.DataFrame(index=close.index, columns=close.columns)
    idx = pd.DatetimeIndex(close.index)
    me = [pd.Timestamp(d) for d in pd.Series(idx, index=idx).groupby(
        [idx.year, idx.month]).last().to_numpy()]
    pos = {ts: i for i, ts in enumerate(close.index)}
    rows = []
    for d in me:
        if d not in pos or pos[d] + _H >= len(close.index):
            continue
        for s in syms:
            df30 = intraday.get(s)
            if df30 is None:
                continue
            day = df30[df30.index.normalize() == d.normalize()]
            if len(day) < 3:
                continue
            ohlcv = day[["open", "high", "low", "close",
                         "volume"]].to_numpy()
            feats = compute_b1_day_features(ohlcv)
            if any(np.isnan(list(feats.values()))):
                continue
            rows.append({"date": d, "symbol": s, "start_pos": pos[d],
                         "year": d.year, **feats})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(index=close.index, columns=close.columns)
    feat_cols = ["open_range_breakout", "vwap_deviation",
                 "realized_vol_regime", "intraday_volume_z"]
    fwd = close.shift(-_H) / close - 1.0
    df["y"] = [float(fwd.at[r.date, r.symbol])
               if r.symbol in fwd.columns else np.nan
               for r in df.itertuples()]
    df = df.dropna(subset=["y"]).reset_index(drop=True)
    sym_codes = {s: i for i, s in enumerate(sorted(df.symbol.unique()))}
    out = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    folds = {}
    for Y in sorted(val_years):
        tr_subset = {y for y in tr_years if y < Y}
        if not tr_subset:
            folds[Y] = "skipped — no train year strictly before"
            continue
        tr = df[df.year.isin(tr_subset)].reset_index(drop=True)
        va = df[df.year == Y].reset_index(drop=True)
        if tr.empty or va.empty:
            folds[Y] = f"skipped — train={len(tr)} val={len(va)}"
            continue
        res = train_b1(
            tr[feat_cols], pd.Series(tr.y.to_numpy()),
            start_pos=tr.start_pos.to_numpy(), horizon=_H,
            groups=np.array([sym_codes[s] for s in tr.symbol]),
            cfg=B1Config(archetype="intraday_reversal",
                         max_depth=3, n_estimators=300))
        pred = res.model.predict(va[feat_cols])
        for r, p in zip(va.itertuples(), pred):
            out.at[r.date, r.symbol] = float(p)
        folds[Y] = f"train_years≤{Y-1} n={len(tr)} val n={len(va)}"
    print("  B1 walk-forward folds:")
    for y, s in folds.items():
        print(f"    {y}: {s}")
    return out


# ── Track-A acceptance gates ─────────────────────────────────────────
def _track_a_gates(name, ev):
    mfp = dict(ev.metrics_full_period)
    per_y = {int(y): dict(m) for y, m in
             ev.metrics_per_validation_year.items()}
    stress = {n: dict(m) for n, m in
              ev.metrics_per_stress_slice.items()}
    conc = dict(ev.concentration)

    g = {}
    # vs SPY HARD (full validation period)
    vs_spy = float(mfp.get("vs_spy", 0.0))
    g["vs_spy_hard"] = {"vs_spy": vs_spy, "pass": vs_spy > 0.0}
    # per-validation-year MaxDD ≤ 20% (hard invariant)
    py_pass = True; py_detail = {}
    for y, m in per_y.items():
        dd = abs(float(m.get("max_dd", 0.0)))
        py_detail[y] = {"max_dd": dd, "pass": dd <= 0.20}
        if dd > 0.20:
            py_pass = False
    g["per_validation_year_maxdd_le_20pct"] = {
        "pass": py_pass, "per_year": py_detail}
    # 2008-style stress slice MaxDD ≤ 25%
    ss_pass = True; ss_detail = {}
    for sn, sm in stress.items():
        dd = abs(float(sm.get("max_dd", 0.0)))
        ss_detail[sn] = {"max_dd": dd, "pass": dd <= 0.25}
        if dd > 0.25:
            ss_pass = False
    g["stress_slice_maxdd_le_25pct"] = {"pass": ss_pass,
                                         "per_slice": ss_detail}
    # concentration: top1 ≤ 40, top3 ≤ 70
    # BUG-FIX 2026-05-19 (auditor R3): real keys emitted by
    # core.backtest.concentration_metrics.compute_concentration_metrics
    # are ``m12_top1_weight_max`` / ``m12_top3_weight_max``, NOT the
    # stale-docstring ``top1_max`` / ``top3_max`` we were reading.
    # Prior driver read top1_max (MISSING) → default 0.0 → false-PASS
    # silently (concentration gate never actually checked anything).
    top1 = float(conc.get("m12_top1_weight_max", 0.0))
    top3 = float(conc.get("m12_top3_weight_max", 0.0))
    g["concentration"] = {"top1_max": top1, "top3_max": top3,
                          "pass": top1 <= 0.40 + 1e-9
                          and top3 <= 0.70 + 1e-9}
    # diagnostic only (NOT blocking)
    vs_qqq = float(mfp.get("vs_qqq", 0.0))
    g["vs_qqq_diagnostic"] = {"vs_qqq": vs_qqq, "blocking": False}

    all_hard_pass = all(g[k].get("pass", True) for k in
                        ("vs_spy_hard", "per_validation_year_maxdd_le_20pct",
                         "stress_slice_maxdd_le_25pct", "concentration"))
    verdict = "PASS" if all_hard_pass else "FAIL_recorded_root_cause"
    return {"name": name, "verdict": verdict,
            "metrics_full_period": mfp, "gates": g,
            "n_observed_days": int(ev.n_observed_days)}


def _evaluate(pred_panel, name, panel, vys, sslices, mask):
    spec = ResearchCompositeSpec(
        features=(f"{name}_pred",), weights=(1.0,),
        family_counts={"ML": 1}, holding_freq="monthly")
    cmap = make_unified_cluster_map(include_cross_asset=True)
    acmap = {s: ASSET_CLASS_BY_CLUSTER[cmap[s]]
             for s in panel["close"].columns if s in cmap}
    hc = HarnessConfig(
        rebalance_cadence="monthly",
        construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cmap, asset_class_map=acmap,
        asset_class_caps={"equities": 0.70, "bonds": 0.40,
                          "commodities": 0.20, "cash_anchor": 0.30})
    return evaluate_composite_spec(
        spec=spec, factor_panel_map={f"{name}_pred": pred_panel},
        price_df=panel["close"], open_df=panel["open"],
        spy_series=panel["close"].get("SPY"),
        qqq_series=panel["close"].get("QQQ"),
        config=hc, validation_years=vys, stress_slices=sslices,
        research_mask=mask)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--only", choices=["a1", "b1", "both"],
                    default="both")
    args = ap.parse_args()

    # BUG-FIX 2026-05-19 (auditor R3): RB1 gate moved INSIDE b1
    # branch — A1 path must not be gated on B prereqs. Prior code
    # asserted unconditionally before the --only branch, creating
    # a false coupling (e.g. an A1-only diagnostic run could be
    # blocked by an unrelated B prereq breaking).
    panel, _f, mask, sc = _c6_panel()
    close = panel["close"]
    integ = _bar_integrity(close)
    tr_years = set(train_year_set(sc))
    val_years = sorted(validation_year_set(sc))
    sslices = {s.name: (s.start.isoformat(), s.end.isoformat())
               for s in sc.partition.stress_slices}

    if args.smoke:
        print(f"SMOKE OK: bar-integrity {integ} | "
              f"train_years={sorted(tr_years)} val_years={val_years} "
              f"stress_slices={list(sslices)} "
              f"(sealed 2026 excluded by construction)")
        return 0

    out = {"experiment": "a1_b1_nav_track_a",
           "sealed_2026_read": False,
           "bar_integrity": integ,
           "train_years": sorted(tr_years),
           "validation_years": val_years,
           "candidates": {}}
    if args.only in ("a1", "both"):
        print("=== A1 (RA1+RA2 daily-close engineered + shallow XGB) ===")
        p_a1 = _a1_pred_panel(panel, tr_years, val_years)
        ev_a1 = _evaluate(p_a1, "a1", panel, val_years, sslices, mask)
        gates_a1 = _track_a_gates("a1", ev_a1)
        out["candidates"]["a1"] = gates_a1
        print(f"  A1 verdict={gates_a1['verdict']}")
        for k, v in gates_a1["metrics_full_period"].items():
            if isinstance(v, (int, float)):
                print(f"    {k}={float(v):+.4f}")
        for k, v in gates_a1["gates"].items():
            print(f"    gate {k}: {v}")

    if args.only in ("b1", "both"):
        # RB1 gate only on the B path (not A) — see auditor fix above.
        assert_component_b_prerequisites()
        print("=== B1 (RB2 intraday engineered + shallow XGB) ===")
        p_b1 = _b1_pred_panel(panel, tr_years, val_years)
        ev_b1 = _evaluate(p_b1, "b1", panel, val_years, sslices, mask)
        gates_b1 = _track_a_gates("b1", ev_b1)
        out["candidates"]["b1"] = gates_b1
        print(f"  B1 verdict={gates_b1['verdict']}")
        for k, v in gates_b1["metrics_full_period"].items():
            if isinstance(v, (int, float)):
                print(f"    {k}={float(v):+.4f}")
        for k, v in gates_b1["gates"].items():
            print(f"    gate {k}: {v}")

    out["funnel_caveat"] = (
        "Track-A PASS does NOT promote to fleet — it unlocks the "
        "next phase (forward observation + sealed gate). FAIL → "
        "ROOT CAUSE which gate broke; NOT blanket 'ML doesn't work'.")
    p = Path("data/audit/ml_redo/a1_b1_nav_track_a.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nverdict JSON -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
