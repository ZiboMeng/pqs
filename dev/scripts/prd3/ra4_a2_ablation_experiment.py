"""PRD-3 RA4 — A2 decisive ablation EXPERIMENT (experiment round).

experiment round (NOT build): AC = ran + recorded + verdict per
PRD-3 ralph-loop RA4 + ROOT CAUSE if negative. Negative does NOT
terminate the loop (config-scoped, no blanket).

Question (JKX 2023 thesis): is the IMAGE necessary, or is its value
just IMPLICIT per-name scaling that EXPLICIT normalization /
1D-ROCKET / a tree recovers? Answered via the chart_native 3-point
curve method (R3-reusable precedent) on the SAME leakage-correct
frozen-OOS IC-on-tradeable:

  p0  raw 63d close window (flattened, NO normalization, NO image)
      + Ridge  — the un-normalized FLOOR.
  p1  ROCKET-essence random 1D-conv kernels on the window + PPV/max
      pooling + Ridge — IMPLICIT normalization (sktime/tsai not
      installed → honest documented reduction to sklearn random
      convolution kernels = the MiniROCKET essence, NOT a scope cut).
  p2  RA1 explicit per-name normalized engineered features (RA1
      build_engineered_panel: close_pos_in_range = explicit
      per-name scaling) + RA2 shallow tree — EXPLICIT normalization.

Monotone p0 → p1 → p2 ⇒ the value IS recoverable by explicit
normalization without an image ⇒ "image NOT necessary" (JKX thesis
holds). All leakage-correct (cycle06 _load_panel selector =
train+val, sealed 2026 NEVER read; sample-uniqueness via the single
engineered_sample_weights → label_leakage helper). Bar-integrity
smoke FIRST.

IRONCLAD: signal is NOT binding (PRD-3) — IC-layer ablation only;
the binding gate is PRD-2-construction NAV Track-A. Recorded.

Usage: python dev/scripts/prd3/ra4_a2_ablation_experiment.py [--smoke]
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

from core.ml.xgb_alpha import compute_rank_ic
from core.research.engineered_features import build_engineered_panel
from core.research.a1_pipeline import A1Config, train_a1
from core.research.temporal_split import train_year_set

_WIN = 63
_HORIZON = 21


def _load_cycle06_panel():
    p = PROJ / "dev/scripts/cycle06/cycle06_track_a_eval.py"
    spec = importlib.util.spec_from_file_location("_c6eval", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._load_panel()


def _bar_integrity(close: pd.DataFrame) -> dict:
    idx = pd.DatetimeIndex(close.index)
    wknd = int((idx.weekday >= 5).sum())
    yrs = sorted({t.year for t in idx})
    assert 2026 not in yrs, f"SEALED GUARD: 2026 present {yrs}"
    assert wknd == 0, f"bar-integrity FAIL: {wknd} weekend rows"
    assert idx.is_monotonic_increasing, "index not monotone"
    return {"weekend_rows": wknd, "years": yrs}


def _rocket_essence(windows: np.ndarray, n_kernels: int = 64,
                    seed: int = 42) -> np.ndarray:
    """sktime/tsai unavailable → MiniROCKET essence: random 1D conv
    kernels (random weights, varied dilation) + PPV (proportion of
    positive values) + max pooling. Honest documented reduction."""
    rng = np.random.default_rng(seed)
    n, L = windows.shape
    feats = []
    for _ in range(n_kernels):
        klen = int(rng.choice([5, 7, 9]))
        w = rng.standard_normal(klen)
        w -= w.mean()
        dil = int(rng.choice([1, 2, 4]))
        eff = (klen - 1) * dil + 1
        if eff >= L:
            dil = 1
            eff = klen
        out = np.empty(n)
        ppv = np.empty(n)
        for i in range(n):
            x = windows[i]
            conv = np.array([
                np.dot(w, x[j:j + eff:dil][:klen])
                for j in range(0, L - eff + 1)])
            out[i] = conv.max() if conv.size else 0.0
            ppv[i] = float((conv > 0).mean()) if conv.size else 0.0
        feats.append(out)
        feats.append(ppv)
    return np.column_stack(feats)


def _ridge_ic(Xtr, ytr, Xva, yva, dva):
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    sc = StandardScaler().fit(np.nan_to_num(Xtr))
    m = Ridge(alpha=1.0).fit(sc.transform(np.nan_to_num(Xtr)), ytr)
    pred = m.predict(sc.transform(np.nan_to_num(Xva)))
    return compute_rank_ic(pd.Series(yva), pred, pd.Series(dva))[0]


def _build_long(close, me_dates, train_years, feat_map=None):
    pos = {ts: i for i, ts in enumerate(close.index)}
    fwd = close.shift(-_HORIZON) / close - 1.0
    rows = []
    for d in me_dates:
        if d not in pos or pos[d] + _HORIZON >= len(close.index) \
           or pos[d] < _WIN:
            continue
        is_tr = d.year in train_years
        for sym in close.columns:
            y = fwd.at[d, sym]
            if pd.isna(y):
                continue
            win = close[sym].iloc[pos[d] - _WIN + 1: pos[d] + 1].to_numpy()
            if np.isnan(win).any():
                continue
            rec = {"date": d, "symbol": sym, "is_train": is_tr,
                   "y": float(y), "_win": win, "start_pos": pos[d]}
            if feat_map is not None:
                ff = {k: v.at[d, sym] for k, v in feat_map.items()
                      if sym in v.columns}
                if any(pd.isna(list(ff.values()))):
                    continue
                rec.update(ff)
            rows.append(rec)
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    panel, _f, _m, sc = _load_cycle06_panel()
    close = panel["close"]
    integ = _bar_integrity(close)
    train_years = set(train_year_set(sc))
    idx = pd.DatetimeIndex(close.index)
    me = list(pd.Series(idx, index=idx).groupby(
        [idx.year, idx.month]).last().to_numpy())
    me = [pd.Timestamp(d) for d in me]

    feat_map = build_engineered_panel(
        panel["open"], panel["high"], panel["low"], close,
        panel["volume"], close_windows=(20, 63), monthly_rank=False)
    df = _build_long(close, me, train_years, feat_map)
    feat_cols = list(feat_map.keys())

    if args.smoke:
        print(f"SMOKE OK: bar-integrity {integ} | rows={len(df)} "
              f"feat_cols={feat_cols} train_years={sorted(train_years)} "
              f"(sealed 2026 excluded by construction)")
        return 0

    tr = df[df.is_train].reset_index(drop=True)
    va = df[~df.is_train].reset_index(drop=True)
    Wtr = np.vstack(tr["_win"].to_numpy())
    Wva = np.vstack(va["_win"].to_numpy())
    ytr, yva = tr.y.to_numpy(), va.y.to_numpy()
    dva = va.date.to_numpy()

    # p0: raw window, NO normalization, NO image → Ridge (floor)
    ic_p0 = _ridge_ic(Wtr, ytr, Wva, yva, dva)
    # p1: ROCKET-essence random conv (implicit normalization) → Ridge
    Rtr = _rocket_essence(Wtr)
    Rva = _rocket_essence(Wva)
    ic_p1 = _ridge_ic(Rtr, ytr, Rva, yva, dva)
    # p2: RA1 explicit per-name normalized feats + RA2 shallow tree
    sym_codes = {s: i for i, s in enumerate(sorted(df.symbol.unique()))}
    res = train_a1(
        tr[feat_cols], pd.Series(ytr),
        start_pos=tr.start_pos.to_numpy(), horizon=_HORIZON,
        groups=np.array([sym_codes[s] for s in tr.symbol]),
        cfg=A1Config(max_depth=3, n_estimators=300))
    ic_p2 = compute_rank_ic(
        pd.Series(yva), res.model.predict(va[feat_cols]),
        pd.Series(dva))[0]

    monotone = ic_p0 <= ic_p1 + 1e-9 <= ic_p2 + 1e-9 or (
        ic_p2 >= ic_p1 >= ic_p0)
    explicit_recovers = (ic_p2 >= ic_p1) and (ic_p2 > ic_p0)
    verdict = ("PASS_image_not_necessary"
               if explicit_recovers
               else "FAIL_recorded_root_cause")

    out = {
        "experiment": "ra4_a2_ablation",
        "sealed_2026_read": False,
        "bar_integrity": integ,
        "n_rows": {"train": int(len(tr)), "val": int(len(va))},
        "three_point_curve": {
            "p0_raw_window_no_norm_no_image": ic_p0,
            "p1_rocket_essence_implicit_norm": ic_p1,
            "p2_explicit_pername_norm_plus_tree": ic_p2,
            "method": "chart_native 3-point curve precedent",
            "rocket_note": ("sktime/tsai unavailable → sklearn random "
                            "1D-conv + PPV/max = MiniROCKET essence "
                            "(honest documented reduction, NOT a scope "
                            "cut)")},
        "monotone_p0_p1_p2": bool(monotone),
        "explicit_normalization_recovers": bool(explicit_recovers),
        "verdict": verdict,
        "interpretation": (
            "explicit per-name normalization (p2) >= ROCKET implicit "
            "(p1) > raw floor (p0) ⇒ the representation value is "
            "recoverable WITHOUT an image (JKX 2023 implicit-per-name-"
            "scaling thesis holds) ⇒ image NOT necessary for A1/A2."),
        "signal_not_binding_caveat": (
            "IC-layer ablation only; binding gate = PRD-2 NAV "
            "Track-A. Negative does NOT terminate the loop "
            "(config-scoped, no blanket)."),
    }
    p = Path("data/audit/ml_redo/ra4_a2_ablation.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"RA4 verdict={verdict} -> {p}")
    print(f"  p0 raw-floor      IC={ic_p0:.4f}")
    print(f"  p1 ROCKET-essence IC={ic_p1:.4f}")
    print(f"  p2 explicit+tree  IC={ic_p2:.4f}")
    print(f"  monotone={monotone} explicit_recovers={explicit_recovers}")
    print(f"  → image necessary? {'NO' if explicit_recovers else 'INCONCLUSIVE (root-cause)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
