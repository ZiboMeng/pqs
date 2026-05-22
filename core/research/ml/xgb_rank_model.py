"""PRD #4 P4.1 sub-step 2 — XGBRanker concrete rank model.

Learning-to-rank concrete impl using xgboost.XGBRanker (pairwise
objective). Each per-bar (date) acts as one "query group" — model
learns to order symbols within each bar.

Architecture mirrors `LinearBaselineRankModel` (PRD #4 P4.1
sub-step 1): same Protocol, same TDD pattern, same §9.0 invariant
enforcement (output is cross-sectional RANK ∈ [0, 1], NOT raw score
as size weight).

References:
- Zhang et al., "Building Cross-Sectional Systematic Strategies by
  Learning to Rank" — learning-to-rank applied to stock selection
- xgboost docs: XGBRanker(objective="rank:pairwise") + group= sizes
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from core.research.ml.rank_model import (
    _cross_sectional_rank,
    _cross_sectional_standardize,
)

__all__ = ["XGBRankerRankModel"]


@dataclass
class XGBRankerRankModel:
    """Pairwise learning-to-rank model for cross-sectional stock
    ranking. Each bar (date) is one query group; XGBRanker learns
    to order symbols within group by forward-return rank.

    Parameters
    ----------
    n_estimators : int (default 100)
        Number of boosting rounds.
    max_depth : int (default 4)
        Max tree depth (shallow trees for tabular ranking).
    learning_rate : float (default 0.1)
    objective : str (default "rank:pairwise")
        Other options: "rank:ndcg", "rank:map". Pairwise is
        Pareto-floor for binary preference learning.
    random_state : int (default 42)
        Reproducibility seed.

    §9.0 invariant: `predict_rank()` returns rank ∈ [0, 1] per bar,
    NOT raw model score. Internal predict yields continuous score
    but public API yields rank only. Tests verify discrete output
    boundary.
    """
    n_estimators: int = 100
    max_depth: int = 4
    learning_rate: float = 0.1
    objective: str = "rank:pairwise"
    random_state: int = 42

    _model: Optional[object] = field(default=None, repr=False)
    feature_columns: Tuple[str, ...] = field(default_factory=tuple)
    fitted: bool = field(default=False)

    def fit(self, features: dict, labels: pd.DataFrame) -> None:
        """Fit XGBRanker on stacked (per-bar standardized features)
        → forward-return labels grouped by bar.

        Args:
          features: dict[feature_name, DataFrame(date × symbol)]
          labels: DataFrame(date × symbol) forward returns
        """
        if not isinstance(features, dict):
            raise NotImplementedError(
                "XGBRankerRankModel.fit currently supports dict["
                "feature_name, panel] form only")
        # cross-sectional standardize features + labels
        feat_names = sorted(features.keys())
        std_feats = {
            name: _cross_sectional_standardize(features[name])
            for name in feat_names
        }
        label_std = _cross_sectional_standardize(labels)
        # stack: per-date group of (X_row, y_row)
        X_list, y_list, group_sizes = [], [], []
        for date in label_std.index:
            if not all(date in std_feats[n].index for n in feat_names):
                continue
            n_in_group = 0
            for sym in label_std.columns:
                y_val = label_std.at[date, sym]
                if pd.isna(y_val):
                    continue
                feat_vals = []
                ok = True
                for n in feat_names:
                    if (sym not in std_feats[n].columns
                            or date not in std_feats[n].index):
                        ok = False
                        break
                    v = std_feats[n].at[date, sym]
                    if pd.isna(v):
                        ok = False
                        break
                    feat_vals.append(v)
                if ok:
                    X_list.append(feat_vals)
                    y_list.append(y_val)
                    n_in_group += 1
            if n_in_group >= 2:  # need ≥ 2 to form a pairwise comparison
                group_sizes.append(n_in_group)
            elif n_in_group == 1:
                # remove the orphan from X/y (no group to form pair)
                X_list.pop()
                y_list.pop()
        if not X_list or not group_sizes:
            raise ValueError(
                "XGBRankerRankModel.fit: insufficient training data "
                "after standardization + group-size filter; need ≥ 2 "
                "symbols per bar for pairwise ranking")
        X = np.asarray(X_list, dtype=float)
        y = np.asarray(y_list, dtype=float)
        # XGBRanker expects integer (or float) target; convert to
        # within-group rank (1..n) so the pairwise comparison is
        # rank-based not magnitude-based — §9.0 alignment
        y_grouped_rank = self._within_group_rank(y, group_sizes)
        # train XGBRanker
        import xgboost as xgb
        xgb_kwargs = dict(
            objective=self.objective,
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            random_state=self.random_state,
            verbosity=0,
        )
        if self.objective == "rank:ndcg":
            # Cross-sectional query groups carry many names (a 79-symbol
            # universe → within-group integer ranks up to 79). XGBoost's
            # default exponential NDCG gain (2^rel - 1) caps relevance at
            # 31; use the linear/custom DCG gain so any group size is
            # valid. (Surfaced by the P2 rank:ndcg smoke, 2026-05-21.)
            xgb_kwargs["ndcg_exp_gain"] = False
        self._model = xgb.XGBRanker(**xgb_kwargs)
        self._model.fit(X, y_grouped_rank, group=group_sizes)
        self.feature_columns = tuple(feat_names)
        self.fitted = True

    @staticmethod
    def _within_group_rank(y: np.ndarray, group_sizes: list) -> np.ndarray:
        """Convert per-group y values to within-group integer ranks
        (1..n) so XGBRanker learns rank-pairwise not magnitude."""
        out = np.empty_like(y, dtype=float)
        idx = 0
        for size in group_sizes:
            sub = y[idx:idx + size]
            # higher value → higher rank (per XGBRanker convention)
            ranks = pd.Series(sub).rank(method="average").values
            out[idx:idx + size] = ranks
            idx += size
        return out

    def predict_rank(self, features: dict) -> pd.DataFrame:
        """Predict cross-sectional rank ∈ [0, 1] per bar."""
        if not self.fitted:
            raise RuntimeError(
                "XGBRankerRankModel.predict_rank: model not fitted; "
                "call .fit() first")
        if not isinstance(features, dict):
            raise TypeError(
                "predict_rank currently supports dict[feature_name, "
                "panel] form only")
        feat_names = list(self.feature_columns)
        std_feats = {
            n: _cross_sectional_standardize(features[n])
            for n in feat_names if n in features
        }
        missing = set(feat_names) - set(std_feats.keys())
        if missing:
            raise ValueError(
                f"predict_rank: features dict missing keys {missing}")
        all_dates = sorted(
            set.union(*(set(std_feats[n].index) for n in feat_names)))
        all_syms = sorted(
            set.union(*(set(std_feats[n].columns) for n in feat_names)))
        score = pd.DataFrame(np.nan, index=all_dates, columns=all_syms)
        # batch-predict per-date for efficiency
        for date in all_dates:
            rows, sym_list = [], []
            for sym in all_syms:
                feat_vals = []
                ok = True
                for n in feat_names:
                    if (date not in std_feats[n].index
                            or sym not in std_feats[n].columns):
                        ok = False
                        break
                    v = std_feats[n].at[date, sym]
                    if pd.isna(v):
                        ok = False
                        break
                    feat_vals.append(v)
                if ok:
                    rows.append(feat_vals)
                    sym_list.append(sym)
            if not rows:
                continue
            X = np.asarray(rows, dtype=float)
            raw = self._model.predict(X)
            for s, r in zip(sym_list, raw):
                score.at[date, s] = float(r)
        # cross-sectional rank to [0, 1] — §9.0 invariant: rank not
        # magnitude.
        return _cross_sectional_rank(score)
