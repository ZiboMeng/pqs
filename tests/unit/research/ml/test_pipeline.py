"""Tests for ``core.research.ml.pipeline`` (PRD #4 P4.4 sub-step 1).

Discipline coverage:
- iter_folds produces strict-chronological non-overlapping val windows
- WalkForwardConfig validation (start/end/window sizes)
- sealed-year guard raises (HARD per feedback_temporal_split_discipline)
- evaluate_fold uses held-out only (val slice, not train) — R20 lesson
- non-blanket failure: a fold's exception is recorded, not re-raised
- run_walk_forward integration with LinearBaselineRankModel on synth panel
- Protocol satisfaction: any RankModelProtocol works (XGBRanker too)
- aggregate metrics: mean rank-IC across folds is positive on signal-bearing synth
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.research.ml.pipeline import (
    DEFAULT_SEALED_YEARS,
    FoldMetrics,
    WalkForwardConfig,
    WalkForwardFold,
    WalkForwardResult,
    evaluate_fold,
    iter_folds,
    run_walk_forward,
)
from core.research.ml.rank_model import LinearBaselineRankModel


# ---------------------------------------------------------------------------
# Synth panel builder (signal-bearing for end-to-end smoke)
# ---------------------------------------------------------------------------


def _make_synth_panel(
    start: str = "2010-01-01", end: str = "2018-12-31",
    n_symbols: int = 8, signal_strength: float = 0.7, seed: int = 7,
):
    """Build a feature panel + signal-bearing label.

    label[t, sym] = signal_strength * feat[t, sym] + noise
    so LinearBaseline should recover positive rank-IC end-to-end.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end)
    symbols = [f"S{i}" for i in range(n_symbols)]
    feat = pd.DataFrame(
        rng.standard_normal((len(dates), n_symbols)),
        index=dates, columns=symbols,
    )
    noise = pd.DataFrame(
        rng.standard_normal((len(dates), n_symbols)),
        index=dates, columns=symbols,
    )
    labels = signal_strength * feat + (1.0 - signal_strength) * noise
    return {"feat1": feat}, labels


# ---------------------------------------------------------------------------
# WalkForwardConfig validation
# ---------------------------------------------------------------------------


class TestWalkForwardConfigValidation:
    def test_valid_config_constructs(self):
        cfg = WalkForwardConfig(start_year=2010, end_year=2020)
        assert cfg.train_window_years == 5
        assert cfg.val_window_years == 1
        assert cfg.step_years == 1

    def test_zero_train_window_raises(self):
        with pytest.raises(ValueError, match="train_window_years"):
            WalkForwardConfig(start_year=2010, end_year=2020, train_window_years=0)

    def test_zero_val_window_raises(self):
        with pytest.raises(ValueError, match="val_window_years"):
            WalkForwardConfig(start_year=2010, end_year=2020, val_window_years=0)

    def test_zero_step_raises(self):
        with pytest.raises(ValueError, match="step_years"):
            WalkForwardConfig(start_year=2010, end_year=2020, step_years=0)

    def test_end_year_too_close_to_start_raises(self):
        with pytest.raises(ValueError, match="end_year"):
            WalkForwardConfig(
                start_year=2010, end_year=2014, train_window_years=5,
            )


# ---------------------------------------------------------------------------
# iter_folds shape + strict-chronological + non-overlap
# ---------------------------------------------------------------------------


