"""R5 acceptance — stacking ensemble (supplementary PRD §8).

R5-A1 OOF via CPCV (no in-fold leak) + Ridge meta · R5-A2 marginal
contribution quantified (weak-orthogonal member can add value).
"""
from __future__ import annotations

import numpy as np

from core.ml.stacking import (
    cpcv_oof_predictions,
    marginal_contribution,
    ridge_meta_fit_predict,
)


def _ic(p, y):
    m = np.isfinite(p) & np.isfinite(y)
    if m.sum() < 5:
        return 0.0
    a = np.argsort(np.argsort(p[m]))
    b = np.argsort(np.argsort(y[m]))
    return float(np.corrcoef(a, b)[0, 1])


def test_cpcv_oof_no_in_fold_leak_and_ridge_meta():
    rng = np.random.default_rng(0)
    n = 600
    X = rng.standard_normal((n, 3))
    y = X[:, 0] * 0.8 + rng.standard_normal(n) * 0.5

    def fp(Xtr, ytr, Xte):
        w = np.linalg.lstsq(Xtr, ytr, rcond=None)[0]
        return Xte @ w

    oof = cpcv_oof_predictions(X, y, fp, n_groups=6, k_test=2, horizon=5)
    assert oof.shape == (n,)
    assert np.isfinite(oof).mean() > 0.9          # most samples tested
    assert _ic(oof, y) > 0.3                       # OOF preds informative
    # ridge meta over 2 base models → coef finite, intercept slot present
    base = np.column_stack([oof, X[:, 1]])
    pred, coef = ridge_meta_fit_predict(base, y, alpha=1.0)
    assert coef.shape == (3,) and np.isfinite(coef).all()
    assert _ic(pred, y) >= _ic(X[:, 1], y)         # meta >= weak member


def test_marginal_contribution_weak_orthogonal_member_adds_value():
    rng = np.random.default_rng(1)
    n = 800
    signal = rng.standard_normal(n)
    noise2 = rng.standard_normal(n)
    y = signal + 0.4 * noise2 + rng.standard_normal(n) * 0.3
    strong = signal + rng.standard_normal(n) * 0.2          # strong base
    weak_orth = noise2 + rng.standard_normal(n) * 0.9        # weak, orthogonal
    base = np.column_stack([strong, weak_orth])
    mc = marginal_contribution(base, y, member_idx=1, score_fn=_ic)
    # weak orthogonal member loses standalone but ADDS at the margin
    assert _ic(weak_orth, y) < _ic(strong, y)
    assert mc["marginal"] > 0.0
    assert mc["score_with"] > mc["score_without"]
