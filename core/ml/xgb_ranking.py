"""XGBoost ranking objectives for cross-sectional alpha mining.

Phase 1.6 — addresses Phase 1.5 finding (`docs/memos/20260513-ml_phase_1_5_closeout.md`)
that `reg:squarederror` is NOT aligned with PQS Rank IC evaluation metric. Per
SOTA literature (Yan Lin LambdaRankIC 2026; Lim et al 2020) ranking objectives
provide +33-174% improvement on Rank IC, ICIR, Sharpe ratio vs MSE regression.

Three new model classes added without modifying `core.ml.xgb_alpha`:
  - XGBRankingModel: XGBoost native rank:pairwise / rank:ndcg with qid groups
  - LambdaRankICModel: custom objective directly optimizing Rank IC (paper §3.1)
  - XGBQuintileModel: 5-class multinomial classifier (top quintile vs bottom)

Common interface:
  model.fit(panel, dates, fwd_return, X_val, val_dates, feature_cols)
  model.predict(panel)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import xgboost as xgb

from core.logging_setup import get_logger

logger = get_logger("xgb_ranking")


# ────────────────────────────────────────────────────────────────────────
# Common helpers (cross-sectional → qid groups)
# ────────────────────────────────────────────────────────────────────────


def build_qid_groups(panel: pd.DataFrame) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Sort panel by date and produce (sorted_panel, qid_array, group_sizes).

    Each unique date in panel forms one query group.

    Returns
    -------
    sorted_panel : panel sorted by date (then symbol for determinism)
    qid_array : int array of query ids matching sorted_panel rows; needed
                for XGBRanker DataFrame mode
    group_sizes : int array of per-group sizes (lengths summing to nrows);
                  needed for DMatrix.set_group()
    """
    if not pd.api.types.is_datetime64_any_dtype(panel["date"]):
        panel = panel.copy()
        panel["date"] = pd.to_datetime(panel["date"])
    sorted_panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)
    # Build qid from sorted dates
    unique_dates = sorted_panel["date"].drop_duplicates().reset_index(drop=True)
    date_to_qid = {d: i for i, d in enumerate(unique_dates)}
    qid_array = sorted_panel["date"].map(date_to_qid).values
    group_sizes = sorted_panel.groupby("date", sort=True).size().values
    return sorted_panel, qid_array, group_sizes


def cross_sectional_rank_target(
    panel: pd.DataFrame,
    target_col: str = "fwd_return",
    as_integer_levels: Optional[int] = None,
) -> np.ndarray:
    """Convert raw forward returns to within-date cross-sectional rank.

    Default (``as_integer_levels=None``): continuous percentile rank in [0,1].
    With ``as_integer_levels=N``: integer relevance levels in {0, 1, ..., N-1}
    (e.g. ``N=10`` = deciles). XGBoost ranking objectives REQUIRE integer
    relevance labels, so the ranking models below use ``as_integer_levels=10``
    when feeding XGBoost.

    Sorted ascending: bottom return = 0, top return = (1 or N-1).
    """
    if not pd.api.types.is_datetime64_any_dtype(panel["date"]):
        panel = panel.copy()
        panel["date"] = pd.to_datetime(panel["date"])
    pct = (
        panel.groupby("date")[target_col]
        .rank(pct=True, ascending=True, na_option="keep")
        .values
    )
    if as_integer_levels is None:
        return pct
    levels = np.clip(
        np.floor(pct * as_integer_levels).astype(int),
        0, as_integer_levels - 1,
    )
    # NaN passes through as -1 (caller's responsibility to mask)
    levels = np.where(np.isnan(pct), -1, levels)
    return levels


