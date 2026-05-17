"""C2 (R5 deferred-closeout) — real-base end-to-end stacking ensemble.

Per supplementary PRD §8 + closeout §4. R5's module/tests were done;
this runs the actual ensemble on REAL bases: {mae_probe (R3 real
pretrained-weight embedding → ridge), gaf_tree, mom_126d}. CPCV-OOF
base predictions → Ridge meta → marginal contribution of the
chart-native member (main PRD §5.2: is a weak-but-orthogonal
chart-native signal additive even though gaf_tree loses standalone?).

Train-only panel + purge + CPCV; config-scoped (D2). Reuses the R4
assembly path. Writes data/audit/ml_redo/r5_real_ensemble.json.
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
from core.ml.chart_cnn import gaf_image  # noqa: E402
from core.ml.stacking import (  # noqa: E402
    cpcv_oof_predictions,
    marginal_contribution,
    ridge_meta_fit_predict,
)
from core.ml.window_embedding import WINDOW_LEN  # noqa: E402
from core.research.temporal_split import (  # noqa: E402
    load_temporal_split,
    partition_for_role,
    purge_labels_at_boundary,
    train_year_set,
    validate_no_holdout_leakage,
)
from core.universe.universe_resolver import resolve_universe  # noqa: E402

_H = 21
_STRIDE = 3


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
    syms = [s for s in resolve_universe("executable")
            if s not in ("SPY", "QQQ")]
    close = {}
    for s in syms:
        df = store.load(s, freq="1d", adjusted=True, fallback="local")
        if df is not None and not df.empty and "close" in df.columns:
            close[s] = df["close"]
    close_df = pd.DataFrame(close).sort_index()
    mp = partition_for_role({"close": close_df}, split, role="miner")
    close_df = mp["close"]
    validate_no_holdout_leakage(mp, split)
    fwd = purge_labels_at_boundary(
        compute_forward_returns(close_df, horizons=[_H], mode="cc")[_H], split)
    mom126 = close_df.pct_change(126)
    dates = [d for d in close_df.index if d.year in train_years]
    kept = set(dates[::_STRIDE])

    enc = MAEEncoder()
    enc.load_state_dict(torch.load(ckpt, map_location="cpu"))
    enc.eval()

    imgs, embs, yv, dts, momv = [], [], [], [], []
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
    I = np.stack(imgs).astype(np.float32)
    E = np.stack(embs).astype(np.float32)
    yv = np.array(yv, np.float32)
    dts = np.array(dts)
    momv = np.array(momv, np.float32)
    o = np.argsort(dts, kind="stable")
    I, E, yv, dts, momv = I[o], E[o], yv[o], dts[o], momv[o]
    n = len(yv)
    print(f"assembled {n} samples ({time.time()-t0:.0f}s)")

    def _ridge_fp(Xtr, ytr, Xte):
        A = Xtr.T @ Xtr + 1.0 * np.eye(Xtr.shape[1])
        return Xte @ np.linalg.solve(A, Xtr.T @ ytr)

    def _tree_fp(Xtr, ytr, Xte):
        try:
            from xgboost import XGBRegressor
            m = XGBRegressor(n_estimators=120, max_depth=4,
                             learning_rate=0.05, subsample=0.8,
                             colsample_bytree=0.6, n_jobs=4, verbosity=0)
        except Exception:
            from sklearn.ensemble import GradientBoostingRegressor
            m = GradientBoostingRegressor(n_estimators=120, max_depth=3)
        m.fit(Xtr, ytr)
        return m.predict(Xte)

    # CPCV-OOF base predictions (no in-fold leak)
    mae_oof = cpcv_oof_predictions(E, yv, _ridge_fp, 6, 2, _H)
    gaf_oof = cpcv_oof_predictions(I.reshape(n, -1), yv, _tree_fp, 6, 2, _H)
    mom_base = momv.copy()
    base = np.column_stack([mae_oof, gaf_oof, mom_base])  # [chart, chart, tab]
    fin = np.isfinite(base).all(1) & np.isfinite(yv)
    base, yvf = base[fin], yv[fin]

    stack_pred, coef = ridge_meta_fit_predict(base, yvf, alpha=1.0)
    res = {
        "ic_mae_probe": round(_ic(base[:, 0], yvf), 5),
        "ic_gaf_tree": round(_ic(base[:, 1], yvf), 5),
        "ic_momentum": round(_ic(base[:, 2], yvf), 5),
        "ic_stack": round(_ic(stack_pred, yvf), 5),
        "meta_coef": [round(float(c), 5) for c in coef],
    }
    # marginal contribution of the chart-native member (idx 0 = mae_probe)
    mc_mae = marginal_contribution(base, yvf, 0, _ic, alpha=1.0)
    mc_gaf = marginal_contribution(base, yvf, 1, _ic, alpha=1.0)

    out = {
        "evaluation": "r5_real_ensemble_C2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bases": ["mae_probe(R3 real pretrained→ridge)", "gaf_tree",
                  "mom_126d"],
        "pipeline": "train-only partition + purge + CPCV-OOF + Ridge meta",
        "n": int(len(yvf)),
        "scores": res,
        "marginal_mae_probe": mc_mae,
        "marginal_gaf_tree": mc_gaf,
        "verdict_scope": "config_scoped",
        "interpretation": (
            "stack IC vs best single base = chart-native's ensemble value; "
            "marginal_* >0 ⇒ that member is additive (weak-orthogonal can "
            "add even if it loses standalone — main PRD §5.2). config-"
            "scoped (D2), research-signal not deployable candidate."),
        "sealed_2026_read": False,
    }
    p = _PROJ / "data" / "audit" / "ml_redo" / "r5_real_ensemble.json"
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"R5 -> {p.name}: stack_IC={res['ic_stack']} "
          f"mae={res['ic_mae_probe']} gaf={res['ic_gaf_tree']} "
          f"mom={res['ic_momentum']} | marg_mae={mc_mae['marginal']:+.4f} "
          f"marg_gaf={mc_gaf['marginal']:+.4f} ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
