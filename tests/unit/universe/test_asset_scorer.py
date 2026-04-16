"""
Unit tests for AssetScorer.

全部使用合成特征 DataFrame，无网络调用。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.universe.asset_scorer import AssetScorer, _percentile_rank


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _make_features(
    n_bars: int = 50,
    ret_20d: float = 0.05,
    ret_60d: float = 0.10,
    ret_120d: float = 0.15,
    hv20: float = 0.20,
    volume_surge20: float = 1.2,
) -> pd.DataFrame:
    """生成单个 symbol 的合成特征 DataFrame（只需末行有意义值）。"""
    idx = pd.bdate_range("2023-01-03", periods=n_bars)
    df  = pd.DataFrame(
        {
            "ret_20d":        ret_20d,
            "ret_60d":        ret_60d,
            "ret_120d":       ret_120d,
            "hv20":           hv20,
            "volume_surge20": volume_surge20,
        },
        index=idx,
    )
    return df


def _make_feature_set(symbols_kwargs: dict) -> dict:
    """
    快速生成多 symbol 特征字典。
    symbols_kwargs = {"SPY": {...kwargs for _make_features...}, ...}
    """
    return {sym: _make_features(**kw) for sym, kw in symbols_kwargs.items()}


# ── _percentile_rank ──────────────────────────────────────────────────────────

class TestPercentileRank:
    def test_single_value_returns_half(self):
        s = pd.Series([1.0], index=["A"])
        r = _percentile_rank(s)
        assert r.iloc[0] == pytest.approx(0.5)

    def test_two_values_range(self):
        s = pd.Series([1.0, 2.0], index=["A", "B"])
        r = _percentile_rank(s)
        assert r["A"] == pytest.approx(0.0)
        assert r["B"] == pytest.approx(1.0)

    def test_equal_values_all_same(self):
        s = pd.Series([3.0] * 5)
        r = _percentile_rank(s)
        assert (r.sub(0.5).abs() < 1e-9).all()

    def test_output_in_0_1(self):
        rng = np.random.default_rng(0)
        s   = pd.Series(rng.standard_normal(20))
        r   = _percentile_rank(s)
        assert (r >= 0.0).all() and (r <= 1.0).all()


# ── AssetScorer.score ─────────────────────────────────────────────────────────

class TestScore:
    def test_returns_dataframe_with_expected_columns(self):
        scorer   = AssetScorer()
        features = _make_feature_set({"SPY": {}, "QQQ": {}, "IWM": {}})
        scores   = scorer.score(features)
        assert scores is not None
        for col in ["momentum", "stability", "liquidity", "composite"]:
            assert col in scores.columns

    def test_all_scores_in_0_1(self):
        scorer   = AssetScorer()
        features = _make_feature_set({"SPY": {}, "QQQ": {}, "IWM": {}})
        scores   = scorer.score(features)
        for col in ["momentum", "stability", "liquidity", "composite"]:
            assert (scores[col] >= 0.0).all() and (scores[col] <= 1.0).all(), (
                f"Column '{col}' has values outside [0, 1]"
            )

    def test_sorted_descending_by_composite(self):
        scorer   = AssetScorer()
        features = _make_feature_set({
            "HIGH": {"ret_20d": 0.15, "ret_60d": 0.25, "hv20": 0.10},
            "MID":  {"ret_20d": 0.05, "ret_60d": 0.08, "hv20": 0.20},
            "LOW":  {"ret_20d": -0.05, "ret_60d": -0.10, "hv20": 0.35},
        })
        scores = scorer.score(features)
        composites = scores["composite"].tolist()
        assert composites == sorted(composites, reverse=True), (
            "Score DataFrame should be sorted descending by composite"
        )

    def test_high_momentum_ranks_first(self):
        scorer   = AssetScorer(weights={"momentum": 1.0, "stability": 0.0, "liquidity": 0.0})
        features = _make_feature_set({
            "BULL": {"ret_20d": 0.20, "ret_60d": 0.40, "ret_120d": 0.60},
            "FLAT": {"ret_20d": 0.01, "ret_60d": 0.01, "ret_120d": 0.01},
            "BEAR": {"ret_20d": -0.10, "ret_60d": -0.20, "ret_120d": -0.30},
        })
        scores = scorer.score(features)
        assert scores.index[0] == "BULL"
        assert scores.index[-1] == "BEAR"

    def test_low_vol_ranks_first_on_stability(self):
        scorer   = AssetScorer(weights={"momentum": 0.0, "stability": 1.0, "liquidity": 0.0})
        features = _make_feature_set({
            "STABLE":   {"hv20": 0.10},
            "VOLATILE": {"hv20": 0.50},
        })
        scores = scorer.score(features)
        assert scores.index[0] == "STABLE"

    def test_fewer_than_min_symbols_returns_none(self):
        scorer   = AssetScorer(min_symbols=3)
        features = _make_feature_set({"SPY": {}, "QQQ": {}})  # 只有 2 个
        result   = scorer.score(features)
        assert result is None

    def test_empty_features_returns_none(self):
        scorer = AssetScorer()
        result = scorer.score({})
        assert result is None

    def test_missing_columns_graceful(self):
        """部分 symbol 缺少某些特征列，不应报错。"""
        scorer   = AssetScorer()
        feat_spy = _make_features()
        # QQQ 缺少 hv20 和 volume_surge20
        feat_qqq = feat_spy.drop(columns=["hv20", "volume_surge20"])
        scores   = scorer.score({"SPY": feat_spy, "QQQ": feat_qqq, "IWM": feat_spy.copy()})
        assert scores is not None
        assert "SPY" in scores.index
        assert "QQQ" in scores.index

    def test_weights_normalized(self):
        """权重不需要加总为 1，AssetScorer 内部会归一化。"""
        scorer = AssetScorer(weights={"momentum": 5.0, "stability": 3.0, "liquidity": 2.0})
        assert abs(sum(scorer.weights.values()) - 1.0) < 1e-9


# ── top_n ─────────────────────────────────────────────────────────────────────

class TestTopN:
    def _scores(self) -> pd.DataFrame:
        scorer   = AssetScorer()
        features = _make_feature_set({
            "A": {"ret_60d": 0.30},
            "B": {"ret_60d": 0.10},
            "C": {"ret_60d": -0.05},
            "D": {"ret_60d": 0.20},
        })
        return scorer.score(features)

    def test_top_n_returns_correct_count(self):
        scorer = AssetScorer()
        scores = self._scores()
        top2   = scorer.top_n(scores, n=2)
        assert len(top2) == 2

    def test_top_n_excludes_symbol(self):
        scorer = AssetScorer()
        scores = self._scores()
        top3   = scorer.top_n(scores, n=3, exclude=["A"])
        assert "A" not in top3

    def test_top_n_returns_list_of_strings(self):
        scorer = AssetScorer()
        scores = self._scores()
        result = scorer.top_n(scores, n=2)
        assert all(isinstance(s, str) for s in result)


# ── rank ──────────────────────────────────────────────────────────────────────

class TestRank:
    def test_rank_returns_series(self):
        scorer   = AssetScorer()
        features = _make_feature_set({"SPY": {}, "QQQ": {}, "IWM": {}})
        scores   = scorer.score(features)
        ranked   = scorer.rank(scores, by="momentum")
        assert len(ranked) == 3

    def test_rank_invalid_column_raises(self):
        scorer   = AssetScorer()
        features = _make_feature_set({"SPY": {}, "QQQ": {}})
        scores   = scorer.score(features)
        with pytest.raises(ValueError, match="not in scores"):
            scorer.rank(scores, by="nonexistent")