def cross_sectional_quintile_target(
    panel: pd.DataFrame, target_col: str = "fwd_return", n_quintiles: int = 5
) -> np.ndarray:
    """Convert forward returns to quintile labels {0, 1, ..., n_quintiles-1}
    per date. 0 = bottom returns, n_quintiles-1 = top returns. NaN → -1.
    """
    if not pd.api.types.is_datetime64_any_dtype(panel["date"]):
        panel = panel.copy()
        panel["date"] = pd.to_datetime(panel["date"])

    def _qcut_safe(s: pd.Series) -> pd.Series:
        s_clean = s.dropna()
        if len(s_clean) < n_quintiles:
            return pd.Series([-1] * len(s), index=s.index)
        # Use rank to assign quintiles deterministically (handles ties)
        ranks = s_clean.rank(pct=True, method="first", ascending=True)
        bins = np.linspace(0, 1, n_quintiles + 1)
        labels = np.clip(np.searchsorted(bins[1:-1], ranks.values), 0, n_quintiles - 1)
        out = pd.Series([-1] * len(s), index=s.index, dtype=int)
        out.loc[s_clean.index] = labels
        return out

    return panel.groupby("date", group_keys=False)[target_col].apply(_qcut_safe).values


# ────────────────────────────────────────────────────────────────────────
# XGBRankingModel — native rank:pairwise / rank:ndcg
# ────────────────────────────────────────────────────────────────────────


