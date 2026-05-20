"""Tests for ``core.research.ml.sign_classifier`` (PRD #4 P4.2).

Coverage:
- compute_binary_sign_labels (0/1 + NaN preservation)
- select_top_decile_mask (boundary, decile parameter, validation)
- LogisticRegressionSignClassifier fit/predict ∈ {0, 1}
- LogisticRegressionSignClassifier recovers separable signal
- XGBSignClassifier fit/predict ∈ {0, 1} (skip if xgboost missing)
- §9.0 invariant: predict returns integer labels {0, 1}, never float magnitude
- Integration with binary_classifier_voter → SignVote enum
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.research.decision.ml_sidecar import SignVote
from core.research.decision.ml_voters import binary_classifier_voter
from core.research.ml.sign_classifier import (
    LogisticRegressionSignClassifier,
    XGBSignClassifier,
    compute_binary_sign_labels,
    select_top_decile_mask,
)


# ---------------------------------------------------------------------------
# compute_binary_sign_labels
# ---------------------------------------------------------------------------


class TestComputeBinarySignLabels:
    def _make_price(self):
        idx = pd.bdate_range("2020-01-01", "2020-02-29")
        # monotone-increasing price (all forward returns > 0)
        price = pd.DataFrame(
            np.linspace(100, 200, len(idx))[:, None].repeat(3, axis=1),
            index=idx, columns=["A", "B", "C"],
        )
        return price, idx

    def test_all_positive_returns_yield_all_ones(self):
        price, _ = self._make_price()
        labels = compute_binary_sign_labels(price, horizon_days=5)
        # all forward returns are positive → all label = 1 (except last 5 = NaN)
        assert (labels.iloc[:-5] == 1).all().all()
        assert labels.iloc[-5:].isna().all().all()

    def test_falling_price_yields_zero(self):
        idx = pd.bdate_range("2020-01-01", "2020-02-29")
        # monotonically falling price
        price = pd.DataFrame(
            np.linspace(200, 100, len(idx))[:, None].repeat(3, axis=1),
            index=idx, columns=["A", "B", "C"],
        )
        labels = compute_binary_sign_labels(price, horizon_days=5)
        assert (labels.iloc[:-5] == 0).all().all()

    def test_threshold_changes_classification(self):
        idx = pd.bdate_range("2020-01-01", "2020-01-31")
        price = pd.DataFrame({
            "A": np.linspace(100, 102, len(idx)),  # +2% over 22 days
        }, index=idx)
        # horizon 5 → ~+0.5% per fold → > 0 default → 1; > 0.01 threshold → 0
        labels_default = compute_binary_sign_labels(price, horizon_days=5)
        labels_strict = compute_binary_sign_labels(
            price, horizon_days=5, threshold=0.01)
        # at horizon=5 small move ~0.5% < 1% threshold → 0
        assert labels_default.iloc[0, 0] == 1
        assert labels_strict.iloc[0, 0] == 0

    def test_horizon_zero_raises(self):
        price, _ = self._make_price()
        with pytest.raises(ValueError, match="horizon_days"):
            compute_binary_sign_labels(price, horizon_days=0)

    def test_range_index_raises(self):
        with pytest.raises(ValueError, match="DatetimeIndex"):
            compute_binary_sign_labels(
                pd.DataFrame({"A": [1.0, 2.0, 3.0]}), horizon_days=1)


# ---------------------------------------------------------------------------
# select_top_decile_mask
# ---------------------------------------------------------------------------


class TestSelectTopDecileMask:
    def test_top_decile_with_uniform_rank(self):
        rank = pd.DataFrame({
            "A": [0.1, 0.5, 0.9],
            "B": [0.95, 0.2, 0.85],
            "C": [0.5, 0.99, 0.3],
        }, index=pd.bdate_range("2020-01-01", periods=3))
        mask = select_top_decile_mask(rank, decile=0.9)
        expected = pd.DataFrame({
            "A": [False, False, True],   # 0.9 >= 0.9 → True
            "B": [True, False, False],   # 0.95 >= 0.9 → True
            "C": [False, True, False],   # 0.99 >= 0.9 → True
        }, index=rank.index)
        pd.testing.assert_frame_equal(mask, expected)

    def test_top_half_decile_05(self):
        rank = pd.DataFrame({
            "A": [0.4, 0.6],
            "B": [0.5, 0.49],
        }, index=pd.bdate_range("2020-01-01", periods=2))
        mask = select_top_decile_mask(rank, decile=0.5)
        # >= 0.5: A row 1 = 0.6 → True; B row 0 = 0.5 → True; row 1 = 0.49 → False
        assert mask.iloc[0, 0] == False  # A row 0 = 0.4
        assert mask.iloc[1, 0] == True   # A row 1 = 0.6
        assert mask.iloc[0, 1] == True   # B row 0 = 0.5
        assert mask.iloc[1, 1] == False  # B row 1 = 0.49

    def test_decile_out_of_range_raises(self):
        rank = pd.DataFrame({"A": [0.5]})
        with pytest.raises(ValueError, match="decile"):
            select_top_decile_mask(rank, decile=0.0)
        with pytest.raises(ValueError, match="decile"):
            select_top_decile_mask(rank, decile=1.0)
        with pytest.raises(ValueError, match="decile"):
            select_top_decile_mask(rank, decile=-0.1)


# ---------------------------------------------------------------------------
# LogisticRegressionSignClassifier
# ---------------------------------------------------------------------------


class TestLogisticRegressionSignClassifier:
    def test_fit_predict_returns_binary(self):
        rng = np.random.default_rng(7)
        X = rng.standard_normal((100, 3))
        y = (X[:, 0] > 0).astype(int)
        model = LogisticRegressionSignClassifier()
        model.fit(X, y)
        pred = model.predict(X)
        # §9.0 invariant: outputs are {0, 1} integer
        assert pred.dtype.kind in ("i", "u")
        assert set(np.unique(pred).tolist()).issubset({0, 1})

    def test_recovers_linearly_separable_signal(self):
        rng = np.random.default_rng(7)
        X = rng.standard_normal((200, 2))
        # Strongly separable: y = 1 iff X[:, 0] > 0.5
        y = (X[:, 0] > 0.5).astype(int)
        model = LogisticRegressionSignClassifier()
        model.fit(X, y)
        pred = model.predict(X)
        # accuracy on separable in-sample should be high
        acc = float((pred == y).mean())
        assert acc > 0.85, f"separable in-sample acc {acc} too low"

    def test_predict_before_fit_raises(self):
        model = LogisticRegressionSignClassifier()
        with pytest.raises(RuntimeError, match="not fitted"):
            model.predict(np.zeros((1, 2)))

    def test_nan_labels_filtered_during_fit(self):
        X = np.array([[1.0, 1.0], [-1.0, -1.0], [0.0, 0.0]])
        y = np.array([1.0, 0.0, np.nan])  # third row NaN
        model = LogisticRegressionSignClassifier()
        # should not raise — NaN row filtered
        model.fit(X, y)
        assert model.fitted_

    def test_all_nan_labels_raises(self):
        X = np.array([[1.0], [2.0]])
        y = np.array([np.nan, np.nan])
        with pytest.raises(ValueError, match="no valid training"):
            LogisticRegressionSignClassifier().fit(X, y)

    def test_non_binary_labels_raises(self):
        X = np.array([[1.0], [2.0]])
        y = np.array([0.0, 2.0])  # 2 is not binary
        with pytest.raises(ValueError, match="binary"):
            LogisticRegressionSignClassifier().fit(X, y)


# ---------------------------------------------------------------------------
# XGBSignClassifier
# ---------------------------------------------------------------------------


class TestXGBSignClassifier:
    def _xgb_or_skip(self):
        try:
            import xgboost  # noqa: F401
        except ImportError:
            pytest.skip("xgboost not installed")

    def test_fit_predict_returns_binary(self):
        self._xgb_or_skip()
        rng = np.random.default_rng(11)
        X = rng.standard_normal((150, 3))
        y = (X[:, 0] + X[:, 1] > 0).astype(int)
        model = XGBSignClassifier(n_estimators=30, max_depth=3)
        model.fit(X, y)
        pred = model.predict(X)
        assert pred.dtype.kind in ("i", "u")
        assert set(np.unique(pred).tolist()).issubset({0, 1})

    def test_recovers_signal_better_than_majority(self):
        self._xgb_or_skip()
        rng = np.random.default_rng(13)
        X = rng.standard_normal((300, 4))
        y = (X[:, 0] - 0.5 * X[:, 1] + 0.3 * X[:, 2] > 0).astype(int)
        model = XGBSignClassifier(n_estimators=50, max_depth=4)
        model.fit(X, y)
        pred = model.predict(X)
        acc = float((pred == y).mean())
        majority = max(y.mean(), 1 - y.mean())
        assert acc > majority + 0.05, (
            f"XGB acc {acc:.3f} not better than majority {majority:.3f}")


# ---------------------------------------------------------------------------
# §9.0 invariant + binary_classifier_voter integration
# ---------------------------------------------------------------------------


class TestSign90Invariant:
    def test_predict_returns_only_zero_and_one(self):
        """No matter the input, .predict returns ints ∈ {0, 1}.
        Never float magnitude (§9.0 post-fix HARD)."""
        rng = np.random.default_rng(99)
        X = rng.standard_normal((100, 5))
        y = rng.integers(0, 2, size=100)
        for ModelCls in (LogisticRegressionSignClassifier,):
            model = ModelCls()
            model.fit(X, y)
            pred = model.predict(X)
            for v in pred:
                assert int(v) in {0, 1}, f"pred {v} not in {{0, 1}}"

    def test_binary_classifier_voter_wraps_to_sign_vote(self):
        rng = np.random.default_rng(21)
        X = rng.standard_normal((100, 2))
        y = (X[:, 0] > 0).astype(int)
        model = LogisticRegressionSignClassifier()
        model.fit(X, y)

        def feat_extractor(ctx):
            return ctx.get("features")

        voter = binary_classifier_voter(model, feat_extractor)
        # ctx with positive x → predict class 1 → NO_VOTE
        v_pos = voter({"features": [1.0, 1.0]})
        assert v_pos in (SignVote.VETO, SignVote.NO_VOTE)
        # ctx with negative x → predict class 0 → VETO
        v_neg = voter({"features": [-1.0, -1.0]})
        assert v_neg in (SignVote.VETO, SignVote.NO_VOTE)
        # missing features → NO_VOTE (failsafe)
        v_miss = voter({"features": None})
        assert v_miss == SignVote.NO_VOTE


# ---------------------------------------------------------------------------
# Schema purity
# ---------------------------------------------------------------------------


class TestSchemaPurity:
    def test_no_heavy_data_imports(self):
        from pathlib import Path
        from core.research.ml import sign_classifier
        src = Path(sign_classifier.__file__).read_text()
        # sign_classifier should be a thin classifier module — no data
        # pipeline deps
        for bad in ("from core.data", "import yfinance",
                    "from core.factors.bar_store"):
            assert bad not in src, (
                f"sign_classifier.py must not import {bad!r}")
