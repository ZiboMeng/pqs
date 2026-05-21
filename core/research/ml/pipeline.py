"""PRD #4 P4.4 — walk-forward training pipeline for rank-model + sign-classifier.

Sub-step 1 (this module): strict-chronological rolling-window walk-forward
orchestration for any ``RankModelProtocol`` implementation (LinearBaseline,
XGBRanker, future LightGBM). Yields per-fold metrics (rank-IC, rank-IR)
computed on the HELD-OUT validation slice only.

Discipline (mandatory; hard-enforced):
  - strict-chronological: ``val_start_year > train_end_year`` (no
    interleaved selector — Track-A R1 leakage discipline).
  - sealed-year guard: ``end_year`` must not be in ``sealed_years``
    (default ``(2026,)`` from ``config/temporal_split.yaml``;
    ``feedback_temporal_split_discipline`` + sealed-2026 ledger rule).
  - per-bar cross-sectional standardization is the MODEL's contract
    (already enforced inside ``LinearBaselineRankModel`` /
    ``XGBRankerRankModel``); this layer does not re-standardize.
  - held-out only: per-fold ``FoldMetrics.rank_ic`` is computed on the
    val slice the model never saw during ``fit`` (R20 in-sample overfit
    catch lesson).
  - non-blanket failure: if a fold raises during fit/predict, that
    fold is recorded with ``error`` field, and the run does NOT abort
    — the per-fold transparency table is the verdict surface (per
    ``feedback_no_blanket_failure_verdict``).

Sub-step 2 (next round): artifact persistence (save/load pickle +
metadata JSON with deterministic spec_id + lineage_tag).
Sub-step 3: walk-forward driver script ``dev/scripts/ml/walk_forward_rank_sign.py``.

PRD: docs/prd/20260520-prd_rank_first_ml_pipeline.md §P4.4
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.research.ml.rank_model import RankModelProtocol, rank_ic, rank_ir

__all__ = [
    "WalkForwardConfig",
    "WalkForwardFold",
    "FoldMetrics",
    "WalkForwardResult",
    "iter_folds",
    "evaluate_fold",
    "run_walk_forward",
    "DEFAULT_SEALED_YEARS",
]


# Sealed years pulled from config/temporal_split.yaml partition.sealed_test_years
# (2026-05-20 snapshot). Pipeline hard-rejects ``end_year`` in this set; if a new
# split_name bumps sealed years, callers pass the new tuple via ``sealed_years``.
DEFAULT_SEALED_YEARS: Tuple[int, ...] = (2026,)


@dataclass(frozen=True)
class WalkForwardConfig:
    """Rolling-window walk-forward configuration.

    Window semantics (calendar-year resolution):
      fold k: train = [start_year + k*step, start_year + k*step + train_window_years - 1]
              val   = [train_end + 1, train_end + val_window_years]
      iterate until ``val_end_year > end_year``.

    All windows are inclusive integer-year ranges.
    """
    start_year: int
    end_year: int
    train_window_years: int = 5
    val_window_years: int = 1
    step_years: int = 1
    embargo_days: int = 0
    """Purge + embargo gap (calendar days) trimmed off the END of each
    train window (PRD 20260521 §8.2; user decision 2026-05-21 — applied
    in the ML pipeline, NOT by editing config/temporal_split*.yaml).
    Default 0 = bit-identical to the prior behaviour. Daily-horizon ML
    drivers should pass ``embargo_days = horizon_days`` so a train
    label's forward window cannot overlap the val window."""

    def __post_init__(self) -> None:
        if self.train_window_years < 1:
            raise ValueError("train_window_years must be ≥ 1")
        if self.val_window_years < 1:
            raise ValueError("val_window_years must be ≥ 1")
        if self.step_years < 1:
            raise ValueError("step_years must be ≥ 1")
        if self.embargo_days < 0:
            raise ValueError("embargo_days must be ≥ 0")
        if self.end_year < self.start_year + self.train_window_years:
            raise ValueError(
                f"end_year ({self.end_year}) too close to start_year "
                f"({self.start_year}) — needs at least "
                f"train_window_years ({self.train_window_years}) + 1 of slack")