@dataclass
class XGBRankingModel:
    """XGBoost with native learning-to-rank objective (rank:pairwise / rank:ndcg).

    For cross-sectional financial prediction:
      - Each trading date = one query group
      - Within a group, stocks are ranked by their forward returns
      - Predictions are real-valued scores; top-N selection uses argsort
    """

    objective: str = "rank:pairwise"  # or 'rank:ndcg'
    n_estimators: int = 200
    max_depth: int = 5
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.7
    reg_alpha: float = 0.1
    reg_lambda: float = 0.1
    early_stopping_rounds: int = 20
    seed: int = 42
    n_jobs: int = -1

    def __post_init__(self):
        if self.objective not in ("rank:pairwise", "rank:ndcg", "rank:map"):
            raise ValueError(
                f"objective must be rank:pairwise / rank:ndcg / rank:map, "
                f"got {self.objective!r}"
            )
        self._model: Optional[xgb.Booster] = None
        self._feature_cols: List[str] = []
        self.best_iteration: Optional[int] = None

    def fit(
        self,
        train_panel: pd.DataFrame,
        y_train: pd.Series,
        val_panel: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
        feature_cols: Optional[List[str]] = None,
    ) -> "XGBRankingModel":
        if feature_cols is None:
            feature_cols = [c for c in train_panel.columns
                           if c not in ("date", "symbol", "year", "fwd_return")]
        self._feature_cols = feature_cols

        sorted_train, _, train_group_sizes = build_qid_groups(train_panel)
        # Sync y_train to sorted order
        y_train_sorted = sorted_train.merge(
            pd.concat([train_panel[["date", "symbol"]], y_train.rename("y")], axis=1),
            on=["date", "symbol"], how="left",
        )["y"].values
        # Convert to within-date rank as relevance score (continuous in [0, 1])
        sorted_train_with_y = sorted_train.copy()
        sorted_train_with_y["y_relevance"] = y_train_sorted
        # XGBoost ranking requires INTEGER relevance labels (paper §3.2)
        y_rank = cross_sectional_rank_target(
            sorted_train_with_y, "y_relevance", as_integer_levels=10,
        )
        train_mask = y_rank >= 0

        dtrain = xgb.DMatrix(
            sorted_train[feature_cols].values[train_mask],
            label=y_rank[train_mask], feature_names=feature_cols,
        )
        # Group sizes after mask: recount per qid
        train_qids_masked = pd.Series(
            sorted_train["date"].values[train_mask]
        ).reset_index(drop=True)
        train_group_sizes_masked = train_qids_masked.groupby(train_qids_masked).size().values
        dtrain.set_group(train_group_sizes_masked)

        evals = [(dtrain, "train")]
        dval = None
        if val_panel is not None and y_val is not None:
            sorted_val, _, val_group_sizes = build_qid_groups(val_panel)
            y_val_sorted = sorted_val.merge(
                pd.concat([val_panel[["date", "symbol"]], y_val.rename("y")], axis=1),
                on=["date", "symbol"], how="left",
            )["y"].values
            sorted_val_with_y = sorted_val.copy()
            sorted_val_with_y["y_relevance"] = y_val_sorted
            y_val_rank = cross_sectional_rank_target(
                sorted_val_with_y, "y_relevance", as_integer_levels=10,
            )
            val_mask = y_val_rank >= 0
            val_qids_masked = pd.Series(
                sorted_val["date"].values[val_mask]
            ).reset_index(drop=True)
            val_group_sizes_masked = val_qids_masked.groupby(val_qids_masked).size().values
            dval = xgb.DMatrix(
                sorted_val[feature_cols].values[val_mask],
                label=y_val_rank[val_mask], feature_names=feature_cols,
            )
            dval.set_group(val_group_sizes_masked)
            evals.append((dval, "val"))

        params = {
            "objective": self.objective,
            "eval_metric": "ndcg@10" if self.objective != "rank:map" else "map@10",
            "max_depth": self.max_depth,
            "learning_rate": self.learning_rate,
            "subsample": self.subsample,
            "colsample_bytree": self.colsample_bytree,
            "reg_alpha": self.reg_alpha,
            "reg_lambda": self.reg_lambda,
            "seed": self.seed,
            "n_jobs": self.n_jobs,
            "verbosity": 0,
        }
        kwargs: Dict[str, Any] = {}
        if dval is not None:
            kwargs["early_stopping_rounds"] = self.early_stopping_rounds

        self._model = xgb.train(
            params, dtrain, num_boost_round=self.n_estimators,
            evals=evals, **kwargs, verbose_eval=False,
        )
        self.best_iteration = self._model.best_iteration if dval is not None else None
        return self

    def predict(self, panel: pd.DataFrame) -> np.ndarray:
        """Predict on panel; returns scores in original panel row order (not sorted)."""
        sorted_panel, _, group_sizes = build_qid_groups(panel)
        d = xgb.DMatrix(
            sorted_panel[self._feature_cols].values,
            feature_names=self._feature_cols,
        )
        d.set_group(group_sizes)
        pred_sorted = self._model.predict(d)
        # Map back to original order
        sorted_panel_with_pred = sorted_panel.copy()
        sorted_panel_with_pred["__pred__"] = pred_sorted
        orig = panel.copy().reset_index(drop=True)
        orig["__row__"] = range(len(orig))
        merged = orig.merge(
            sorted_panel_with_pred[["date", "symbol", "__pred__"]],
            on=["date", "symbol"], how="left",
        )
        return merged.sort_values("__row__")["__pred__"].values


# ────────────────────────────────────────────────────────────────────────
# LambdaRankICModel — custom objective directly optimizing Rank IC
# ────────────────────────────────────────────────────────────────────────


