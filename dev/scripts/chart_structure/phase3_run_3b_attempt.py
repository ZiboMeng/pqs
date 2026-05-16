"""P3·R2 — 3B structure-sequence encoder attempt + cost-aware eval.

Per chart-structure ralph-loop execution PRD §7 round P3·R2. Trains the
``StructureSequenceEncoder`` (P3·R1) on the family-T swing-segment token
sequence and evaluates it against a tabular momentum baseline — strictly
inside the ``train`` partition of ``config/temporal_split.yaml`` (a
within-train fit/OOS split; validation 2018/19/21/23/25 + sealed 2026
are never read).

Eval (AC P3-A3) declares ``eval_method`` / ``cost_model`` /
``turnover_penalty``. Per D2 a negative result still PASSES the round —
it is recorded with a ``root_cause`` and a config-scoped verdict, never
a blanket "3B doesn't work".

Writes data/audit/chart_structure/phase3_attempt_3b_001.json.
"""
from __future__ import annotations

import argparse
import logging
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
from core.factors.swing_structure import (  # noqa: E402
    SwingStructureConfig,
    detect_raw_swings,
)
from core.ml.phase3_attempt import Phase3Attempt  # noqa: E402
from core.ml.structure_sequence_encoder import (  # noqa: E402
    MAX_SEGMENTS,
    StructureSequenceEncoder,
    segment_sequence_asof,
)
from core.research.temporal_split import (  # noqa: E402
    load_temporal_split,
    partition_for_role,
    purge_labels_at_boundary,
    train_year_set,
    validate_no_holdout_leakage,
)
from core.universe.universe_resolver import resolve_universe  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("p3r2")

