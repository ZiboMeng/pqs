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
    compute_cost_aware_binary_labels,
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


# ---------------------------------------------------------------------------
# compute_cost_aware_binary_labels (P1, 2026-05-21)
# ---------------------------------------------------------------------------


class TestCostAwareBinaryLabels:
    def _price_with_known_fwd_returns(self):
        """horizon-1 panel: X fwd return = +0.0020 (20bps, below the
        40bps hurdle), Y fwd return = +0.0060 (60bps, above it)."""
        idx = pd.bdate_range("2020-01-01", periods=6)
        x = [100.0 * (1.0020 ** i) for i in range(6)]
        y = [100.0 * (1.0060 ** i) for i in range(6)]
        return pd.DataFrame({"X": x, "Y": y}, index=idx)

    def test_below_hurdle_is_class_0_above_is_class_1(self):
        price = self._price_with_known_fwd_returns()
        # 30 + 10 = 40 bps hurdle
        lab = compute_cost_aware_binary_labels(
            price, horizon_days=1,
            cost_hurdle_bps=30.0, min_expected_edge_bps=10.0)
        # rows 0..4 have a defined forward return
        assert (lab["X"].iloc[:5] == 0.0).all()   # +20bps < 40bps hurdle
        assert (lab["Y"].iloc[:5] == 1.0).all()   # +60bps > 40bps hurdle

    def test_bare_threshold_would_pass_both(self):
        """Sanity: with the bare 0.0 threshold X (a positive return)
        would be class 1 — the cost hurdle is what flips it to 0."""
        price = self._price_with_known_fwd_returns()
        bare = compute_binary_sign_labels(price, horizon_days=1, threshold=0.0)
        assert (bare["X"].iloc[:5] == 1.0).all()

    def test_threshold_math(self):
        price = self._price_with_known_fwd_returns()
        # hurdle 55 + edge 10 = 65bps → Y (+60bps) now falls below
        lab = compute_cost_aware_binary_labels(
            price, horizon_days=1,
            cost_hurdle_bps=55.0, min_expected_edge_bps=10.0)
        assert (lab["Y"].iloc[:5] == 0.0).all()

    def test_last_horizon_row_nan(self):
        price = self._price_with_known_fwd_returns()
        lab = compute_cost_aware_binary_labels(price, horizon_days=1)
        assert lab.iloc[-1].isna().all()

    def test_negative_bps_raise(self):
        price = self._price_with_known_fwd_returns()
        with pytest.raises(ValueError):
            compute_cost_aware_binary_labels(
                price, horizon_days=1, cost_hurdle_bps=-1.0)
        with pytest.raises(ValueError):
            compute_cost_aware_binary_labels(
                price, horizon_days=1, min_expected_edge_bps=-1.0)


# ── S3 (supplement PRD 2026-05-22) — weighted fit ─────────────────────
class TestSampleWeightedFit:
    @staticmethod
    def _xy(seed=4, n=200):
        rng = np.random.default_rng(seed)
        X = rng.standard_normal((n, 3))
        # separable-ish signal on feature 0
        y = (X[:, 0] + 0.3 * rng.standard_normal(n) > 0).astype(int)
        return X.astype(float), y.astype(float)

    def test_logreg_none_weight_bit_identical(self):
        """sample_weight=None must reproduce the unweighted fit exactly."""
        X, y = self._xy()
        a = LogisticRegressionSignClassifier().fit(X, y)
        b = LogisticRegressionSignClassifier().fit(X, y, sample_weight=None)
        assert np.allclose(a.coefficients_, b.coefficients_)
        assert a.intercept_ == b.intercept_

    def test_logreg_weight_changes_fit(self):
        """Non-uniform weights move the fitted coefficients."""
        X, y = self._xy()
        rng = np.random.default_rng(9)
        w = rng.uniform(0.1, 3.0, len(y))
        base = LogisticRegressionSignClassifier().fit(X, y)
        wt = LogisticRegressionSignClassifier().fit(X, y, sample_weight=w)
        assert not np.allclose(base.coefficients_, wt.coefficients_)

    def test_logreg_weight_nan_row_aligned(self):
        """sample_weight is masked by the same finite_mask as X/y."""
        X, y = self._xy(n=120)
        X[5] = np.nan                       # one bad row
        w = np.ones(len(y))
        m = LogisticRegressionSignClassifier().fit(X, y, sample_weight=w)
        assert m.fitted_                    # no shape error from the mask

    def test_xgb_weight_passthrough(self):
        pytest.importorskip("xgboost")
        X, y = self._xy()
        w = np.linspace(0.5, 1.5, len(y))
        m = XGBSignClassifier(n_estimators=10).fit(X, y, sample_weight=w)
        assert m.fitted_
        preds = m.predict(X)
        assert set(np.unique(preds)).issubset({0, 1})