@dataclass(frozen=True)
class WalkForwardFold:
    """A single train/val split."""
    fold_idx: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    val_start: pd.Timestamp
    val_end: pd.Timestamp

    def __post_init__(self) -> None:
        # strict-chronological guard
        if self.val_start <= self.train_end:
            raise ValueError(
                f"WalkForwardFold {self.fold_idx} not strict-chronological: "
                f"val_start ({self.val_start.date()}) must be > "
                f"train_end ({self.train_end.date()})")


@dataclass
class FoldMetrics:
    """Per-fold metrics. Held-out only."""
    fold: WalkForwardFold
    rank_ic: float
    rank_ir: float
    train_n_obs: int
    val_n_obs: int
    error: Optional[str] = None


@dataclass
class WalkForwardResult:
    """Aggregate walk-forward output."""
    config: WalkForwardConfig
    per_fold: List[FoldMetrics]
    sealed_years: Tuple[int, ...]

    @property
    def mean_rank_ic(self) -> float:
        ics = [f.rank_ic for f in self.per_fold if f.error is None]
        return float(np.mean(ics)) if ics else 0.0

    @property
    def mean_rank_ir(self) -> float:
        irs = [f.rank_ir for f in self.per_fold if f.error is None]
        return float(np.mean(irs)) if irs else 0.0

    @property
    def n_successful_folds(self) -> int:
        return sum(1 for f in self.per_fold if f.error is None)

    @property
    def n_failed_folds(self) -> int:
        return sum(1 for f in self.per_fold if f.error is not None)


def _check_sealed_guard(
    end_year: int, sealed_years: Iterable[int],
) -> None:
    """Hard-fail if any sealed year ≤ end_year.

    Per ``feedback_temporal_split_discipline`` + sealed-2026 ledger rule:
    pipeline MUST NEVER train or evaluate on sealed years. Raises
    ``ValueError`` immediately at config-validation time.
    """
    sealed_set = set(sealed_years)
    if end_year in sealed_set:
        raise ValueError(
            f"WalkForwardConfig.end_year={end_year} is in sealed_years "
            f"{sorted(sealed_set)}; sealed years are off-limits per "
            f"config/temporal_split.yaml + feedback_temporal_split_discipline.")
    # also reject if any val window would cross into sealed
    for sealed in sealed_set:
        if sealed <= end_year:
            raise ValueError(
                f"sealed_year {sealed} ≤ end_year {end_year}: pipeline "
                f"would evaluate on sealed data. Reduce end_year to "
                f"{min(sealed_set) - 1} or bump split_name.")


def iter_folds(
    config: WalkForwardConfig,
    sealed_years: Iterable[int] = DEFAULT_SEALED_YEARS,
) -> Iterator[WalkForwardFold]:
    """Yield strict-chronological train/val folds.

    Each fold's val window is non-overlapping with prior folds' val
    windows (rolling, not expanding). Stops when val_end_year would
    exceed config.end_year.
    """
    _check_sealed_guard(config.end_year, sealed_years)
    fold_idx = 0
    k = 0
    while True:
        train_start_year = config.start_year + k * config.step_years
        train_end_year = train_start_year + config.train_window_years - 1
        val_start_year = train_end_year + 1
        val_end_year = val_start_year + config.val_window_years - 1
        if val_end_year > config.end_year:
            break
        # Purge + embargo: trim the last `embargo_days` calendar days off
        # the train window so a train label's forward (horizon) window
        # cannot reach into the val window. embargo_days=0 → unchanged.
        train_end = (pd.Timestamp(f"{train_end_year}-12-31")
                     - pd.Timedelta(days=config.embargo_days))
        yield WalkForwardFold(
            fold_idx=fold_idx,
            train_start=pd.Timestamp(f"{train_start_year}-01-01"),
            train_end=train_end,
            val_start=pd.Timestamp(f"{val_start_year}-01-01"),
            val_end=pd.Timestamp(f"{val_end_year}-12-31"),
        )
        fold_idx += 1
        k += 1


