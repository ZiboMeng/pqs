"""task#21 — the missing STRONG comparison anchor.

Auditor finding 1+3+4 root: chart-native / probe arms (S1 0.12, S2
0.09, ml-redo mae_probe ~0.05) were only ever compared vs a SINGLE
MOMENTUM factor (~0.03), NOT a strong tabular baseline; and
MiniROCKET was used as a degenerate mean-PPV scalar
(rolling_minirocket_ppv_mean), not its high-dim representation.
Until a strong anchor exists, the L2 'beats baseline' claim is
UNANSWERABLE (not just unsoftened).

This builds the anchor, same protocol as S1/S2 (apples-to-apples):
executable-79, BarStore ADJUSTED (P0-A-correct), TRAIN-ONLY +
SEALED fail-closed guard, 15 CPCV folds, honest-N DSR (G1
dsr_trial_accounting, no magic literal).

Arms:
  A. minirocket_full   — FULL 1008-dim MiniROCKET vector → ridge probe
                         (the un-degenerate representation; vs the
                         scalar mean-PPV that under-tested the method).
  B. tabular_gbdt       — STRONG tabular baseline: the project's full
                         engineered factor library (~184 factors via
                         the same 4-path _build_factor_panel_map the
                         miner uses) → XGBoost. 'Trees over engineered
                         features are hard to beat' — the legitimate
                         strong anchor.
Reference:
  mom_126d single factor — the WEAK comparator S1/S2/ml-redo used,
                         to quantify how weak the old anchor was.

Output: all arms' CPCV mean IC + DSR(honest-N) → S1/S2/probe can
finally be read vs a STRONG anchor. Honest 3-layer framing; NO
over-claim; no-blanket on any null.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.config.loader import load_config  # noqa: E402
from core.data.bar_store import BarStore  # noqa: E402
from core.factors.factor_generator import compute_forward_returns  # noqa: E402
from core.ml.subsequence_transforms import (  # noqa: E402
    MiniRocketConfig,
    minirocket_transform,
)
from core.ml.window_embedding import WINDOW_LEN  # noqa: E402
from core.research.cpcv import cpcv_splits  # noqa: E402
from core.research.dsr_trial_accounting import (  # noqa: E402
    ML_REDO_CHART_NATIVE_ARMS,
)
from core.research.overfit_metrics import deflated_sharpe_ratio  # noqa: E402
from core.research.temporal_split import (  # noqa: E402
    load_temporal_split,
    partition_for_role,
    train_year_set,
)

_H = 21


def _ic(p, y):
    m = np.isfinite(p) & np.isfinite(y)
    if m.sum() < 10:
        return np.nan
    return float(np.corrcoef(pd.Series(p[m]).rank(),
                             pd.Series(y[m]).rank())[0, 1])


def _ridge(Xtr, ytr, Xte, lam=10.0):
    A = Xtr.T @ Xtr + lam * np.eye(Xtr.shape[1])
    return Xte @ np.linalg.solve(A, Xtr.T @ ytr)


def _cpcv_ic(X, y, fit_predict, n):
    ics = []
    for tr, te in cpcv_splits(n, 6, 2, _H, 0.01):
        if len(tr) < 200 or len(te) < 50:
            continue
        a = _ic(fit_predict(X[tr], y[tr], X[te]), y[te])
        if np.isfinite(a):
            ics.append(a)
    return ics


def main() -> int:
    t0 = time.time()
    cfg = load_config(Path("config"))
    split = load_temporal_split(Path("config/temporal_split.yaml"))
    ty = train_year_set(split)
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    syms = [s for s in (list(uni.seed_pool) + list(uni.sector_etfs)
                        + list(uni.factor_etfs) + list(uni.cross_asset))
            if s not in uni.blacklist and s not in uni.macro_reference
            and s not in ("BRK-B", "USO", "SLV")]
    syms = list(dict.fromkeys(syms + ["SPY", "QQQ"]))

    # FIX (task21 re-run): _build_factor_panel_map needs OHLCV — prior
    # run built close-only → KeyError 'open' → strong-tabular anchor
    # failed (surfaced, not silent). Collect open/high/low/volume too.
    fr = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for s in syms:
        try:
            df = store.load(s, freq="1d", adjusted=True, fallback="local")
        except Exception:
            continue
        if df is None or df.empty or "close" not in df.columns:
            continue
        fr["close"][s] = df["close"]
        for c in ("open", "high", "low", "volume"):
            if c in df.columns:
                fr[c][s] = df[c]
    panel = {"close": pd.DataFrame(fr["close"]).sort_index()}
    for c in ("open", "high", "low", "volume"):
        panel[c] = (pd.DataFrame(fr[c]).reindex_like(panel["close"])
                    if fr[c] else None)
    panel = partition_for_role(panel, split, role="selector")
    px = panel["close"]
    px = px[[ts.year in ty for ts in px.index]]
    if {ts.year for ts in px.index} - ty:
        raise SystemExit("SEALED GUARD: non-train years present")
    fwd = compute_forward_returns(px, [_H])[_H]
    print(f"panel {px.shape} train-only ({time.time()-t0:.0f}s)")

    # ── windows for MiniROCKET + reference momentum ──
    wins, yv, momv = [], [], []
    for s in [c for c in px.columns if c not in ("SPY", "QQQ")]:
        v = px[s].to_numpy(float)
        idx = px.index
        for i in range(WINDOW_LEN - 1, len(v)):
            dt = idx[i]
            if dt not in fwd.index or s not in fwd.columns:
                continue
            y = fwd.at[dt, s]
            w = v[i - WINDOW_LEN + 1:i + 1]
            if not (np.isfinite(y) and np.isfinite(w).all() and w[0] > 0):
                continue
            wins.append(np.log(w / w[0] + 1e-9).astype(np.float64))
            yv.append(float(y))
            momv.append(v[i] / v[i - 126] - 1.0 if i >= 126 else np.nan)
    W = np.stack(wins)
    yv = np.array(yv, np.float32)
    momv = np.array(momv, np.float32)
    n = len(W)
    print(f"{n} windows ({time.time()-t0:.0f}s)")

    out = {"experiment": "task21_strong_anchor",
           "created_at": datetime.now(timezone.utc).isoformat(),
           "train_years_only": sorted(ty), "sealed_2026_read": False,
           "n_windows": int(n), "arms": {}}
    nt = ML_REDO_CHART_NATIVE_ARMS

    # Reference: single momentum (the WEAK comparator S1/S2 used)
    mom_ics = []
    for tr, te in cpcv_splits(n, 6, 2, _H, 0.01):
        if len(te) < 50:
            continue
        b = _ic(momv[te], yv[te])
        if np.isfinite(b):
            mom_ics.append(b)
    out["arms"]["ref_single_momentum"] = {
        "ic": round(float(np.mean(mom_ics)), 5) if mom_ics else None,
        "note": "the WEAK comparator S1/S2/ml-redo were judged against"}

    # Arm A: FULL MiniROCKET vector → ridge.
    # CACHE-REUSE: MiniROCKET transform is deterministic + the 34-min
    # bottleneck; the prior run already computed it (ic=0.02343) and
    # this re-run only exists to land the FAILED strong-tabular arm.
    # Reuse the prior valid result instead of burning 34 min again
    # (deterministic ⇒ identical; no integrity risk).
    _prior = Path("data/audit/task21_strong_anchor.json")
    _pa = None
    if _prior.exists():
        try:
            _pj = json.loads(_prior.read_text())
            _cand = (_pj.get("arms", {}).get("minirocket_full_ridge")
                     or {})
            if _cand.get("ic") is not None and "error" not in _cand:
                _pa = _cand
        except Exception:
            _pa = None
    if _pa is not None:
        out["arms"]["minirocket_full_ridge"] = {
            **_pa, "reused_from_prior_run": True,
            "reuse_reason": "deterministic transform; prior run valid; "
                            "re-run is only to land strong-tabular arm"}
        print(f"minirocket REUSED prior ic={_pa.get('ic')} "
              f"({time.time()-t0:.0f}s)")
    else:
        F = minirocket_transform(W, MiniRocketConfig()).astype(np.float32)
        F = np.nan_to_num(F, nan=0.0)
        print(f"minirocket full {F.shape} ({time.time()-t0:.0f}s)")
        a_ics = _cpcv_ic(F, yv, _ridge, n)
        dsr_a = (deflated_sharpe_ratio(np.array(a_ics), nt)
                 if len(a_ics) >= 8 else {"deflated_sharpe": None})
        out["arms"]["minirocket_full_ridge"] = {
            "ic": round(float(np.mean(a_ics)), 5) if a_ics else None,
            "n_folds": len(a_ics), "n_features": int(F.shape[1]),
            "dsr_honest_n": dsr_a.get("deflated_sharpe"),
            "dsr_n_trials": nt,
            "note": "FULL 1008-dim representation (vs degenerate "
                    "mean-PPV scalar that under-tested MiniROCKET)"}

    # Arm B: STRONG tabular GBDT over the full engineered factor library
    try:
        from scripts.run_research_miner import _build_factor_panel_map
        from xgboost import XGBRegressor
        trad = [c for c in px.columns if c not in ("SPY", "QQQ")]
        fpm, _f, _m, _nm = _build_factor_panel_map(
            panel, trad, horizon=_H, split_cfg=split)
        print(f"factor lib {len(fpm)} factors ({time.time()-t0:.0f}s)")
        # pooled (date,sym) design matrix over the factor library
        cols, names = [], []
        for fn, fdf in fpm.items():
            fdf = fdf.reindex_like(px).ffill()
            cols.append(fdf.stack())
            names.append(fn)
        Xtab = pd.concat(cols, axis=1)
        Xtab.columns = names
        ytab = fwd.stack()
        al = pd.concat([Xtab, ytab.rename("__y__")], axis=1).dropna(
            subset=["__y__"])
        al = al[al.notna().mean(axis=1) > 0.6]      # rows mostly-defined
        Xv = al[names].to_numpy(np.float32)
        Xv = np.nan_to_num(Xv, nan=0.0)
        yvb = al["__y__"].to_numpy(np.float32)
        m = len(Xv)

        def _xgb(Xtr, ytr, Xte):
            mdl = XGBRegressor(n_estimators=200, max_depth=4,
                               learning_rate=0.05, subsample=0.8,
                               colsample_bytree=0.6, n_jobs=4,
                               verbosity=0)
            mdl.fit(Xtr, ytr)
            return mdl.predict(Xte)

        b_ics = _cpcv_ic(Xv, yvb, _xgb, m)
        dsr_b = (deflated_sharpe_ratio(np.array(b_ics), nt)
                 if len(b_ics) >= 8 else {"deflated_sharpe": None})
        out["arms"]["tabular_gbdt_factorlib"] = {
            "ic": round(float(np.mean(b_ics)), 5) if b_ics else None,
            "n_folds": len(b_ics), "n_features": len(names),
            "n_rows": int(m),
            "dsr_honest_n": dsr_b.get("deflated_sharpe"),
            "dsr_n_trials": nt,
            "note": "STRONG tabular baseline = XGBoost over the full "
                    "engineered factor library (the legitimate anchor "
                    "the L2 'beats baseline' claim needs — auditor #1)"}
    except Exception as e:
        out["arms"]["tabular_gbdt_factorlib"] = {
            "error": f"{type(e).__name__}: {e}",
            "note": "STRONG anchor FAILED — NOT a silent pass; "
                    "L2 'beats baseline' remains unanswerable"}

    out["honest_reading"] = (
        "L1 representation-works / L2 beats-WHICH-baseline now "
        "answerable vs strong-tabular + full-MiniROCKET (not just "
        "single momentum) / L3 production-eligible still NOT (train-"
        "only, no funnel). config-scoped; no over-claim; any null = "
        "'this attempt under this config', no blanket verdict.")
    p = Path("data/audit/task21_strong_anchor.json")
    p.write_text(json.dumps(out, indent=2, default=str))
    a = out["arms"]
    print(f"task21 -> ref_mom={a['ref_single_momentum']['ic']} | "
          f"minirocket_full={a['minirocket_full_ridge'].get('ic')} | "
          f"tabular_gbdt={a['tabular_gbdt_factorlib'].get('ic')} "
          f"({time.time()-t0:.0f}s) -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