def _lambda_rank_ic_objective_factory(group_sizes: np.ndarray):
    """Factory returning XGBoost custom obj function that implements
    LambdaRankIC (Yan Lin 2026 arxiv 2605.00501).

    Per paper Algorithm 1 + Proposition 1:
      ΔRankIC(i,j) = 12 * |r̂_j - r̂_i| * |ỹ_i - ỹ_j| / (n * (n² - 1))
        where:
          r̂_i = predicted rank of i within its group
          ỹ_i = true rank of i (from labels)
          n = group size
      p_ij = sigmoid(s_i - s_j)
      λ_ij = (p_ij - 1) * |ΔRankIC|
      h_ij = 2 * p_ij * (1 - p_ij) * |ΔRankIC|
    """
    # Pre-compute group offsets
    group_offsets = np.concatenate([[0], np.cumsum(group_sizes)])

    def _obj(predt: np.ndarray, dtrain: xgb.DMatrix) -> Tuple[np.ndarray, np.ndarray]:
        y_true = dtrain.get_label()
        grad = np.zeros_like(predt, dtype=np.float64)
        hess = np.zeros_like(predt, dtype=np.float64)

        for g_idx, n in enumerate(group_sizes):
            start = group_offsets[g_idx]
            end = group_offsets[g_idx + 1]
            if n < 2:
                continue
            scores = predt[start:end]
            labels = y_true[start:end]
            # method='first' breaks ties by position; gives non-zero pred_rank
            # diffs even when initial scores are all 0 (XGBoost cold-start).
            # This preserves LambdaRankIC's |Δ| weight as non-degenerate.
            pred_ranks = pd.Series(scores).rank(method="first").values
            label_ranks = pd.Series(labels).rank(method="first").values
            denom = n * (n * n - 1)
            if denom <= 0:
                continue
            for i in range(n):
                for j in range(i + 1, n):
                    # Pairwise direction: y_i > y_j means i should rank higher
                    if labels[i] == labels[j]:
                        continue
                    sign = 1.0 if labels[i] > labels[j] else -1.0
                    # ΔRankIC magnitude
                    delta = 12.0 * abs(pred_ranks[j] - pred_ranks[i]) * abs(
                        label_ranks[i] - label_ranks[j]
                    ) / denom
                    # Sigmoid for ranking probability
                    diff = sign * (scores[i] - scores[j])
                    # Numerical stability for sigmoid
                    if diff > 30:
                        p = 1.0
                    elif diff < -30:
                        p = 0.0
                    else:
                        p = 1.0 / (1.0 + np.exp(-diff))
                    lam = (p - 1.0) * abs(delta) * sign
                    h = 2.0 * p * (1.0 - p) * abs(delta)
                    grad[start + i] += lam
                    grad[start + j] -= lam
                    hess[start + i] += h
                    hess[start + j] += h
        return grad, hess

    return _obj


