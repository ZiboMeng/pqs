"""P3·R5 — 3C late-fusion attempt + cost-aware eval.

Per chart-structure ralph-loop execution PRD §7 round P3·R5. Trains the
``FusionModel`` (3B swing-segment branch + 3A GASF/GADF image branch,
late-fused by a small MLP) and evaluates it against the 126d momentum
baseline — strictly inside the ``train`` partition of
``config/temporal_split.yaml`` (a within-train fit/OOS split; validation
2018/19/21/23/25 + sealed 2026 are never read).

Both branch inputs are built for the SAME (symbol, bar) sample so the
fusion is exactly comparable to the single-branch 3B / 3A attempts. The
attempt JSON additionally records 3C-vs-3B and 3C-vs-3A IC so the
Phase-3 closeout can answer "is the combination > either single path".

Date-subsampled (every 3rd train trading day) to keep the GAF image
tensor inside RAM, identical to P3·R4 — loss-free for cross-sectional IC.

Per D2 a negative result still PASSES the round; the attempt JSON
records the exact config + a config-scoped ``root_cause`` — never a
blanket "3C doesn't work".

Writes data/audit/chart_structure/phase3_attempt_3c_001.json.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from math import erfc, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

_PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJ))

from core.config.loader import load_config  # noqa: E402
from core.data.bar_store import BarStore  # noqa: E402
from core.factors.factor_generator import compute_forward_returns  # noqa: E402
from core.factors.swing_structure import (  # noqa: E402
    SwingStructureConfig,
    detect_raw_swings,
)
from core.ml.chart_cnn import gaf_image  # noqa: E402
from core.ml.fusion_model import FusionModel, count_fusion_params  # noqa: E402
from core.ml.phase3_attempt import Phase3Attempt  # noqa: E402
from core.ml.phase3_eval import purged_fit_mask  # noqa: E402
from core.ml.structure_sequence_encoder import (  # noqa: E402
    MAX_SEGMENTS,
    segment_sequence_asof,
)
from core.ml.window_embedding import WINDOW_LEN  # noqa: E402
from core.research.temporal_split import load_temporal_split, train_year_set  # noqa: E402
from core.universe.universe_resolver import resolve_universe  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("p3r5")

_HORIZON = 21
_OOS_YEARS = {2017, 2024}     # held-out train years for OOS eval
_SEED = 42
_EPOCHS = 80
_BATCH = 256
_COST_BPS = 30.0              # realistic per-side cost
_TOPN = 8
_DATE_STRIDE = 3              # keep every 3rd train trading day (RAM bound)


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5:
        return np.nan
    ra = pd.Series(a[m]).rank().to_numpy()
    rb = pd.Series(b[m]).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return np.nan
    return float(np.corrcoef(ra, rb)[0, 1])


def _paired(scores: np.ndarray, base: np.ndarray, y: np.ndarray,
            oos_m: np.ndarray, dts: np.ndarray):
    """Per-OOS-date IC of `scores` and `base`, paired on shared dates."""
    ic_a, ic_b, paired = [], [], []
    for dt in np.unique(dts[oos_m]):
        sel = oos_m & (dts == dt)
        if sel.sum() < 10:
            continue
        a = _spearman(scores[sel], y[sel])
        b = _spearman(base[sel], y[sel])
        if np.isfinite(a):
            ic_a.append(a)
        if np.isfinite(b):
            ic_b.append(b)
        if np.isfinite(a) and np.isfinite(b):
            paired.append(a - b)
    return (float(np.mean(ic_a)), float(np.mean(ic_b)), np.array(paired))


def main() -> int:
    import torch

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--universe", choices=["executable", "expanded_v1"],
                    default="executable",
                    help="symbol universe (default executable = 79-symbol; "
                         "expanded_v1 = Phase-4 expanded). P4-A1 entrypoint flag.")
    args = ap.parse_args()

    t0 = time.time()
    cfg = load_config(_PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    syms = [s for s in resolve_universe(args.universe)
            if s not in ("SPY", "QQQ")]
    split = load_temporal_split(_PROJ / "config" / "temporal_split.yaml")
    train_years = train_year_set(split)
    fit_years = train_years - _OOS_YEARS

    close, bars_by_sym = {}, {}
    for s in syms:
        df = store.load(s, freq="1d", adjusted=True, fallback="local")
        if df is None or df.empty or "close" not in df.columns:
            continue
        close[s] = df["close"]
        bars_by_sym[s] = df
    close_df = pd.DataFrame(close).sort_index()
    fwd = compute_forward_returns(close_df, horizons=[_HORIZON], mode="cc")[_HORIZON]
    mom126 = close_df.pct_change(126)

    # date subsampling — keep every _DATE_STRIDE-th train trading day
    train_dates = [d for d in close_df.index if d.year in train_years]
    kept = set(train_dates[::_DATE_STRIDE])
    log.info("panel %s, %d symbols, %d kept train dates (%.1fs)",
             close_df.shape, len(close), len(kept), time.time() - t0)

    # ---- assemble aligned (seg, img) samples for the SAME (sym, bar) -----
    sscfg = SwingStructureConfig()
    segs, imgs, yv, dts, symv, momv, years = [], [], [], [], [], [], []
    for s, bars in bars_by_sym.items():
        raw = detect_raw_swings(bars, sscfg)
        series = bars["close"].to_numpy(dtype=float)
        idx = bars.index
        for i, dt in enumerate(idx):
            if dt not in kept:
                continue
            if i < WINDOW_LEN - 1:
                continue
            if dt not in fwd.index or s not in fwd.columns:
                continue
            y = fwd.at[dt, s]
            if not np.isfinite(y):
                continue
            win = series[i - WINDOW_LEN + 1: i + 1]
            if not np.isfinite(win).all():
                continue
            seq = segment_sequence_asof(raw, i, MAX_SEGMENTS)
            if not seq.any():            # no confirmed structure yet
                continue
            segs.append(seq)
            imgs.append(gaf_image(win))
            yv.append(float(y))
            dts.append(dt)
            symv.append(s)
            momv.append(mom126.at[dt, s] if dt in mom126.index else np.nan)
            years.append(dt.year)

    S = np.stack(segs).astype(np.float32)        # (N, MAX_SEGMENTS, 4)
    I = np.stack(imgs).astype(np.float32)        # (N, 2, W, W)
    yv = np.array(yv, np.float32)
    dts = np.array(dts)
    symv = np.array(symv)
    momv = np.array(momv, np.float32)
    years = np.array(years)
    log.info("assembled %d aligned (seg,img) samples (img %.2f GB) (%.1fs)",
             len(I), I.nbytes / 1e9, time.time() - t0)

    fit_m = np.isin(years, list(fit_years))
    oos_m = np.isin(years, list(_OOS_YEARS))

    # cross-sectional z-score of the target within each fit date
    yz = np.full_like(yv, np.nan)
    for dt in np.unique(dts[fit_m]):
        sel = fit_m & (dts == dt)
        v = yv[sel]
        if v.std() > 0:
            yz[sel] = (v - v.mean()) / v.std()
    train_ok = np.where(fit_m & np.isfinite(yz))[0]

    # P3-A3 purge: embargo fit samples whose 21d label crosses into an
    # OOS year (year-block split leaks at the fit→OOS boundary).
    all_sorted = np.array(sorted(close_df.index))
    keep_purge = purged_fit_mask(
        sample_dates=dts, sample_years=years,
        fit_years=fit_years, oos_years=_OOS_YEARS,
        horizon=_HORIZON, all_sorted_dates=all_sorted)
    n_pre = len(train_ok)
    train_ok = np.array([i for i in train_ok if keep_purge[i]])
    n_purged = n_pre - len(train_ok)
    log.info("P3-A3 purge: dropped %d/%d boundary-leaking fit samples",
             n_purged, n_pre)

    # ---- train 3C (image stays on CPU, batches → device) ----------------
    torch.manual_seed(_SEED)
    np.random.seed(_SEED)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = FusionModel().to(device).train()
    log.info("FusionModel params=%d device=%s",
             count_fusion_params(model), device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    losses = []
    for ep in range(_EPOCHS):
        perm = np.random.permutation(train_ok)
        ep_loss = 0.0
        for b in range(0, len(perm), _BATCH):
            bi = perm[b:b + _BATCH]
            sb = torch.tensor(S[bi], device=device)
            ib = torch.tensor(I[bi], device=device)
            yb = torch.tensor(yz[bi], device=device)
            opt.zero_grad()
            loss = torch.mean((model(sb, ib) - yb) ** 2)
            loss.backward()
            opt.step()
            ep_loss += float(loss.detach().cpu()) * len(bi)
        losses.append(ep_loss / len(perm))
    log.info("trained 3C: %d epochs, loss %.4f -> %.4f (%.1fs)",
             _EPOCHS, losses[0], losses[-1], time.time() - t0)

    # ---- OOS eval -------------------------------------------------------
    model.eval()
    scores = np.full(len(I), np.nan, np.float32)
    oidx = np.where(oos_m)[0]
    with torch.no_grad():
        for b in range(0, len(oidx), _BATCH):
            bi = oidx[b:b + _BATCH]
            sb = torch.tensor(S[bi], device=device)
            ib = torch.tensor(I[bi], device=device)
            scores[bi] = model(sb, ib).cpu().numpy()

    oos_ic_3c, oos_ic_base, paired = _paired(scores, momv, yv, oos_m, dts)
    diff_mean = float(paired.mean())
    diff_se = (float(paired.std(ddof=1) / np.sqrt(len(paired)))
               if len(paired) > 1 else 0.0)
    t_stat = diff_mean / diff_se if diff_se > 0 else 0.0
    p_val = float(erfc(abs(t_stat) / sqrt(2)))

    # ---- turnover -------------------------------------------------------
    oos_dates = sorted(np.unique(dts[oos_m]))
    rebal = oos_dates[::_HORIZON]
    prev_top, turnovers = None, []
    for dt in rebal:
        sel = oos_m & (dts == dt)
        if sel.sum() < _TOPN:
            continue
        order = np.argsort(-scores[sel])
        sh = symv[sel][order[:_TOPN]]
        top = set(sh)
        if prev_top is not None:
            turnovers.append(len(top - prev_top) / _TOPN)
        prev_top = top
    turnover = float(np.mean(turnovers)) if turnovers else float("nan")
    cost_drag_yr = (turnover * (_COST_BPS / 1e4) * (252 / _HORIZON)
                    if np.isfinite(turnover) else float("nan"))

    # underfit diagnostic — z-scored target has unit variance, so a
    # train MSE near 1.0 means the model explained almost none of it.
    underfit = losses[-1] > 0.80
    underfit_note = (
        f" IMPORTANT — UNDERFIT CONFOUND: train MSE only fell "
        f"{losses[0]:.3f}->{losses[-1]:.3f} on a unit-variance z-scored "
        f"target, i.e. the fused model explained <{(1-losses[-1])*100:.0f}% "
        f"of even the TRAINING signal. The weak OOS result is therefore "
        f"confounded with underfitting and is NOT evidence that late "
        f"fusion cannot work — config-scoped diagnostic, not a verdict."
        if underfit else "")

    # ---- verdict --------------------------------------------------------
    if p_val < 0.05 and diff_mean > 0:
        verdict, root_cause = "beats_tabular_baseline", None
    elif p_val < 0.05 and diff_mean < 0:
        verdict = "underperforms_tabular_baseline"
        root_cause = (
            "3C late-fusion OOS rank-IC is significantly BELOW the 126d "
            "momentum baseline. Late fusion takes the two branch scores "
            "([3B segment-sequence score, 3A GAF-image score]) and combines "
            "them with a small MLP; it cannot recover cross-sectional rank "
            "signal that neither branch carries. Both branches (P3·R2 / "
            "P3·R4) individually underperformed the same momentum baseline, "
            "so their late combination has no orthogonal signal to fuse — "
            "the fusion MLP only re-weights two already-dominated scores."
            + underfit_note)
    else:
        verdict = "no_significant_increment"
        root_cause = (
            "3C late-fusion OOS rank-IC is not significantly different from "
            f"the 126d momentum baseline (paired t-test p={p_val:.3f}). The "
            "two fused branches both re-encode the same price-window trend "
            "the momentum factor already summarizes — consistent with the "
            "Phase 2A family-T redundancy finding and the 3B/3A negative "
            "results. Config-scoped: THIS fusion topology, THESE branch "
            "encoders, THIS within-train sample — not a blanket verdict on "
            "chart-native fusion." + underfit_note)

    # 3C vs single-branch reference (closeout P3-A4 narrative input)
    ic_3b_ref = float(0.0153)   # P3·R2 3b_001 oos_rank_ic (recorded)
    ic_3a_ref = float(0.03185)  # P3·R4 3a_001 oos_rank_ic (recorded)

    attempt = Phase3Attempt(
        schema_version="1.0",
        attempt_id="3c_001",
        model="3C",
        created_at=datetime.now(timezone.utc).isoformat(),
        representation="late_fusion_3b_segseq_plus_3a_gaf_image",
        status="experimented",
        verdict=verdict,
        verdict_scope="config_scoped",
        config={
            "model": "FusionModel (3B StructureSequenceEncoder + 3A "
                     "ChartCNN, late-fused by a 2->8->1 MLP)",
            "fusion": "late (each branch -> scalar score; MLP over "
                      "[score_3b, score_3a])",
            "branches_trained": "end-to-end (branches NOT frozen)",
            "max_segments": MAX_SEGMENTS,
            "image": "GASF+GADF 2-channel, window_len=%d" % WINDOW_LEN,
            "horizon_days": _HORIZON,
            "universe": "executable (79, ex-SPY/QQQ)",
            "fit_years": sorted(fit_years),
            "oos_years": sorted(_OOS_YEARS),
            "date_stride": _DATE_STRIDE,
            "universe_flag": args.universe,
            "purge": f"P3-A3 year-boundary embargo: dropped {n_purged} "
                     f"fit samples whose {_HORIZON}d label crossed into "
                     f"an OOS year",
            "epochs": _EPOCHS, "batch": _BATCH, "lr": 1e-3, "seed": _SEED,
            "n_train_samples": int(len(train_ok)),
            "n_oos_samples": int(oos_m.sum()),
            "train_loss_first_last": [round(losses[0], 4), round(losses[-1], 4)],
        },
        eval={
            "eval_method": "within-train fit/OOS year-block split with "
                           "P3-A3 fit→OOS year-boundary purge embargo; "
                           "per-OOS-date cross-sectional Spearman rank-IC "
                           "of fused score vs 21d close-to-close forward "
                           "return; paired t-test of per-date IC vs baseline",
            "cost_model": f"{_COST_BPS:.0f}bp_per_side (reported; rank-IC "
                          "itself is pre-cost)",
            "turnover_penalty": f"monthly top-{_TOPN} name turnover = "
                                f"{turnover:.3f}; implied cost drag "
                                f"~{cost_drag_yr*100:.2f}%/yr at "
                                f"{_COST_BPS:.0f}bp/side",
            "oos_rank_ic": round(oos_ic_3c, 5),
            "vs_tabular_baseline": round(oos_ic_3c - oos_ic_base, 5),
            "baseline": "126d trailing return (mom_126d)",
            "baseline_oos_rank_ic": round(oos_ic_base, 5),
            "vs_3b_single_branch": round(oos_ic_3c - ic_3b_ref, 5),
            "vs_3a_single_branch": round(oos_ic_3c - ic_3a_ref, 5),
            "ref_3b_oos_rank_ic": ic_3b_ref,
            "ref_3a_oos_rank_ic": ic_3a_ref,
            "paired_diff_mean": round(diff_mean, 5),
            "paired_t_stat": round(t_stat, 3),
            "paired_p_value": round(p_val, 4),
            "n_oos_dates": int(len(paired)),
        },
        root_cause=root_cause,
        notes="Phase 3 chart-native late-fusion attempt. Within-train "
              "fit/OOS split — no validation/sealed data read. Date-"
              "subsampled (stride 3) for RAM, aligned (seg,img) per sample. "
              "ref_3b/3a IC are the recorded P3·R2/P3·R4 single-branch "
              "OOS rank-IC on the same protocol.",
    )
    out = (_PROJ / "data" / "audit" / "chart_structure" /
           "phase3_attempt_3c_001.json")
    out.write_text(attempt.model_dump_json(indent=2, exclude_none=True))
    log.info("verdict=%s  3C IC=%.4f  baseline IC=%.4f  p=%.3f  -> %s",
             verdict, oos_ic_3c, oos_ic_base, p_val, out.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