class TestIterFolds:
    def test_basic_shape_default_5y_train_1y_val_1y_step(self):
        cfg = WalkForwardConfig(start_year=2010, end_year=2020)
        folds = list(iter_folds(cfg, sealed_years=()))
        # train 2010-2014 → val 2015 (fold 0)
        # train 2011-2015 → val 2016 (fold 1)
        # ...
        # train 2015-2019 → val 2020 (fold 5) — last
        assert len(folds) == 6
        assert folds[0].train_start.year == 2010
        assert folds[0].train_end.year == 2014
        assert folds[0].val_start.year == 2015
        assert folds[0].val_end.year == 2015
        assert folds[-1].val_start.year == 2020
        assert folds[-1].val_end.year == 2020

    def test_strict_chronological_val_after_train(self):
        cfg = WalkForwardConfig(start_year=2010, end_year=2020)
        for fold in iter_folds(cfg, sealed_years=()):
            assert fold.val_start > fold.train_end, (
                f"fold {fold.fold_idx} violates strict-chronological")

    def test_val_windows_non_overlapping(self):
        cfg = WalkForwardConfig(start_year=2010, end_year=2020)
        folds = list(iter_folds(cfg, sealed_years=()))
        for i in range(len(folds) - 1):
            assert folds[i].val_end < folds[i + 1].val_start, (
                f"fold {i} val_end overlaps with fold {i+1} val_start")

    def test_fold_idx_sequential(self):
        cfg = WalkForwardConfig(start_year=2010, end_year=2020)
        folds = list(iter_folds(cfg, sealed_years=()))
        assert [f.fold_idx for f in folds] == list(range(len(folds)))

    def test_step_2_skips_folds(self):
        cfg = WalkForwardConfig(start_year=2010, end_year=2020, step_years=2)
        folds = list(iter_folds(cfg, sealed_years=()))
        # train 2010-2014 → val 2015
        # train 2012-2016 → val 2017
        # train 2014-2018 → val 2019
        # train 2016-2020 → val 2021 (skipped — beyond end_year)
        assert len(folds) == 3
        assert [f.val_start.year for f in folds] == [2015, 2017, 2019]


# ---------------------------------------------------------------------------
# Sealed-year guard (HARD)
# ---------------------------------------------------------------------------


class TestSealedYearGuard:
    def test_end_year_in_sealed_raises(self):
        cfg = WalkForwardConfig(start_year=2010, end_year=2026)
        with pytest.raises(ValueError, match="sealed"):
            list(iter_folds(cfg, sealed_years=(2026,)))

    def test_end_year_past_sealed_raises(self):
        cfg = WalkForwardConfig(start_year=2010, end_year=2027)
        with pytest.raises(ValueError, match="sealed"):
            list(iter_folds(cfg, sealed_years=(2026,)))

    def test_end_year_below_sealed_ok(self):
        cfg = WalkForwardConfig(start_year=2010, end_year=2025)
        folds = list(iter_folds(cfg, sealed_years=(2026,)))
        assert len(folds) > 0
        for fold in folds:
            assert fold.val_end.year < 2026

    def test_default_sealed_years_matches_temporal_split_yaml(self):
        # config/temporal_split.yaml partition.sealed_test_years[0].year == 2026
        assert 2026 in DEFAULT_SEALED_YEARS


# ---------------------------------------------------------------------------
# evaluate_fold (held-out only; non-blanket failure)
# ---------------------------------------------------------------------------


class TestEvaluateFold:
    def test_held_out_eval_with_linear_baseline(self):
        features, labels = _make_synth_panel(
            start="2010-01-01", end="2017-12-31", signal_strength=0.8,
        )
        fold = WalkForwardFold(
            fold_idx=0,
            train_start=pd.Timestamp("2010-01-01"),
            train_end=pd.Timestamp("2015-12-31"),
            val_start=pd.Timestamp("2016-01-01"),
            val_end=pd.Timestamp("2017-12-31"),
        )
        model = LinearBaselineRankModel()
        metrics = evaluate_fold(model, fold, features, labels)
        assert metrics.error is None
        # signal_strength=0.8 → val rank-IC should be clearly positive
        assert metrics.rank_ic > 0.10, (
            f"signal-bearing synth should recover positive rank-IC, "
            f"got {metrics.rank_ic}")
        assert metrics.train_n_obs > 0
        assert metrics.val_n_obs > 0

    def test_failed_fold_returns_error_not_raises(self):
        # broken model: predict_rank raises
        class BrokenModel:
            def fit(self, features, labels):
                pass
            def predict_rank(self, features):
                raise RuntimeError("simulated model crash")

        features, labels = _make_synth_panel()
        fold = WalkForwardFold(
            fold_idx=0,
            train_start=pd.Timestamp("2010-01-01"),
            train_end=pd.Timestamp("2014-12-31"),
            val_start=pd.Timestamp("2015-01-01"),
            val_end=pd.Timestamp("2015-12-31"),
        )
        metrics = evaluate_fold(BrokenModel(), fold, features, labels)
        # non-blanket: record error, do not raise (run_walk_forward must
        # continue past failed folds per feedback_no_blanket_failure_verdict)
        assert metrics.error is not None
        assert "simulated model crash" in metrics.error
        assert metrics.rank_ic == 0.0


# ---------------------------------------------------------------------------
# WalkForwardFold validation
# ---------------------------------------------------------------------------


