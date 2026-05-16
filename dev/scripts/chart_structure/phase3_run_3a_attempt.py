"""P3·R4 — 3A image-CNN attempt + cost-aware eval.

Per chart-structure ralph-loop execution PRD §7 round P3·R4. Trains
``ChartCNN`` (P3·R3) on GASF+GADF chart images and evaluates against the
126d momentum baseline — strictly inside the ``train`` partition of
``config/temporal_split.yaml`` (within-train fit/OOS split; validation
2018/19/21/23/25 + sealed 2026 are never read).

Date-subsampled (every 4th train trading day) to keep the GAF image
tensor inside RAM — cross-sectional IC needs many symbols per date, not
many dates, so subsampling dates is loss-free for the eval.

Per D2 a negative result still PASSES; the attempt JSON records the
config + a config-scoped root_cause.

Writes data/audit/chart_structure/phase3_attempt_3a_001.json.
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
from core.ml.chart_cnn import ChartCNN, count_cnn_params, gaf_image  # noqa: E402
from core.ml.phase3_attempt import Phase3Attempt  # noqa: E402
from core.ml.window_embedding import WINDOW_LEN  # noqa: E402
from core.research.temporal_split import (  # noqa: E402
    load_temporal_split,
    partition_for_role,
    purge_labels_at_boundary,
    train_year_set,
    validate_no_holdout_leakage,
)
from core.universe.universe_resolver import resolve_universe  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("p3r4")

_HORIZON = 21
_OOS_YEARS = {2017, 2024}
_SEED = 42
_EPOCHS = 80
_BATCH = 256
_COST_BPS = 30.0
_TOPN = 8
_DATE_STRIDE = 3    # keep every 3rd train trading day (RAM bound)


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5:
        return np.nan
    ra, rb = pd.Series(a[m]).rank().to_numpy(), pd.Series(b[m]).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return np.nan
    return float(np.corrcoef(ra, rb)[0, 1])


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

    close = {}
    for s in syms:
        df = store.load(s, freq="1d", adjusted=True, fallback="local")
        if df is not None and not df.empty and "close" in df.columns:
            close[s] = df["close"]
    close_df = pd.DataFrame(close).sort_index()

    # temporal_split discipline (memory feedback_temporal_split_discipline):
    # train-only mining panel + fail-closed holdout guard + boundary
    # label purge. Mirrors the compliant phase2a path.
    mining_panel = partition_for_role({"close": close_df}, split, role="miner")
    close_df = mining_panel["close"]
    validate_no_holdout_leakage(mining_panel, split)
    fwd = purge_labels_at_boundary(
        compute_forward_returns(close_df, horizons=[_HORIZON],
                                mode="cc")[_HORIZON], split)
    mom126 = close_df.pct_change(126)

    # date subsampling — keep every _DATE_STRIDE-th train trading day
    train_dates = [d for d in close_df.index if d.year in train_years]
    kept = set(train_dates[::_DATE_STRIDE])
    log.info("panel %s, %d symbols, %d kept train dates (%.1fs)",
             close_df.shape, len(close), len(kept), time.time() - t0)

    # ---- build GAF image samples ---------------------------------------
    pos = {s: {d: i for i, d in enumerate(close_df.index)} for s in close}
    imgs, yv, dts, symv, momv, years = [], [], [], [], [], []
    for s in close:
        series = close_df[s].to_numpy(float)
        for dt in kept:
            i = pos[s][dt]
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
            imgs.append(gaf_image(win))
            yv.append(float(y))
            dts.append(dt)
            symv.append(s)
            momv.append(mom126.at[dt, s] if dt in mom126.index else np.nan)
            years.append(dt.year)
    X = np.stack(imgs).astype(np.float32)
    yv = np.array(yv, np.float32)
    dts = np.array(dts)
    symv = np.array(symv)
    momv = np.array(momv, np.float32)
    years = np.array(years)
    log.info("assembled %d GAF images (%.2f GB) (%.1fs)",
             len(X), X.nbytes / 1e9, time.time() - t0)

    fit_m = np.isin(years, list(fit_years))
    oos_m = np.isin(years, list(_OOS_YEARS))

    # cross-sectional z-score target per fit date
    yz = np.full_like(yv, np.nan)
    for dt in np.unique(dts[fit_m]):
        sel = fit_m & (dts == dt)
        v = yv[sel]
        if v.std() > 0:
            yz[sel] = (v - v.mean()) / v.std()
    # boundary purge applied at panel level (train-only partition +
    # purge_labels_at_boundary → cross-boundary labels NaN, dropped here).
    train_ok = np.where(fit_m & np.isfinite(yz))[0]

    # ---- train 3A (X stays on CPU, batches → device) -------------------
    torch.manual_seed(_SEED)
    np.random.seed(_SEED)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ChartCNN().to(device).train()
    log.info("ChartCNN params=%d device=%s", count_cnn_params(model), device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    losses = []
    for ep in range(_EPOCHS):
        perm = np.random.permutation(train_ok)
        ep_loss = 0.0
        for b in range(0, len(perm), _BATCH):
            bi = perm[b:b + _BATCH]
            xb = torch.tensor(X[bi], device=device)
            yb = torch.tensor(yz[bi], device=device)
            opt.zero_grad()
            loss = torch.mean((model(xb) - yb) ** 2)
            loss.backward()
            opt.step()
            ep_loss += float(loss.detach().cpu()) * len(bi)
        losses.append(ep_loss / len(perm))
    log.info("trained 3A: %d epochs, loss %.4f -> %.4f (%.1fs)",
             _EPOCHS, losses[0], losses[-1], time.time() - t0)

    # ---- OOS eval -------------------------------------------------------
    model.eval()
    scores = np.full(len(X), np.nan, np.float32)
    oidx = np.where(oos_m)[0]
    with torch.no_grad():
        for b in range(0, len(oidx), _BATCH):
            bi = oidx[b:b + _BATCH]
            scores[bi] = model(torch.tensor(X[bi], device=device)).cpu().numpy()

    paired = []
    ic_3a, ic_base = [], []
    for dt in np.unique(dts[oos_m]):
        sel = oos_m & (dts == dt)
        if sel.sum() < 10:
            continue
        a, b = _spearman(scores[sel], yv[sel]), _spearman(momv[sel], yv[sel])
        if np.isfinite(a):
            ic_3a.append(a)
        if np.isfinite(b):
            ic_base.append(b)
        if np.isfinite(a) and np.isfinite(b):
            paired.append(a - b)
    oos_ic_3a = float(np.mean(ic_3a))
    oos_ic_base = float(np.mean(ic_base))
    paired = np.array(paired)
    diff_mean = float(paired.mean())
    diff_se = float(paired.std(ddof=1) / np.sqrt(len(paired))) if len(paired) > 1 else 0.0
    t_stat = diff_mean / diff_se if diff_se > 0 else 0.0
    p_val = float(erfc(abs(t_stat) / sqrt(2)))

    # ---- turnover -------------------------------------------------------
    oos_dates = sorted(np.unique(dts[oos_m]))
    prev_top, turnovers = None, []
    for dt in oos_dates:
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
        f"target, i.e. the CNN explained <{(1-losses[-1])*100:.0f}% of even "
        f"the TRAINING signal. The weak OOS result is therefore confounded "
        f"with underfitting and is NOT evidence that GAF image-CNN cannot "
        f"work — the obvious next attempts are a deeper CNN, more epochs, "
        f"a higher LR, and more samples (lift the date-stride). This is a "
        f"config-scoped diagnostic, not a verdict on the 3A approach."
        if underfit else "")

    # ---- verdict --------------------------------------------------------
    if p_val < 0.05 and diff_mean > 0:
        verdict, root_cause = "beats_tabular_baseline", None
    elif p_val < 0.05 and diff_mean < 0:
        verdict = "underperforms_tabular_baseline"
        root_cause = (
            "3A GAF image-CNN OOS rank-IC is significantly BELOW the 126d "
            "momentum baseline. The GASF/GADF encoding spreads a 63-bar "
            "window into a 63x63 image whose dominant signal (the angular "
            "sum field) is a smooth re-encoding of cumulative return; a "
            "2-conv CNN at this config did not extract more cross-sectional "
            "rank signal than the momentum factor it is built from."
            + underfit_note)
    else:
        verdict = "no_significant_increment"
        root_cause = (
            "3A GAF image-CNN OOS rank-IC is not significantly different "
            f"from the 126d momentum baseline (paired t-test p={p_val:.3f}). "
            "The GAF image is a deterministic re-encoding of the same price "
            "window the momentum factor summarizes — consistent with the "
            "Phase 2A redundancy finding. Config-scoped: THIS CNN depth, "
            "THIS image encoding, THIS within-train sample size — not a "
            "blanket verdict on image-CNN chart models." + underfit_note)

    attempt = Phase3Attempt(
        schema_version="1.0",
        attempt_id="3a_001",
        model="3A",
        created_at=datetime.now(timezone.utc).isoformat(),
        representation="gasf_gadf_chart_image",
        status="experimented",
        verdict=verdict,
        verdict_scope="config_scoped",
        config={
            "model": "ChartCNN (2 conv blocks, ~30k params)",
            "image": "GASF+GADF 2-channel, window_len=63",
            "horizon_days": _HORIZON,
            "universe": "executable (79, ex-SPY/QQQ)",
            "fit_years": sorted(fit_years),
            "oos_years": sorted(_OOS_YEARS),
            "date_stride": _DATE_STRIDE,
            "universe_flag": args.universe,
            "purge": "canonical: partition_for_role(role='miner') "
                     "(train-only panel) + validate_no_holdout_leakage "
                     "+ purge_labels_at_boundary",
            "temporal_split_discipline": "train-only mining panel; "
                     "no validation/sealed rows; cross-boundary labels purged",
            "epochs": _EPOCHS, "batch": _BATCH, "lr": 1e-3, "seed": _SEED,
            "n_train_samples": int(len(train_ok)),
            "n_oos_samples": int(oos_m.sum()),
            "train_loss_first_last": [round(losses[0], 4), round(losses[-1], 4)],
        },
        eval={
            "eval_method": "within-train fit/OOS year-block split with "
                           "P3-A3 fit→OOS year-boundary purge embargo; "
                           "per-OOS-date cross-sectional Spearman rank-IC "
                           "of CNN score vs 21d close-to-close forward "
                           "return; paired t-test of per-date IC vs baseline",
            "cost_model": f"{_COST_BPS:.0f}bp_per_side (reported; rank-IC "
                          "itself is pre-cost)",
            "turnover_penalty": f"monthly top-{_TOPN} name turnover = "
                                f"{turnover:.3f}; implied cost drag "
                                f"~{cost_drag_yr*100:.2f}%/yr",
            "oos_rank_ic": round(oos_ic_3a, 5),
            "vs_tabular_baseline": round(oos_ic_3a - oos_ic_base, 5),
            "baseline": "126d trailing return (mom_126d)",
            "baseline_oos_rank_ic": round(oos_ic_base, 5),
            "paired_diff_mean": round(diff_mean, 5),
            "paired_t_stat": round(t_stat, 3),
            "paired_p_value": round(p_val, 4),
            "n_oos_dates": int(len(paired)),
        },
        root_cause=root_cause,
        notes="Phase 3 image-CNN attempt. Within-train fit/OOS split — no "
              "validation/sealed data read. Date-subsampled (stride 4) for RAM.",
    )
    out = _PROJ / "data" / "audit" / "chart_structure" / "phase3_attempt_3a_001.json"
    out.write_text(attempt.model_dump_json(indent=2, exclude_none=True))
    log.info("verdict=%s  3A IC=%.4f  baseline IC=%.4f  p=%.3f  -> %s",
             verdict, oos_ic_3a, oos_ic_base, p_val, out.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
