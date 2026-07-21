"""Out-of-fold prediction harness for governed cross-sectional rank mining."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

import numpy as np
import pandas as pd

from core.research.feature_clustering import fit_feature_correlation_clusters
from core.research.ml.pipeline import WalkForwardConfig, iter_folds
from core.research.ml.rank_model import RankModelProtocol, rank_ic, rank_ir


@dataclass(frozen=True, slots=True)
class OOFFoldResult:
    fold_idx: int
    train_start: str
    train_end: str
    val_start: str
    val_end: str
    selected_features: tuple[str, ...]
    rank_ic: float
    rank_ir: float
    train_observations: int
    validation_observations: int
    error: str | None = None


@dataclass(frozen=True, slots=True)
class OOFMiningResult:
    predictions: pd.DataFrame
    folds: tuple[OOFFoldResult, ...]

    @property
    def successful_folds(self) -> int:
        return sum(fold.error is None for fold in self.folds)


class RuleRankModel:
    """Fixed-orientation, equal-vote rank baseline with no fitted parameters."""

    def __init__(self, orientations: Mapping[str, float]):
        if not orientations or any(value not in {-1.0, 1.0} for value in orientations.values()):
            raise ValueError("rule orientations must be a non-empty ±1 mapping")
        self.orientations = dict(sorted(orientations.items()))

    def fit(self, features: dict, labels: pd.DataFrame) -> None:
        missing = set(self.orientations) - set(features)
        if missing:
            raise ValueError(f"rule features missing: {sorted(missing)}")

    def predict_rank(self, features: dict) -> pd.DataFrame:
        votes = []
        for name, orientation in self.orientations.items():
            votes.append(features[name].rank(axis=1, pct=True) * orientation)
        score = sum(votes) / len(votes)
        return score.rank(axis=1, pct=True)


def run_oof_rank_mining(
    model_factory: Callable[[], RankModelProtocol],
    config: WalkForwardConfig,
    features: Mapping[str, pd.DataFrame],
    labels: pd.DataFrame,
    eligibility: pd.DataFrame,
    *,
    daily_trading_index: pd.DatetimeIndex,
    cluster_features: bool,
    correlation_threshold: float = 0.85,
    sealed_years: tuple[int, ...] = (2025, 2026),
) -> OOFMiningResult:
    """Fit on rolling train folds and return validation-only rank predictions."""

    if not labels.index.equals(eligibility.index):
        raise ValueError("labels and eligibility must share decision dates")
    predictions = pd.DataFrame(np.nan, index=labels.index, columns=labels.columns)
    fold_results: list[OOFFoldResult] = []
    for fold in iter_folds(
        config,
        sealed_years=sealed_years,
        trading_index=daily_trading_index,
    ):
        train_dates = labels.index[
            (labels.index >= fold.train_start) & (labels.index <= fold.train_end)]
        val_dates = labels.index[
            (labels.index >= fold.val_start) & (labels.index <= fold.val_end)]
        train_labels = labels.loc[train_dates].where(eligibility.loc[train_dates])
        val_labels = labels.loc[val_dates].where(eligibility.loc[val_dates])
        selected = tuple(sorted(features))
        try:
            valid_validation_bars = val_labels.notna().sum(axis=1) >= 3
            if not bool(valid_validation_bars.any()):
                raise ValueError(
                    "validation slice has no cross-section with at least "
                    "3 eligible forward labels"
                )
            if cluster_features:
                cluster_fit = fit_feature_correlation_clusters(
                    features,
                    eligibility,
                    train_dates,
                    absolute_correlation_threshold=correlation_threshold,
                )
                selected = cluster_fit.representatives
            train_features = {
                name: features[name].loc[train_dates].where(
                    eligibility.loc[train_dates])
                for name in selected
            }
            val_features = {
                name: features[name].loc[val_dates].where(
                    eligibility.loc[val_dates])
                for name in selected
            }
            model = model_factory()
            model.fit(train_features, train_labels)
            predicted = model.predict_rank(val_features).reindex_like(val_labels)
            predicted = predicted.where(eligibility.loc[val_dates])
            paired = predicted.notna() & val_labels.notna()
            if not bool((paired.sum(axis=1) >= 3).any()):
                raise ValueError(
                    "model produced no validation cross-section with at least "
                    "3 prediction/label pairs"
                )
            predictions.loc[val_dates] = predicted
            fold_results.append(OOFFoldResult(
                fold_idx=fold.fold_idx,
                train_start=str(fold.train_start.date()),
                train_end=str(fold.train_end.date()),
                val_start=str(fold.val_start.date()),
                val_end=str(fold.val_end.date()),
                selected_features=selected,
                rank_ic=rank_ic(predicted, val_labels),
                rank_ir=rank_ir(predicted, val_labels),
                train_observations=int(train_labels.notna().sum().sum()),
                validation_observations=int(val_labels.notna().sum().sum()),
            ))
        except ValueError as exc:
            fold_results.append(OOFFoldResult(
                fold_idx=fold.fold_idx,
                train_start=str(fold.train_start.date()),
                train_end=str(fold.train_end.date()),
                val_start=str(fold.val_start.date()),
                val_end=str(fold.val_end.date()),
                selected_features=selected,
                rank_ic=0.0,
                rank_ir=0.0,
                train_observations=int(train_labels.notna().sum().sum()),
                validation_observations=int(val_labels.notna().sum().sum()),
                error=f"{type(exc).__name__}: {exc}",
            ))
        except Exception as exc:
            raise RuntimeError(
                f"OOF fold {fold.fold_idx} raised a non-data exception: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
    return OOFMiningResult(predictions=predictions, folds=tuple(fold_results))


__all__ = [
    "OOFFoldResult",
    "OOFMiningResult",
    "RuleRankModel",
    "run_oof_rank_mining",
]
