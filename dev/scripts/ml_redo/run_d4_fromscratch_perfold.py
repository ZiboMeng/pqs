"""D4 — from-scratch ChartCNN trained PER-CPCV-FOLD (closeout §4 last
deferred caveat closure).

C4 (in run_c3c4_expanded_fromscratch.py) trained the from-scratch CNN
ONCE on the fit block then scored OOS — a bounded, honestly-recorded
approximation, NOT a per-fold retrain. This script closes that caveat:
identical data assembly / universe / preprocessing / temporal-split
discipline as D3's C3C4 (so it is apples-to-apples), but for each CPCV
split it trains a FRESH ChartCNN from scratch on the train indices and
evaluates on the held test indices, collecting per-fold OOS rank-IC vs
the momentum baseline + DSR — the same rigor C3's probe arms already
get.

Expectation (recorded up-front, no overclaim either way): the
"from-scratch loses to pretrain->probe" verdict is already stable
across dirty fit-once (IC -0.003) and clean fit-once (IC +0.002); this
run is expected to CONFIRM, not flip it. Value = closing the last
bounded-approximation caveat with a rigorous number (做透 not just
做出来), per feedback_audit_surfaces_not_thorough.

train-only partition + purge + CPCV; config-scoped (D2); sealed 2026
NEVER read. Writes data/audit/ml_redo/d4_fromscratch_perfold.json.
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
_STRIDE = 10          # identical to D3 C3C4 (1000-universe RAM bound)
_EPOCHS = 60          # identical per-fold training budget to C4 fit-once


def _ic(p, y):
    m = np.isfinite(p) & np.isfinite(y)
    if m.sum() < 10:
        return 0.0
    return float(np.corrcoef(pd.Series(p[m]).rank(),
                             pd.Series(y[m]).rank())[0, 1])


def main() -> int:
    t0 = time.time()
    import torch

    cfg = load_config(_PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    split = load_temporal_split(_PROJ / "config" / "temporal_split.yaml")
    train_years = train_year_set(split)
    syms = [s for s in resolve_universe("expanded_v2")
            if s not in ("SPY", "QQQ")]
    print(f"expanded_v2 universe: {len(syms)} symbols")

    close = {}
    _skipped_loaderr = 0
    for s in syms:
        try:
            df = store.load(s, freq="1d", adjusted=True, fallback="local")
        except Exception:
            _skipped_loaderr += 1
            continue
        if df is not None and not df.empty and "close" in df.columns:
            close[s] = df["close"]
    print(f"loaded {len(close)}/{len(syms)} (skipped {_skipped_loaderr})")
    close_df = pd.DataFrame(close).sort_index()
    mp = partition_for_role({"close": close_df}, split, role="miner")
    close_df = mp["close"]
    validate_no_holdout_leakage(mp, split)
    fwd = purge_labels_at_boundary(
        compute_forward_returns(close_df, horizons=[_H], mode="cc")[_H], split)
    mom126 = close_df.pct_change(126)
    dts_all = [d for d in close_df.index if d.year in train_years]
    kept = set(dts_all[::_STRIDE])

    imgs, yv, dts, momv = [], [], [], []
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
            imgs.append(gaf_image(w))
            yv.append(float(y))
            dts.append(dt)
            momv.append(mom126.at[dt, s] if dt in mom126.index else np.nan)
    I = np.stack(imgs).astype(np.float32)
    yv = np.array(yv, np.float32)
    dts = np.array(dts)
    momv = np.array(momv, np.float32)
    o = np.argsort(dts, kind="stable")
    I, yv, dts, momv = I[o], yv[o], dts[o], momv[o]
    n = len(yv)
    print(f"assembled {n} samples (img {I.nbytes/1e9:.2f}GB) "
          f"({time.time()-t0:.0f}s)")

    dev = "cuda" if torch.cuda.is_available() else "cpu"

    def _fit_predict(tr, te):
        """Fresh ChartCNN from scratch on tr, predict te. Per-date
        z-scored target (mirrors C4 fit-once normalization)."""
        torch.manual_seed(42)
        np.random.seed(42)
        yz = yv.copy()
        for dt in np.unique(dts[tr]):
            sel = (dts == dt)
            vv = yv[sel]
            if vv.std() > 0:
                yz[sel] = (vv - vv.mean()) / vv.std()
        fi = tr[np.isfinite(yz[tr])]
        cnn = ChartCNN().to(dev).train()
        opt = torch.optim.Adam(cnn.parameters(), lr=1e-3, weight_decay=1e-5)
        for _ in range(_EPOCHS):
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
        out = np.full(len(te), np.nan, np.float32)
        with torch.no_grad():
            for b in range(0, len(te), 256):
                bi = te[b:b + 256]
                out[b:b + len(bi)] = cnn(
                    torch.tensor(I[bi], device=dev)).cpu().numpy()
        return out

    ic_fs, ic_m, pr = [], [], []
    fold_no = 0
    for tr, te in cpcv_splits(n, 6, 2, _H, 0.01):
        if len(tr) < 200 or len(te) < 50:
            continue
        fold_no += 1
        sc = _fit_predict(tr, te)
        a = _ic(sc, yv[te])
        b = _ic(momv[te], yv[te])
        if np.isfinite(a):
            ic_fs.append(a)
        if np.isfinite(b):
            ic_m.append(b)
        if np.isfinite(a) and np.isfinite(b):
            pr.append(a - b)
        print(f"  fold {fold_no}: fs_ic={a:.5f} mom_ic={b:.5f} "
              f"({time.time()-t0:.0f}s)")
    pr = np.array(pr)

    out = {
        "evaluation": "d4_fromscratch_perfold",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "universe": "expanded_v2",
        "n_universe_loaded": len(close),
        "n_skipped_barstore_nanvol_bug": _skipped_loaderr,
        "n_samples": int(n),
        "date_stride": _STRIDE,
        "epochs_per_fold": _EPOCHS,
        "n_folds": int(len(pr)),
        "fromscratch_perfold": {
            "oos_rank_ic": round(float(np.mean(ic_fs)), 5) if ic_fs else None,
            "mom_ic": round(float(np.mean(ic_m)), 5) if ic_m else None,
            "vs_momentum": round(float(np.mean(pr)), 5) if len(pr) else None,
            "dsr": deflated_sharpe_ratio(pr, 3).get("deflated_sharpe")
            if len(pr) >= 8 else None,
        },
        "comparison_baseline_c4_fit_once_clean": {
            "oos_rank_ic": 0.00223,
            "note": "from c3c4_expanded.cleandata.json (D3 clean fit-once)",
        },
        "verdict_scope": "config_scoped",
        "note": "D4 = rigorous per-CPCV-fold from-scratch retrain, "
                "closing the C4 fit-once bounded-approximation caveat. "
                "Same data/universe/prep/temporal-split as D3 C3C4. "
                "config-scoped (D2), research-signal not deployable. "
                "sealed 2026 never read.",
        "sealed_2026_read": False,
    }
    p = _PROJ / "data" / "audit" / "ml_redo" / "d4_fromscratch_perfold.json"
    p.write_text(json.dumps(out, indent=2, default=str))
    fs = out["fromscratch_perfold"]
    print(f"D4 -> {p.name}: fs_ic={fs['oos_rank_ic']} "
          f"mom_ic={fs['mom_ic']} vs_mom={fs['vs_momentum']} "
          f"dsr={fs['dsr']} ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