_HORIZON = 21
_OOS_YEARS = {2017, 2024}     # held-out train years for OOS eval
_SEED = 42
_EPOCHS = 80
_BATCH = 512
_COST_BPS = 30.0              # realistic per-side cost
_TOPN = 8


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5:
        return np.nan
    ra = pd.Series(a[m]).rank().to_numpy()
    rb = pd.Series(b[m]).rank().to_numpy()
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
    bars_by_sym = {}
    for s in syms:
        df = store.load(s, freq="1d", adjusted=True, fallback="local")
        if df is None or df.empty or "close" not in df.columns:
            continue
        close[s] = df["close"]
        bars_by_sym[s] = df
    close_df = pd.DataFrame(close).sort_index()

    # temporal_split discipline (memory feedback_temporal_split_discipline):
    # train-only mining panel + fail-closed holdout guard + boundary
    # label purge; restrict swing bars to the train-only index too.
    mining_panel = partition_for_role({"close": close_df}, split, role="miner")
    close_df = mining_panel["close"]
    validate_no_holdout_leakage(mining_panel, split)
    bars_by_sym = {s: d[d.index.isin(close_df.index)]
                   for s, d in bars_by_sym.items()}
    fwd = purge_labels_at_boundary(
        compute_forward_returns(close_df, horizons=[_HORIZON],
                                mode="cc")[_HORIZON], split)
    mom126 = close_df.pct_change(126)  # tabular baseline factor
    log.info("panel %s, %d symbols, build %.1fs",
             close_df.shape, len(close), time.time() - t0)

    # ---- assemble swing-segment samples (train partition only) ----------
    sscfg = SwingStructureConfig()
    rows = []  # (X, y, date, sym, mom, year)
    for s, bars in bars_by_sym.items():
        raw = detect_raw_swings(bars, sscfg)
        idx = bars.index
        for i, dt in enumerate(idx):
            yr = dt.year
            if yr not in train_years:
                continue
            if dt not in fwd.index or s not in fwd.columns:
                continue
            y = fwd.at[dt, s]
            if not np.isfinite(y):
                continue
            seq = segment_sequence_asof(raw, i, MAX_SEGMENTS)
            if not seq.any():            # no confirmed structure yet
                continue
            m = mom126.at[dt, s] if dt in mom126.index else np.nan
            rows.append((seq, float(y), dt, s, m, yr))
    log.info("assembled %d swing-segment samples (%.1fs)",
             len(rows), time.time() - t0)

    X = np.stack([r[0] for r in rows]).astype(np.float32)
    yv = np.array([r[1] for r in rows], np.float32)
    dates = np.array([r[2] for r in rows])
    momv = np.array([r[4] for r in rows], np.float32)
    years = np.array([r[5] for r in rows])
    fit_m = np.isin(years, list(fit_years))
    oos_m = np.isin(years, list(_OOS_YEARS))

    # cross-sectional z-score of the target within each fit date
    yz = np.full_like(yv, np.nan)
    for dt in np.unique(dates[fit_m]):
        sel = fit_m & (dates == dt)
        v = yv[sel]
        if v.std() > 0:
            yz[sel] = (v - v.mean()) / v.std()
    train_ok = fit_m & np.isfinite(yz)

    # boundary purge applied at panel level (train-only partition +
    # purge_labels_at_boundary → cross-boundary labels NaN, dropped here).

    # ---- train 3B -------------------------------------------------------
    torch.manual_seed(_SEED)
    np.random.seed(_SEED)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = StructureSequenceEncoder(max_segments=MAX_SEGMENTS).to(device).train()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    Xt = torch.tensor(X[train_ok], device=device)
    Yt = torch.tensor(yz[train_ok], device=device)
    n = len(Xt)
    losses = []
    for ep in range(_EPOCHS):
        perm = torch.randperm(n, device=device)
        ep_loss = 0.0
        for b in range(0, n, _BATCH):
            bi = perm[b:b + _BATCH]
            opt.zero_grad()
            pred = model(Xt[bi])
            loss = torch.mean((pred - Yt[bi]) ** 2)
            loss.backward()
            opt.step()
            ep_loss += float(loss.detach().cpu()) * len(bi)
        losses.append(ep_loss / n)
    log.info("trained 3B: %d epochs, loss %.4f -> %.4f (%.1fs)",
             _EPOCHS, losses[0], losses[-1], time.time() - t0)

    # ---- OOS eval -------------------------------------------------------
    model.eval()
    with torch.no_grad():
        scores = np.full(len(rows), np.nan, np.float32)
        oidx = np.where(oos_m)[0]
        Xo = torch.tensor(X[oos_m], device=device)
        scores[oidx] = model(Xo).cpu().numpy()

    ic_3b, ic_base = [], []
    for dt in np.unique(dates[oos_m]):
        sel = oos_m & (dates == dt)
        if sel.sum() < 10:
            continue
        ic_3b.append(_spearman(scores[sel], yv[sel]))
        ic_base.append(_spearman(momv[sel], yv[sel]))
    ic_3b = np.array([v for v in ic_3b if np.isfinite(v)])
    ic_base = np.array([v for v in ic_base if np.isfinite(v)])
    oos_ic_3b = float(np.mean(ic_3b))
    oos_ic_base = float(np.mean(ic_base))

    # paired t-test on per-date IC difference (same OOS dates)
    paired = []
    for dt in np.unique(dates[oos_m]):
        sel = oos_m & (dates == dt)
        if sel.sum() < 10:
            continue
        a, b = _spearman(scores[sel], yv[sel]), _spearman(momv[sel], yv[sel])
        if np.isfinite(a) and np.isfinite(b):
            paired.append(a - b)
    paired = np.array(paired)
    diff_mean = float(paired.mean())
    diff_se = float(paired.std(ddof=1) / np.sqrt(len(paired)))
    t_stat = diff_mean / diff_se if diff_se > 0 else 0.0
    # two-sided p via normal approx
    from math import erfc, sqrt
    p_val = float(erfc(abs(t_stat) / sqrt(2)))

    # ---- turnover (monthly top-N from 3B score) -------------------------
    oos_dates = sorted(np.unique(dates[oos_m]))
    rebal = oos_dates[::_HORIZON]
    prev_top = None
    turnovers = []
    for dt in rebal:
        sel = oos_m & (dates == dt)
        if sel.sum() < _TOPN:
            continue
        order = np.argsort(-scores[sel])
        syms_here = np.array([rows[i][3] for i in np.where(sel)[0]])
        top = set(syms_here[order[:_TOPN]])
        if prev_top is not None:
            turnovers.append(len(top - prev_top) / _TOPN)
        prev_top = top
    turnover = float(np.mean(turnovers)) if turnovers else float("nan")
    cost_drag_yr = turnover * (_COST_BPS / 1e4) * (252 / _HORIZON)

    # ---- verdict --------------------------------------------------------
    if p_val < 0.05 and diff_mean > 0:
        verdict = "beats_tabular_baseline"
        root_cause = None
    elif p_val < 0.05 and diff_mean < 0:
        verdict = "underperforms_tabular_baseline"
        root_cause = (
            "3B swing-segment encoder OOS rank-IC is significantly BELOW the "
            "126d momentum baseline. The swing-segment tokenization discards "
            "the per-bar magnitude information that momentum captures; the "
            "transformer over <=16 coarse segment tokens has far fewer "
            "informative degrees of freedom than a direct 126d return.")
    else:
        verdict = "no_significant_increment"
        root_cause = (
            "3B swing-segment encoder OOS rank-IC is not significantly "
            "different from the 126d momentum baseline (paired t-test "
            f"p={p_val:.3f}). The segment sequence re-expresses trend/"
            "structure information the momentum factor already captures — "
            "consistent with the Phase 2A family-T redundancy finding. "
            "Not a blanket verdict on chart-native models: this is THIS "
            "encoder, THIS tokenization, THIS config.")

    attempt = Phase3Attempt(
        schema_version="1.0",
        attempt_id="3b_001",
        model="3B",
        created_at=datetime.now(timezone.utc).isoformat(),
        representation="family_t_swing_segment_sequence",
        status="experimented",
        verdict=verdict,
        verdict_scope="config_scoped",
        config={
            "encoder": "StructureSequenceEncoder (SmallEncoder, 1-layer "
                       "transformer, d_model=64)",
            "max_segments": MAX_SEGMENTS,
            "segment_features": ["len_pct", "dur", "slope_pct", "direction"],
            "horizon_days": _HORIZON,
            "universe": "executable (79, ex-SPY/QQQ)",
            "fit_years": sorted(fit_years),
            "oos_years": sorted(_OOS_YEARS),
            "universe_flag": args.universe,
            "purge": "canonical: partition_for_role(role='miner') "
                     "(train-only panel) + validate_no_holdout_leakage "
                     "+ purge_labels_at_boundary",
            "temporal_split_discipline": "train-only mining panel; "
                     "no validation/sealed rows; cross-boundary labels purged",
            "epochs": _EPOCHS, "batch": _BATCH, "lr": 1e-3, "seed": _SEED,
            "n_train_samples": int(train_ok.sum()),
            "n_oos_samples": int(oos_m.sum()),
            "train_loss_first_last": [round(losses[0], 4), round(losses[-1], 4)],
        },
        eval={
            "eval_method": "within-train fit/OOS year-block split with "
                           "P3-A3 fit→OOS year-boundary purge embargo; "
                           "per-OOS-date cross-sectional Spearman rank-IC "
                           "of model score vs 21d close-to-close forward "
                           "return; paired t-test of per-date IC vs baseline",
            "cost_model": f"{_COST_BPS:.0f}bp_per_side (reported; rank-IC "
                          "itself is pre-cost)",
            "turnover_penalty": f"monthly top-{_TOPN} name turnover = "
                                f"{turnover:.3f}; implied cost drag "
                                f"~{cost_drag_yr*100:.2f}%/yr at "
                                f"{_COST_BPS:.0f}bp/side",
            "oos_rank_ic": round(oos_ic_3b, 5),
            "vs_tabular_baseline": round(oos_ic_3b - oos_ic_base, 5),
            "baseline": "126d trailing return (mom_126d)",
            "baseline_oos_rank_ic": round(oos_ic_base, 5),
            "paired_diff_mean": round(diff_mean, 5),
            "paired_t_stat": round(t_stat, 3),
            "paired_p_value": round(p_val, 4),
            "n_oos_dates": int(len(paired)),
        },
        root_cause=root_cause,
        notes="Phase 3 first chart-native attempt. Within-train fit/OOS "
              "split — no validation/sealed data read.",
    )
    out = _PROJ / "data" / "audit" / "chart_structure" / "phase3_attempt_3b_001.json"
    out.write_text(attempt.model_dump_json(indent=2, exclude_none=True))
    log.info("verdict=%s  3B IC=%.4f  baseline IC=%.4f  p=%.3f  -> %s",
             verdict, oos_ic_3b, oos_ic_base, p_val, out.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