@dataclass
class LambdaRankICModel:
    """XGBoost with custom LambdaRankIC objective.

    Per Yan Lin 2026 paper (arxiv 2605.00501): closed-form lambda gradients
    that directly optimize Rank IC (Spearman correlation between predictions
    and labels within each group).

    O(n²) per group in current implementation; for typical PQS groups (~80
    stocks per date) and ~1500 train dates, ~10M pairwise ops per epoch.
    """

    n_estimators: int = 200
    max_depth: int = 5
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.7
    reg_alpha: float = 0.1
    reg_lambda: float = 0.1
    early_stopping_rounds: int = 20
    seed: int = 42

    def __post_init__(self):
        self._model: Optional[xgb.Booster] = None
        self._feature_cols: List[str] = []
        self.best_iteration: Optional[int] = None

    def fit(
        self,
        train_panel: pd.DataFrame,
        y_train: pd.Series,
        val_panel: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
        feature_cols: Optional[List[str]] = None,
    ) -> "LambdaRankICModel":
        if feature_cols is None:
            feature_cols = [c for c in train_panel.columns
                           if c not in ("date", "symbol", "year", "fwd_return")]
        self._feature_cols = feature_cols

        sorted_train, _, train_group_sizes = build_qid_groups(train_panel)
        y_train_sorted = sorted_train.merge(
            pd.concat([train_panel[["date", "symbol"]], y_train.rename("y")], axis=1),
            on=["date", "symbol"], how="left",
        )["y"].values
        # Use cross-sectional rank as labels (in [0, 1])
        sorted_train_with_y = sorted_train.copy()
        sorted_train_with_y["y_relevance"] = y_train_sorted
        y_rank = cross_sectional_rank_target(sorted_train_with_y, "y_relevance")

        dtrain = xgb.DMatrix(
            sorted_train[feature_cols].values,
            label=y_rank, feature_names=feature_cols,
        )

        evals = [(dtrain, "train")]
        dval = None
        val_group_sizes = None
        if val_panel is not None and y_val is not None:
            sorted_val, _, val_group_sizes = build_qid_groups(val_panel)
            y_val_sorted = sorted_val.merge(
                pd.concat([val_panel[["date", "symbol"]], y_val.rename("y")], axis=1),
                on=["date", "symbol"], how="left",
            )["y"].values
            sorted_val_with_y = sorted_val.copy()
            sorted_val_with_y["y_relevance"] = y_val_sorted
            y_val_rank = cross_sectional_rank_target(sorted_val_with_y, "y_relevance")
            dval = xgb.DMatrix(
                sorted_val[feature_cols].values,
                label=y_val_rank, feature_names=feature_cols,
            )
            evals.append((dval, "val"))

        train_obj = _lambda_rank_ic_objective_factory(train_group_sizes)
        # For eval, use a feval that approximates Rank IC
        params = {
            "max_depth": self.max_depth,
            "learning_rate": self.learning_rate,
            "subsample": self.subsample,
            "colsample_bytree": self.colsample_bytree,
            "reg_alpha": self.reg_alpha,
            "reg_lambda": self.reg_lambda,
            "seed": self.seed,
            "verbosity": 0,
            "disable_default_eval_metric": 1,
        }
        kwargs: Dict[str, Any] = {"maximize": True}  # Rank IC: higher better
        if dval is not None:
            kwargs["early_stopping_rounds"] = self.early_stopping_rounds

        # Custom metric: use VAL group_sizes for val DMatrix, TRAIN for train
        # DMatrix. XGBoost calls metric once per (eval_set, dmatrix) pair.
        # We always use train_group_sizes for the train eval and val_group_sizes
        # for val eval. Implementation: closure over both then dispatch by len.
        feval_train_only = _rank_ic_eval_metric_factory(train_group_sizes)
        if val_group_sizes is not None:
            feval_val = _rank_ic_eval_metric_factory(val_group_sizes)

            def _dispatched_metric(predt, dm):
                # Heuristic: dispatch by total length matching train vs val
                if len(predt) == train_group_sizes.sum():
                    return feval_train_only(predt, dm)
                return feval_val(predt, dm)
            metric_fn = _dispatched_metric
        else:
            metric_fn = feval_train_only

        self._model = xgb.train(
            params, dtrain, num_boost_round=self.n_estimators,
            evals=evals, obj=train_obj, custom_metric=metric_fn,
            **kwargs, verbose_eval=False,
        )
        self.best_iteration = self._model.best_iteration if dval is not None else None
        return self

    def predict(self, panel: pd.DataFrame) -> np.ndarray:
        sorted_panel, _, _ = build_qid_groups(panel)
        d = xgb.DMatrix(
            sorted_panel[self._feature_cols].values,
            feature_names=self._feature_cols,
        )
        pred_sorted = self._model.predict(d)
        sorted_panel_with_pred = sorted_panel.copy()
        sorted_panel_with_pred["__pred__"] = pred_sorted
        orig = panel.copy().reset_index(drop=True)
        orig["__row__"] = range(len(orig))
        merged = orig.merge(
            sorted_panel_with_pred[["date", "symbol", "__pred__"]],
            on=["date", "symbol"], how="left",
        )
        return merged.sort_values("__row__")["__pred__"].values


