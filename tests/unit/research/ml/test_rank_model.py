"""PRD #4 P4.1 — rank model + metrics TDD."""
import numpy as np
import pandas as pd
import pytest

from core.research.ml.rank_model import (
    LinearBaselineRankModel,
    _cross_sectional_rank,
    _cross_sectional_standardize,
    rank_ic,
    rank_ir,
)


# ── fixtures ─────────────────────────────────────────────────────────
@pytest.fixture
def synth_panel():
    """Synthetic 60-bar × 8-symbol panel with KNOWN cross-sectional
    signal: feature[i] = label[i] + noise, so a fitted linear
    model should achieve positive rank-IC."""
    rng = np.random.default_rng(7)
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    syms = [f"S{i:02d}" for i in range(8)]
    label = pd.DataFrame(
        rng.normal(0, 0.02, size=(60, 8)),
        index=dates, columns=syms)
    feat_a = label + rng.normal(0, 0.005, size=(60, 8))
    feat_b = pd.DataFrame(
        rng.normal(0, 0.01, size=(60, 8)),
        index=dates, columns=syms)  # pure noise
    return {"feat_a": feat_a, "feat_b": feat_b}, label


# ── standardize / rank helpers ───────────────────────────────────────
class TestHelpers:
    def test_cross_sectional_standardize_zero_mean(self, synth_panel):
        feats, _ = synth_panel
        std = _cross_sectional_standardize(feats["feat_a"])
        # row mean should be ≈ 0
        row_means = std.mean(axis=1).dropna()
        assert (row_means.abs() < 1e-9).all()

    def test_cross_sectional_rank_in_unit_interval(self, synth_panel):
        feats, _ = synth_panel
        r = _cross_sectional_rank(feats["feat_a"])
        flat = r.values.flatten()
        flat = flat[~np.isnan(flat)]
        assert flat.min() > 0
        assert flat.max() <= 1


# ── metrics ──────────────────────────────────────────────────────────
class TestRankIC:
    def test_perfect_match_yields_high_ic(self):
        # If pred_rank == label_rank, rank-IC should be ~1.0
        rng = np.random.default_rng(11)
        dates = pd.date_range("2020-01-01", periods=20, freq="B")
        syms = [f"S{i:02d}" for i in range(5)]
        label = pd.DataFrame(
            rng.normal(0, 0.02, size=(20, 5)),
            index=dates, columns=syms)
        # pred_rank = label_rank
        pred = _cross_sectional_rank(label)
        ic = rank_ic(pred, label)
        assert ic > 0.95, f"expected ≈ 1.0, got {ic}"

    def test_antimatch_yields_negative_ic(self):
        rng = np.random.default_rng(13)
        dates = pd.date_range("2020-01-01", periods=20, freq="B")
        syms = [f"S{i:02d}" for i in range(5)]
        label = pd.DataFrame(
            rng.normal(0, 0.02, size=(20, 5)),
            index=dates, columns=syms)
        # pred is INVERSE rank
        pred = 1 - _cross_sectional_rank(label)
        ic = rank_ic(pred, label)
        assert ic < -0.95

    def test_noise_yields_near_zero_ic(self):
        rng = np.random.default_rng(17)
        dates = pd.date_range("2020-01-01", periods=100, freq="B")
        syms = [f"S{i:02d}" for i in range(8)]
        label = pd.DataFrame(
            rng.normal(0, 0.02, size=(100, 8)),
            index=dates, columns=syms)
        pred = pd.DataFrame(
            rng.normal(0, 0.02, size=(100, 8)),
            index=dates, columns=syms)
        pred_rank = _cross_sectional_rank(pred)
        ic = rank_ic(pred_rank, label)
        assert abs(ic) < 0.1


# ── LinearBaselineRankModel ──────────────────────────────────────────
class TestLinearBaselineRankModel:
    def test_unfitted_predict_raises(self):
        m = LinearBaselineRankModel()
        with pytest.raises(RuntimeError, match=r"not fitted"):
            m.predict_rank({"feat_a": pd.DataFrame()})

    def test_fit_with_synth_signal_yields_positive_rank_ic(self, synth_panel):
        feats, label = synth_panel
        m = LinearBaselineRankModel()
        m.fit(feats, label)
        assert m.fitted
        assert m.coefficients is not None
        assert len(m.coefficients) == 2
        # feat_a is informative, feat_b is noise — feat_a coef should be
        # larger in abs value
        pred = m.predict_rank(feats)
        ic = rank_ic(pred, label)
        assert ic > 0.10, (
            f"expected positive rank-IC > 0.10 on synthetic data "
            f"(feat_a strongly correlated with label), got {ic}")

    def test_pure_noise_fit_yields_near_zero_ic(self):
        rng = np.random.default_rng(23)
        dates = pd.date_range("2020-01-01", periods=80, freq="B")
        syms = [f"S{i:02d}" for i in range(6)]
        label = pd.DataFrame(
            rng.normal(0, 0.02, size=(80, 6)),
            index=dates, columns=syms)
        noise_feat = pd.DataFrame(
            rng.normal(0, 0.01, size=(80, 6)),
            index=dates, columns=syms)
        m = LinearBaselineRankModel()
        m.fit({"noise": noise_feat}, label)
        # fit will succeed, but rank-IC should be near zero
        pred = m.predict_rank({"noise": noise_feat})
        ic = rank_ic(pred, label)
        assert abs(ic) < 0.30, (
            f"pure-noise feature should yield near-zero rank-IC, "
            f"got {ic}")


# ── §9.0 invariant: output is RANK not magnitude ─────────────────────
class TestSign90Invariant:
    def test_predict_output_in_unit_interval(self, synth_panel):
        feats, label = synth_panel
        m = LinearBaselineRankModel()
        m.fit(feats, label)
        pred = m.predict_rank(feats)
        flat = pred.values.flatten()
        flat = flat[~np.isnan(flat)]
        assert flat.min() > 0, "rank should be > 0"
        assert flat.max() <= 1.0, "rank should be ≤ 1"


# ── schema purity (no panel imports at module level) ────────────────
class TestSchemaPurity:
    def test_rank_model_no_yfinance_or_bar_store(self):
        import ast
        import inspect
        import core.research.ml.rank_model as mod
        tree = ast.parse(inspect.getsource(mod))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                for n in node.names:
                    imported.add(n.name)
        for forbidden in ("yfinance", "core.data.bar_store"):
            for name in imported:
                assert not name.startswith(forbidden), (
                    f"rank_model imports {name}; should be pure "
                    f"compute layer (sealed-2026 守 via training "
                    f"discipline, not module-level import)")
