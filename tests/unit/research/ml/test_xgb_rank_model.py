"""PRD #4 P4.1 sub-step 2 — XGBRanker concrete rank model TDD."""
import numpy as np
import pandas as pd
import pytest

from core.research.ml.rank_model import rank_ic
from core.research.ml.xgb_rank_model import XGBRankerRankModel


@pytest.fixture
def synth_panel():
    """Same synthetic generator as LinearBaseline tests, slightly
    larger panel for XGB to have enough samples per query group."""
    rng = np.random.default_rng(11)
    dates = pd.date_range("2020-01-01", periods=80, freq="B")
    syms = [f"S{i:02d}" for i in range(10)]
    label = pd.DataFrame(
        rng.normal(0, 0.02, size=(80, 10)),
        index=dates, columns=syms)
    # feat_a informative (correlated with label), feat_b noise
    feat_a = label + rng.normal(0, 0.005, size=(80, 10))
    feat_b = pd.DataFrame(
        rng.normal(0, 0.01, size=(80, 10)),
        index=dates, columns=syms)
    return {"feat_a": feat_a, "feat_b": feat_b}, label


# ── construction + fitted flag ───────────────────────────────────────
class TestConstruction:
    def test_default_init(self):
        m = XGBRankerRankModel()
        assert not m.fitted
        assert m.n_estimators == 100
        assert m.max_depth == 4

    def test_custom_init(self):
        m = XGBRankerRankModel(
            n_estimators=50, max_depth=3, learning_rate=0.05)
        assert m.n_estimators == 50
        assert m.max_depth == 3


# ── unfitted predict raises ──────────────────────────────────────────
class TestUnfittedSafety:
    def test_predict_before_fit_raises(self):
        m = XGBRankerRankModel()
        with pytest.raises(RuntimeError, match=r"not fitted"):
            m.predict_rank({"feat_a": pd.DataFrame()})


# ── fit on synth signal yields positive rank-IC ──────────────────────
class TestFitSynth:
    def test_fit_succeeds(self, synth_panel):
        feats, label = synth_panel
        m = XGBRankerRankModel(n_estimators=20, max_depth=3)
        m.fit(feats, label)
        assert m.fitted
        assert m.feature_columns == ("feat_a", "feat_b")

    def test_synth_yields_positive_rank_ic(self, synth_panel):
        feats, label = synth_panel
        m = XGBRankerRankModel(n_estimators=30, max_depth=3,
                                random_state=42)
        m.fit(feats, label)
        pred = m.predict_rank(feats)
        ic = rank_ic(pred, label)
        # XGBRanker should be ≥ LinearBaseline on the same panel
        # (Pareto-floor: XGB ≥ Linear or comparable); both should
        # be > 0.10 on this strongly-correlated synthetic data
        assert ic > 0.10, (
            f"expected positive rank-IC > 0.10 on synth panel; "
            f"got {ic}")


# ── pure noise yields near-zero rank-IC ─────────────────────────────
class TestNoiseFit:
    def test_pure_noise_rank_ic_near_zero_OUT_OF_SAMPLE(self):
        """R3 self-audit fix: XGB with 20 trees + depth 3 on a small
        80-bar × 8-symbol noise panel CAN memorize in-sample
        (initial test attempt showed |IC|=0.45 in-sample — that's
        overfitting, not signal).

        Honest test: train/test split BEFORE evaluation. Train on
        first 60 bars, predict on last 20 (held-out). On pure
        noise the held-out IC should be near zero.

        Per `feedback_temporal_split_discipline` + Track-A R1
        leakage discipline: in-sample evaluation on small panel is
        misleading; walk-forward / held-out is the discipline.
        """
        rng = np.random.default_rng(19)
        dates = pd.date_range("2020-01-01", periods=100, freq="B")
        syms = [f"S{i:02d}" for i in range(8)]
        label = pd.DataFrame(
            rng.normal(0, 0.02, size=(100, 8)),
            index=dates, columns=syms)
        noise_feat = pd.DataFrame(
            rng.normal(0, 0.01, size=(100, 8)),
            index=dates, columns=syms)
        # strict-chronological train/test split (sealed-equivalent)
        train_label = label.iloc[:70]
        train_feat = noise_feat.iloc[:70]
        test_label = label.iloc[70:]
        test_feat = noise_feat.iloc[70:]
        m = XGBRankerRankModel(n_estimators=20, max_depth=3,
                                random_state=42)
        m.fit({"noise": train_feat}, train_label)
        pred = m.predict_rank({"noise": test_feat})
        # restrict to test window
        pred_test = pred.reindex(test_label.index)
        ic = rank_ic(pred_test, test_label)
        # on held-out pure noise, IC should be near zero
        assert abs(ic) < 0.30, (
            f"pure-noise held-out rank-IC should be near zero; "
            f"got {ic} — possible feature leak or bug")


