"""PRD #4 P4.1 — cross-sectional rank model (Stage 1 RANK).

§9.0 post-fix HARD constraint: output is RANK / percentile score
∈ [0, 1], NOT a magnitude prediction. Downstream sidecar (Stage 2,
PRD #4 P4.2) maps top-decile rank to SignVote — this layer never
sees its raw output used as a position size weight.

Per-bar discipline:
  - cross-sectional standardization of features per bar (avoids
    magnitude leakage)
  - cross-sectional standardization of label per bar (rank-based,
    not absolute return)
  - strict-chronological training (no interleaved selector)
  - sealed-2026 never trained/evaluated on

Architecture: Protocol-based to allow XGBRanker / LightGBM /
LinearBaseline interchangeable. P4.1 ships LinearBaseline first as
the Pareto-floor sanity baseline; XGBRanker follows in P4.1+.

References:
  - Gu/Kelly/Xiu (2020) Empirical Asset Pricing via Machine Learning
  - Zhang et al. Learning to Rank for cross-sectional stock selection
  - Alekseenko et al. Learning-to-Rank ranking objectives
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "RankModelProtocol",
    "LinearBaselineRankModel",
    "rank_ic",
    "rank_ir",
]


# ── Protocol ──────────────────────────────────────────────────────────
class RankModelProtocol(Protocol):
    """PRD #4 P4.1 RANK model API.

    fit(features, labels): train on (date×symbol×feature) features +
    (date×symbol) labels (forward returns or pre-ranked targets).

    predict_rank(features): return (date×symbol) cross-sectional
    rank/percentile in [0, 1] per row.
    """

    def fit(self, features: pd.DataFrame, labels: pd.DataFrame) -> None:
        ...

    def predict_rank(self, features: pd.DataFrame) -> pd.DataFrame:
        ...


# ── Helper: cross-sectional standardization + rank ───────────────────
def _cross_sectional_standardize(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-row z-score: (x - row_mean) / row_std.

    Per `feedback_temporal_split_discipline` + leakage discipline:
    standardization is ALWAYS per-bar (cross-sectional), never
    across-time. Avoids look-ahead bias from time-aggregated stats.
    """
    mu = panel.mean(axis=1)
    sigma = panel.std(axis=1)
    sigma = sigma.replace(0, np.nan)  # avoid div-by-zero
    standardized = panel.sub(mu, axis=0).div(sigma, axis=0)
    return standardized


