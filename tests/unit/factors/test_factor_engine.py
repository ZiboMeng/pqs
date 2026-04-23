"""
Unit tests for FactorEngine.

全部使用合成数据。
设计思路：构造一个"强因子"（因子值 ∝ 未来收益），验证 IC 为正且显著；
          构造"随机因子"，验证 IC 均值接近零。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_engine import FactorEngine, FactorStats, _rolling_crosssection_corr


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _make_dates(n: int = 100, start: str = "2022-01-03") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _strong_factor(n_dates: int = 100, n_syms: int = 20, seed: int = 42) -> tuple:
    """
    构造强预测因子：factor_value ∝ next-day return + noise。
    IC 应当为正。
    """
    rng    = np.random.default_rng(seed)
    dates  = _make_dates(n_dates)
    syms   = [f"S{i:02d}" for i in range(n_syms)]

    # 真实收益矩阵
    ret = pd.DataFrame(rng.normal(0, 0.01, (n_dates, n_syms)), index=dates, columns=syms)

    # 因子 = 真实收益 + 少量噪声（强信号）
    noise  = rng.normal(0, 0.002, (n_dates, n_syms))
    factor = ret + noise

    # 价格矩阵（从因子构造前向收益用）
    price  = (1 + ret).cumprod()

    return factor, ret, price


def _random_factor(n_dates: int = 100, n_syms: int = 20, seed: int = 99) -> tuple:
    """
    构造纯噪声因子：IC 应接近零。
    """
    rng    = np.random.default_rng(seed)
    dates  = _make_dates(n_dates)
    syms   = [f"S{i:02d}" for i in range(n_syms)]

    ret    = pd.DataFrame(rng.normal(0, 0.01, (n_dates, n_syms)), index=dates, columns=syms)
    factor = pd.DataFrame(rng.normal(0, 1,    (n_dates, n_syms)), index=dates, columns=syms)
    price  = (1 + ret).cumprod()

    return factor, ret, price


# ── compute_ic ────────────────────────────────────────────────────────────────

class TestComputeIC:
    def test_returns_series(self):
        factor, ret, _ = _strong_factor()
        engine = FactorEngine()
        ic = engine.compute_ic(factor, ret)
        assert isinstance(ic, pd.Series)

    def test_strong_factor_positive_mean_ic(self):
        factor, ret, _ = _strong_factor()
        engine = FactorEngine()
        ic = engine.compute_ic(factor, ret)
        assert ic.dropna().mean() > 0.3, "强因子的 Pearson IC 均值应 > 0.3"

    def test_random_factor_ic_near_zero(self):
        factor, ret, _ = _random_factor()
        engine = FactorEngine()
        ic = engine.compute_ic(factor, ret)
        mean_ic = ic.dropna().mean()
        assert abs(mean_ic) < 0.1, f"随机因子 IC 均值应接近0，得到 {mean_ic:.4f}"

    def test_ic_values_in_minus1_to_1(self):
        factor, ret, _ = _strong_factor()
        engine = FactorEngine()
        ic = engine.compute_ic(factor, ret)
        valid = ic.dropna()
        assert (valid >= -1.0).all() and (valid <= 1.0).all()

    def test_few_symbols_produces_nan(self):
        """只有 2 个 symbol（< min_symbols=3）时该日 IC 应为 NaN。"""
        dates  = _make_dates(10)
        syms   = ["A", "B"]
        factor = pd.DataFrame({"A": 1.0, "B": -1.0}, index=dates)
        ret    = pd.DataFrame({"A": 0.01, "B": -0.01}, index=dates)
        engine = FactorEngine()
        ic = engine.compute_ic(factor, ret)
        assert ic.isna().all()


# ── compute_rank_ic ───────────────────────────────────────────────────────────

class TestComputeRankIC:
    def test_strong_factor_positive_rank_ic(self):
        factor, ret, _ = _strong_factor()
        engine = FactorEngine()
        ic = engine.compute_rank_ic(factor, ret)
        assert ic.dropna().mean() > 0.3

    def test_rank_ic_in_minus1_to_1(self):
        factor, ret, _ = _strong_factor()
        engine = FactorEngine()
        ic = engine.compute_rank_ic(factor, ret)
        valid = ic.dropna()
        assert (valid >= -1.0).all() and (valid <= 1.0).all()

    def test_rank_ic_more_robust_to_outliers(self):
        """Rank IC 对异常值更鲁棒：加入极端值后 Rank IC 应比 Pearson IC 更稳定。"""
        factor, ret, _ = _strong_factor(n_dates=200)
        # 注入几个极端异常值
        factor_noisy = factor.copy()
        factor_noisy.iloc[10, 0] = 1000.0
        factor_noisy.iloc[50, 1] = -1000.0

        engine = FactorEngine()
        pearson_std = engine.compute_ic(factor_noisy, ret).dropna().std()
        rank_std    = engine.compute_rank_ic(factor_noisy, ret).dropna().std()
        assert rank_std <= pearson_std + 0.05, (
            "Rank IC 标准差应 ≤ Pearson IC 标准差（对异常值更鲁棒）"
        )


# ── compute_ir ────────────────────────────────────────────────────────────────

class TestComputeIR:
    def test_positive_ic_gives_positive_ir(self):
        ic = pd.Series([0.1, 0.05, 0.08, 0.12, 0.06])
        ir = FactorEngine.compute_ir(ic)
        assert ir > 0

    def test_ir_formula(self):
        ic = pd.Series([0.1, 0.2, 0.3])
        expected = ic.mean() / ic.std(ddof=1)
        assert abs(FactorEngine.compute_ir(ic) - expected) < 1e-9

    def test_single_value_returns_nan(self):
        ic = pd.Series([0.1])
        assert np.isnan(FactorEngine.compute_ir(ic))

    def test_zero_std_returns_nan(self):
        ic = pd.Series([0.1, 0.1, 0.1])
        assert np.isnan(FactorEngine.compute_ir(ic))

    def test_strong_factor_ir_above_threshold(self):
        factor, ret, _ = _strong_factor(n_dates=200)
        engine = FactorEngine()
        ic = engine.compute_rank_ic(factor, ret)
        ir = engine.compute_ir(ic)
        assert ir > 0.5, f"强因子 IR 应 > 0.5，得到 {ir:.3f}"


# ── compute_factor_stats ──────────────────────────────────────────────────────

class TestComputeFactorStats:
    def test_returns_factor_stats_dataclass(self):
        ic = pd.Series([0.05, 0.10, 0.08, 0.12, -0.02, 0.07] * 10)
        s  = FactorEngine.compute_factor_stats(ic, "test_factor", horizon=5)
        assert isinstance(s, FactorStats)

    def test_stats_fields_populated(self):
        ic = pd.Series([0.05, 0.10, 0.08, 0.12, -0.02, 0.07] * 10)
        s  = FactorEngine.compute_factor_stats(ic, "mom", 5)
        assert not np.isnan(s.mean_ic)
        assert not np.isnan(s.ir)
        assert not np.isnan(s.t_stat)
        assert not np.isnan(s.p_value)
        assert 0.0 <= s.ic_positive_ratio <= 1.0

    def test_significant_factor_detected(self):
        # 构造非常一致的正 IC
        ic = pd.Series([0.15] * 50)
        s  = FactorEngine.compute_factor_stats(ic, "strong", 1)
        assert s.is_significant

    def test_random_factor_not_significant(self):
        rng = np.random.default_rng(0)
        ic  = pd.Series(rng.normal(0, 0.05, 50))
        s   = FactorEngine.compute_factor_stats(ic, "noise", 1)
        # p_value 应较大（不显著）
        assert s.p_value > 0.1 or abs(s.ir) < 0.3

    def test_insufficient_data_returns_nan_stats(self):
        ic = pd.Series([0.1])   # 只有 1 个观测
        s  = FactorEngine.compute_factor_stats(ic, "tiny", 1)
        assert np.isnan(s.ir)

    def test_str_representation(self):
        ic = pd.Series([0.08] * 30)
        s  = FactorEngine.compute_factor_stats(ic, "f", 5)
        text = str(s)
        assert "f" in text and "IC=" in text


# ── compute_ic_decay ─────────────────────────────────────────────────────────

class TestComputeICDecay:
    def test_returns_dataframe(self):
        factor, _, price = _strong_factor(n_dates=150)
        engine = FactorEngine()
        decay  = engine.compute_ic_decay(factor, price, max_lag=5)
        assert isinstance(decay, pd.DataFrame)
        assert len(decay) == 5

    def test_decay_index_is_lag(self):
        factor, _, price = _strong_factor(n_dates=150)
        engine = FactorEngine()
        decay  = engine.compute_ic_decay(factor, price, max_lag=5)
        assert list(decay.index) == [1, 2, 3, 4, 5]

    def test_strong_factor_decays_over_time(self):
        """预测能力应随 lag 增加而减弱（lag=1 的 |IC| ≥ lag=10 的 |IC|）。"""
        factor, _, price = _strong_factor(n_dates=300, n_syms=20)
        engine = FactorEngine()
        decay  = engine.compute_ic_decay(factor, price, max_lag=10)
        ic_lag1  = abs(decay.loc[1, "mean_ic"])
        ic_lag10 = abs(decay.loc[10, "mean_ic"])
        assert ic_lag1 >= ic_lag10 - 0.05, (
            f"强因子 lag=1 |IC|={ic_lag1:.4f} 应 ≥ lag=10 |IC|={ic_lag10:.4f}"
        )

    def test_columns_present(self):
        factor, _, price = _strong_factor(n_dates=150)
        engine = FactorEngine()
        decay  = engine.compute_ic_decay(factor, price, max_lag=3)
        for col in ["mean_ic", "ir", "n"]:
            assert col in decay.columns


# ── make_forward_returns ──────────────────────────────────────────────────────

class TestMakeForwardReturns:
    def test_shape_same_as_input(self):
        _, _, price = _strong_factor()
        fwd = FactorEngine.make_forward_returns(price, horizon=5)
        assert fwd.shape == price.shape

    def test_last_n_rows_are_nan(self):
        _, _, price = _strong_factor(n_dates=50)
        fwd = FactorEngine.make_forward_returns(price, horizon=5)
        # 最后 5 行应为 NaN（shift(-5) 移出范围）
        assert fwd.iloc[-5:].isna().all().all()

    # ── mode extension (PRD 20260423 R13, symmetric with R04) ─────────
    def test_cc_mode_default(self):
        _, _, price = _strong_factor(n_dates=50)
        default = FactorEngine.make_forward_returns(price, horizon=3)
        cc = FactorEngine.make_forward_returns(price, horizon=3, mode="cc")
        pd.testing.assert_frame_equal(default, cc)

    def test_oc_mode_requires_open_df(self):
        _, _, price = _strong_factor(n_dates=20)
        with pytest.raises(ValueError, match="requires open_df"):
            FactorEngine.make_forward_returns(price, horizon=1, mode="oc")

    def test_oo_mode_requires_open_df(self):
        _, _, price = _strong_factor(n_dates=20)
        with pytest.raises(ValueError, match="requires open_df"):
            FactorEngine.make_forward_returns(price, horizon=1, mode="oo")

    def test_invalid_mode_rejected(self):
        _, _, price = _strong_factor(n_dates=20)
        with pytest.raises(ValueError, match="mode must be one of"):
            FactorEngine.make_forward_returns(price, horizon=1, mode="xx")

    def test_oc_mode_value_matches_compute_forward_returns(self):
        """factor_engine.make_forward_returns and factor_generator.
        compute_forward_returns should produce identical values in each mode."""
        from core.factors.factor_generator import compute_forward_returns
        _, _, price = _strong_factor(n_dates=30)
        # Synthetic open: close shifted by -0.5
        open_df = price - 0.5
        fwd_engine = FactorEngine.make_forward_returns(
            price, horizon=2, mode="oc", open_df=open_df,
        )
        fwd_gen = compute_forward_returns(
            price, horizons=[2], mode="oc", open_df=open_df,
        )[2]
        pd.testing.assert_frame_equal(fwd_engine, fwd_gen)

    def test_oo_mode_value_matches_compute_forward_returns(self):
        from core.factors.factor_generator import compute_forward_returns
        _, _, price = _strong_factor(n_dates=30)
        open_df = price * 0.995
        fwd_engine = FactorEngine.make_forward_returns(
            price, horizon=3, mode="oo", open_df=open_df,
        )
        fwd_gen = compute_forward_returns(
            price, horizons=[3], mode="oo", open_df=open_df,
        )[3]
        pd.testing.assert_frame_equal(fwd_engine, fwd_gen)
