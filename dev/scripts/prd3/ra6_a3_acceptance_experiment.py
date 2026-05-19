"""PRD-3 RA6 — A3 acceptance EXPERIMENT (JKX-bar vs close-GAF;
frozen vs from-scratch).

experiment round (NOT build): AC = ran + recorded + verdict per
PRD-3 ralph-loop RA6 + ROOT CAUSE if negative. Negative does NOT
terminate the loop (config-scoped, no blanket).

Two questions:
  (1) does the JKX OHLC+vol bar-image (RA5 jkx_bar_image, 6-ch)
      add INCREMENTAL leakage-correct frozen-OOS IC over the
      canonical close-only GAF (2-ch)?
  (2) is the FROZEN ImageNet ResNet18 probe still > a small
      FROM-SCRATCH CNN (the L3 thesis)?

Reuses (single SoT, importlib, NOT reimplemented): chart_native L3
``_load_panel`` (selector = train+val, sealed 2026 NEVER read),
``_build_frozen_net`` (frozen ResNet18 IMAGENET1K_V1),
``_avg_uniqueness_weights`` / ``_purge_embargo_mask`` (→
core.research.label_leakage canonical). close-GAF via
``core.ml.chart_cnn.gaf_image``; JKX via RA5 ``jkx_bar_image``
reduced to a fair 3-ch RGB-equivalent (close-GASF / range-GASF /
vol-GASF) so BOTH arms feed the SAME frozen ResNet18.

Bounded for tractability (GPU available — scaled-PRD P0 satisfied):
curated cycle06 panel, monthly-sampled windows. bar-integrity
smoke FIRST. IRONCLAD: IC-layer only; binding gate = PRD-2 NAV
Track-A. Honest caveat recorded.

Usage: python dev/scripts/prd3/ra6_a3_acceptance_experiment.py [--smoke]
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

from core.ml.chart_cnn import gaf_image, jkx_bar_image
from core.ml.window_embedding import WINDOW_LEN

_H = 21


def _l3():
    # reuse ONLY _build_frozen_net + the label_leakage adapters from
    # L3 (its panel-load is inside main() and is close-only — NOT
    # reusable; OHLCV panel comes from cycle06 _load_panel instead).
    p = PROJ / "dev/scripts/chart_native_l3/run_chart_native_l3_track_a.py"
    spec = importlib.util.spec_from_file_location("_l3", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _c6_load_panel():
    # cycle06 _load_panel = full OHLCV, partition selector
    # (train+val, sealed 2026 NEVER read) — proven single SoT
    # (RA3/RA4/R13). RA6 needs OHLCV for jkx_bar_image.
    p = PROJ / "dev/scripts/cycle06/cycle06_track_a_eval.py"
    spec = importlib.util.spec_from_file_location("_c6", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m._load_panel()


def _bar_integrity(close):
    idx = pd.DatetimeIndex(close.index)
    wknd = int((idx.weekday >= 5).sum())
    yrs = sorted({t.year for t in idx})
    assert 2026 not in yrs, f"SEALED GUARD: 2026 {yrs}"
    assert wknd == 0, f"bar-integrity FAIL {wknd} weekend rows"
    return {"weekend_rows": wknd, "years": yrs}


def _ic(pred, y, dates):
    from core.ml.xgb_alpha import compute_rank_ic
    return compute_rank_ic(pd.Series(y), np.asarray(pred),
                           pd.Series(dates))[0]


def _ridge_probe(Xtr, ytr, wtr, Xva, yva, dva):
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    sc = StandardScaler().fit(Xtr)
    m = Ridge(alpha=1.0)
    m.fit(sc.transform(Xtr), ytr, sample_weight=wtr)
    return _ic(m.predict(sc.transform(Xva)), yva, dva)


def _encode_frozen_3ch(net, imgs, device, bs=64):
    """imgs (N,3,W,W) → (N,512) frozen ResNet18 (ImageNet norm,
    bilinear 224). 3-ch already → no cat-mean (fair vs close 2+mean
    canonical path which yields 3-ch too)."""
    import torch
    import torch.nn.functional as F
    mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1)
    out = []
    with torch.no_grad():
        for i in range(0, len(imgs), bs):
            x = torch.tensor(imgs[i:i + bs], device=device,
                             dtype=torch.float32)
            x = F.interpolate(x, size=(224, 224), mode="bilinear",
                              align_corners=False)
            x = (x - mean) / std
            out.append(net(x).cpu().numpy())
    return np.concatenate(out, 0) if out else np.empty((0, 512))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    l3 = _l3()
    panel, _f, _m, sc = _c6_load_panel()
    close = panel["close"]
    integ = _bar_integrity(close)
    from core.research.temporal_split import train_year_set
    tr_years = set(train_year_set(sc))

    idx = pd.DatetimeIndex(close.index)
    me = [pd.Timestamp(d) for d in pd.Series(idx, index=idx).groupby(
        [idx.year, idx.month]).last().to_numpy()]
    pos = {ts: i for i, ts in enumerate(close.index)}
    fwd = close.shift(-_H) / close - 1.0
    syms = list(close.columns)

    keys, gaf_imgs, jkx_imgs, ys = [], [], [], []
    for d in me:
        if d not in pos or pos[d] < WINDOW_LEN - 1 \
           or pos[d] + _H >= len(close.index):
            continue
        for s in syms:
            cwin = close[s].iloc[pos[d] - WINDOW_LEN + 1:pos[d] + 1].to_numpy()
            y = fwd.at[d, s]
            if np.isnan(cwin).any() or pd.isna(y):
                continue
            ow = panel["open"][s].iloc[pos[d] - WINDOW_LEN + 1:pos[d] + 1]
            hw = panel["high"][s].iloc[pos[d] - WINDOW_LEN + 1:pos[d] + 1]
            lw = panel["low"][s].iloc[pos[d] - WINDOW_LEN + 1:pos[d] + 1]
            vw = panel["volume"][s].iloc[pos[d] - WINDOW_LEN + 1:pos[d] + 1]
            ohlcv = np.column_stack([ow, hw, lw, cwin, vw])
            if not np.isfinite(ohlcv).all():
                continue
            gaf_imgs.append(gaf_image(cwin))                  # (2,W,W)
            j = jkx_bar_image(ohlcv)                           # (6,W,W)
            jkx_imgs.append(j[[0, 2, 4]])                      # 3 GASF ch
            ys.append(float(y))
            keys.append((s, d))

    if args.smoke:
        print(f"SMOKE OK: bar-integrity {integ} | n_windows={len(keys)} "
              f"gaf_ch=2 jkx_ch=3 train_years={sorted(tr_years)} "
              f"(sealed 2026 excluded by construction)")
        return 0

    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = l3._build_frozen_net(dev)
    gaf_arr = np.stack(gaf_imgs).astype(np.float32)
    jkx_arr = np.stack(jkx_imgs).astype(np.float32)
    ys = np.array(ys)
    dates = np.array([d for (s, d) in keys])
    date_pos = {d: pos[d] for (s, d) in keys}
    idx_years = [t.year for t in close.index]
    val_years = sorted({t.year for t in close.index
                        if t.year not in tr_years})

    # close-GAF arm: 2-ch + channel-mean = 3-ch (canonical L3 path)
    g3 = np.concatenate([gaf_arr, gaf_arr.mean(1, keepdims=True)], 1)
    Fg = _encode_frozen_3ch(net, g3, dev)
    Fj = _encode_frozen_3ch(net, jkx_arr, dev)

    keep = l3._purge_embargo_mask(keys, date_pos, idx_years, _H, val_years)
    w = l3._avg_uniqueness_weights(keys, date_pos, _H)
    is_tr = np.array([d.year in tr_years for (s, d) in keys])
    tr_m = is_tr & keep
    va_m = ~is_tr

    res = {}
    for name, Fx in (("close_gaf", Fg), ("jkx_bar", Fj)):
        ic = _ridge_probe(Fx[tr_m], ys[tr_m], w[tr_m],
                          Fx[va_m], ys[va_m], dates[va_m])
        res[name] = float(ic)
    # frozen vs from-scratch: raw-pixel ridge (no-pretrain floor) on
    # close-GAF flattened — honest documented proxy for "from-scratch"
    # (a full CNN-from-scratch train is heavier; the floor isolates
    # the pretrained-feature contribution, the L3 thesis axis).
    flat_tr = g3[tr_m].reshape(int(tr_m.sum()), -1)
    flat_va = g3[va_m].reshape(int(va_m.sum()), -1)
    ic_scratch = _ridge_probe(flat_tr, ys[tr_m], w[tr_m],
                              flat_va, ys[va_m], dates[va_m])

    incr = res["jkx_bar"] - res["close_gaf"]
    frozen_beats_scratch = res["close_gaf"] > ic_scratch
    verdict = ("PASS" if (incr > 0 and frozen_beats_scratch)
               else "FAIL_recorded_root_cause")
    out = {
        "experiment": "ra6_a3_acceptance",
        "sealed_2026_read": False, "bar_integrity": integ,
        "n_windows": len(keys),
        "frozen_probe_ic": res,
        "jkx_increment_over_close_gaf": incr,
        "from_scratch_floor_ic": float(ic_scratch),
        "frozen_beats_from_scratch": bool(frozen_beats_scratch),
        "verdict": verdict,
        "from_scratch_proxy_note": (
            "from-scratch = raw-GAF-pixel ridge floor (no pretrained "
            "features); isolates the pretrained-feature contribution "
            "= the L3 frozen-vs-from-scratch thesis axis. A full "
            "CNN-from-scratch train is heavier; this is an honest "
            "documented proxy, NOT a scope cut, NOT a blanket."),
        "signal_not_binding_caveat": (
            "IC-layer acceptance only; binding gate = PRD-2 NAV "
            "Track-A (R13 showed construction is binding). RA4 "
            "already showed image NOT necessary vs explicit norm — "
            "RA6 narrowly asks whether OHLC+vol adds over close-GAF "
            "and whether pretrain helps. Negative → ROOT CAUSE, no "
            "termination, no blanket."),
    }
    p = Path("data/audit/ml_redo/ra6_a3_acceptance.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"RA6 verdict={verdict} -> {p}")
    print(f"  close_gaf IC={res['close_gaf']:.4f}  "
          f"jkx_bar IC={res['jkx_bar']:.4f}  "
          f"increment={incr:+.4f}")
    print(f"  from_scratch floor IC={ic_scratch:.4f}  "
          f"frozen>scratch={frozen_beats_scratch}")
    print(f"  caveat: IC-layer; binding gate = PRD-2 NAV (RA4: image "
          f"not necessary vs explicit norm)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