def _cross_sectional_rank(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-row percentile rank ∈ [0, 1]; NaN preserved."""
    return panel.rank(axis=1, pct=True, method="average")


# ── Metrics ──────────────────────────────────────────────────────────
def rank_ic(pred_rank: pd.DataFrame, label: pd.DataFrame) -> float:
    """Mean cross-sectional Spearman rank-IC across all bars.

    Per-bar: rank-correlate pred_rank row vs label rank row;
    average across bars.

    Returns 0.0 if no overlapping rows or all-NaN.
    """
    label_rank = _cross_sectional_rank(label)
    common_idx = pred_rank.index.intersection(label_rank.index)
    if len(common_idx) == 0:
        return 0.0
    ics = []
    for date in common_idx:
        p = pred_rank.loc[date].dropna()
        l = label_rank.loc[date].dropna()
        common_syms = p.index.intersection(l.index)
        if len(common_syms) < 3:
            continue
        # Spearman on the per-bar ranks (already rank-transformed)
        # equivalent to Pearson of ranks
        ic = p.loc[common_syms].corr(l.loc[common_syms])
        if not np.isnan(ic):
            ics.append(ic)
    return float(np.mean(ics)) if ics else 0.0


def rank_ir(pred_rank: pd.DataFrame, label: pd.DataFrame) -> float:
    """Information ratio of per-bar rank-IC: mean / std.

    Per Grinold-Kahn equivalent for ranking; not annualized (raw IR).
    Returns 0.0 if std ≤ 0 or insufficient data.
    """
    label_rank = _cross_sectional_rank(label)
    common_idx = pred_rank.index.intersection(label_rank.index)
    ics = []
    for date in common_idx:
        p = pred_rank.loc[date].dropna()
        l = label_rank.loc[date].dropna()
        common_syms = p.index.intersection(l.index)
        if len(common_syms) < 3:
            continue
        ic = p.loc[common_syms].corr(l.loc[common_syms])
        if not np.isnan(ic):
            ics.append(ic)
    if len(ics) < 2:
        return 0.0
    arr = np.asarray(ics)
    s = arr.std()
    if s <= 0:
        return 0.0
    return float(arr.mean() / s)


# ── LinearBaselineRankModel ──────────────────────────────────────────
@dataclass
class LinearBaselineRankModel:
    """Pareto-floor sanity baseline.

    Trains a single global linear regression on stacked
    (cross-sectionally standardized features) → standardized labels.
    Prediction = per-row dot product, then cross-sectional rank in
    [0, 1].

    No regularization (intentionally simple); use as the floor
    against which XGBRanker / LightGBM are compared.

    §9.0 invariant: output is RANK ∈ [0, 1], not magnitude. Even
    if internal regression produces continuous score, the public
    API yields rank only.
    """
    coefficients: Optional[np.ndarray] = field(default=None)
    feature_columns: Tuple[str, ...] = field(default_factory=tuple)
    fitted: bool = field(default=False)

    def fit(
        self, features: pd.DataFrame, labels: pd.DataFrame,
    ) -> None:
        """Fit linear regression on stacked (panel × features) →
        per-bar standardized labels.

        Features must be a MultiIndex panel: outer = features
        (column groups), inner = date×symbol matrix. For now we
        accept dict[str, DataFrame] = {feature_name: panel} and
        stack ourselves.

        labels: (date × symbol) DataFrame of forward returns or
        targets.
        """
        if isinstance(features, dict):
            # dict[feature_name, panel] form
            feat_names = sorted(features.keys())
            standardized = {
                name: _cross_sectional_standardize(features[name])
                for name in feat_names
            }
            # stack into (n_obs, n_features) matrix
            X_list = []
            y_list = []
            label_std = _cross_sectional_standardize(labels)
            for date in label_std.index:
                if not all(date in standardized[name].index
                           for name in feat_names):
                    continue
                # per-symbol row of features at this date
                for sym in label_std.columns:
                    label_val = label_std.at[date, sym]
                    if pd.isna(label_val):
                        continue
                    feat_vals = []
                    ok = True
                    for name in feat_names:
                        v = standardized[name].at[date, sym] \
                            if (sym in standardized[name].columns
                                and date in standardized[name].index) \
                            else np.nan
                        if pd.isna(v):
                            ok = False
                            break
                        feat_vals.append(v)
                    if ok:
                        X_list.append(feat_vals)
                        y_list.append(label_val)
            if not X_list:
                raise ValueError(
                    "LinearBaselineRankModel.fit: no valid training "
                    "observations after standardization + NaN filter")
            X = np.asarray(X_list)
            y = np.asarray(y_list)
            # closed-form OLS: beta = (X'X)^-1 X'y
            XtX = X.T @ X
            # tiny regularization to prevent singular matrix on
            # highly correlated features (1e-8 ridge — does not
            # materially change Pareto-floor behavior)
            n_feat = X.shape[1]
            XtX_reg = XtX + 1e-8 * np.eye(n_feat)
            self.coefficients = np.linalg.solve(XtX_reg, X.T @ y)
            self.feature_columns = tuple(feat_names)
            self.fitted = True
            return
        raise NotImplementedError(
            "LinearBaselineRankModel.fit currently only supports "
            "dict[feature_name, panel] features form; matrix-form "
            "features will be added in P4.4 pipeline scaffold")

    def predict_rank(
        self, features: dict,
    ) -> pd.DataFrame:
        """Predict cross-sectional rank ∈ [0, 1] per bar."""
        if not self.fitted:
            raise RuntimeError(
                "LinearBaselineRankModel.predict_rank: model not "
                "fitted; call .fit() first")
        if not isinstance(features, dict):
            raise TypeError(
                "predict_rank currently supports dict[feature_name, "
                "panel] form only")
        # cross-sectional standardize per-bar
        feat_names = list(self.feature_columns)
        if not feat_names:
            raise RuntimeError(
                "LinearBaselineRankModel.predict_rank: feature_columns "
                "is empty (model not fitted)")
        standardized = {
            name: _cross_sectional_standardize(features[name])
            for name in feat_names if name in features
        }
        if len(standardized) != len(feat_names):
            missing = set(feat_names) - set(standardized.keys())
            raise ValueError(
                f"predict_rank: features dict missing keys {missing}")
        # build score panel
        # iterate union of dates/symbols
        all_dates = sorted(
            set.union(*(set(standardized[n].index)
                        for n in feat_names)))
        all_syms = sorted(
            set.union(*(set(standardized[n].columns)
                        for n in feat_names)))
        score = pd.DataFrame(np.nan, index=all_dates, columns=all_syms)
        for date in all_dates:
            for sym in all_syms:
                feat_vals = []
                ok = True
                for n in feat_names:
                    if (date not in standardized[n].index
                            or sym not in standardized[n].columns):
                        ok = False
                        break
                    v = standardized[n].at[date, sym]
                    if pd.isna(v):
                        ok = False
                        break
                    feat_vals.append(v)
                if ok:
                    s = float(np.dot(self.coefficients,
                                     np.asarray(feat_vals)))
                    score.at[date, sym] = s
        # cross-sectional rank to [0, 1]
        return _cross_sectional_rank(score)