# ── §9.0 invariant: output is RANK ∈ [0, 1], not magnitude ──────────
class TestSign90Invariant:
    def test_predict_output_in_unit_interval(self, synth_panel):
        feats, label = synth_panel
        m = XGBRankerRankModel(n_estimators=20, max_depth=3)
        m.fit(feats, label)
        pred = m.predict_rank(feats)
        flat = pred.values.flatten()
        flat = flat[~np.isnan(flat)]
        assert flat.min() > 0
        assert flat.max() <= 1.0


# ── compare to LinearBaseline (XGB ≥ Linear Pareto floor) ────────────
class TestXgbVsLinear:
    def test_xgb_at_least_competitive_with_linear(self, synth_panel):
        from core.research.ml.rank_model import LinearBaselineRankModel
        feats, label = synth_panel
        # Linear
        linear = LinearBaselineRankModel()
        linear.fit(feats, label)
        ic_lin = rank_ic(linear.predict_rank(feats), label)
        # XGB
        xgb_m = XGBRankerRankModel(n_estimators=30, max_depth=3,
                                    random_state=42)
        xgb_m.fit(feats, label)
        ic_xgb = rank_ic(xgb_m.predict_rank(feats), label)
        # XGB should be ≥ linear baseline OR within reasonable
        # margin (XGB can overfit small N; loose check)
        # Hard claim: both positive
        assert ic_lin > 0
        assert ic_xgb > 0
        # XGB should be at least 0.7× linear's IC (informative)
        assert ic_xgb >= ic_lin * 0.7, (
            f"XGB IC {ic_xgb} should be at least 0.7× linear IC "
            f"{ic_lin}")


# ── feature columns preserved post-fit ───────────────────────────────
class TestFeatureColumns:
    def test_feature_columns_set_after_fit(self, synth_panel):
        feats, label = synth_panel
        m = XGBRankerRankModel(n_estimators=20)
        m.fit(feats, label)
        assert set(m.feature_columns) == {"feat_a", "feat_b"}


# ── insufficient data raises ─────────────────────────────────────────
class TestInsufficientData:
    def test_single_symbol_per_bar_raises(self):
        # Each bar has only 1 valid symbol → no pairwise grouping
        rng = np.random.default_rng(23)
        dates = pd.date_range("2020-01-01", periods=20, freq="B")
        # 5 columns but most NaN — leave only 1 valid per row
        label = pd.DataFrame(np.nan, index=dates,
                              columns=["A", "B", "C", "D", "E"])
        label["A"] = rng.normal(0, 0.02, size=20)
        feat = pd.DataFrame(np.nan, index=dates,
                             columns=["A", "B", "C", "D", "E"])
        feat["A"] = rng.normal(0, 0.01, size=20)
        m = XGBRankerRankModel(n_estimators=10)
        with pytest.raises(ValueError,
                           match=r"insufficient training data"):
            m.fit({"feat": feat}, label)


# ── rank:ndcg objective at cross-sectional scale (P2, 2026-05-21) ─────
class TestNdcgObjectiveLargeGroups:
    """XGBoost's exponential NDCG gain caps relevance at 31; a
    cross-sectional universe has 79+ names per query group → within-
    group integer ranks exceed 31. XGBRankerRankModel must set
    ndcg_exp_gain=False for objective='rank:ndcg' so any group size
    fits. Pins the P2 rank:ndcg-smoke fix."""

    def _big_panel(self, k=79, n=120, seed=3):
        rng = np.random.default_rng(seed)
        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        syms = [f"S{i:02d}" for i in range(k)]
        label = pd.DataFrame(rng.normal(0, 0.02, (n, k)),
                             index=dates, columns=syms)
        feat = label + rng.normal(0, 0.006, (n, k))
        return {"f": pd.DataFrame(feat, index=dates, columns=syms)}, label

    def test_ndcg_fits_on_79_symbol_groups(self):
        feats, label = self._big_panel(k=79)
        m = XGBRankerRankModel(objective="rank:ndcg",
                               n_estimators=20, max_depth=3)
        m.fit(feats, label)          # must NOT raise (relevance > 31)
        assert m.fitted
        pred = m.predict_rank(feats)
        vals = pred.to_numpy()
        finite = vals[np.isfinite(vals)]
        assert ((finite >= 0.0) & (finite <= 1.0)).all()

    def test_pairwise_still_fits(self):
        feats, label = self._big_panel(k=79)
        m = XGBRankerRankModel(objective="rank:pairwise",
                               n_estimators=20, max_depth=3)
        m.fit(feats, label)
        assert m.fitted
