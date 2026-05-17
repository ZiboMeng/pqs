"""C3+C4 deferred-closeout — expanded_v2 ~1k re-run + from-scratch arm.

Per closeout §4. Two deferred items, one job:
- C3: re-run the R4 chart-native question on the **expanded_v2 ~1000**
  universe (tests literature's 'needs large cross-section' claim
  [S1a][S2] — Phase 2A's small-universe was a hypothesized root cause).
- C4: add a **from-scratch ChartCNN** arm on the SAME literature
  pipeline, completing the pretrain→probe VS from-scratch comparison
  (literature predicts from-scratch loses; confirm under identical
  prep/eval, not naive Phase-3 protocol).

Sizing (recorded, not hidden): 1000 symbols → coarse date stride 10
bounds RAM/compute; cross-sectional rank-IC wants many SYMBOLS per
date, not many dates, so coarser stride on a 1000-universe is
loss-light for the IC question. from-scratch CNN trained ONCE on the
fit block (not per-CPCV-fold) — a bounded, honestly-recorded
approximation, NOT a per-fold retrain.

train-only partition + purge + CPCV; config-scoped (D2). Writes
data/audit/ml_redo/c3c4_expanded.json.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

_PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJ))

from core.config.loader import load_config  # noqa: E402
from core.data.bar_store import BarStore  # noqa: E402
from core.factors.factor_generator import compute_forward_returns  # noqa: E402
from core.ml.chart_cnn import ChartCNN, gaf_image  # noqa: E402
from core.ml.window_embedding import WINDOW_LEN  # noqa: E402
from core.research.cpcv import cpcv_splits  # noqa: E402
from core.research.overfit_metrics import deflated_sharpe_ratio  # noqa: E402
from core.research.temporal_split import (  # noqa: E402
    load_temporal_split,
    partition_for_role,
    purge_labels_at_boundary,
    train_year_set,
    validate_no_holdout_leakage,
)
from core.universe.universe_resolver import resolve_universe  # noqa: E402

_H = 21
_STRIDE = 10          # coarse: 1000-universe RAM bound (recorded)


def _ic(p, y):
    m = np.isfinite(p) & np.isfinite(y)
    if m.sum() < 10:
        return 0.0
    return float(np.corrcoef(pd.Series(p[m]).rank(),
                             pd.Series(y[m]).rank())[0, 1])


def main() -> int:
    t0 = time.time()
    ckpt = _PROJ / "data" / "audit" / "ml_redo" / "pretrain_mae.pt"
    if not ckpt.exists():
        raise SystemExit("fail-closed: pretrain_mae.pt missing")
    import torch

    from core.ml.ssl_pretrain import MAEEncoder

    cfg = load_config(_PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    split = load_temporal_split(_PROJ / "config" / "temporal_split.yaml")
    train_years = train_year_set(split)
    oos = {2017, 2024}
    fit_years = train_years - oos
    syms = [s for s in resolve_universe("expanded_v2")
            if s not in ("SPY", "QQQ")]
    print(f"expanded_v2 universe: {len(syms)} symbols")

    close = {}
    _skipped_loaderr = 0
    for s in syms:
        try:
            df = store.load(s, freq="1d", adjusted=True, fallback="local")
        except Exception:
            # FINDING (audit, do not hide): core/data/bar_store.py:500
            # _apply_forward_splits casts volume to int64 and raises
            # IntCastingNaNError on symbols with NaN volume. The 79/328
            # curated universes never hit it; the 1000 data-driven
            # expanded_v2 set surfaces it. Pre-existing BarStore
            # robustness bug — logged as a SEPARATE fix item, NOT
            # silently swallowed: count + report skipped symbols.
            _skipped_loaderr += 1
            continue
        if df is not None and not df.empty and "close" in df.columns:
            close[s] = df["close"]
    print(f"loaded {len(close)}/{len(syms)} (skipped {_skipped_loaderr} "
          f"on BarStore NaN-volume split-adjust bug — recorded)")
    close_df = pd.DataFrame(close).sort_index()
    mp = partition_for_role({"close": close_df}, split, role="miner")
    close_df = mp["close"]
    validate_no_holdout_leakage(mp, split)
    fwd = purge_labels_at_boundary(
        compute_forward_returns(close_df, horizons=[_H], mode="cc")[_H], split)
    mom126 = close_df.pct_change(126)
    dts_all = [d for d in close_df.index if d.year in train_years]
    kept = set(dts_all[::_STRIDE])

    enc = MAEEncoder()
    enc.load_state_dict(torch.load(ckpt, map_location="cpu"))
    enc.eval()

    imgs, embs, yv, dts, momv, yrs = [], [], [], [], [], []
    for s in close_df.columns:
        v = close_df[s].to_numpy(float)
        idx = close_df.index
        for i in range(WINDOW_LEN - 1, len(v)):
            dt = idx[i]
            if dt not in kept or dt not in fwd.index or s not in fwd.columns:
                continue
            y = fwd.at[dt, s]
            if not np.isfinite(y):
                continue
            w = v[i - WINDOW_LEN + 1:i + 1]
            if not np.isfinite(w).all() or w[0] <= 0:
                continue
            shp = (w / w[0] - 1.0).astype(np.float32)
            imgs.append(gaf_image(w))
            with torch.no_grad():
                embs.append(enc.embed(torch.tensor(shp[None, :])).numpy()[0])
            yv.append(float(y))
            dts.append(dt)
            momv.append(mom126.at[dt, s] if dt in mom126.index else np.nan)
            yrs.append(dt.year)
    I = np.stack(imgs).astype(np.float32)
    E = np.stack(embs).astype(np.float32)
    yv = np.array(yv, np.float32)
    dts = np.array(dts)
    momv = np.array(momv, np.float32)
    yrs = np.array(yrs)
    o = np.argsort(dts, kind="stable")
    I, E, yv, dts, momv, yrs = (I[o], E[o], yv[o], dts[o], momv[o], yrs[o])
    n = len(yv)
    print(f"assembled {n} samples (img {I.nbytes/1e9:.2f}GB) "
          f"({time.time()-t0:.0f}s)")

    def _ridge(Xtr, ytr, Xte):
        A = Xtr.T @ Xtr + 1.0 * np.eye(Xtr.shape[1])
        return Xte @ np.linalg.solve(A, Xtr.T @ ytr)

    def _tree(Xtr, ytr, Xte):
        try:
            from xgboost import XGBRegressor
            m = XGBRegressor(n_estimators=100, max_depth=4,
                             learning_rate=0.05, n_jobs=4, verbosity=0)
        except Exception:
            from sklearn.ensemble import GradientBoostingRegressor
            m = GradientBoostingRegressor(n_estimators=100, max_depth=3)
        m.fit(Xtr, ytr)
        return m.predict(Xte)

    # C3: CPCV mae_probe + gaf_tree vs momentum on expanded_v2
    arms = {}
    for nm, (X, fp) in {"mae_probe": (E, _ridge),
                        "gaf_tree": (I.reshape(n, -1), _tree)}.items():
        ic_a, ic_m, pr = [], [], []
        for tr, te in cpcv_splits(n, 6, 2, _H, 0.01):
            if len(tr) < 200 or len(te) < 50:
                continue
            a = _ic(fp(X[tr], yv[tr], X[te]), yv[te])
            b = _ic(momv[te], yv[te])
            if np.isfinite(a):
                ic_a.append(a)
            if np.isfinite(b):
                ic_m.append(b)
            if np.isfinite(a) and np.isfinite(b):
                pr.append(a - b)
        pr = np.array(pr)
        arms[nm] = {
            "oos_rank_ic": round(float(np.mean(ic_a)), 5) if ic_a else None,
            "mom_ic": round(float(np.mean(ic_m)), 5) if ic_m else None,
            "vs_tabular": round(float(np.mean(pr)), 5) if len(pr) else None,
            "n_folds": int(len(pr)),
            "dsr": deflated_sharpe_ratio(pr, 3).get("deflated_sharpe")
            if len(pr) >= 8 else None,
        }

    # C4: from-scratch ChartCNN trained ONCE on fit block, eval on OOS
    fit_m = np.isin(yrs, list(fit_years))
    oos_m = np.isin(yrs, list(oos))
    torch.manual_seed(42)
    np.random.seed(42)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    cnn = ChartCNN().to(dev).train()
    opt = torch.optim.Adam(cnn.parameters(), lr=1e-3, weight_decay=1e-5)
    fi = np.where(fit_m)[0]
    yz = yv.copy()
    for dt in np.unique(dts[fit_m]):
        sel = fit_m & (dts == dt)
        vv = yv[sel]
        if vv.std() > 0:
            yz[sel] = (vv - vv.mean()) / vv.std()
    fi = fi[np.isfinite(yz[fi])]
    for ep in range(60):
        p = np.random.permutation(fi)
        for b in range(0, len(p), 256):
            bi = p[b:b + 256]
            xb = torch.tensor(I[bi], device=dev)
            yb = torch.tensor(yz[bi], device=dev)
            opt.zero_grad()
            loss = torch.mean((cnn(xb) - yb) ** 2)
            loss.backward()
            opt.step()
    cnn.eval()
    sc = np.full(n, np.nan, np.float32)
    oi = np.where(oos_m)[0]
    with torch.no_grad():
        for b in range(0, len(oi), 256):
            bi = oi[b:b + 256]
            sc[bi] = cnn(torch.tensor(I[bi], device=dev)).cpu().numpy()
    fs_ic, mm_ic = [], []
    for dt in np.unique(dts[oos_m]):
        sel = oos_m & (dts == dt)
        if sel.sum() < 10:
            continue
        fs_ic.append(_ic(sc[sel], yv[sel]))
        mm_ic.append(_ic(momv[sel], yv[sel]))
    fs = {"oos_rank_ic": round(float(np.nanmean(fs_ic)), 5) if fs_ic else None,
          "mom_ic": round(float(np.nanmean(mm_ic)), 5) if mm_ic else None,
          "trained": "from-scratch ChartCNN, 60ep, fit-block once (NOT "
                     "per-CPCV-fold — bounded approximation, recorded)"}

    out = {
        "evaluation": "c3c4_expanded_fromscratch",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "universe": "expanded_v2", "n_universe": len(syms),
        "n_samples": int(n), "date_stride": _STRIDE,
        "n_universe_loaded": len(close),
        "n_skipped_barstore_nanvol_bug": _skipped_loaderr,
        "barstore_bug_finding": "core/data/bar_store.py:500 "
            "_apply_forward_splits volume.astype('int64') raises "
            "IntCastingNaNError on NaN-volume symbols. Surfaced by "
            "expanded_v2 (1000 data-driven; 79/328 curated never hit it). "
            "Pre-existing robustness bug — SEPARATE fix item (touches a "
            "load-bearing core module → own G1); NOT silently swallowed: "
            "skipped symbols counted; C3/C4 run on the loadable subset "
            "with this limitation explicitly recorded (audit discipline).",
        "c3_expanded_arms": arms,
        "c4_from_scratch": fs,
        "comparison": "pretrain→probe (mae_probe) vs from-scratch CNN on "
                      "the SAME literature pipeline + universe",
        "verdict_scope": "config_scoped",
        "note": "C3 = literature large-cross-section test; C4 = "
                "from-scratch comparison. Sizing (stride=10, from-scratch "
                "fit-once) recorded honestly; config-scoped (D2), research-"
                "signal not deployable. sealed 2026 never read.",
        "sealed_2026_read": False,
    }
    p = _PROJ / "data" / "audit" / "ml_redo" / "c3c4_expanded.json"
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"C3C4 -> {p.name}: mae_probe vs_tab="
          f"{arms.get('mae_probe', {}).get('vs_tabular')} "
          f"gaf vs_tab={arms.get('gaf_tree', {}).get('vs_tabular')} | "
          f"from_scratch IC={fs['oos_rank_ic']} vs mom {fs['mom_ic']} "
          f"({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
