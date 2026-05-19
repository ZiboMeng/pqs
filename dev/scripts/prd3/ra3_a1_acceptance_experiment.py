"""PRD-3 RA3 — A1 acceptance EXPERIMENT (experiment round).

experiment round (NOT build): AC = ran + recorded + verdict per
PRD-3 §4 + ROOT CAUSE if negative. A negative result does NOT
terminate the loop (config-scoped, no blanket "X 不行").

Pipeline (leakage-correct, sealed-NEVER-read by construction):
reuse cycle06_track_a_eval._load_panel (partition_for_role
'selector' = train + validation only; sealed 2026 excluded) via
importlib — single SoT, no panel-builder duplication (same pattern
as PRD-2 R5/R8). Embedded bar-level data-integrity smoke runs FIRST
(memory feedback_bar_level_data_integrity_smoke: weekend-row scan +
monotone index + sealed-year guard) before any ML.

Signal = RA1 engineered stationary features → RA2 A1 shallow-XGB
(leakage-correct uniqueness weights via the single
engineered_sample_weights → label_leakage helper; purge via
engineered_purge_mask). Trained TRAIN-only, scored VALIDATION =
frozen-OOS.

§4 acceptance (recorded; verdict, not "must pass"):
  - leakage-correct frozen-OOS rank-IC: pooled + on-tradeable
    (on-tradeable = research_mask True subset).
  - JKX sibling test: regress the A1 signal on the established
    [momentum / reversal / Amihud] factors; R^2 <= 0.12 ⇒
    differentiated non-sibling (Jiang-Kelly-Xiu 2023).
  - baselines: momentum factor raw IC + a linear "DLinear-essence"
    Ridge-on-the-same-features IC. (Honest scope: in the
    cross-sectional daily-return setting DLinear's trend/seasonal
    linear decomposition collapses to a linear model on the
    features; we label it DLinear-essence-linear, not a full
    sequence DLinear — recorded reduction, not a scope cut.)
  - verdict = differentiated non-sibling AND A1 IC > best baseline.

IRONCLAD (PRD-3): signal is NOT the binding constraint (L3 proven)
→ this IC-layer screen alone is not progress; the binding gate is
the PRD-2-construction NAV Track-A. The verdict explicitly records
this caveat; RA3 is the differentiation + IC screen only.

Usage: python dev/scripts/prd3/ra3_a1_acceptance_experiment.py [--smoke]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]  # dev/scripts/prd3/ → root
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.ml.xgb_alpha import compute_rank_ic
from core.research.engineered_features import build_engineered_panel
from core.research.a1_pipeline import A1Config, train_a1
from core.research.temporal_split import train_year_set

# established sibling factors (registry names; present in _load_panel
# `factors`): momentum = trend_tstat_20d, reversal = ret_5d,
# illiquidity = amihud_20d.
_SIB = ("trend_tstat_20d", "ret_5d", "amihud_20d")
_HORIZON = 21  # ≈ 1 trading month (cycle06 spec = monthly cadence)


def _load_cycle06_panel():
    p = PROJ / "dev/scripts/cycle06/cycle06_track_a_eval.py"
    spec = importlib.util.spec_from_file_location("_c6eval", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._load_panel()


def _bar_integrity_smoke(close: pd.DataFrame) -> dict:
    """5-min bar-level integrity smoke (run BEFORE any ML)."""
    idx = pd.DatetimeIndex(close.index)
    wknd = int(((idx.weekday >= 5)).sum())
    mono = bool(idx.is_monotonic_increasing)
    yrs = sorted({t.year for t in idx})
    assert 2026 not in yrs, f"SEALED GUARD: 2026 present {yrs}"
    assert wknd == 0, f"bar-integrity FAIL: {wknd} weekend rows in panel"
    assert mono, "bar-integrity FAIL: panel index not monotone increasing"
    return {"weekend_rows": wknd, "monotone": mono, "years": yrs}


def _month_end_idx(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(idx, index=idx)
    return pd.DatetimeIndex(
        s.groupby([idx.year, idx.month]).last().to_numpy())


def _long_frame(feat_map, close, me, train_years):
    """Melt month-end engineered features + fwd return + sibling
    factors to a long (date,symbol) table with a train/val flag."""
    pos = {ts: i for i, ts in enumerate(close.index)}
    fwd = close.shift(-_HORIZON) / close - 1.0
    rows = []
    for d in me:
        if d not in pos or pos[d] + _HORIZON >= len(close.index):
            continue
        is_train = d.year in train_years
        for sym in close.columns:
            feats = {k: v.at[d, sym] for k, v in feat_map.items()
                     if sym in v.columns}
            y = fwd.at[d, sym]
            if any(pd.isna(list(feats.values()))) or pd.isna(y):
                continue
            rows.append({"date": d, "symbol": sym, "start_pos": pos[d],
                         "is_train": is_train, "y": float(y), **feats})
    return pd.DataFrame(rows)


def _ridge_ic(Xtr, ytr, Xva, yva, dva):
    from sklearn.linear_model import Ridge
    m = Ridge(alpha=1.0).fit(Xtr, ytr)
    return compute_rank_ic(yva, m.predict(Xva), dva)[0]


def _jkx_r2(signal: np.ndarray, sib: np.ndarray) -> float:
    """OLS R^2 of the A1 signal explained by the established sibling
    factors (Jiang-Kelly-Xiu sibling test). Lower = more orthogonal."""
    X = np.column_stack([np.ones(len(signal)), sib])
    beta, *_ = np.linalg.lstsq(X, signal, rcond=None)
    resid = signal - X @ beta
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((signal - signal.mean()) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    panel, factors, mask, split_cfg = _load_cycle06_panel()
    close = panel["close"]
    integ = _bar_integrity_smoke(close)
    # canonical train-year expander (handles _YearRange + _SingleYear;
    # do NOT reimplement — single SoT in temporal_split).
    train_years = sorted(train_year_set(split_cfg))
    me = _month_end_idx(pd.DatetimeIndex(close.index))

    feat_map = build_engineered_panel(
        panel["open"], panel["high"], panel["low"], close,
        panel["volume"], close_windows=(20, 63), monthly_rank=False)
    # restrict the long frame to engineered cols (+ keep sibling
    # factor values aligned for the JKX test)
    df = _long_frame(feat_map, close, me, set(train_years))
    feat_cols = list(feat_map.keys())

    if args.smoke:
        print(f"SMOKE OK: bar-integrity {integ} | rows={len(df)} "
              f"feat_cols={feat_cols} train_years={train_years} "
              f"(sealed 2026 excluded by construction)")
        return 0

    tr = df[df.is_train].reset_index(drop=True)
    va = df[~df.is_train].reset_index(drop=True)
    sym_codes = {s: i for i, s in enumerate(sorted(df.symbol.unique()))}

    Xtr = tr[feat_cols]
    ytr = pd.Series(tr.y.to_numpy())
    res = train_a1(
        Xtr, ytr,
        start_pos=tr.start_pos.to_numpy(),
        horizon=_HORIZON,
        groups=np.array([sym_codes[s] for s in tr.symbol]),
        cfg=A1Config(max_depth=3, n_estimators=300, random_state=42))
    pred_va = res.model.predict(va[feat_cols])

    yva = pd.Series(va.y.to_numpy())
    dva = pd.Series(va.date.to_numpy())
    ic_pooled = compute_rank_ic(yva, pred_va, dva)[0]
    # on-tradeable = research_mask True at (date,symbol)
    tradeable = np.array([
        bool(mask.at[d, s]) if (d in mask.index and s in mask.columns)
        else False for d, s in zip(va.date, va.symbol)])
    if tradeable.sum() >= 50:
        ic_tradeable = compute_rank_ic(
            yva[tradeable], pred_va[tradeable], dva[tradeable])[0]
    else:
        ic_tradeable = float("nan")

    # baselines on identical val rows
    mom = "trend_tstat_20d"
    mom_vals = np.array([factors[mom].at[d, s]
                         if (mom in factors and d in factors[mom].index
                             and s in factors[mom].columns) else np.nan
                         for d, s in zip(va.date, va.symbol)])
    mfin = ~np.isnan(mom_vals)
    ic_mom = (compute_rank_ic(yva[mfin], mom_vals[mfin], dva[mfin])[0]
              if mfin.sum() >= 50 else float("nan"))
    ic_dlin = _ridge_ic(Xtr, ytr, va[feat_cols], yva, dva)

    # JKX sibling test on the val signal
    sib_cols = []
    for f in _SIB:
        sib_cols.append(np.array([
            factors[f].at[d, s]
            if (f in factors and d in factors[f].index
                and s in factors[f].columns) else np.nan
            for d, s in zip(va.date, va.symbol)]))
    sib = np.column_stack(sib_cols)
    ok = ~np.isnan(sib).any(axis=1)
    jkx = _jkx_r2(pred_va[ok], sib[ok]) if ok.sum() >= 50 else float("nan")

    best_base = np.nanmax([ic_mom, ic_dlin])
    differentiated = (not np.isnan(jkx)) and jkx <= 0.12
    beats_base = (not np.isnan(ic_pooled)) and ic_pooled > best_base
    verdict = ("PASS" if (differentiated and beats_base)
               else "FAIL_recorded_root_cause")

    out = {
        "experiment": "ra3_a1_acceptance",
        "sealed_2026_read": False,
        "bar_integrity": integ,
        "n_rows": {"train": int(len(tr)), "val": int(len(va))},
        "feat_cols": feat_cols,
        "ic": {"pooled": ic_pooled, "on_tradeable": ic_tradeable},
        "baselines": {"momentum_trend_tstat_20d": ic_mom,
                      "dlinear_essence_ridge": ic_dlin,
                      "best_baseline": float(best_base)},
        "jkx_sibling": {"sib_factors": list(_SIB), "r2": jkx,
                        "threshold": 0.12,
                        "differentiated_non_sibling": bool(differentiated)},
        "verdict": verdict,
        "signal_not_binding_caveat": (
            "IC-layer screen only. Per PRD-3 ironclad rule the binding "
            "gate is the PRD-2-construction NAV Track-A; RA3 is the "
            "differentiation + IC screen, NOT a promotion. Negative "
            "does not terminate the loop (config-scoped, no blanket)."),
    }
    p = Path("data/audit/ml_redo/ra3_a1_acceptance.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"RA3 verdict={verdict} -> {p}")
    print(f"  IC pooled={ic_pooled:.4f} on_tradeable={ic_tradeable:.4f}")
    print(f"  baselines mom={ic_mom:.4f} dlinear_ess={ic_dlin:.4f} "
          f"best={best_base:.4f}")
    print(f"  JKX sibling R^2={jkx:.4f} (<=0.12 → "
          f"differentiated={differentiated})")
    print(f"  caveat: signal NOT binding — NAV Track-A is the gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