def _slice_panel_dict(
    features: Dict[str, pd.DataFrame],
    start: pd.Timestamp, end: pd.Timestamp,
) -> Dict[str, pd.DataFrame]:
    """Inclusive date-slice each panel in the features dict."""
    return {
        name: panel.loc[(panel.index >= start) & (panel.index <= end)]
        for name, panel in features.items()
    }


def _slice_labels(
    labels: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
) -> pd.DataFrame:
    return labels.loc[(labels.index >= start) & (labels.index <= end)]


def evaluate_fold(
    model: RankModelProtocol,
    fold: WalkForwardFold,
    features: Dict[str, pd.DataFrame],
    labels: pd.DataFrame,
) -> FoldMetrics:
    """Fit ``model`` on the fold's train slice, evaluate on val slice.

    Held-out only — per R20 in-sample overfit catch lesson, val
    metrics are computed on the slice the model never saw during fit.
    """
    train_features = _slice_panel_dict(features, fold.train_start, fold.train_end)
    train_labels = _slice_labels(labels, fold.train_start, fold.train_end)
    val_features = _slice_panel_dict(features, fold.val_start, fold.val_end)
    val_labels = _slice_labels(labels, fold.val_start, fold.val_end)

    train_n = int(train_labels.notna().sum().sum())
    val_n = int(val_labels.notna().sum().sum())

    try:
        model.fit(train_features, train_labels)
        pred_rank = model.predict_rank(val_features)
        ic = rank_ic(pred_rank, val_labels)
        ir = rank_ir(pred_rank, val_labels)
    except Exception as exc:
        # non-blanket: record the failure, do not abort run
        return FoldMetrics(
            fold=fold, rank_ic=0.0, rank_ir=0.0,
            train_n_obs=train_n, val_n_obs=val_n,
            error=f"{type(exc).__name__}: {exc}",
        )

    return FoldMetrics(
        fold=fold, rank_ic=ic, rank_ir=ir,
        train_n_obs=train_n, val_n_obs=val_n, error=None,
    )


def _validate_panel_indices(
    features: Dict[str, pd.DataFrame], labels: pd.DataFrame,
) -> None:
    """Enforce DatetimeIndex on features panels + labels (R23 catch follow-up).

    `_slice_panel_dict` uses `panel.index >= start` which silently fails
    on RangeIndex with `TypeError`. Validate upstream so the failure
    surfaces at driver entry with a clear message.
    """
    if not isinstance(labels.index, pd.DatetimeIndex):
        raise ValueError(
            f"labels must have DatetimeIndex; got "
            f"{type(labels.index).__name__}")
    for name, panel in features.items():
        if not isinstance(panel.index, pd.DatetimeIndex):
            raise ValueError(
                f"features[{name!r}] must have DatetimeIndex; got "
                f"{type(panel.index).__name__}")


def run_walk_forward(
    model_factory: Callable[[], RankModelProtocol],
    config: WalkForwardConfig,
    features: Dict[str, pd.DataFrame],
    labels: pd.DataFrame,
    sealed_years: Iterable[int] = DEFAULT_SEALED_YEARS,
) -> WalkForwardResult:
    """Run rolling-window walk-forward training + evaluation.

    Args:
        model_factory: zero-arg callable producing a fresh model per
            fold (each fold gets a fresh model — no warm-start).
        config: WalkForwardConfig.
        features: dict[feature_name, panel(date×symbol)] with DatetimeIndex.
        labels: DataFrame(date×symbol) of forward returns or rank
            targets, with DatetimeIndex. Per PRD #4 P4.1 AC: horizon
            MUST match the canonical config's holding_freq (currently
            weekly/monthly per cycle06 spec); caller is responsible
            for shifting + aligning the label upstream.
        sealed_years: tuple of years off-limits.

    Returns:
        WalkForwardResult with per-fold transparency + aggregate
        mean rank-IC / rank-IR.
    """
    _validate_panel_indices(features, labels)
    sealed_tuple = tuple(sealed_years)
    per_fold: List[FoldMetrics] = []
    for fold in iter_folds(config, sealed_tuple):
        model = model_factory()
        metrics = evaluate_fold(model, fold, features, labels)
        per_fold.append(metrics)
    return WalkForwardResult(
        config=config, per_fold=per_fold, sealed_years=sealed_tuple,
    )
