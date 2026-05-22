"""P2 (PRD 20260521) — LGBMRankerRankModel parity-path TDD."""
import numpy as np
import pandas as pd
import pytest

from core.research.ml.lgbm_rank_model import LGBMRankerRankModel
from core.research.ml.rank_model import rank_ic


@pytest.fixture
def synth_panel():
    rng = np.random.default_rng(11)
    dates = pd.date_range("2020-01-01", periods=80, freq="B")
    syms = [f"S{i:02d}" for i in range(10)]
    label = pd.DataFrame(rng.normal(0, 0.02, (80, 10)),
                         index=dates, columns=syms)
    feat_a = label + rng.normal(0, 0.005, (80, 10))
    feat_b = pd.DataFrame(rng.normal(0, 0.01, (80, 10)),
                          index=dates, columns=syms)
    return {"feat_a": feat_a, "feat_b": feat_b}, label


class TestConstruction:
    def test_default_init(self):
        m = LGBMRankerRankModel()
        assert not m.fitted
        assert m.objective == "lambdarank"
        assert m.n_estimators == 100

    def test_predict_before_fit_raises(self):
        m = LGBMRankerRankModel()
        with pytest.raises(RuntimeError, match="not fitted"):
            m.predict_rank({"f": pd.DataFrame()})


class TestFitPredict:
    def test_fit_sets_fitted_flag(self, synth_panel):
        feats, label = synth_panel
        m = LGBMRankerRankModel(n_estimators=20, max_depth=3)
        m.fit(feats, label)
        assert m.fitted
        assert set(m.feature_columns) == {"feat_a", "feat_b"}

    def test_predict_rank_in_unit_interval(self, synth_panel):
        feats, label = synth_panel
        m = LGBMRankerRankModel(n_estimators=20, max_depth=3)
        m.fit(feats, label)
        pred = m.predict_rank(feats)
        vals = pred.to_numpy()
        finite = vals[np.isfinite(vals)]
        assert ((finite >= 0.0) & (finite <= 1.0)).all()

    def test_deterministic(self, synth_panel):
        feats, label = synth_panel
        a = LGBMRankerRankModel(n_estimators=20, max_depth=3)
        a.fit(feats, label)
        b = LGBMRankerRankModel(n_estimators=20, max_depth=3)
        b.fit(feats, label)
        pd.testing.assert_frame_equal(a.predict_rank(feats),
                                      b.predict_rank(feats))

    def test_insufficient_data_raises(self):
        idx = pd.date_range("2020-01-01", periods=5, freq="B")
        # 1 symbol → no group of ≥ 2 → raise
        feats = {"f": pd.DataFrame({"S0": [1.0] * 5}, index=idx)}
        label = pd.DataFrame({"S0": [0.01] * 5}, index=idx)
        with pytest.raises(ValueError, match="insufficient training data"):
            LGBMRankerRankModel().fit(feats, label)


class TestLargeGroupParity:
    """A 79-name cross-section → relevance grades 0..78. The linear
    label_gain must accept it (LightGBM's default exponential gain caps
    relevance) — the LightGBM analog of the XGBoost ndcg_exp_gain fix."""

    def test_lambdarank_fits_79_symbol_groups(self):
        rng = np.random.default_rng(3)
        n, k = 120, 79
        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        syms = [f"S{i:02d}" for i in range(k)]
        label = pd.DataFrame(rng.normal(0, 0.02, (n, k)),
                             index=dates, columns=syms)
        feat = label + rng.normal(0, 0.006, (n, k))
        m = LGBMRankerRankModel(n_estimators=20, max_depth=3)
        m.fit({"f": pd.DataFrame(feat, index=dates, columns=syms)}, label)
        assert m.fitted
        pred = m.predict_rank(
            {"f": pd.DataFrame(feat, index=dates, columns=syms)})
        finite = pred.to_numpy()[np.isfinite(pred.to_numpy())]
        assert ((finite >= 0.0) & (finite <= 1.0)).all()
