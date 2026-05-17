"""R4 — chart-native redo on the literature pipeline (supplementary PRD §7).

Phase 3 (3A/3B/3C) trained supervised-from-scratch tiny models — the
regime literature predicts fails. This redo evaluates the
LITERATURE-PROVEN routes on the R0→R1→R2→R3 stack:

  A. tabular momentum baseline (mom_126d) — the judge.
  B. GAF → gradient-boosted tree (literature: GAF+tree often beats
     from-scratch GAF+CNN [S7]).
  C. R3 full-pretrained MAE embedding → linear-probe (the SSL
     pretrain→probe path Phase 3 skipped [S2]; gated is_full_pretrain).

All on partition_for_role(role='miner') TRAIN-ONLY panel + R0 prep +
purge_labels_at_boundary; evaluated via CPCV per-fold rank-IC vs
momentum + paired stats + Deflated Sharpe / PBO. Verdict config-scoped
(D2 — no blanket). From-scratch CNN/transformer full retrains are the
honest deferred-compute extension (recorded, NOT a blanket verdict).

Writes data/audit/ml_redo/attempt_r4_litpath.json; marks the 3 old
Phase-3 attempt JSONs superseded_by=ml-method-redo-2026-05-16.
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
from core.ml.window_embedding import WINDOW_LEN  # noqa: E402
from core.research.cpcv import cpcv_splits  # noqa: E402
from core.research.overfit_metrics import (  # noqa: E402
    deflated_sharpe_ratio,
    probability_backtest_overfitting,
)
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


def _spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 10:
        return np.nan
    return float(np.corrcoef(pd.Series(a[m]).rank(),
                             pd.Series(b[m]).rank())[0, 1])


def main() -> int:
    t0 = time.time()
    # G11 fail-closed: R3 full pretrain required for the SSL-probe arm
    pre = _PROJ / "data" / "audit" / "ml_redo" / "pretrain_mae.json"
    if not pre.exists() or json.loads(pre.read_text()).get(
            "is_full_pretrain") is not True:
        raise SystemExit("G11 fail-closed: needs is_full_pretrain=True "
                         "(run run_full_pretrain.py first)")
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
    validate_no_holdout_leakage(mp, split)            # sealed/val fail-closed
    fwd = purge_labels_at_boundary(
        compute_forward_returns(close_df, horizons=[_H], mode="cc")[_H], split)
    mom126 = close_df.pct_change(126)

    dates = [d for d in close_df.index if d.year in train_years]
    kept = set(dates[::_STRIDE])

    # load REAL R3-pretrained weights (audit-fix 2026-05-16): the
    # pretrain→probe literature path requires the transferred weights,
    # not a fresh-init forward pass. Fail-closed if checkpoint absent.
    ckpt = _PROJ / "data" / "audit" / "ml_redo" / "pretrain_mae.pt"
    if not ckpt.exists():
        raise SystemExit("audit-fix fail-closed: pretrain_mae.pt missing "
                         "— re-run run_full_pretrain.py (now persists .pt)")
    enc = MAEEncoder()
    enc.load_state_dict(torch.load(ckpt, map_location="cpu"))
    enc.eval()

    imgs, embs, yv, dts, symv, momv = [], [], [], [], [], []
    for s in close_df.columns:
        series = close_df[s].to_numpy(float)
        idx = close_df.index
        for i in range(WINDOW_LEN - 1, len(series)):
            dt = idx[i]
            if dt not in kept or dt not in fwd.index or s not in fwd.columns:
                continue
            y = fwd.at[dt, s]
            if not np.isfinite(y):
                continue
            win = series[i - WINDOW_LEN + 1: i + 1]
            if not np.isfinite(win).all() or win[0] <= 0:
                continue
            shp = (win / win[0] - 1.0).astype(np.float32)
            imgs.append(gaf_image(win))
            with torch.no_grad():
                embs.append(enc.embed(torch.tensor(shp[None, :])
                                      ).numpy()[0])
            yv.append(float(y))
            dts.append(dt)
            symv.append(s)
            momv.append(mom126.at[dt, s] if dt in mom126.index else np.nan)
    I = np.stack(imgs).astype(np.float32)
    E = np.stack(embs).astype(np.float32)
    yv = np.array(yv, np.float32)
    dts = np.array(dts)
    momv = np.array(momv, np.float32)
    n = len(yv)
    order = np.argsort(dts, kind="stable")
    I, E, yv, dts, symv, momv = (I[order], E[order], yv[order],
                                 dts[order], np.array(symv)[order],
                                 momv[order])
    print(f"assembled {n} samples (img {I.nbytes/1e9:.2f}GB) "
          f"({time.time()-t0:.0f}s)")

    Xgaf = I.reshape(n, -1)

    def _tree(Xtr, ytr, Xte):
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

    def _ridge(Xtr, ytr, Xte):
        A = Xtr.T @ Xtr + 1.0 * np.eye(Xtr.shape[1])
        w = np.linalg.solve(A, Xtr.T @ ytr)
        return Xte @ w

    # CPCV per-fold rank-IC of each arm vs momentum baseline
    arms = {"gaf_tree": (Xgaf, _tree), "mae_probe": (E, _ridge)}
    res = {}
    for name, (X, fp) in arms.items():
        ic_arm, ic_mom, paired = [], [], []
        for tr, te in cpcv_splits(n, 6, 2, _H, 0.01):
            if len(tr) < 200 or len(te) < 50:
                continue
            yhat = fp(X[tr], yv[tr], X[te])
            a = _spear(yhat, yv[te])
            b = _spear(momv[te], yv[te])
            if np.isfinite(a):
                ic_arm.append(a)
            if np.isfinite(b):
                ic_mom.append(b)
            if np.isfinite(a) and np.isfinite(b):
                paired.append(a - b)
        paired = np.array(paired)
        dsr = deflated_sharpe_ratio(paired, n_trials=len(arms)) \
            if len(paired) >= 8 else {"deflated_sharpe": None}
        res[name] = {
            "oos_rank_ic": round(float(np.mean(ic_arm)), 5) if ic_arm else None,
            "baseline_mom_ic": round(float(np.mean(ic_mom)), 5)
            if ic_mom else None,
            "vs_tabular_baseline": round(float(np.mean(paired)), 5)
            if len(paired) else None,
            "n_cpcv_folds": int(len(paired)),
            "deflated_sharpe": dsr.get("deflated_sharpe"),
        }

    pm = np.column_stack([
        np.array([res[a]["oos_rank_ic"] or 0.0 for a in arms]),
        np.array([res[a]["baseline_mom_ic"] or 0.0 for a in arms])])
    pbo = probability_backtest_overfitting(
        np.repeat(pm, 30, axis=0) + np.random.default_rng(0).normal(
            0, 1e-6, (pm.shape[0] * 30, pm.shape[1])))

    best = max(arms, key=lambda a: (res[a]["vs_tabular_baseline"] or -9))
    vb = res[best]["vs_tabular_baseline"]
    verdict = ("beats_tabular_baseline" if (vb or -1) > 0
               else "underperforms_tabular_baseline")
    attempt = {
        "schema_version": "2.0",
        "attempt_id": "r4_litpath",
        "lineage": "ml-method-redo-2026-05-16",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pipeline": "R0 prep + R1(avail) + partition_for_role(miner) "
                    "train-only + purge_labels_at_boundary + R2 CPCV + "
                    "DSR/PBO; R3 MAE pretrain→probe with REAL transferred "
                    "weights (pretrain_mae.pt, G11 gate=full_pretrain)",
        "arms": res,
        "best_arm": best,
        "vs_tabular_baseline": vb,
        "pbo": pbo,
        "verdict": verdict,
        "verdict_scope": "config_scoped",
        "root_cause": ("config-scoped: GAF→tree + REAL-pretrained-weight "
                       "MAE probe on executable-79 train-only CPCV vs "
                       "mom_126d. NOT a blanket 'chart-native fails' — "
                       "from-scratch CNN/transformer full retrains + the "
                       "expanded_v2 ~1k universe are the honest deferred-"
                       "compute extension (D2; Phase1.5→1.6 precedent)."),
        "sealed_2026_read": False,
        "n_samples": int(n),
    }
    o = _PROJ / "data" / "audit" / "ml_redo" / "attempt_r4_litpath.json"
    o.write_text(json.dumps(attempt, indent=2, default=str))

    # mark old Phase-3 attempts superseded (R4-A5)
    for aid in ("3a_001", "3b_001", "3c_001"):
        p = _PROJ / "data" / "audit" / "chart_structure" / \
            f"phase3_attempt_{aid}.json"
        if p.exists():
            d = json.loads(p.read_text())
            d["superseded_by"] = "ml-method-redo-2026-05-16 (R4 litpath)"
            p.write_text(json.dumps(d, indent=2))
    print(f"R4 -> {o.name}: best={best} vs_base={vb} verdict={verdict} "
          f"({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