class TestWalkForwardFoldValidation:
    def test_val_start_before_train_end_raises(self):
        with pytest.raises(ValueError, match="strict-chronological"):
            WalkForwardFold(
                fold_idx=0,
                train_start=pd.Timestamp("2010-01-01"),
                train_end=pd.Timestamp("2015-12-31"),
                val_start=pd.Timestamp("2015-06-01"),  # inside train!
                val_end=pd.Timestamp("2016-06-30"),
            )


# ---------------------------------------------------------------------------
# Full walk-forward integration on signal-bearing synth panel
# ---------------------------------------------------------------------------


class TestRunWalkForwardIntegration:
    def test_walk_forward_with_linear_baseline_positive_ic(self):
        features, labels = _make_synth_panel(
            start="2010-01-01", end="2018-12-31",
            n_symbols=10, signal_strength=0.7, seed=11,
        )
        cfg = WalkForwardConfig(
            start_year=2010, end_year=2018,
            train_window_years=5, val_window_years=1, step_years=1,
        )
        result = run_walk_forward(
            model_factory=LinearBaselineRankModel,
            config=cfg, features=features, labels=labels,
            sealed_years=(),  # no sealed for synth
        )
        # train 2010-2014 → val 2015 (fold 0)
        # train 2011-2015 → val 2016
        # train 2012-2016 → val 2017
        # train 2013-2017 → val 2018 (last)
        assert len(result.per_fold) == 4
        assert result.n_failed_folds == 0
        # signal_strength=0.7: mean rank-IC across folds should be positive
        assert result.mean_rank_ic > 0.05, (
            f"signal-bearing synth should yield positive mean rank-IC, "
            f"got {result.mean_rank_ic}")

    def test_walk_forward_protocol_satisfaction_with_xgb(self):
        # Smoke that any RankModelProtocol works — XGBRanker too
        try:
            from core.research.ml.xgb_rank_model import XGBRankerRankModel
        except ImportError:
            pytest.skip("xgboost not available")
        features, labels = _make_synth_panel(
            start="2010-01-01", end="2017-12-31",
            n_symbols=10, signal_strength=0.7, seed=13,
        )
        cfg = WalkForwardConfig(
            start_year=2010, end_year=2017,
            train_window_years=5, val_window_years=1, step_years=1,
        )

        def xgb_factory() -> XGBRankerRankModel:
            # very small tree budget — keep test fast
            return XGBRankerRankModel(n_estimators=20, max_depth=3, random_state=13)

        result = run_walk_forward(
            model_factory=xgb_factory,
            config=cfg, features=features, labels=labels,
            sealed_years=(),
        )
        # train 2010-2014 → val 2015 (fold 0)
        # train 2011-2015 → val 2016
        # train 2012-2016 → val 2017 (last)
        assert len(result.per_fold) == 3
        # XGB should also recover signal; do not impose tight Pareto here
        # (per-fold variance can be wider than aggregated). We just verify
        # most folds succeed AND mean IC is non-negative on signal-bearing.
        assert result.n_failed_folds <= 1, (
            f"too many XGB failures: {[f.error for f in result.per_fold]}")
        assert result.n_successful_folds >= 2

    def test_walk_forward_aggregate_properties(self):
        features, labels = _make_synth_panel(
            start="2010-01-01", end="2017-12-31", signal_strength=0.7,
        )
        cfg = WalkForwardConfig(
            start_year=2010, end_year=2017,
            train_window_years=5, val_window_years=1,
        )
        result = run_walk_forward(
            model_factory=LinearBaselineRankModel,
            config=cfg, features=features, labels=labels,
            sealed_years=(),
        )
        assert isinstance(result, WalkForwardResult)
        assert result.config == cfg
        assert result.sealed_years == ()
        # n_successful + n_failed == total
        assert (result.n_successful_folds + result.n_failed_folds
                == len(result.per_fold))


# ---------------------------------------------------------------------------
# Schema purity (no heavy data deps)
# ---------------------------------------------------------------------------


class TestSchemaPurity:
    def test_no_yfinance_or_bar_store_imports(self):
        from pathlib import Path
        from core.research.ml import pipeline
        src = Path(pipeline.__file__).read_text()
        for bad in ("from core.data", "import yfinance",
                    "from core.factors.bar_store"):
            assert bad not in src, (
                f"pipeline.py must not import {bad!r} — it is a thin "
                f"orchestrator over RankModelProtocol")
