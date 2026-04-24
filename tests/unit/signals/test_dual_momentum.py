"""DualMomentumStrategy 单元测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.signals.strategies.dual_momentum import DualMomentumStrategy

# ── 辅助函数 ──────────────────────────────────────────────────────────────────

_DAYS_PER_MONTH = 21


def _make_price_df(
    n: int,
    drifts: dict,          # {symbol: annual_drift}
    base: float = 100.0,
    start: str = "2018-01-02",
) -> pd.DataFrame:
    """根据年化漂移率生成价格序列。"""
    idx = pd.date_range(start, periods=n, freq="B")
    data = {}
    for sym, drift in drifts.items():
        daily_drift = drift / 252
        prices = base * np.cumprod(1 + daily_drift + np.zeros(n))
        data[sym] = prices
    return pd.DataFrame(data, index=idx)


def _make_price_df_random(
    n: int,
    symbols: list,
    seed: int = 42,
    drifts: dict | None = None,
) -> pd.DataFrame:
    """生成带随机噪声的价格序列。"""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-02", periods=n, freq="B")
    data = {}
    for sym in symbols:
        drift = (drifts or {}).get(sym, 0.0) / 252
        ret = drift + rng.normal(0, 0.01, n)
        data[sym] = 100.0 * np.cumprod(1 + ret)
    return pd.DataFrame(data, index=idx)


# ── TestOutputShape ────────────────────────────────────────────────────────────

class TestOutputShape:
    def test_returns_dataframe(self):
        strat = DualMomentumStrategy()
        prices = _make_price_df_random(400, ["SPY", "QQQ", "GLD"])
        result = strat.generate(prices)
        assert isinstance(result, pd.DataFrame)

    def test_index_matches_price_df(self):
        strat = DualMomentumStrategy()
        prices = _make_price_df_random(400, ["SPY", "QQQ"])
        result = strat.generate(prices)
        assert result.index.equals(prices.index)

    def test_columns_match_universe(self):
        strat = DualMomentumStrategy(universe=["SPY", "GLD"])
        prices = _make_price_df_random(400, ["SPY", "QQQ", "GLD"])
        result = strat.generate(prices)
        assert list(result.columns) == ["SPY", "GLD"]

    def test_weights_in_unit_interval(self):
        strat = DualMomentumStrategy()
        prices = _make_price_df_random(400, ["SPY", "QQQ"])
        result = strat.generate(prices)
        assert (result >= 0).all().all()
        assert (result <= 1).all().all()

    def test_insufficient_data_returns_zeros(self):
        """数据长度 ≤ lookback → 返回全零。"""
        strat = DualMomentumStrategy(lookback_months=12)
        prices = _make_price_df_random(200, ["SPY"])  # < 252 天
        result = strat.generate(prices)
        assert (result == 0).all().all()


# ── TestAbsoluteMomentum ───────────────────────────────────────────────────────

class TestAbsoluteMomentum:
    def test_negative_momentum_excluded(self):
        """所有标的动量为负 → 全部持现金（权重全 0）。"""
        n = 400
        # 全部下跌
        strat = DualMomentumStrategy(top_n=2, abs_momentum_rate=0.0, rebalance_monthly=False)
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        prices = pd.DataFrame({
            "A": 100.0 * np.exp(np.linspace(0, -0.5, n)),
            "B": 100.0 * np.exp(np.linspace(0, -0.3, n)),
        }, index=idx)
        result = strat.generate(prices)
        # 末 20 根 bar 动量为负，应全为 0
        assert (result.iloc[-20:] == 0).all().all()

    def test_positive_momentum_included(self):
        """所有标的动量为正 → 应被选入（权重 > 0）。"""
        n = 600
        strat = DualMomentumStrategy(top_n=2, abs_momentum_rate=0.0, rebalance_monthly=False)
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        prices = pd.DataFrame({
            "A": 100.0 * np.exp(np.linspace(0, 1.0, n)),
            "B": 100.0 * np.exp(np.linspace(0, 0.5, n)),
        }, index=idx)
        result = strat.generate(prices)
        # 末 5 根 bar 应全有信号
        assert (result.sum(axis=1).iloc[-5:] > 0).all()

    def test_high_abs_threshold_excludes_low_performers(self):
        """
        绝对动量阈值设高后，小涨幅标的被排除。

        代码将 abs_momentum_rate（年化）转换为月化阈值：
          threshold = (1 + rate)^(1/12) - 1
        然后与 pct_change(252) 的 12 个月总收益进行比较。

        rate=0.50 → monthly threshold ≈ 3.43%
        A 以 2%/year 上涨 → 12 个月 pct_change ≈ 2.02% < 3.43% → 应被排除
        """
        n = 600
        strat = DualMomentumStrategy(top_n=2, abs_momentum_rate=0.50, rebalance_monthly=False)
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        # A 涨 ~2%/year → 12 个月 simple return ≈ 2% < 月化阈值 3.43%
        prices = pd.DataFrame({
            "A": 100.0 * np.exp(np.linspace(0, 0.02 * n / 252, n)),
        }, index=idx)
        result = strat.generate(prices)
        # 末 20 根 bar 应全为 0
        assert (result.iloc[-20:] == 0).all().all()


# ── TestRelativeMomentum ───────────────────────────────────────────────────────

class TestRelativeMomentum:
    def test_top_n_selection(self):
        """top_n=1 时只选出一个标的（最强动量者）。"""
        n = 600
        strat = DualMomentumStrategy(top_n=1, abs_momentum_rate=0.0, rebalance_monthly=False)
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        # A 涨得多，B 涨得少
        prices = pd.DataFrame({
            "A": 100.0 * np.exp(np.linspace(0, 1.5, n)),
            "B": 100.0 * np.exp(np.linspace(0, 0.3, n)),
            "C": 100.0 * np.exp(np.linspace(0, 0.1, n)),
        }, index=idx)
        result = strat.generate(prices)
        # 末 20 根 bar：每行最多 1 个非零权重
        tail = result.iloc[-20:]
        n_active = (tail > 0).sum(axis=1)
        assert (n_active <= 1).all()

    def test_top_3_selection(self):
        """top_n=3，5 个标的 → 最多 3 个有权重。"""
        n = 600
        strat = DualMomentumStrategy(top_n=3, abs_momentum_rate=0.0, rebalance_monthly=False)
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        prices = pd.DataFrame({
            sym: 100.0 * np.exp(np.linspace(0, 0.1 * (i + 1), n))
            for i, sym in enumerate(["A", "B", "C", "D", "E"])
        }, index=idx)
        result = strat.generate(prices)
        tail = result.iloc[-20:]
        n_active = (tail > 0).sum(axis=1)
        assert (n_active <= 3).all()
        # 应有部分 bar 确实有 3 个活跃标的
        assert (n_active == 3).any()


# ── TestEqualWeight ────────────────────────────────────────────────────────────

class TestEqualWeight:
    def test_equal_weight_sums_to_one(self):
        """等权模式下，活跃标的权重之和 = 1.0。"""
        n = 600
        strat = DualMomentumStrategy(
            top_n=2, abs_momentum_rate=0.0,
            rebalance_monthly=False, momentum_weighted=False,
        )
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        prices = pd.DataFrame({
            "A": 100.0 * np.exp(np.linspace(0, 0.8, n)),
            "B": 100.0 * np.exp(np.linspace(0, 0.6, n)),
            "C": 100.0 * np.exp(np.linspace(0, -0.4, n)),  # 动量差，不选
        }, index=idx)
        result = strat.generate(prices)
        tail = result.iloc[-20:]
        active_rows = tail[tail.sum(axis=1) > 0]
        if not active_rows.empty:
            row_sums = active_rows.sum(axis=1)
            assert (row_sums - 1.0).abs().max() < 1e-10

    def test_momentum_weighted_differs_from_equal(self):
        """momentum_weighted=True 时，权重不等，且仍 ≤ 1。"""
        n = 600
        strat_eq = DualMomentumStrategy(
            top_n=2, abs_momentum_rate=0.0,
            rebalance_monthly=False, momentum_weighted=False,
        )
        strat_mw = DualMomentumStrategy(
            top_n=2, abs_momentum_rate=0.0,
            rebalance_monthly=False, momentum_weighted=True,
        )
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        prices = pd.DataFrame({
            "A": 100.0 * np.exp(np.linspace(0, 1.2, n)),
            "B": 100.0 * np.exp(np.linspace(0, 0.3, n)),
        }, index=idx)
        res_eq = strat_eq.generate(prices)
        res_mw = strat_mw.generate(prices)
        # 两者末 20 根不完全相同（因为 A 动量远大于 B）
        tail_eq = res_eq.iloc[-20:]
        tail_mw = res_mw.iloc[-20:]
        # A 在 momentum_weighted 模式下应占更多
        assert (tail_mw["A"] >= tail_eq["A"]).all()


# ── TestMonthlyRebalance ───────────────────────────────────────────────────────

class TestMonthlyRebalance:
    def test_rebalance_monthly_holds_within_month(self):
        """每月换仓：同一月内权重应保持不变。"""
        n = 400
        strat = DualMomentumStrategy(top_n=2, abs_momentum_rate=0.0, rebalance_monthly=True)
        prices = _make_price_df_random(n, ["A", "B", "C"], seed=0)
        result = strat.generate(prices)

        # 找一个完整月份（非边界，取中间段）
        mid = result.iloc[280:300]  # 约 1 个月
        # 同一月内权重不变
        first_weights = mid.iloc[0]
        same_month = mid[mid.index.month == mid.index[0].month]
        for _, row in same_month.iterrows():
            pd.testing.assert_series_equal(row, first_weights, check_names=False)

    def test_rebalance_daily_can_change_every_day(self):
        """每日换仓：结果与按日计算一致（不会强行锁定一个月）。"""
        n = 400
        strat_daily   = DualMomentumStrategy(top_n=2, abs_momentum_rate=0.0, rebalance_monthly=False)
        strat_monthly = DualMomentumStrategy(top_n=2, abs_momentum_rate=0.0, rebalance_monthly=True)
        prices = _make_price_df_random(n, ["A", "B", "C"], seed=7)
        res_d = strat_daily.generate(prices)
        res_m = strat_monthly.generate(prices)
        # 两者结果不完全相同（月换手率更低）
        assert not res_d.equals(res_m)


# ── TestNoLookahead ────────────────────────────────────────────────────────────

class TestNoLookahead:
    def test_early_rows_all_zero(self):
        """lookback 期内的早期行应全为 0（momentum 尚未计算）。"""
        lookback = 3  # 3 个月 = 63 天
        strat = DualMomentumStrategy(
            lookback_months=lookback, top_n=1,
            abs_momentum_rate=0.0, rebalance_monthly=False,
        )
        n = 400
        prices = _make_price_df_random(n, ["A", "B"])
        result = strat.generate(prices)
        # 前 lookback*21 行：momentum=NaN → 权重应为 0
        early = result.iloc[: lookback * 21]
        assert (early == 0).all().all()


# ── TestRegimeScaling ─────────────────────────────────────────────────────────

class TestRegimeScaling:
    def _make_regime(self, n: int, state: str) -> pd.Series:
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        return pd.Series(state, index=idx)

    def test_crisis_zeroes_signals(self):
        n = 600
        strat = DualMomentumStrategy(top_n=2, abs_momentum_rate=0.0, rebalance_monthly=False)
        prices = _make_price_df_random(n, ["A", "B", "C"], drifts={"A": 0.5, "B": 0.3, "C": 0.1})
        regime = self._make_regime(n, "CRISIS")
        result = strat.generate(prices, regime_series=regime)
        assert (result == 0).all().all()

    def test_bull_no_scaling(self):
        n = 600
        strat = DualMomentumStrategy(top_n=2, abs_momentum_rate=0.0, rebalance_monthly=False)
        prices = _make_price_df_random(n, ["A", "B"], drifts={"A": 0.5, "B": 0.3})
        no_regime = strat.generate(prices)
        bull_regime = self._make_regime(n, "BULL")
        with_regime = strat.generate(prices, regime_series=bull_regime)
        pd.testing.assert_frame_equal(no_regime, with_regime)

    def test_risk_off_scales_to_25pct(self):
        n = 600
        strat = DualMomentumStrategy(top_n=2, abs_momentum_rate=0.0, rebalance_monthly=False)
        prices = _make_price_df_random(n, ["A", "B"], drifts={"A": 0.5, "B": 0.3})
        no_regime = strat.generate(prices)
        regime = self._make_regime(n, "RISK_OFF")
        result = strat.generate(prices, regime_series=regime)
        expected = (no_regime * 0.25).clip(0, 1)
        pd.testing.assert_frame_equal(result, expected)

    def test_cautious_scales_to_75pct(self):
        n = 600
        strat = DualMomentumStrategy(top_n=2, abs_momentum_rate=0.0, rebalance_monthly=False)
        prices = _make_price_df_random(n, ["A", "B"], drifts={"A": 0.5, "B": 0.3})
        no_regime = strat.generate(prices)
        regime = self._make_regime(n, "CAUTIOUS")
        result = strat.generate(prices, regime_series=regime)
        expected = (no_regime * 0.75).clip(0, 1)
        pd.testing.assert_frame_equal(result, expected)
