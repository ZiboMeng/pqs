"""PRD #4 P4.2 — sign-vote binary classifier (Stage 2).

Stage 2 of the two-stage rank-first ML architecture. Takes top-decile
entries selected by Stage 1 (rank model), classifies them as winner/loser
based on forward return, outputs binary labels {0, 1} that are wrapped
by ``core.research.decision.ml_voters.binary_classifier_voter`` into
``SignVote{VETO, NO_VOTE}`` per §9.0 post-fix invariant.

Architecture:
  Stage 1 (RANK) → top-decile mask → Stage 2 fit on entry-eligible names
  Stage 2 .predict(X) → 0/1 → binary_classifier_voter → VETO/NO_VOTE

§9.0 invariant:
  - Classifiers in this module produce DISCRETE labels {0, 1}
  - The SignVote enum mapping is in ``binary_classifier_voter`` (not here);
    runtime check happens in ``MLSidecarPolicy.vote`` (raises TypeError on
    non-SignVote)
  - We test ``.predict()`` always returns labels ⊂ {0, 1}, NEVER float magnitude

References (per PRD #4):
  - Lopez de Prado (2018) triple-barrier labeling + meta-labeling: Stage 2
    is the meta-labeling layer
  - PRD-X v2 §9.0 post-fix: ML outputs must be categorical
  - ml_voters.binary_classifier_voter: voter wrapping contract

PRD: docs/prd/20260520-prd_rank_first_ml_pipeline.md §P4.2
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "SignClassifierProtocol",
    "LogisticRegressionSignClassifier",
    "XGBSignClassifier",
    "compute_binary_sign_labels",
    "compute_cost_aware_binary_labels",
    "select_top_decile_mask",
]


# ── Protocol ──────────────────────────────────────────────────────────
class SignClassifierProtocol(Protocol):
    """sklearn-style binary classifier API for Stage 2 sign voting.

    fit(X, y): train on (n_obs, n_features) feature matrix + (n_obs,)
        binary {0, 1} labels.

    predict(X): return (n_obs,) array of binary labels {0, 1}.
        NEVER continuous magnitude per §9.0.

    predict_proba(X) [optional]: return (n_obs, 2) probabilities. Used
        for diagnostic only — voter wrapping always thresholds back to
        the discrete label.
    """

    def fit(self, X: np.ndarray, y: np.ndarray) -> None: ...

    def predict(self, X: np.ndarray) -> np.ndarray: ...


# ── Helpers ──────────────────────────────────────────────────────────


def compute_binary_sign_labels(
    price_df: pd.DataFrame, horizon_days: int, threshold: float = 0.0,
) -> pd.DataFrame:
    """Build 0/1 winner-loser labels from forward returns.

    label[t, sym] = 1 if (price[t+horizon] / price[t] - 1) > threshold else 0
    label[t, sym] = NaN where forward return is missing (last horizon rows
                    or NaN price)

    Default threshold=0.0 = "winner if forward return > 0", matching
    PRD #4 P4.2 default.

    Args:
        price_df: (date × symbol) adjusted close panel; DatetimeIndex
        horizon_days: forward window in business-day (bar-count) units
        threshold: return threshold for class 1 (winner). 0.0 default;
            non-zero threshold lets caller train on "winners that beat
            cost basis" instead of any non-negative return.
    """
    if horizon_days < 1:
        raise ValueError(f"horizon_days must be ≥ 1, got {horizon_days}")
    if not isinstance(price_df.index, pd.DatetimeIndex):
        raise ValueError(
            f"price_df must have DatetimeIndex; got "
            f"{type(price_df.index).__name__}")
    forward_return = price_df.shift(-horizon_days).div(price_df) - 1.0
    # NaN where forward_return is NaN (last horizon rows + missing prices)
    labels = (forward_return > threshold).astype(float)
    labels = labels.where(forward_return.notna())  # preserve NaN
    return labels


def compute_cost_aware_binary_labels(
    price_df: pd.DataFrame, horizon_days: int,
    cost_hurdle_bps: float = 30.0, min_expected_edge_bps: float = 10.0,
) -> pd.DataFrame:
    """Cost-aware binary winner/loser label.

    PRD 20260521 §3.5 / §7.2 ``binary_forward_return_after_cost``: a name
    is class 1 only if its forward return clears the expected round-trip
    cost hurdle PLUS a minimum edge::

        threshold = (cost_hurdle_bps + min_expected_edge_bps) / 10_000
        label     = 1 if forward_return > threshold else 0

    This closes the §3.5 gap that the bare ``threshold=0.0`` of
    ``compute_binary_sign_labels`` left open — "slightly positive but
    below realistic trading cost + slippage" no longer counts as a
    winner. Thin wrapper over ``compute_binary_sign_labels`` (single
    label definition; cost-awareness is purely the threshold).

    Args:
        price_df: (date × symbol) adjusted close panel
        horizon_days: forward window in bar-count units
        cost_hurdle_bps: expected round-trip cost + slippage, in bps
        min_expected_edge_bps: extra edge required above the cost hurdle
    """
    if cost_hurdle_bps < 0.0:
        raise ValueError(f"cost_hurdle_bps must be ≥ 0, got {cost_hurdle_bps}")
    if min_expected_edge_bps < 0.0:
        raise ValueError(
            f"min_expected_edge_bps must be ≥ 0, got {min_expected_edge_bps}")
    threshold = (cost_hurdle_bps + min_expected_edge_bps) / 10_000.0
    return compute_binary_sign_labels(
        price_df, horizon_days, threshold=threshold)


def select_top_decile_mask(
    rank_pred: pd.DataFrame, decile: float = 0.9,
) -> pd.DataFrame:
    """Boolean mask of cells in top `decile` of cross-sectional rank.

    Per PRD #4 P4.2: Stage 2 is trained on entries that PASS Stage 1's
    top-decile filter (the entry-eligible candidate set). decile=0.9
    means "above 90th percentile of per-bar rank distribution".

    rank_pred values are expected to be cross-sectional percentile in
    [0, 1] (output of Stage 1 ``RankModelProtocol.predict_rank``).

    Args:
        rank_pred: (date × symbol) rank ∈ [0, 1]
        decile: threshold ∈ (0, 1), e.g. 0.9 for top decile.
            decile=0.5 → top half (use for less restrictive entry sets).

    Returns:
        Same-shape DataFrame of bool; True = rank ≥ decile (cell is in
        the entry-eligible set).
    """
    if not 0.0 < decile < 1.0:
        raise ValueError(
            f"decile must be in (0, 1); got {decile}")
    return rank_pred >= decile


# ── Logistic baseline ────────────────────────────────────────────────
@dataclass
class LogisticRegressionSignClassifier:
    """Simple closed-form-ish logistic baseline (no sklearn dep).

    Uses pseudo-inverse Newton-Raphson with 1 step starting from OLS
    initialization — converges in 1-3 steps for linearly-separable-ish
    data. For training/inference parity with sklearn LogisticRegression
    you can swap in sklearn (we deliberately avoid the dep for the
    Pareto-floor baseline).

    Why not stdlib? Closed-form OLS doesn't yield probabilities; we
    need binary classification specifically. Logistic-via-IRLS is the
    minimal-correctness baseline that produces .predict ∈ {0, 1} from
    a probability cutoff.

    §9.0: .predict returns {0, 1} integer labels. .predict_proba
    diagnostic only — never wired to SignVote magnitude.
    """
    n_iter: int = 5            # IRLS iterations
    fit_intercept: bool = True
    decision_threshold: float = 0.5
    coefficients_: Optional[np.ndarray] = field(default=None)
    intercept_: float = field(default=0.0)
    fitted_: bool = field(default=False)

    @staticmethod
    def _sigmoid(z: np.ndarray) -> np.ndarray:
        # numerically stable sigmoid
        positive = z >= 0
        result = np.empty_like(z, dtype=float)
        result[positive] = 1.0 / (1.0 + np.exp(-z[positive]))
        e = np.exp(z[~positive])
        result[~positive] = e / (1.0 + e)
        return result

    def fit(self, X: np.ndarray, y: np.ndarray,
            sample_weight: np.ndarray | None = None,
            ) -> "LogisticRegressionSignClassifier":
        """Weighted IRLS logistic fit (S3 — supplement 20260522).
        ``sample_weight`` (per-row, non-negative) scales each
        observation's contribution to the gradient and Hessian; None
        ⇒ uniform 1.0 — bit-identical to the pre-S3 fit."""
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        if X.ndim != 2:
            raise ValueError(f"X must be 2D; got shape {X.shape}")
        if y.shape != (X.shape[0],):
            raise ValueError(
                f"y shape {y.shape} must be ({X.shape[0]},)")
        if not set(np.unique(y[~np.isnan(y)])).issubset({0.0, 1.0}):
            raise ValueError(
                f"y must be binary {{0, 1}}; got "
                f"unique={sorted(set(np.unique(y).tolist()))}")
        # mask NaN labels out
        finite_mask = ~(np.isnan(y) | np.isnan(X).any(axis=1))
        X_f = X[finite_mask]
        y_f = y[finite_mask]
        if len(y_f) == 0:
            raise ValueError(
                "no valid training observations (all NaN after mask)")
        if sample_weight is None:
            sw = np.ones(len(y_f))
        else:
            sw = np.clip(
                np.asarray(sample_weight, dtype=float)[finite_mask],
                0.0, None)
        n, p = X_f.shape
        if self.fit_intercept:
            X_aug = np.hstack([np.ones((n, 1)), X_f])
        else:
            X_aug = X_f
        beta = np.zeros(X_aug.shape[1])
        for _ in range(self.n_iter):
            z = X_aug @ beta
            mu = self._sigmoid(z)
            W = mu * (1.0 - mu)
            # avoid division by zero on perfectly separable
            W = np.clip(W, 1e-6, None)
            grad = X_aug.T @ (sw * (mu - y_f))
            hess = X_aug.T @ ((sw * W)[:, None] * X_aug)
            # ridge for numerical stability
            hess = hess + 1e-6 * np.eye(hess.shape[0])
            try:
                step = np.linalg.solve(hess, grad)
            except np.linalg.LinAlgError:
                break
            beta = beta - step
        if self.fit_intercept:
            self.intercept_ = float(beta[0])
            self.coefficients_ = beta[1:].copy()
        else:
            self.intercept_ = 0.0
            self.coefficients_ = beta.copy()
        self.fitted_ = True
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.fitted_:
            raise RuntimeError("model not fitted")
        X = np.asarray(X, dtype=float).reshape(-1, len(self.coefficients_))
        z = X @ self.coefficients_ + self.intercept_
        p1 = self._sigmoid(z)
        return np.stack([1 - p1, p1], axis=1)

    def predict(self, X: np.ndarray) -> np.ndarray:
        proba = self.predict_proba(X)
        # §9.0 invariant: return discrete labels {0, 1}, NEVER magnitude
        return (proba[:, 1] >= self.decision_threshold).astype(int)


# ── XGB classifier wrapper ────────────────────────────────────────────
@dataclass
class XGBSignClassifier:
    """xgboost.XGBClassifier wrapper with §9.0-compliant predict.

    Lazy import of xgboost so the module loads even where xgb is absent
    (matching XGBRankerRankModel pattern in P4.1).
    """
    n_estimators: int = 100
    max_depth: int = 4
    learning_rate: float = 0.1
    random_state: int = 42
    decision_threshold: float = 0.5
    booster_: object = field(default=None)
    fitted_: bool = field(default=False)

    def fit(self, X: np.ndarray, y: np.ndarray,
            sample_weight: np.ndarray | None = None,
            ) -> "XGBSignClassifier":
        """S3 (supplement 20260522): ``sample_weight`` (per-row) is
        passed through to xgboost.XGBClassifier.fit; None ⇒ uniform."""
        try:
            from xgboost import XGBClassifier
        except ImportError as exc:
            raise ImportError(
                "xgboost not installed; XGBSignClassifier requires it. "
                "pip install xgboost. Fall back to "
                "LogisticRegressionSignClassifier if unavailable.") from exc
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        if not set(np.unique(y[~np.isnan(y)])).issubset({0.0, 1.0}):
            raise ValueError(
                f"y must be binary {{0, 1}}; got unique="
                f"{sorted(set(np.unique(y).tolist()))}")
        finite_mask = ~(np.isnan(y) | np.isnan(X).any(axis=1))
        X_f = X[finite_mask]
        y_f = y[finite_mask].astype(int)
        if len(y_f) == 0:
            raise ValueError(
                "no valid training observations (all NaN after mask)")
        sw_f = (np.clip(np.asarray(sample_weight, dtype=float)[finite_mask],
                        0.0, None)
                if sample_weight is not None else None)
        self.booster_ = XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            random_state=self.random_state,
            objective="binary:logistic",
            eval_metric="logloss",
            tree_method="hist",
            verbosity=0,
        )
        self.booster_.fit(X_f, y_f, sample_weight=sw_f)
        self.fitted_ = True
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.fitted_:
            raise RuntimeError("model not fitted")
        X = np.asarray(X, dtype=float)
        return self.booster_.predict_proba(X)

    def predict(self, X: np.ndarray) -> np.ndarray:
        proba = self.predict_proba(X)
        # §9.0 invariant: discrete labels only
        return (proba[:, 1] >= self.decision_threshold).astype(int)
