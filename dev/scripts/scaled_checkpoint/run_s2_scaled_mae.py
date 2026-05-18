"""W8 S2 — scale the in-domain MAE (scaled-checkpoint PRD §4 S2).

User intuition (2026-05-17): "big models from a reasonable checkpoint
do better". landmark②/④ confirmed pretrain→probe >> from-scratch at
d_model=64. S2 tests whether SCALING the in-domain MAE (embedding_dim
64→128, encoder_hidden 64→128) lifts the probe IC beyond the d=64
baseline.

S1 (external ImageNet backbone) is DEPENDENCY-BLOCKED: torchvision is
not installed and the project avoids heavy deps (MiniROCKET/statsmodels
self-impl precedent) → recorded as `s1_dependency_blocked_honest_caveat`
(mirrors the PRD's own S3 no-credible-checkpoint honest pattern), NOT
a silent pip-install (that is a directional dependency decision). S2
is the no-new-dep, on-thesis, 4GB-VRAM-feasible W8 piece per the GPU
feasibility memo.

Discipline: TRAIN-ONLY (temporal_split; SEALED 2026 fail-closed guard),
P0-A-correct adjusted prices (BarStore.load adjusted=True — NOT the
buggy MarketDataStore raw path), CPCV, honest-N DSR via
dsr_trial_accounting (G1, no magic literal). config-scoped, research
signal not deployable. GPU serial (run AFTER cycle13b mining — RAM).
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
from core.ml.ssl_pretrain import MAEEncoder, segment_mask  # noqa: E402
from core.ml.window_embedding import (  # noqa: E402
    WINDOW_LEN,
    WindowEmbeddingConfig,
)
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


def _ic(p, y):
    m = np.isfinite(p) & np.isfinite(y)
    if m.sum() < 10:
        return np.nan
    return float(np.corrcoef(pd.Series(p[m]).rank(),
                             pd.Series(y[m]).rank())[0, 1])


def _ridge(Xtr, ytr, Xte, lam=1.0):
    A = Xtr.T @ Xtr + lam * np.eye(Xtr.shape[1])
    return Xte @ np.linalg.solve(A, Xtr.T @ ytr)


def _pretrain_probe(W, yv, dts, embed_dim, steps, device):
    """Self-contained scaled-MAE pretrain (segment-mask reconstruction)
    + frozen-embed ridge probe under CPCV. Mirrors run_c3c4 mae_probe
    arm but with a scaled WindowEmbeddingConfig."""
    import torch

    cfg = WindowEmbeddingConfig(embedding_dim=embed_dim,
                                encoder_hidden=embed_dim)
    torch.manual_seed(42)
    np.random.seed(42)
    model = MAEEncoder(cfg).to(device).train()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    Wt = torch.tensor(W, dtype=torch.float32, device=device)
    n = len(W)
    rng = np.random.default_rng(42)
    for _ in range(steps):
        idx = rng.choice(n, min(256, n), replace=False)
        xb = Wt[idx]
        masked, _m = segment_mask(xb.cpu().numpy(), 0.5, 6, rng)
        mb = torch.tensor(masked, dtype=torch.float32, device=device)
        opt.zero_grad()
        rec = model(mb)
        loss = torch.mean((rec - xb) ** 2)
        loss.backward()
        opt.step()
    model.eval()
    with torch.no_grad():
        E = model.embed(Wt).cpu().numpy()
        if E.ndim == 3:
            E = E[:, -1, :]
    ic_a = []
    for tr, te in cpcv_splits(n, 6, 2, _H, 0.01):
        if len(tr) < 200 or len(te) < 50:
            continue
        a = _ic(_ridge(E[tr], yv[tr], E[te]), yv[te])
        if np.isfinite(a):
            ic_a.append(a)
    return (float(np.mean(ic_a)) if ic_a else np.nan, len(ic_a))


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
    bad = {ts.year for ts in cdf.index} - ty
    if bad:
        raise SystemExit(f"SEALED GUARD: non-train years {sorted(bad)}")
    fwd = compute_forward_returns(cdf, [_H])[_H]

    Ws, ys = [], []
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
            Ws.append((w / w[0] - 1.0).astype(np.float32))
            ys.append(float(y))
    W = np.stack(Ws)
    yv = np.array(ys, np.float32)
    o = np.argsort(np.arange(len(W)))  # already time-ordered by build
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"assembled {len(W)} windows train-only ({time.time()-t0:.0f}s) "
          f"device={dev}")

    steps = 5000
    base_ic, base_n = _pretrain_probe(W, yv, None, 64, steps, dev)
    scaled_ic, scaled_n = _pretrain_probe(W, yv, None, 128, steps, dev)
    n_trials = ML_REDO_CHART_NATIVE_ARMS  # honest-N (G1), not a literal

    out = {
        "experiment": "w8_s2_scaled_mae",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "train_years_only": sorted(ty), "sealed_2026_read": False,
        "n_windows": int(len(W)), "pretrain_steps": steps,
        "baseline_d64": {"probe_ic": round(base_ic, 5)
                         if np.isfinite(base_ic) else None,
                         "n_folds": base_n},
        "scaled_d128": {"probe_ic": round(scaled_ic, 5)
                        if np.isfinite(scaled_ic) else None,
                        "n_folds": scaled_n},
        "delta_scaled_minus_base": (round(scaled_ic - base_ic, 5)
                                    if np.isfinite(scaled_ic)
                                    and np.isfinite(base_ic) else None),
        "dsr_n_trials_honest": n_trials,
        "s1_status": "s1_dependency_blocked_honest_caveat: torchvision "
                     "absent; no silent heavy-dep install (project "
                     "stance); see scaled-checkpoint PRD §S3 pattern",
        "verdict_scope": "config_scoped; research signal; NOT deployable; "
                         "GPU 4GB-bounded; train-only; sealed never read",
    }
    p = Path("data/audit/w8_s2_scaled_mae.json")
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"S2: base_d64 ic={out['baseline_d64']['probe_ic']} "
          f"scaled_d128 ic={out['scaled_d128']['probe_ic']} "
          f"delta={out['delta_scaled_minus_base']} -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
