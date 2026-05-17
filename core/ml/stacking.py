"""R5 — stacking ensemble (supplementary PRD §8).

Per literature review §1.F [S15a][S15b]. Stacking blends relatively
weak but orthogonal/additive signals without the strong signal drowning
them — the exact mechanism by which a chart-native model that LOSES to
momentum standalone can still add marginal value as an ensemble member
(main PRD §5.2 ensemble-candidate role).

Discipline:
- base out-of-fold predictions use **CPCV** (no in-fold leakage; the
  literature's #1 stacking pitfall) — R2 ``cpcv_splits``.
- meta-model = **Ridge** (simple; complex metas overfit base preds).
- per literature: meta should be linear/ridge, NOT a deep stack.

This module is pure numpy/sklearn-free (closed-form ridge); callers
supply base per-period predictions + target.
"""
from __future__ import annotations

import numpy as np

from core.research.cpcv import cpcv_splits


def cpcv_oof_predictions(
    X: np.ndarray,
    y: np.ndarray,
    fit_predict,
    n_groups: int = 6,
    k_test: int = 2,
    horizon: int = 21,
    embargo_frac: float = 0.01,
) -> np.ndarray:
    """Out-of-fold base predictions via CPCV (no in-fold leakage).

    ``fit_predict(X_tr, y_tr, X_te) -> y_hat_te``. Each sample's OOF
    prediction = mean over the CPCV test folds it falls in (φ paths →
    a sample appears in multiple test sets; averaging = the CPCV path
    aggregate). Returns (n,) OOF predictions (NaN if never tested).
    """
    n = len(y)
    acc = np.zeros(n)
    cnt = np.zeros(n)
    for tr, te in cpcv_splits(n, n_groups, k_test, horizon, embargo_frac):
        if len(tr) == 0 or len(te) == 0:
            continue
        yh = np.asarray(fit_predict(X[tr], y[tr], X[te]), float)
        acc[te] += yh
        cnt[te] += 1.0
    out = np.where(cnt > 0, acc / np.maximum(cnt, 1.0), np.nan)
    return out


def ridge_meta_fit_predict(
    base_oof: np.ndarray,   # (n, n_base) OOF preds of each base model
    y: np.ndarray,
    base_new: np.ndarray | None = None,
    alpha: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Ridge meta-model over base OOF predictions (closed form).

    Returns (in_sample_meta_pred, coef). ``base_new`` optional → also
    returns its meta prediction in slot 0 (caller can ignore). Ridge
    (not OLS / not a deep meta) per [S15b] — regularizes base-pred
    collinearity, resists meta-overfit.
    """
    M = np.asarray(base_oof, float)
    yv = np.asarray(y, float)
    ok = np.isfinite(M).all(axis=1) & np.isfinite(yv)
    Mo, yo = M[ok], yv[ok]
    Mo = np.column_stack([np.ones(len(Mo)), Mo])  # intercept
    A = Mo.T @ Mo + alpha * np.eye(Mo.shape[1])
    A[0, 0] -= alpha  # don't penalize intercept
    coef = np.linalg.solve(A, Mo.T @ yo)
    pred = M.copy()
    full = np.column_stack([np.ones(len(M)), np.nan_to_num(M)])
    in_pred = full @ coef
    return in_pred, coef


def marginal_contribution(
    base_oof: np.ndarray,
    y: np.ndarray,
    member_idx: int,
    score_fn,
    alpha: float = 1.0,
) -> dict:
    """Quantify a base member's marginal ensemble value: stack WITH vs
    WITHOUT ``member_idx``, score each (e.g. rank-IC / Sharpe via
    ``score_fn(pred, y)``). A weak-but-orthogonal member can have
    positive marginal contribution even if its standalone score loses.
    """
    M = np.asarray(base_oof, float)
    keep = [j for j in range(M.shape[1]) if j != member_idx]
    with_pred, _ = ridge_meta_fit_predict(M, y, alpha=alpha)
    wo_pred, _ = ridge_meta_fit_predict(M[:, keep], y, alpha=alpha)
    s_with = float(score_fn(with_pred, y))
    s_without = float(score_fn(wo_pred, y))
    return {
        "score_with": s_with,
        "score_without": s_without,
        "marginal": s_with - s_without,
        "member_idx": member_idx,
    }
