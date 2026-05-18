"""G4 — CPCV-distribution acceptance (replaces single-path walk_forward).

PRD docs/prd/20260517-backtest_robustness_completion_prd.md §4 G4.

Literature (Bailey/LdP; arXiv 2512.12924): single-path walk_forward is
high-variance / weak at false-discovery control; CPCV yields a
*distribution* over many combinatorial purged train/test splits — the
robust acceptance object. This module turns per-period strategy
performance into that distribution + sample-size-weighted aggregate
+ G1 honest-N DSR + G2 PBO, as ONE acceptance summary.

Boundaries (re-audit 2026-05-17, PRD §4 G4-A2/A3):
- new-cycle-only: cycle06/08 went through per-validation-year
  temporal_split_acceptance (NOT single-path walk_forward); their
  retro scope ≈ 0; this module is NOT applied retroactively to them.
- single-path walk_forward (`core/backtest/window_analyzer.py`) is
  left BYTE-UNTOUCHED as a diagnostic API (G4-A3 back-compat by
  construction — this module does not import or modify it).
- §3 decision: the ONLY allowed weighting is sample-size (more test
  observations ⇒ more weight); NO recency / regime score weighting
  (that is an extra researcher DOF that worsens overfitting).
"""
from __future__ import annotations

import numpy as np

from core.research.cpcv import cpcv_splits
from core.research.mining_pbo import compute_mining_pbo
from core.research.overfit_metrics import deflated_sharpe_ratio


def _ic(pred: np.ndarray, fwd: np.ndarray) -> float:
    m = np.isfinite(pred) & np.isfinite(fwd)
    if m.sum() < 10:
        return float("nan")
    return float(np.corrcoef(
        np.argsort(np.argsort(pred[m])),
        np.argsort(np.argsort(fwd[m])))[0, 1])


def cpcv_acceptance_distribution(
    pred: np.ndarray,
    fwd: np.ndarray,
    *,
    n_groups: int = 6,
    k_test: int = 2,
    horizon: int = 21,
    honest_n_trials: int,
    embargo_frac: float = 0.01,
) -> dict:
    """Per-fold OOS IC distribution + sample-size-weighted aggregate +
    DSR (G1 honest N) + PBO (G2).

    ``pred``/``fwd`` = aligned 1-D arrays (signal, forward return),
    time-ordered. ``honest_n_trials`` MUST come from
    ``dsr_trial_accounting`` or a runtime config count (G1 — no magic
    literal). Returns mean/std/quantiles, the sample-size-weighted IC
    (the §3 weighting), DSR, PBO, and a fail-closed ``insufficient``
    flag (never a silent pass).
    """
    pred = np.asarray(pred, float)
    fwd = np.asarray(fwd, float)
    n = len(pred)
    fold_ic: list[float] = []
    fold_w: list[int] = []
    per_period_cols: list[np.ndarray] = []
    for tr, te in cpcv_splits(n, n_groups, k_test, horizon, embargo_frac):
        if len(te) < 10:
            continue
        ic = _ic(pred[te], fwd[te])
        if not np.isfinite(ic):
            continue
        fold_ic.append(ic)
        fold_w.append(len(te))            # sample-size weight (§3)
        col = np.full(n, np.nan)
        col[te] = np.sign(pred[te]) * fwd[te]   # per-period perf proxy
        per_period_cols.append(col)
    if len(fold_ic) < 2:
        return {"insufficient": True,
                "reason": "fewer than 2 valid CPCV folds — NOT a pass",
                "n_folds": len(fold_ic)}
    a = np.array(fold_ic)
    w = np.array(fold_w, float)
    wmean = float(np.sum(a * w) / np.sum(w))   # sample-size-weighted IC
    dsr = deflated_sharpe_ratio(a, honest_n_trials)
    M = np.vstack([c for c in per_period_cols]).T   # (period × fold)
    pbo = compute_mining_pbo(np.nan_to_num(M, nan=0.0))
    return {"insufficient": False,
            "n_folds": len(fold_ic),
            "ic_mean": float(a.mean()),
            "ic_std": float(a.std(ddof=1)),
            "ic_q10": float(np.quantile(a, 0.10)),
            "ic_q90": float(np.quantile(a, 0.90)),
            "ic_sample_weighted": wmean,
            "weighting": "sample_size_only (PRD §3; NO recency/regime)",
            "dsr": dsr.get("deflated_sharpe"),
            "dsr_n_trials": int(honest_n_trials),
            "pbo": pbo.get("pbo"),
            "pbo_red_flag": pbo.get("red_flag"),
            "scope": "new_cycle_only; single-path walk_forward "
                     "untouched (diagnostic back-compat)"}
