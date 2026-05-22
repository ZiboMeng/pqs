"""P2 (PRD 20260521 §12.6) — LightGBM ranker, parity path.

`LGBMRankerRankModel` implements the SAME `RankModelProtocol` as
`XGBRankerRankModel` — a Protocol implementation, NOT a fourth
competing rank stack (per
`docs/memos/20260521-p2-canonical-rank-model-decision.md`). Each bar
(date) is one LightGBM query group; `lambdarank` learns to order
symbols within the bar.

§9.0 invariant: `predict_rank()` returns cross-sectional rank ∈ [0, 1]
per bar, never a raw model score used as a size weight.

The per-bar group-assembly glue mirrors `XGBRankerRankModel.fit` /
`.predict_rank` (a shared `_stack_grouped` helper is a future refactor;
the duplication is contained and labelled).
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from core.research.ml.rank_model import (
    _cross_sectional_rank,
    _cross_sectional_standardize,
)

__all__ = ["LGBMRankerRankModel"]


@dataclass
class LGBMRankerRankModel:
    """LightGBM lambdarank parity path for XGBRankerRankModel.

    lightgbm.LGBMRanker(objective="lambdarank"). Within-group integer
    relevance ranks are 0-based; ``label_gain`` is a linear ramp sized
    to the largest query group, so a 79-name cross-section (relevance
    grades 0..78) is valid — LightGBM's default exponential label_gain
    caps relevance at ~30, the same trap the XGBoost ndcg_exp_gain fix
    addresses.
    """
    n_estimators: int = 100
    max_depth: int = 4
    learning_rate: float = 0.1
    objective: str = "lambdarank"
    random_state: int = 42

    _model: Optional[object] = field(default=None, repr=False)
    feature_columns: Tuple[str, ...] = field(default_factory=tuple)
    fitted: bool = field(default=False)

    def fit(self, features: dict, labels: pd.DataFrame) -> None:
        """Fit LGBMRanker on stacked per-bar standardized features →
        forward-return labels grouped by bar.

        Args:
          features: dict[feature_name, DataFrame(date × symbol)]
          labels: DataFrame(date × symbol) forward returns
        """
        if not isinstance(features, dict):
            raise NotImplementedError(
                "LGBMRankerRankModel.fit supports dict[feature, panel] only")
        feat_names = sorted(features.keys())
        std_feats = {n: _cross_sectional_standardize(features[n])
                     for n in feat_names}
        label_std = _cross_sectional_standardize(labels)

        X_list, y_list, group_sizes = [], [], []
        for date in label_std.index:
            if not all(date in std_feats[n].index for n in feat_names):
                continue
            n_in_group = 0
            for sym in label_std.columns:
                y_val = label_std.at[date, sym]
                if pd.isna(y_val):
                    continue
                feat_vals, ok = [], True
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
            if n_in_group >= 2:
                group_sizes.append(n_in_group)
            elif n_in_group == 1:
                X_list.pop()
                y_list.pop()
        if not X_list or not group_sizes:
            raise ValueError(
                "LGBMRankerRankModel.fit: insufficient training data after "
                "standardization + group-size filter; need ≥ 2 symbols/bar")

        X = np.asarray(X_list, dtype=float)
        y = np.asarray(y_list, dtype=float)
        y_int_rank = self._within_group_int_rank(y, group_sizes)
        max_group = max(group_sizes)

        import lightgbm as lgb
        self._model = lgb.LGBMRanker(
            objective=self.objective,
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            random_state=self.random_state,
            # Linear label_gain sized to the largest group — LightGBM's
            # default exponential gain caps relevance grades; a 79-name
            # cross-section needs grades 0..78. (P2, 2026-05-21.)
            label_gain=list(range(max_group + 1)),
            verbose=-1,
        )
        self._model.fit(X, y_int_rank, group=group_sizes)
        self.feature_columns = tuple(feat_names)
        self.fitted = True

    @staticmethod
    def _within_group_int_rank(y: np.ndarray, group_sizes: list) -> np.ndarray:
        """Per-group 0-based integer relevance ranks (LightGBM lambdarank
        requires non-negative integer labels). Ties broken by order."""
        out = np.empty_like(y, dtype=int)
        idx = 0
        for size in group_sizes:
            sub = y[idx:idx + size]
            ranks = pd.Series(sub).rank(method="first").to_numpy()
            out[idx:idx + size] = ranks.astype(int) - 1  # 0-based
            idx += size
        return out

    def predict_rank(self, features: dict) -> pd.DataFrame:
        """Predict cross-sectional rank ∈ [0, 1] per bar (§9.0)."""
        if not self.fitted:
            raise RuntimeError(
                "LGBMRankerRankModel.predict_rank: model not fitted")
        if not isinstance(features, dict):
            raise TypeError("predict_rank supports dict[feature, panel] only")
        feat_names = list(self.feature_columns)
        std_feats = {n: _cross_sectional_standardize(features[n])
                     for n in feat_names if n in features}
        missing = set(feat_names) - set(std_feats.keys())
        if missing:
            raise ValueError(f"predict_rank: features missing {missing}")
        all_dates = sorted(
            set.union(*(set(std_feats[n].index) for n in feat_names)))
        all_syms = sorted(
            set.union(*(set(std_feats[n].columns) for n in feat_names)))
        score = pd.DataFrame(np.nan, index=all_dates, columns=all_syms)
        # The model is fit on a numpy array (no column names); predicting
        # with a numpy array triggers a benign sklearn feature-name
        # UserWarning per call — scoped-suppress that one warning only.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=".*does not have valid feature names.*",
                category=UserWarning)
            score = self._predict_scores(
                std_feats, feat_names, all_dates, all_syms, score)
        return _cross_sectional_rank(score)

    def _predict_scores(self, std_feats, feat_names, all_dates,
                        all_syms, score):
        for date in all_dates:
            rows, sym_list = [], []
            for sym in all_syms:
                feat_vals, ok = [], True
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
            raw = self._model.predict(np.asarray(rows, dtype=float))
            for s, r in zip(sym_list, raw):
                score.at[date, s] = float(r)
        return score
