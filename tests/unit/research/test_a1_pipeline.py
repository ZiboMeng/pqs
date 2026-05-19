"""PRD-3 RA2 — A1 shallow-XGBoost + frozen-probe PCA stack (TDD).

build round. AC (PRD-3 ralph-loop RA2): fixed-seed → training
pipeline reproducible unit GREEN; leakage-correct sample weights
applied (assertion).

Grounded scope (honest, R4/R6/R7 pattern): the shallow-XGB +
early-stop + reproducible-seed mechanics ALREADY exist
(``core.ml.xgb_alpha.XGBAlphaModel``) and are DELEGATED to — but
that wrapper does NOT thread ``sample_weight``, so RA2 adds a
minimal, default-bit-identical ``sample_weight=None`` passthrough
to it (regression-guarded here) and a thin A1 pipeline in
``core.research.a1_pipeline`` that wires RA1 engineered features +
the PRD-1 canonical leakage weights + an optional train-only
PCA-reduced frozen-probe embedding stack.
"""
import numpy as np
import pandas as pd
import pytest

from core.ml.xgb_alpha import XGBAlphaModel
from core.research import a1_pipeline as a1
from core.research.label_leakage import average_uniqueness_weights


def _xy(n=240, p=6, seed=0):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.standard_normal((n, p)),
                     columns=[f"f{i}" for i in range(p)])
    # y has real signal in f0 so the tree learns something
    y = pd.Series(0.7 * X["f0"] + 0.2 * rng.standard_normal(n))
    return X, y


# ── XGBAlphaModel.sample_weight passthrough (additive, regression) ────
class TestXGBSampleWeightPassthrough:
    def test_default_none_is_bit_identical(self):
        X, y = _xy()
        a = XGBAlphaModel(max_depth=3, n_estimators=40).fit(X, y)
        b = XGBAlphaModel(max_depth=3, n_estimators=40).fit(
            X, y, sample_weight=None)
        np.testing.assert_array_equal(a.predict(X), b.predict(X))

    def test_weights_actually_change_the_fit(self):
        X, y = _xy()
        base = XGBAlphaModel(max_depth=3, n_estimators=40).fit(X, y)
        w = np.ones(len(X)); w[: len(X) // 2] = 5.0  # skew to first half
        wt = XGBAlphaModel(max_depth=3, n_estimators=40).fit(
            X, y, sample_weight=w)
        assert not np.allclose(base.predict(X), wt.predict(X)), (
            "sample_weight had no effect — not threaded into model.fit")

    def test_passthrough_in_early_stop_branch_too(self):
        X, y = _xy()
        Xv, yv = _xy(n=60, seed=9)
        w = np.linspace(0.5, 2.0, len(X))
        m = XGBAlphaModel(max_depth=3, n_estimators=80,
                          early_stopping_rounds=10)
        m.fit(X, y, Xv, yv, sample_weight=w)
        assert m.model is not None and m.predict(X).shape == (len(X),)


# ── frozen-probe PCA stack: train-only, bounded dims, deterministic ──
class TestFrozenProbePCA:
    def test_n_components_in_16_32(self):
        emb = np.random.default_rng(1).standard_normal((300, 64))
        for k in (16, 24, 32):
            out = a1.stack_frozen_probe_pca(emb, n_components=k)
            assert out.shape == (300, k)
        with pytest.raises(ValueError):
            a1.stack_frozen_probe_pca(emb, n_components=8)   # < 16
        with pytest.raises(ValueError):
            a1.stack_frozen_probe_pca(emb, n_components=40)  # > 32

    def test_deterministic(self):
        emb = np.random.default_rng(2).standard_normal((200, 50))
        o1 = a1.stack_frozen_probe_pca(emb, n_components=16)
        o2 = a1.stack_frozen_probe_pca(emb, n_components=16)
        np.testing.assert_array_equal(o1, o2)

    def test_pca_fit_is_train_only_no_leakage(self):
        # PCA basis must come from train rows ONLY; truncating the
        # post-train rows must not change any train-row projection.
        rng = np.random.default_rng(3)
        emb = rng.standard_normal((250, 40))
        mask = np.zeros(250, bool); mask[:150] = True   # first 150 = train
        full = a1.stack_frozen_probe_pca(emb, 16, train_mask=mask)
        # rebuild with the post-train rows zeroed → train projection same
        emb2 = emb.copy(); emb2[150:] = 0.0
        part = a1.stack_frozen_probe_pca(emb2, 16, train_mask=mask)
        np.testing.assert_allclose(full[:150], part[:150], atol=1e-10)


# ── A1 pipeline: reproducible + leakage-correct weights applied ──────
class TestA1Pipeline:
    def test_fixed_seed_reproducible(self):
        X, y = _xy(seed=4)
        sp = np.arange(len(X)); g = np.zeros(len(X), int)
        r1 = a1.train_a1(X, y, start_pos=sp, horizon=21, groups=g,
                         cfg=a1.A1Config(max_depth=3, random_state=123,
                                         n_estimators=60))
        r2 = a1.train_a1(X, y, start_pos=sp, horizon=21, groups=g,
                         cfg=a1.A1Config(max_depth=3, random_state=123,
                                         n_estimators=60))
        np.testing.assert_array_equal(
            r1.model.predict(X), r2.model.predict(X))

    def test_applies_canonical_leakage_correct_weights(self):
        X, y = _xy(seed=5)
        sp = np.array([0, 0, 3, 3, 7] + list(range(5, len(X))))
        g = np.zeros(len(X), int)
        r = a1.train_a1(X, y, start_pos=sp, horizon=21, groups=g,
                        cfg=a1.A1Config(max_depth=3, n_estimators=40))
        exp = average_uniqueness_weights(sp, 21, groups=g)
        # the pipeline's weights ARE the PRD-1 canonical helper output
        np.testing.assert_array_equal(r.sample_weight, exp)
        # and they were actually applied (vs an unweighted fit differs)
        base = XGBAlphaModel(max_depth=3, n_estimators=40).fit(X, y)
        assert not np.allclose(base.predict(X), r.model.predict(X))

    def test_shallow_depth_enforced_2_to_4(self):
        X, y = _xy(seed=6)
        sp = np.arange(len(X)); g = np.zeros(len(X), int)
        for d in (2, 3, 4):
            a1.train_a1(X, y, start_pos=sp, horizon=5, groups=g,
                        cfg=a1.A1Config(max_depth=d, n_estimators=30))
        for bad in (1, 5, 8):
            with pytest.raises(ValueError):
                a1.train_a1(X, y, start_pos=sp, horizon=5, groups=g,
                            cfg=a1.A1Config(max_depth=bad))

    def test_probe_embedding_stacked_as_extra_cols(self):
        X, y = _xy(seed=7)
        sp = np.arange(len(X)); g = np.zeros(len(X), int)
        emb = np.random.default_rng(8).standard_normal((len(X), 48))
        tm = np.zeros(len(X), bool); tm[: int(0.7 * len(X))] = True
        r = a1.train_a1(X, y, start_pos=sp, horizon=21, groups=g,
                        probe_embedding=emb, train_mask=tm,
                        cfg=a1.A1Config(max_depth=3, n_estimators=30,
                                        probe_pca_components=16))
        # 16 PCA probe cols appended to the 6 engineered cols
        assert sum(c.startswith("probe_pc") for c in r.feature_cols) == 16
        assert len(r.feature_cols) == 6 + 16
