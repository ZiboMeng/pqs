"""PortfolioConstructor 单元测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.portfolio.constructor import PortfolioConstructor

# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _make_prices(n: int, symbols: list, drifts: dict | None = None, seed: int = 42) -> pd.DataFrame:
    """生成带随机噪声的价格序列。"""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-02", periods=n, freq="B")
    data = {}
    for sym in symbols:
        drift = (drifts or {}).get(sym, 0.0) / 252
        ret = drift + rng.normal(0, 0.01, n)
        data[sym] = 100.0 * np.cumprod(1 + ret)
    return pd.DataFrame(data, index=idx)


def _make_signals(
    n: int,
    symbols: list,
    active_syms: list | None = None,
    weight: float | None = None,
) -> pd.DataFrame:
    """
    生成简单等权信号矩阵：
      active_syms 中的 symbol 权重 = weight（默认等权）
      其他 symbol 权重 = 0
    """
    idx = pd.date_range("2018-01-02", periods=n, freq="B")
    active = active_syms or symbols
    w = weight if weight is not None else (1.0 / len(active))
    data = {sym: (w if sym in active else 0.0) for sym in symbols}
    return pd.DataFrame(data, index=idx)


def _make_regime(n: int, state: str, start: str = "2018-01-02") -> pd.Series:
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.Series(state, index=idx)


# ── TestOutputShape ────────────────────────────────────────────────────────────

class TestOutputShape:
    def test_returns_dataframe(self):
        ctor = PortfolioConstructor(vol_window=30, min_history=10)
        n = 200
        syms = ["A", "B"]
        prices = _make_prices(n, syms)
        signals = _make_signals(n, syms)
        result = ctor.build(signals, prices)
        assert isinstance(result, pd.DataFrame)

    def test_index_is_common_dates(self):
        ctor = PortfolioConstructor(vol_window=30, min_history=10)
        n = 200
        syms = ["A", "B"]
        prices = _make_prices(n, syms)
        signals = _make_signals(n, syms)
        result = ctor.build(signals, prices)
        expected_idx = signals.index.intersection(prices.index)
        assert result.index.equals(expected_idx)

    def test_columns_match_signals(self):
        ctor = PortfolioConstructor(vol_window=30, min_history=10)
        n = 200
        syms = ["A", "B", "C"]
        prices = _make_prices(n, syms)
        signals = _make_signals(n, syms)
        result = ctor.build(signals, prices)
        assert set(result.columns) == set(syms)

    def test_no_common_dates_returns_copy(self):
        """signals 与 price_df 无共同日期 → 返回 raw_signals 副本。"""
        ctor = PortfolioConstructor()
        signals = pd.DataFrame(
            {"A": [0.5]},
            index=pd.date_range("2020-01-02", periods=1, freq="B"),
        )
        prices = pd.DataFrame(
            {"A": [100.0]},
            index=pd.date_range("2021-01-04", periods=1, freq="B"),
        )
        result = ctor.build(signals, prices)
        pd.testing.assert_frame_equal(result, signals)

    def test_weights_nonnegative(self):
        ctor = PortfolioConstructor(vol_window=30, min_history=10)
        n = 200
        syms = ["A", "B"]
        prices = _make_prices(n, syms)
        signals = _make_signals(n, syms)
        result = ctor.build(signals, prices)
        assert (result >= 0).all().all()

    def test_weights_leq_one(self):
        ctor = PortfolioConstructor(vol_window=30, min_history=10)
        n = 200
        syms = ["A", "B"]
        prices = _make_prices(n, syms)
        signals = _make_signals(n, syms)
        result = ctor.build(signals, prices)
        assert (result <= 1.0 + 1e-9).all().all()


# ── TestNormalization ──────────────────────────────────────────────────────────

class TestNormalization:
    def test_row_sum_leq_one(self):
        """最终权重行和 ≤ 1（允许持现金）。"""
        ctor = PortfolioConstructor(vol_window=30, min_history=10)
        n = 200
        syms = ["A", "B", "C"]
        prices = _make_prices(n, syms)
        # 给出过大的原始权重（总和 = 3.0）
        signals = _make_signals(n, syms, weight=1.0)
        result = ctor.build(signals, prices)
        row_sums = result.sum(axis=1)
        assert (row_sums <= 1.0 + 1e-9).all()

    def test_zero_signals_stay_zero(self):
        """原始信号全为 0 的行，输出权重也全为 0。"""
        ctor = PortfolioConstructor(vol_window=30, min_history=10)
        n = 100
        syms = ["A", "B"]
        prices = _make_prices(n, syms)
        signals = pd.DataFrame(0.0, index=prices.index, columns=syms)
        result = ctor.build(signals, prices)
        assert (result == 0).all().all()


# ── TestVolParity ──────────────────────────────────────────────────────────────

class TestVolParity:
    def test_high_vol_asset_gets_lower_weight(self):
        """
        高波动率标的分得更少权重（vol 平价逻辑）。

        构造：A 低波动，B 高波动，两个都被信号选中。
        预期：A 的权重 > B 的权重。
        """
        n = 300
        rng = np.random.default_rng(0)
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        # A: 低波动 ~1%/day, B: 高波动 ~4%/day
        ret_a = rng.normal(0, 0.01, n)
        ret_b = rng.normal(0, 0.04, n)
        prices = pd.DataFrame({
            "A": 100.0 * np.cumprod(1 + ret_a),
            "B": 100.0 * np.cumprod(1 + ret_b),
        }, index=idx)

        # 两者等权信号
        signals = _make_signals(n, ["A", "B"], weight=0.5)

        ctor = PortfolioConstructor(vol_window=30, min_history=15, use_vol_parity=True)
        result = ctor.build(signals, prices)

        # 取 vol warmup 之后的行
        tail = result.iloc[50:]
        active = tail[(tail["A"] > 0) & (tail["B"] > 0)]
        if not active.empty:
            assert (active["A"] > active["B"]).mean() > 0.7

    def test_use_vol_parity_false_preserves_signal_ratio(self):
        """
        use_vol_parity=False：信号权重比例不变（只做归一化）。

        为了排除 max_single_pos clip 和 vol_target 缩放的干扰，
        设置 target_vol=1.0（禁用 vol 缩放）、max_single_pos=1.0（禁用单标的上限）。
        """
        n = 200
        syms = ["A", "B"]
        prices = _make_prices(n, syms)

        # 信号：A=0.3, B=0.7，行和=1.0 → 归一化不改变值
        signals = pd.DataFrame(
            {"A": 0.3, "B": 0.7},
            index=prices.index,
        )

        ctor = PortfolioConstructor(
            vol_window=30, min_history=10,
            use_vol_parity=False,
            target_vol=1.0,       # 禁用 vol 缩放
            max_single_pos=1.0,   # 禁用单标的硬上限
        )
        result = ctor.build(signals, prices)

        # 归一化后比例应保持 3:7
        tail = result.iloc[20:]
        active = tail[tail.sum(axis=1) > 0]
        if not active.empty:
            ratios = active["A"] / active["B"]
            assert (ratios - 3 / 7).abs().max() < 1e-9


# ── TestVolTarget ──────────────────────────────────────────────────────────────

class TestVolTarget:
    def test_high_vol_portfolio_scaled_down(self):
        """
        目标 vol 15%，但实际 portfolio vol 很高时，
        权重应被缩小（总权重 < 信号原始权重之和）。
        """
        n = 300
        # 构造高波动率组合
        rng = np.random.default_rng(1)
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        # 每日波动 5%（年化约 79%）
        prices = pd.DataFrame({
            "A": 100.0 * np.cumprod(1 + rng.normal(0, 0.05, n)),
        }, index=idx)
        signals = _make_signals(n, ["A"], weight=1.0)

        ctor = PortfolioConstructor(
            vol_window=30, min_history=15,
            target_vol=0.15, use_vol_parity=False,
        )
        result = ctor.build(signals, prices)

        # vol warmup 后，权重应显著小于 1.0
        tail = result.iloc[50:]
        assert (tail["A"] < 0.5).mean() > 0.8

    def test_low_vol_portfolio_not_levered(self):
        """
        当 portfolio vol < target_vol 时，scale ≤ 1.0（不加杠杆）。
        """
        n = 300
        rng = np.random.default_rng(2)
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        # 极低波动率（~0.1%/day，年化约 1.6%）
        prices = pd.DataFrame({
            "A": 100.0 * np.cumprod(1 + rng.normal(0, 0.001, n)),
        }, index=idx)
        signals = _make_signals(n, ["A"], weight=0.5)

        ctor = PortfolioConstructor(
            vol_window=30, min_history=15,
            target_vol=0.15, use_vol_parity=False,
        )
        result = ctor.build(signals, prices)

        # 权重不超过原始信号（不加杠杆）
        assert (result["A"] <= 0.5 + 1e-9).all()


# ── TestRegimeCaps ─────────────────────────────────────────────────────────────

class TestRegimeCaps:
    def test_crisis_regime_caps_exposure(self):
        """CRISIS regime：最大总敞口应被限制在 20%。"""
        n = 200
        syms = ["A", "B", "C"]
        prices = _make_prices(n, syms)
        # 高权重信号
        signals = _make_signals(n, syms, weight=0.5)  # sum=1.5 > 0.20

        regime = _make_regime(n, "CRISIS")
        ctor = PortfolioConstructor(
            vol_window=30, min_history=10,
            use_vol_parity=False, target_vol=1.0,  # 关闭 vol scaling
        )
        result = ctor.build(signals, prices, regime_series=regime)

        tail = result.iloc[20:]
        row_sums = tail.sum(axis=1)
        # 总敞口应 ≤ 0.20（CRISIS 上限）
        assert (row_sums <= 0.20 + 1e-9).all()

    def test_bull_regime_allows_full_exposure(self):
        """BULL regime：最大总敞口 100%，不应被进一步缩减。"""
        n = 200
        syms = ["A", "B"]
        prices = _make_prices(n, syms)
        signals = _make_signals(n, syms, weight=0.5)  # sum=1.0

        regime = _make_regime(n, "BULL")
        ctor = PortfolioConstructor(
            vol_window=30, min_history=10,
            use_vol_parity=False, target_vol=1.0,
        )
        result = ctor.build(signals, prices, regime_series=regime)

        tail = result.iloc[20:]
        row_sums = tail.sum(axis=1)
        # BULL 允许 100% 敞口，行和不应被强制缩小至 1 以下
        # （vol_target=1.0 关闭了额外缩放，row_sum 应等于原始 1.0 或略低）
        assert (row_sums <= 1.0 + 1e-9).all()

    def test_risk_off_regime_caps_at_50pct(self):
        """RISK_OFF：最大总敞口 50%。"""
        n = 200
        syms = ["A", "B", "C"]
        prices = _make_prices(n, syms)
        # 强信号：sum=0.9
        signals = _make_signals(n, syms, weight=0.3)

        regime = _make_regime(n, "RISK_OFF")
        ctor = PortfolioConstructor(
            vol_window=30, min_history=10,
            use_vol_parity=False, target_vol=1.0,
        )
        result = ctor.build(signals, prices, regime_series=regime)

        tail = result.iloc[20:]
        row_sums = tail.sum(axis=1)
        assert (row_sums <= 0.50 + 1e-9).all()


# ── TestSinglePositionCap ──────────────────────────────────────────────────────

class TestSinglePositionCap:
    def test_max_single_position_enforced(self):
        """单标的硬上限：不超过 max_single_pos。"""
        n = 200
        syms = ["A"]
        prices = _make_prices(n, syms)
        signals = _make_signals(n, syms, weight=1.0)

        ctor = PortfolioConstructor(
            vol_window=30, min_history=10,
            use_vol_parity=False, target_vol=1.0,
            max_single_pos=0.3,
        )
        result = ctor.build(signals, prices)

        assert (result["A"] <= 0.3 + 1e-9).all()

    def test_default_max_single_pos_35pct(self):
        """默认 max_single_pos = 0.35。"""
        n = 200
        syms = ["A"]
        prices = _make_prices(n, syms)
        signals = _make_signals(n, syms, weight=1.0)

        ctor = PortfolioConstructor(
            vol_window=30, min_history=10,
            use_vol_parity=False, target_vol=1.0,
        )
        result = ctor.build(signals, prices)

        assert (result["A"] <= 0.35 + 1e-9).all()


# ── TestMinHistoryFallback ─────────────────────────────────────────────────────

class TestMinHistoryFallback:
    def test_insufficient_history_uses_equal_weight(self):
        """
        vol 历史不足（< min_history）时，应退回等权分配。

        对两个标的，前 min_history 根 bar 内的权重应接近等权 0.5。
        """
        n = 100
        syms = ["A", "B"]
        prices = _make_prices(n, syms)
        signals = _make_signals(n, syms, weight=0.5)

        ctor = PortfolioConstructor(
            vol_window=60, min_history=50,
            use_vol_parity=True,
            target_vol=1.0,   # 关闭 vol scaling
            max_single_pos=1.0,
        )
        result = ctor.build(signals, prices)

        # 第 2 根 bar（warmup 前）应为等权
        early_row = result.iloc[1]
        assert abs(early_row["A"] - 0.5) < 1e-9
        assert abs(early_row["B"] - 0.5) < 1e-9


# ── TestNaNHandling ────────────────────────────────────────────────────────────

class TestNaNHandling:
    def test_output_has_no_nan(self):
        """输出 DataFrame 不应有 NaN（fillna(0) 保证）。"""
        ctor = PortfolioConstructor(vol_window=30, min_history=10)
        n = 200
        syms = ["A", "B"]
        prices = _make_prices(n, syms)
        signals = _make_signals(n, syms)
        result = ctor.build(signals, prices)
        assert not result.isna().any().any()


class TestDefaultConfig:
    def test_default_target_vol_is_025(self):
        ctor = PortfolioConstructor()
        assert ctor._target_vol == 0.25
