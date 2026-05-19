"""PRD-3 RA8 — A4 acceptance EXPERIMENT (in-domain SSL vs ImageNet
domain-transfer). FINAL PRD-3-A round.

experiment round (NOT build): AC = ran + recorded + verdict
(in-domain increment MAGNITUDE; **NO vision-scale overclaim**) +
DSR true-N + ROOT CAUSE if negative. Negative does NOT terminate
the loop (config-scoped, no blanket).

Two arms, SAME leakage-correct frozen-OOS ridge probe (cycle06
_load_panel selector = train+val, sealed 2026 NEVER read;
sample-uniqueness + purge via the L3 → core.research.label_leakage
canonical adapters):
  in_domain_ssl : RA7 a4_ssl_frozen_probe_scaffold — MAE masked-SSL
      pretrained on TRAIN-ONLY close windows, frozen 64-d embed
      (curated 'executable' universe → R6 guard passes).
  imagenet_xfer : close GAF → L3 _build_frozen_net frozen ResNet18
      IMAGENET1K_V1, 512-d (domain-OUT transfer; the
      chart_native_s1 family — close-GAF under leakage-correct is
      ~0 per RA6, recorded honestly, NOT a new finding).

DSR true-N: deflated_sharpe_ratio on the better arm's per-period
IC, n_trials = assert_honest_n(PRD-3-A representation
model-selection breadth ≈ 10: RA1/RA2/RA4×3/RA6×3/RA8×2) — a
conservative HONEST count (larger N ⇒ stricter DSR = the honest
direction), NEVER a placeholder N=1/2 (the self-corrected
ML-redo overclaim precedent).

IRONCLAD: IC-layer only; binding gate = PRD-2 NAV Track-A. RA4
already showed image NOT necessary vs explicit norm. **NO
vision-magnitude overclaim** — report the modest financial-SNR
increment plainly. bar-integrity smoke FIRST.

Usage: python dev/scripts/prd3/ra8_a4_acceptance_experiment.py [--smoke]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

# 4GB-VRAM constraint (PRD-3 RA7 "GPU 4GB 串行"): reduce allocator
# fragmentation per the torch OOM guidance. Set BEFORE torch import.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.ml.chart_cnn import gaf_image
from core.ml.window_embedding import WINDOW_LEN
from core.research.a4_universe_guard import a4_ssl_frozen_probe_scaffold
from core.research.temporal_split import train_year_set
from core.research.overfit_metrics import deflated_sharpe_ratio
from core.research.dsr_trial_accounting import assert_honest_n

_H = 21
# honest PRD-3-A representation model-selection breadth (documented,
# conservative — NOT a placeholder; larger ⇒ stricter DSR).
_HONEST_N = 10


def _imp(path, name):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _bar_integrity(close):
    idx = pd.DatetimeIndex(close.index)
    wknd = int((idx.weekday >= 5).sum())
    yrs = sorted({t.year for t in idx})
    assert 2026 not in yrs, f"SEALED GUARD: 2026 {yrs}"
    assert wknd == 0, f"bar-integrity FAIL {wknd} weekend rows"
    return {"weekend_rows": wknd, "years": yrs}


def _ridge_probe_ic(Xtr, ytr, wtr, Xva, yva, dva):
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    from core.ml.xgb_alpha import compute_rank_ic
    sc = StandardScaler().fit(Xtr)
    m = Ridge(alpha=1.0).fit(sc.transform(Xtr), ytr, sample_weight=wtr)
    pred = m.predict(sc.transform(Xva))
    ic_mean, _std, ic_series = compute_rank_ic(
        pd.Series(yva), pred, pd.Series(dva))
    return ic_mean, ic_series


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    c6 = _imp(PROJ / "dev/scripts/cycle06/cycle06_track_a_eval.py", "_c6")
    l3 = _imp(PROJ / "dev/scripts/chart_native_l3/run_chart_native_l3_track_a.py",
              "_l3")
    panel, _f, _m, sc = c6._load_panel()
    close = panel["close"]
    integ = _bar_integrity(close)
    tr_years = set(train_year_set(sc))

    idx = pd.DatetimeIndex(close.index)
    me = [pd.Timestamp(d) for d in pd.Series(idx, index=idx).groupby(
        [idx.year, idx.month]).last().to_numpy()]
    pos = {ts: i for i, ts in enumerate(close.index)}
    fwd = close.shift(-_H) / close - 1.0

    keys, cwins, ys = [], [], []
    for d in me:
        if d not in pos or pos[d] < WINDOW_LEN - 1 \
           or pos[d] + _H >= len(close.index):
            continue
        for s in close.columns:
            w = close[s].iloc[pos[d] - WINDOW_LEN + 1:pos[d] + 1].to_numpy()
            y = fwd.at[d, s]
            if np.isnan(w).any() or pd.isna(y):
                continue
            cwins.append(w.astype(np.float32))
            ys.append(float(y))
            keys.append((s, d))

    if args.smoke:
        print(f"SMOKE OK: bar-integrity {integ} | n_windows={len(keys)} "
              f"honest_n={_HONEST_N} train_years={sorted(tr_years)} "
              f"(sealed 2026 excluded by construction)")
        return 0

    cwins = np.stack(cwins)
    ys = np.array(ys)
    dates = np.array([d for (s, d) in keys])
    date_pos = {d: pos[d] for (s, d) in keys}
    idx_years = [t.year for t in close.index]
    val_years = sorted({t.year for t in close.index
                        if t.year not in tr_years})
    is_tr = np.array([d.year in tr_years for (s, d) in keys])
    keep = l3._purge_embargo_mask(keys, date_pos, idx_years, _H, val_years)
    w_uniq = l3._avg_uniqueness_weights(keys, date_pos, _H)
    tr_m, va_m = is_tr & keep, ~is_tr

    import torch

    # in-domain SSL arm (RA7 scaffold, curated → guard passes)
    _model, embed = a4_ssl_frozen_probe_scaffold(
        cwins[tr_m], steps=200, universe_name="executable", seed=42)
    Fssl = embed(cwins)
    ic_ssl, ics_ssl = _ridge_probe_ic(
        Fssl[tr_m], ys[tr_m], w_uniq[tr_m],
        Fssl[va_m], ys[va_m], dates[va_m])
    # ROOT CAUSE fix (R41): free the SSL MAE model from the 4GB GPU
    # BEFORE the ImageNet arm — otherwise the resident SSL graph +
    # ResNet18 + the 224-interpolate forward OOM the 4GB card.
    del _model, embed
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # ImageNet domain-transfer arm (close GAF → frozen ResNet18).
    # ROOT CAUSE fix (R41): NEVER call _encode_batch on the full
    # ~7781-image array (that allocates ~23GB on a 4GB GPU = the OOM
    # crash). ALWAYS stream bounded small batches (the S1/L3
    # streaming discipline; bs=16 is safe for 4GB at 224x224x3).
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = l3._build_frozen_net(dev)
    outs = []
    for i in range(0, len(cwins), 16):
        gb = np.stack([gaf_image(w) for w in cwins[i:i + 16]]
                      ).astype(np.float32)
        outs.append(l3._encode_batch(net, gb, dev))
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    Fimg = np.concatenate(outs, 0)
    ic_img, _ics_img = _ridge_probe_ic(
        Fimg[tr_m], ys[tr_m], w_uniq[tr_m],
        Fimg[va_m], ys[va_m], dates[va_m])

    incr = ic_ssl - ic_img
    n_tr = assert_honest_n(
        _HONEST_N, source="RA8 PRD-3-A representation model-selection")
    dsr = deflated_sharpe_ratio(ics_ssl.to_numpy(), n_tr)
    in_domain_better = ic_ssl > ic_img
    dsr_ok = float(dsr.get("dsr", 0.0)) > 0.5
    verdict = ("PASS" if (in_domain_better and dsr_ok)
               else "FAIL_recorded_root_cause")

    out = {
        "experiment": "ra8_a4_acceptance", "sealed_2026_read": False,
        "bar_integrity": integ, "n_windows": len(keys),
        "in_domain_ssl_ic": float(ic_ssl),
        "imagenet_xfer_ic": float(ic_img),
        "in_domain_increment": float(incr),
        "dsr": {k: (float(v) if isinstance(v, (int, float)) else v)
                for k, v in dsr.items()},
        "dsr_honest_n_trials": int(n_tr),
        "in_domain_better": bool(in_domain_better),
        "dsr_survives": bool(dsr_ok),
        "verdict": verdict,
        "no_vision_overclaim_note": (
            "Increment reported at financial-SNR scale ONLY. NO "
            "CV/vision-magnitude claim. close-GAF ImageNet arm ~0 "
            "under leakage-correct eval is EXPECTED per the "
            "chart_native_s1 leakage caveat + RA6 (NOT new). RA4 "
            "already showed the image is NOT necessary vs explicit "
            "normalization — RA8 narrowly asks whether IN-DOMAIN SSL "
            "pretrain beats OUT-of-domain ImageNet transfer."),
        "signal_not_binding_caveat": (
            "IC-layer acceptance only; binding gate = PRD-2 NAV "
            "Track-A (R13 showed construction is binding). Negative "
            "→ ROOT CAUSE, no termination, no blanket. Not a "
            "promotion (PRD-3 funnel discipline)."),
    }
    p = Path("data/audit/ml_redo/ra8_a4_acceptance.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"RA8 verdict={verdict} -> {p}")
    print(f"  in_domain_ssl IC={ic_ssl:.4f}  imagenet_xfer IC={ic_img:.4f}"
          f"  increment={incr:+.4f}")
    print(f"  DSR={dsr.get('dsr')} (honest_n={n_tr})  "
          f"in_domain_better={in_domain_better} dsr_survives={dsr_ok}")
    print(f"  NO vision-scale overclaim; IC-layer; binding=PRD-2 NAV")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