def _rank_ic_eval_metric_factory(group_sizes: np.ndarray):
    """Factory returning XGBoost custom_metric that computes mean Rank IC
    across query groups."""
    group_offsets = np.concatenate([[0], np.cumsum(group_sizes)])

    def _metric(predt: np.ndarray, dtrain: xgb.DMatrix) -> Tuple[str, float]:
        labels = dtrain.get_label()
        ics = []
        for g_idx, n in enumerate(group_sizes):
            start = group_offsets[g_idx]
            end = group_offsets[g_idx + 1]
            if n < 5:
                continue
            scores_g = predt[start:end]
            labels_g = labels[start:end]
            if pd.Series(scores_g).std() < 1e-12 or pd.Series(labels_g).std() < 1e-12:
                continue
            from scipy.stats import spearmanr
            rho, _ = spearmanr(scores_g, labels_g, nan_policy="omit")
            if np.isfinite(rho):
                ics.append(rho)
        if not ics:
            return "rank_ic", 0.0
        return "rank_ic", float(np.mean(ics))

    return _metric


# ────────────────────────────────────────────────────────────────────────
# XGBQuintileModel — 5-class multinomial classifier
# ────────────────────────────────────────────────────────────────────────


@dataclass
class XGBQuintileModel:
    """5-class multinomial XGBoost. Labels = {0, 1, 2, 3, 4} for {bottom,
    Q2, mid, Q4, top} quintile of within-date forward returns.

    Predictions = probability of top quintile (class 4); used as score for
    top-N selection.
    """

    n_estimators: int = 200
    max_depth: int = 5
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.7
    reg_alpha: float = 0.1
    reg_lambda: float = 0.1
    early_stopping_rounds: int = 20
    seed: int = 42
    n_quintiles: int = 5

    def __post_init__(self):
        from xgboost.sklearn import XGBClassifier
        self._XGBClassifier = XGBClassifier
        self._model = None
        self._feature_cols: List[str] = []
        self.best_iteration: Optional[int] = None

    def fit(
        self,
        train_panel: pd.DataFrame,
        y_train: pd.Series,  # fwd_return (raw)
        val_panel: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
        feature_cols: Optional[List[str]] = None,
    ) -> "XGBQuintileModel":
        if feature_cols is None:
            feature_cols = [c for c in train_panel.columns
                           if c not in ("date", "symbol", "year", "fwd_return")]
        self._feature_cols = feature_cols

        # Build quintile labels per date
        train_q = train_panel.copy()
        train_q["fwd_return_aligned"] = y_train.values
        train_labels = cross_sectional_quintile_target(
            train_q, "fwd_return_aligned", self.n_quintiles,
        )
        train_mask = train_labels >= 0
        X_train = train_panel[feature_cols].values[train_mask]
        y_q = train_labels[train_mask]

        kwargs: Dict[str, Any] = dict(
            n_estimators=self.n_estimators, max_depth=self.max_depth,
            learning_rate=self.learning_rate, subsample=self.subsample,
            colsample_bytree=self.colsample_bytree, reg_alpha=self.reg_alpha,
            reg_lambda=self.reg_lambda, random_state=self.seed,
            tree_method="hist", verbosity=0,
            objective="multi:softprob", num_class=self.n_quintiles,
        )
        if val_panel is not None and y_val is not None:
            val_q = val_panel.copy()
            val_q["fwd_return_aligned"] = y_val.values
            val_labels = cross_sectional_quintile_target(
                val_q, "fwd_return_aligned", self.n_quintiles,
            )
            val_mask = val_labels >= 0
            X_val = val_panel[feature_cols].values[val_mask]
            y_val_q = val_labels[val_mask]
            kwargs["early_stopping_rounds"] = self.early_stopping_rounds
            self._model = self._XGBClassifier(**kwargs)
            self._model.fit(X_train, y_q, eval_set=[(X_val, y_val_q)], verbose=False)
            self.best_iteration = getattr(self._model, "best_iteration", None)
        else:
            self._model = self._XGBClassifier(**kwargs)
            self._model.fit(X_train, y_q)
        return self

    def predict(self, panel: pd.DataFrame) -> np.ndarray:
        """Return probability of top quintile (class n_quintiles - 1) as score."""
        proba = self._model.predict_proba(panel[self._feature_cols].values)
        return proba[:, -1]  # P(top quintile)
