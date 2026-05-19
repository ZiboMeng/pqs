"""PRD-3 RA2 — A1 shallow-XGBoost + frozen-probe PCA stack.

The highest-ROI signal arm (Grinsztajn/Krauss/ROCKET synthesis):
RA1 engineered stationary features → a *shallow* gradient-boosted
tree, with the chart frozen-probe embedding optionally stacked on
as a small PCA-reduced block.

Honest grounded scope (R4/R6/R7 pattern): the shallow-XGB +
early-stop + reproducible-seed machinery is ``core.ml.xgb_alpha.
XGBAlphaModel`` — DELEGATED to, not reimplemented. The PRD-1 P1.1
leakage-correct uniqueness weights come through the RA1 single
helper (``engineered_sample_weights`` → ``label_leakage``). The
genuinely-new RA2 surface is (a) the minimal default-bit-identical
``sample_weight`` passthrough added to ``XGBAlphaModel.fit`` and
(b) this thin pipeline + the train-only PCA frozen-probe stack.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from core.ml.xgb_alpha import XGBAlphaModel
from core.research.engineered_features import engineered_sample_weights

__all__ = ["A1Config", "A1FitResult", "stack_frozen_probe_pca", "train_a1"]

_MIN_PCA, _MAX_PCA = 16, 32


@dataclass
class A1Config:
    """Shallow by design (depth 2-4 → low variance at low SNR, per the
    literature synthesis); fixed seed → reproducible."""
    max_depth: int = 3
    n_estimators: int = 200
    random_state: int = 42
    probe_pca_components: int = 24


@dataclass
class A1FitResult:
    model: XGBAlphaModel
    sample_weight: np.ndarray
    feature_cols: List[str]


def stack_frozen_probe_pca(
    embedding: np.ndarray,
    n_components: int = 24,
    train_mask: Optional[np.ndarray] = None,
    random_state: int = 42,
) -> np.ndarray:
    """PCA-reduce a frozen-probe embedding to ``n_components`` dims.

    Leakage-safe: the PCA basis is fit on ``train_mask`` rows ONLY
    (the projection of a train row never depends on any post-train
    row), then *all* rows are transformed. ``svd_solver='full'`` →
    deterministic (no stochastic component). ``n_components`` is
    constrained to the literature's 16-32 band.
    """
    from sklearn.decomposition import PCA

    if not (_MIN_PCA <= n_components <= _MAX_PCA):
        raise ValueError(
            f"probe_pca_components={n_components} outside the "
            f"[{_MIN_PCA}, {_MAX_PCA}] band (RA2 spec)")
    emb = np.asarray(embedding, dtype=float)
    fit_rows = emb if train_mask is None else emb[np.asarray(train_mask)]
    pca = PCA(n_components=n_components, svd_solver="full",
              random_state=random_state)
    pca.fit(fit_rows)
    return pca.transform(emb)


def train_a1(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    start_pos: np.ndarray,
    horizon: int,
    groups: Optional[np.ndarray] = None,
    X_val: Optional[pd.DataFrame] = None,
    y_val: Optional[pd.Series] = None,
    probe_embedding: Optional[np.ndarray] = None,
    train_mask: Optional[np.ndarray] = None,
    cfg: A1Config = A1Config(),
) -> A1FitResult:
    """Fit the A1 shallow-XGB model on RA1 engineered features.

    * shallow tree (``2 <= max_depth <= 4`` enforced),
    * PRD-1 leakage-correct sample weights applied (one helper:
      ``engineered_sample_weights`` → ``label_leakage``),
    * optional train-only PCA frozen-probe block stacked as extra
      ``probe_pc{j}`` columns.
    """
    if not (2 <= cfg.max_depth <= 4):
        raise ValueError(
            f"max_depth={cfg.max_depth} — A1 is shallow by design "
            f"(2-4 only; low variance at low SNR per RA2 synthesis)")

    Xf = X.copy()
    if probe_embedding is not None:
        pcs = stack_frozen_probe_pca(
            probe_embedding, cfg.probe_pca_components,
            train_mask=train_mask, random_state=cfg.random_state)
        for j in range(pcs.shape[1]):
            Xf[f"probe_pc{j}"] = pcs[:, j]

    w = engineered_sample_weights(
        np.asarray(start_pos), horizon, groups=groups)

    feature_cols = list(Xf.columns)
    model = XGBAlphaModel(
        max_depth=cfg.max_depth, n_estimators=cfg.n_estimators,
        random_state=cfg.random_state)
    model.fit(Xf, y, X_val, y_val, feature_cols=feature_cols,
              sample_weight=w)
    return A1FitResult(model=model, sample_weight=w,
                       feature_cols=feature_cols)
