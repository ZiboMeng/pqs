"""W8 S1 — GAF chart images → FROZEN ImageNet-pretrained ResNet18
backbone → linear probe (scaled-checkpoint PRD §4 S1).

User explicit-go 2026-05-18: "装库做 imagenet 那就装,不要自己去弄一个
模型" → torchvision installed (forced torch 2.11→2.12; bump regression-
smoked 60/60 green, recorded honestly). This uses a STANDARD pretrained
backbone (torchvision ResNet18 IMAGENET1K_V1), NOT a hand-rolled model.

S1 hypothesis (user's original intuition + PRD): does starting the
GAF/CNN path from a "reasonable external checkpoint" (ImageNet) beat
from-scratch on financial chart images? Honest caveat (PRD §6):
ImageNet→GAF transfer is literature-mixed (GAF is not a natural
image). Verdict is config-scoped, research-signal, NOT deployable.

Discipline: TRAIN-ONLY (temporal_split; SEALED 2026 fail-closed
guard), P0-A-correct adjusted prices (BarStore adjusted), CPCV,
honest-N DSR (G1 dsr_trial_accounting, no magic literal). GPU
4GB-bounded; run SERIAL after S2 (single GPU). Mirrors S2 structure.
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
from core.ml.chart_cnn import gaf_image  # noqa: E402
from core.ml.window_embedding import WINDOW_LEN  # noqa: E402
from core.research.cpcv import cpcv_splits  # noqa: E402
from core.research.dsr_trial_accounting import (  # noqa: E402
    ML_REDO_CHART_NATIVE_ARMS,
)
from core.research.overfit_metrics import deflated_sharpe_ratio  # noqa: E402
from core.research.temporal_split import (  # noqa: E402
    load_temporal_split,
    train_year_set,
)
from core.universe.universe_resolver import resolve_universe  # noqa: E402

_H = 21
# ImageNet normalization (the pretrained backbone's training stats)
_IMN_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_IMN_STD = np.array([0.229, 0.224, 0.225], np.float32)


def _ic(p, y):
    m = np.isfinite(p) & np.isfinite(y)
    if m.sum() < 10:
        return np.nan
    return float(np.corrcoef(pd.Series(p[m]).rank(),
                             pd.Series(y[m]).rank())[0, 1])


def _ridge(Xtr, ytr, Xte, lam=10.0):
    A = Xtr.T @ Xtr + lam * np.eye(Xtr.shape[1])
    return Xte @ np.linalg.solve(A, Xtr.T @ ytr)


def _frozen_imagenet_features(imgs, device, batch=64):
    """GAF (N,2,W,W) → frozen ImageNet ResNet18 512-d features.
    GAF 2ch → 3ch [gasf, gadf, mean]; resize W→224; ImageNet-norm;
    backbone frozen (no grad, eval) — a STANDARD pretrained encoder,
    not a trained-here model."""
    import torch
    import torch.nn.functional as F
    from torchvision.models import ResNet18_Weights, resnet18

    net = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)
    net.fc = torch.nn.Identity()          # 512-d penultimate features
    net = net.to(device).eval()
    for p in net.parameters():
        p.requires_grad_(False)
    feats = []
    with torch.no_grad():
        for i in range(0, len(imgs), batch):
            x = torch.tensor(imgs[i:i + batch], device=device)  # (b,2,W,W)
            third = x.mean(dim=1, keepdim=True)
            x = torch.cat([x, third], dim=1)                    # (b,3,W,W)
            x = F.interpolate(x, size=(224, 224), mode="bilinear",
                              align_corners=False)
            mean = torch.tensor(_IMN_MEAN, device=device).view(1, 3, 1, 1)
            std = torch.tensor(_IMN_STD, device=device).view(1, 3, 1, 1)
            x = (x - mean) / std
            feats.append(net(x).cpu().numpy())
    return np.concatenate(feats, 0)


def main() -> int:
    import torch

    t0 = time.time()
    cfg = load_config(Path("config"))
    split = load_temporal_split(Path("config/temporal_split.yaml"))
    ty = train_year_set(split)
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    syms = [s for s in resolve_universe("executable")
            if s not in ("SPY", "QQQ")]

    close = {}
    for s in syms:
        try:
            df = store.load(s, freq="1d", adjusted=True, fallback="local")
        except Exception:
            continue
        if df is not None and not df.empty and "close" in df.columns:
            close[s] = df["close"]
    cdf = pd.DataFrame(close).sort_index()
    cdf = cdf[[ts.year in ty for ts in cdf.index]]
    if {ts.year for ts in cdf.index} - ty:
        raise SystemExit("SEALED GUARD: non-train years present")
    fwd = compute_forward_returns(cdf, [_H])[_H]

    imgs, yv, momv = [], [], []
    for s in cdf.columns:
        v = cdf[s].to_numpy(float)
        idx = cdf.index
        for i in range(WINDOW_LEN - 1, len(v)):
            dt = idx[i]
            if dt not in fwd.index or s not in fwd.columns:
                continue
            y = fwd.at[dt, s]
            w = v[i - WINDOW_LEN + 1:i + 1]
            if not (np.isfinite(y) and np.isfinite(w).all() and w[0] > 0):
                continue
            imgs.append(gaf_image(w))
            yv.append(float(y))
            momv.append(v[i] / v[i - 126] - 1.0 if i >= 126 else np.nan)
    I = np.stack(imgs).astype(np.float32)
    yv = np.array(yv, np.float32)
    momv = np.array(momv, np.float32)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"assembled {len(I)} GAF windows train-only "
          f"({time.time()-t0:.0f}s) device={dev}")

    E = _frozen_imagenet_features(I, dev)
    print(f"frozen ImageNet features {E.shape} ({time.time()-t0:.0f}s)")

    ic_probe, ic_mom = [], []
    for tr, te in cpcv_splits(len(E), 6, 2, _H, 0.01):
        if len(tr) < 200 or len(te) < 50:
            continue
        a = _ic(_ridge(E[tr], yv[tr], E[te]), yv[te])
        b = _ic(momv[te], yv[te])
        if np.isfinite(a):
            ic_probe.append(a)
        if np.isfinite(b):
            ic_mom.append(b)
    probe_ic = float(np.mean(ic_probe)) if ic_probe else np.nan
    mom_ic = float(np.mean(ic_mom)) if ic_mom else np.nan
    n_trials = ML_REDO_CHART_NATIVE_ARMS
    dsr = (deflated_sharpe_ratio(np.array(ic_probe), n_trials)
           if len(ic_probe) >= 8 else {"deflated_sharpe": None})

    out = {
        "experiment": "w8_s1_imagenet_frozen_backbone",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "torch_version": torch.__version__,
        "backbone": "torchvision resnet18 IMAGENET1K_V1 (frozen, fc=Identity)",
        "train_years_only": sorted(ty), "sealed_2026_read": False,
        "n_windows": int(len(I)), "n_folds": len(ic_probe),
        "imagenet_probe_ic": round(probe_ic, 5)
        if np.isfinite(probe_ic) else None,
        "momentum_baseline_ic": round(mom_ic, 5)
        if np.isfinite(mom_ic) else None,
        "vs_momentum": round(probe_ic - mom_ic, 5)
        if np.isfinite(probe_ic) and np.isfinite(mom_ic) else None,
        "dsr_honest_n": dsr.get("deflated_sharpe"),
        "dsr_n_trials": n_trials,
        "honest_caveat": "ImageNet→GAF transfer literature-mixed (GAF "
                         "not a natural image); config-scoped research "
                         "signal; NOT deployable; not hand-rolled "
                         "(standard torchvision pretrained backbone).",
        "verdict_scope": "config_scoped; train-only; sealed never read",
    }
    p = Path("data/audit/w8_s1_imagenet_backbone.json")
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"S1: imagenet_probe_ic={out['imagenet_probe_ic']} "
          f"mom_ic={out['momentum_baseline_ic']} "
          f"vs_mom={out['vs_momentum']} dsr={out['dsr_honest_n']} -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
