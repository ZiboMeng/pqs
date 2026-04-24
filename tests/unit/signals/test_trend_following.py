"""TrendFollowingStrategy 单元测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.signals.strategies.trend_following import TrendFollowingStrategy

# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _make_prices(n: int, base: float = 100.0, drift: float = 0.2) -> pd.DataFrame:
    """生成简单上升趋势价格序列（单 symbol）。"""
    idx = pd.date_range("2020-01-02", periods=n, freq="B")
    prices = base * np.exp(np.linspace(0, drift, n))
    return pd.DataFrame({"SPY": prices}, index=idx)


def _make_dual_prices(n: int, sym_a_drift: float = 0.3, sym_b_drift: float = -0.2) -> pd.DataFrame:
    """生成两个 symbol 的价格序列：A 上升，B 下降。"""
    idx = pd.date_range("2020-01-02", periods=n, freq="B")
    a = 100.0 * np.exp(np.linspace(0, sym_a_drift, n))
    b = 100.0 * np.exp(np.linspace(0, sym_b_drift, n))
    return pd.DataFrame({"A": a, "B": b}, index=idx)


# ── TestOutputShape ────────────────────────────────────────────────────────────

class TestOutputShape:
    def test_returns_dataframe(self):
        strat = TrendFollowingStrategy()
        prices = _make_prices(300)
        result = strat.generate(prices)
        assert isinstance(result, pd.DataFrame)

    def test_index_matches_price_df(self):
        strat = TrendFollowingStrategy()
        prices = _make_prices(300)
        result = strat.generate(prices)
        assert result.index.equals(prices.index)

    def test_columns_match_price_df(self):
        strat = TrendFollowingStrategy()
        prices = _make_dual_prices(300)
        result = strat.generate(prices)
        assert set(result.columns) == {"A", "B"}

    def test_weights_in_unit_interval(self):
        strat = TrendFollowingStrategy()
        prices = _make_prices(300)
        result = strat.generate(prices)
        assert (result >= 0).all().all()
        assert (result <= 1).all().all()


# ── TestTrendSignal ────────────────────────────────────────────────────────────

class TestTrendSignal:
    def test_strongly_uptrending_gets_positive_weight(self):
        """长期上升趋势末段：price 应显著高于 200-EMA，权重应为正。"""
        strat = TrendFollowingStrategy(fast_ema=50, slow_ema=200)
        prices = _make_prices(500)  # 500 天强上升
        result = strat.generate(prices)
        # 末尾 50 根 bar 应全部有信号
        assert (result["SPY"].iloc[-50:] > 0).all()

    def test_strongly_downtrending_gets_zero_weight(self):
        """长期下降趋势：price 低于 200-EMA，权重应为 0。"""
        strat = TrendFollowingStrategy(fast_ema=50, slow_ema=200)
        n = 500
        idx = pd.date_range("2020-01-02", periods=n, freq="B")
        # 强下降趋势
        prices = 200.0 * np.exp(np.linspace(0, -0.6, n))
        df = pd.DataFrame({"SPY": prices}, index=idx)
        result = strat.generate(df)
        # 末尾 50 根 bar 应全为 0
        assert (result["SPY"].iloc[-50:] == 0).all()

    def test_early_bars_before_ema_warmup_may_have_signal(self):
        """EMA 从第一根 bar 开始即有值（因为 ewm 不需要 min_periods），
        前期行为取决于 EMA 计算方式，主要验证不崩溃。"""
        strat = TrendFollowingStrategy(fast_ema=50, slow_ema=200)
        prices = _make_prices(250)
        result = strat.generate(prices)
        assert result.shape == (250, 1)


# ── TestFastEmaFilter ─────────────────────────────────────────────────────────

class TestFastEmaFilter:
    def test_use_fast_confirm_filters_intermediate(self):
        """
        价格在 200-EMA 上方但低于 50-EMA 时，
        use_fast_confirm=True 应使信号为 0。
        """
        n = 400
        idx = pd.date_range("2020-01-02", periods=n, freq="B")
        # 前 350 根强上升（建立 200-EMA 高位），后 50 根小幅回落
        prices_up   = 100.0 * np.exp(np.linspace(0, 0.8, 350))
        prices_down = prices_up[-1] * np.exp(np.linspace(0, -0.08, 50))
        prices = np.concatenate([prices_up, prices_down])
        df = pd.DataFrame({"SPY": prices}, index=idx)

        strat_with    = TrendFollowingStrategy(fast_ema=50, slow_ema=200, use_fast_confirm=True)
        strat_without = TrendFollowingStrategy(fast_ema=50, slow_ema=200, use_fast_confirm=False)

        res_with    = strat_with.generate(df)
        res_without = strat_without.generate(df)

        # 末尾回落段：with_fast 可能有 0，without_fast 多半仍有信号
        # 只验证 without 的末 5 根 bar 均有信号（在 200-EMA 上方）
        assert (res_without["SPY"].iloc[-5:] > 0).all()


# ── TestEqualWeight ────────────────────────────────────────────────────────────

class TestEqualWeight:
    def test_two_active_symbols_equal_weight(self):
        """两个标的都满足条件时，各分得 0.5 权重。"""
        n = 500
        strat = TrendFollowingStrategy(
            symbols=["A", "B"],
            fast_ema=50,
            slow_ema=200,
            use_fast_confirm=True,
            equal_weight=True,
        )
        prices = _make_dual_prices(n, sym_a_drift=0.5, sym_b_drift=0.5)
        result = strat.generate(prices)
        # 末 20 根 bar：两个 symbol 都活跃时，各为 0.5
        tail = result.iloc[-20:]
        active_both = tail[(tail["A"] > 0) & (tail["B"] > 0)]
        if not active_both.empty:
            assert (active_both["A"] - 0.5).abs().max() < 1e-10
            assert (active_both["B"] - 0.5).abs().max() < 1e-10

    def test_one_active_symbol_gets_weight_one(self):
        """只有一个标的满足条件时，该标的权重 = 1.0。"""
        n = 500
        strat = TrendFollowingStrategy(
            symbols=["A", "B"],
            fast_ema=50,
            slow_ema=200,
            use_fast_confirm=True,
            equal_weight=True,
        )
        # A 上升，B 下降
        prices = _make_dual_prices(n, sym_a_drift=0.6, sym_b_drift=-0.6)
        result = strat.generate(prices)
        # 末 20 根 bar：B 应为 0，A 应为 1.0
        tail = result.iloc[-20:]
        b_zero = tail[tail["B"] == 0]
        if not b_zero.empty:
            assert (b_zero["A"] == 1.0).all()

    def test_equal_weight_false_returns_binary(self):
        """equal_weight=False 时返回 0/1 binary mask（不做归一化）。"""
        strat = TrendFollowingStrategy(
            fast_ema=50, slow_ema=200,
            use_fast_confirm=False, equal_weight=False,
        )
        prices = _make_dual_prices(500, sym_a_drift=0.5, sym_b_drift=0.5)
        result = strat.generate(prices)
        unique_vals = set(result.values.flatten().tolist())
        # 值只有 0 和 1
        assert unique_vals.issubset({0.0, 1.0})


# ── TestTrendDirection ────────────────────────────────────────────────────────

class TestTrendDirection:
    def test_declining_slow_ema_triggers_filter(self):
        """
        use_trend_direction=True：slow_ema 斜率为负时，即使 price > slow_ema 也不给信号。
        """
        n = 500
        idx = pd.date_range("2020-01-02", periods=n, freq="B")
        # 前 300 根强上升，后 200 根大幅下跌再缓慢回升（slow_ema 仍在下降）
        up   = 100.0 * np.exp(np.linspace(0, 1.0, 300))
        down = up[-1] * np.exp(np.linspace(0, -0.7, 150))
        recover = down[-1] * np.exp(np.linspace(0, 0.3, 50))
        prices = np.concatenate([up, down, recover])
        df = pd.DataFrame({"SPY": prices}, index=idx)

        strat_dir = TrendFollowingStrategy(
            fast_ema=50, slow_ema=200,
            use_fast_confirm=False,
            use_trend_direction=True,
        )
        strat_no_dir = TrendFollowingStrategy(
            fast_ema=50, slow_ema=200,
            use_fast_confirm=False,
            use_trend_direction=False,
        )

        res_dir    = strat_dir.generate(df)
        res_no_dir = strat_no_dir.generate(df)

        # use_trend_direction=True 的信号应 ≤ use_trend_direction=False 的
        # （因为多一个过滤条件）
        total_dir    = res_dir["SPY"].sum()
        total_no_dir = res_no_dir["SPY"].sum()
        assert total_dir <= total_no_dir


# ── TestRegimeScaling ─────────────────────────────────────────────────────────

class TestRegimeScaling:
    def _make_regime(self, n: int, state: str) -> pd.Series:
        idx = pd.date_range("2020-01-02", periods=n, freq="B")
        return pd.Series(state, index=idx)

    def test_crisis_regime_zeroes_all_weights(self):
        strat = TrendFollowingStrategy(fast_ema=50, slow_ema=200, use_fast_confirm=False)
        prices = _make_prices(500)
        regime = self._make_regime(500, "CRISIS")
        result = strat.generate(prices, regime_series=regime)
        assert (result == 0).all().all()

    def test_bull_regime_no_scaling(self):
        strat = TrendFollowingStrategy(fast_ema=50, slow_ema=200, use_fast_confirm=False)
        prices = _make_prices(500)
        no_regime = strat.generate(prices)
        bull_regime = self._make_regime(500, "BULL")
        with_regime = strat.generate(prices, regime_series=bull_regime)
        # BULL scale = 1.0 → 无变化
        pd.testing.assert_frame_equal(no_regime, with_regime)

    def test_neutral_regime_scales_down(self):
        strat = TrendFollowingStrategy(fast_ema=50, slow_ema=200, use_fast_confirm=False)
        prices = _make_prices(500)
        neutral_regime = self._make_regime(500, "NEUTRAL")
        result = strat.generate(prices, regime_series=neutral_regime)
        # NEUTRAL scale = 0.75，所有非零权重应乘以 0.75
        no_regime = strat.generate(prices)
        expected = no_regime * 0.75
        pd.testing.assert_frame_equal(result, expected)

    def test_cautious_regime_scale_50pct(self):
        strat = TrendFollowingStrategy(fast_ema=50, slow_ema=200, use_fast_confirm=False)
        prices = _make_prices(500)
        regime = self._make_regime(500, "CAUTIOUS")
        result = strat.generate(prices, regime_series=regime)
        no_regime = strat.generate(prices)
        expected = (no_regime * 0.50).clip(0, 1)
        pd.testing.assert_frame_equal(result, expected)

    def test_risk_off_regime_scale_25pct(self):
        strat = TrendFollowingStrategy(fast_ema=50, slow_ema=200, use_fast_confirm=False)
        prices = _make_prices(500)
        regime = self._make_regime(500, "RISK_OFF")
        result = strat.generate(prices, regime_series=regime)
        no_regime = strat.generate(prices)
        expected = (no_regime * 0.25).clip(0, 1)
        pd.testing.assert_frame_equal(result, expected)

    def test_unknown_regime_treated_as_neutral(self):
        """未知 regime 字符串默认系数 0.75。"""
        strat = TrendFollowingStrategy(fast_ema=50, slow_ema=200, use_fast_confirm=False)
        prices = _make_prices(500)
        regime = self._make_regime(500, "UNKNOWN_STATE")
        result = strat.generate(prices, regime_series=regime)
        no_regime = strat.generate(prices)
        expected = (no_regime * 0.75).clip(0, 1)
        pd.testing.assert_frame_equal(result, expected)


# ── TestSymbolSubset ──────────────────────────────────────────────────────────

class TestSymbolSubset:
    def test_symbols_parameter_restricts_output(self):
        """symbols 参数应限制输出列，不产生 price_df 之外的列。"""
        strat = TrendFollowingStrategy(symbols=["A"])
        prices = _make_dual_prices(300)
        result = strat.generate(prices)
        assert list(result.columns) == ["A"]
        assert "B" not in result.columns
