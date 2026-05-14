"""SimpleBaselineStrategy 单元测试。

70% MTUM + 30% TQQQ-200SMA-or-cash, monthly rebalance.

测试维度：
  - 输出 shape / 列契约
  - 权重 invariants (不为负、总和 ≤ 1)
  - SMA filter 行为 (above/below SMA → leveraged/cash)
  - Monthly rebalance 语义
  - 边界 (缺数据 / 缺 symbol / 参数验证)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.signals.strategies.simple_baseline import SimpleBaselineStrategy


# ── 辅助函数 ─────────────────────────────────────────────────────────────────

def _make_prices(
    n: int,
    qqq_above_sma: bool,
    start: str = "2018-01-02",
    base: float = 100.0,
    vix_level: float = 15.0,
) -> pd.DataFrame:
    """生成 MTUM / TQQQ / BIL / QQQ / SPY / VIX 的价格序列。

    qqq_above_sma=True → QQQ 单调上涨，价格 > 200SMA。
    qqq_above_sma=False → QQQ 单调下跌，价格 < 200SMA。
    vix_level → constant VIX level. default 15 (calm regime, allows risk-on).
    """
    idx = pd.date_range(start, periods=n, freq="B")
    if qqq_above_sma:
        qqq_drift = 0.20 / 252  # 20%/yr up
    else:
        qqq_drift = -0.20 / 252  # 20%/yr down
    qqq = base * np.cumprod(1 + np.full(n, qqq_drift))

    mtum = base * np.cumprod(1 + np.full(n, 0.10 / 252))  # +10%/yr
    tqqq = base * np.cumprod(1 + np.full(n, 0.30 / 252))  # +30%/yr (3x QQQ proxy)
    bil = base * np.cumprod(1 + np.full(n, 0.04 / 252))   # +4%/yr (cash-like)
    spy = base * np.cumprod(1 + np.full(n, 0.10 / 252))   # benchmark
    vix = np.full(n, vix_level)

    return pd.DataFrame({
        "MTUM": mtum,
        "TQQQ": tqqq,
        "BIL": bil,
        "QQQ": qqq,
        "SPY": spy,
        "VIX": vix,
    }, index=idx)


def _make_prices_qqq_crosses(
    n: int = 600,
    cross_at: int = 300,
    vix_level: float = 15.0,
) -> pd.DataFrame:
    """生成 QQQ 在 cross_at 之前上涨、之后下跌的序列。VIX 默认平静."""
    idx = pd.date_range("2018-01-02", periods=n, freq="B")
    up_drift = 0.30 / 252
    down_drift = -0.30 / 252
    qqq_ret = np.concatenate([
        np.full(cross_at, up_drift),
        np.full(n - cross_at, down_drift),
    ])
    qqq = 100.0 * np.cumprod(1 + qqq_ret)
    mtum = 100.0 * np.cumprod(1 + np.full(n, 0.10 / 252))
    tqqq = 100.0 * np.cumprod(1 + np.full(n, 0.30 / 252))
    bil = 100.0 * np.cumprod(1 + np.full(n, 0.04 / 252))
    spy = 100.0 * np.cumprod(1 + np.full(n, 0.10 / 252))
    vix = np.full(n, vix_level)
    return pd.DataFrame({
        "MTUM": mtum, "TQQQ": tqqq, "BIL": bil, "QQQ": qqq, "SPY": spy, "VIX": vix,
    }, index=idx)


# ── 1. 输出 shape / 列契约 ─────────────────────────────────────────────────────

class TestOutputShape:
    def test_returns_dataframe(self):
        strat = SimpleBaselineStrategy()
        prices = _make_prices(400, qqq_above_sma=True)
        result = strat.generate(prices)
        assert isinstance(result, pd.DataFrame)

    def test_index_matches(self):
        strat = SimpleBaselineStrategy()
        prices = _make_prices(400, qqq_above_sma=True)
        result = strat.generate(prices)
        assert result.index.equals(prices.index)

    def test_columns_match(self):
        strat = SimpleBaselineStrategy()
        prices = _make_prices(400, qqq_above_sma=True)
        result = strat.generate(prices)
        assert list(result.columns) == list(prices.columns)


# ── 2. Weights invariants ──────────────────────────────────────────────────────

class TestWeightsInvariants:
    def test_non_negative(self):
        """所有权重 >= 0 (long-only)."""
        strat = SimpleBaselineStrategy()
        prices = _make_prices(400, qqq_above_sma=True)
        result = strat.generate(prices)
        assert (result >= 0).all().all()

    def test_no_short_positions(self):
        """no_short invariant — 没有负权重."""
        strat = SimpleBaselineStrategy()
        prices = _make_prices_qqq_crosses(600)
        result = strat.generate(prices)
        assert (result >= 0).all().all()

    def test_total_weight_at_most_one(self):
        """总权重 <= 1.0 (no margin)."""
        strat = SimpleBaselineStrategy()
        prices = _make_prices(400, qqq_above_sma=True)
        result = strat.generate(prices)
        # After SMA warmup
        warmup = 250
        row_sums = result.iloc[warmup:].sum(axis=1)
        assert (row_sums <= 1.0 + 1e-6).all()

    def test_total_weight_close_to_one_when_filter_passes(self):
        """SMA filter pass + 所有 symbols 都有数据 → total weight = 1.0."""
        strat = SimpleBaselineStrategy()
        prices = _make_prices(400, qqq_above_sma=True)
        result = strat.generate(prices)
        warmup = 250
        row_sums = result.iloc[warmup:].sum(axis=1)
        assert np.allclose(row_sums, 1.0, atol=1e-6)


# ── 3. SMA filter behavior ─────────────────────────────────────────────────────

class TestSMAFilter:
    def test_above_sma_holds_leveraged(self):
        """QQQ 持续上涨 → leveraged sleeve 满仓 30%, cash leg 0."""
        strat = SimpleBaselineStrategy()
        prices = _make_prices(400, qqq_above_sma=True)
        result = strat.generate(prices)
        warmup = 250  # post SMA warmup
        assert (result["TQQQ"].iloc[warmup:] > 0.29).all()
        assert (result["BIL"].iloc[warmup:].abs() < 1e-10).all()

    def test_below_sma_holds_cash(self):
        """QQQ 持续下跌 → cash sleeve 满仓 30%, leveraged 0."""
        strat = SimpleBaselineStrategy()
        prices = _make_prices(400, qqq_above_sma=False)
        result = strat.generate(prices)
        warmup = 250
        assert (result["TQQQ"].iloc[warmup:] == 0.0).all()
        assert (result["BIL"].iloc[warmup:] > 0.29).all()

    def test_sma_crossover_switches_leg(self):
        """QQQ 中段从涨转跌 → leveraged → cash 切换发生."""
        strat = SimpleBaselineStrategy(rebalance_monthly=False)  # daily for precise check
        prices = _make_prices_qqq_crosses(600, cross_at=300)
        result = strat.generate(prices)
        # Early: above SMA → TQQQ > 0
        # Late: below SMA → BIL > 0
        late = result.iloc[500:]
        assert (late["TQQQ"] == 0.0).all()
        assert (late["BIL"] > 0.29).all()

    def test_sma_warmup_returns_cash(self):
        """SMA 还没 warmup 完 → leveraged sleeve = 0, 走 cash."""
        strat = SimpleBaselineStrategy(rebalance_monthly=False)
        prices = _make_prices(100, qqq_above_sma=True)  # < 200 SMA window
        result = strat.generate(prices)
        # 整个窗口 SMA 都不够 → above_sma = NaN → fillna 0 → 全走 cash
        assert (result["TQQQ"] == 0.0).all()
        # BIL leg should carry the leveraged_weight throughout
        assert (result["BIL"] > 0.29).all()


# ── 4. MTUM weight is constant ────────────────────────────────────────────────

class TestMTUMSleeve:
    def test_mtum_70pct_in_risk_on(self):
        """MTUM = 0.70 when risk-on (QQQ above SMA, VIX calm)."""
        strat = SimpleBaselineStrategy()
        prices = _make_prices(400, qqq_above_sma=True, vix_level=15.0)
        result = strat.generate(prices)
        warmup = 250
        assert np.allclose(result["MTUM"].iloc[warmup:], 0.70, atol=1e-6)

    def test_mtum_drops_to_risk_off_weight_in_risk_off(self):
        """MTUM = mtum_risk_off_weight (default 0) when risk-off."""
        strat = SimpleBaselineStrategy()  # default mtum_risk_off_weight=0
        prices = _make_prices(400, qqq_above_sma=False, vix_level=15.0)
        result = strat.generate(prices)
        warmup = 250
        assert (result["MTUM"].iloc[warmup:].abs() < 1e-10).all(), \
            "Risk-off MTUM should be 0 (Faber GTAA default)"

    def test_mtum_partial_defense_via_risk_off_weight(self):
        """Newfound-style partial defense: MTUM stays at 0.35 in risk-off."""
        strat = SimpleBaselineStrategy(mtum_risk_off_weight=0.35)
        prices = _make_prices(400, qqq_above_sma=False, vix_level=15.0)
        result = strat.generate(prices)
        warmup = 250
        assert np.allclose(result["MTUM"].iloc[warmup:], 0.35, atol=1e-6)
        # Cash absorbs the rest
        assert np.allclose(result["BIL"].iloc[warmup:], 0.65, atol=1e-6)

    def test_mtum_risk_off_weight_validation(self):
        with pytest.raises(ValueError, match="mtum_risk_off_weight"):
            SimpleBaselineStrategy(mtum_weight=0.70, mtum_risk_off_weight=0.80)
        with pytest.raises(ValueError, match="mtum_risk_off_weight"):
            SimpleBaselineStrategy(mtum_risk_off_weight=-0.1)


# ── 5. Monthly rebalance semantics ────────────────────────────────────────────

class TestMonthlyRebalance:
    def test_monthly_no_intra_month_change_when_above_sma(self):
        """月内 weight 不变 (monthly rebalance only)."""
        strat = SimpleBaselineStrategy(rebalance_monthly=True)
        prices = _make_prices(400, qqq_above_sma=True)
        result = strat.generate(prices)
        # 取一个完整月 (e.g. middle month)
        sample = result.iloc[250:271]  # ~one month
        # 月内 MTUM weight 应该 constant
        assert sample["MTUM"].nunique() == 1

    def test_daily_mode_allows_intra_month_change(self):
        """rebalance_monthly=False 时，signal 可以日内变化.

        QQQ from up trend (day 0-300) to down trend (day 300+). SMA200 is
        lagging — actual crossover happens later. Cover full series and
        check both regimes are observed in the signal.
        """
        strat = SimpleBaselineStrategy(rebalance_monthly=False)
        prices = _make_prices_qqq_crosses(900, cross_at=300)
        result = strat.generate(prices)
        # 整个 series 上看：早期 (post SMA warmup) TQQQ>0; 晚期 BIL>0
        early = result.iloc[250:300]
        late = result.iloc[700:]
        assert (early["TQQQ"] > 0.29).all(), "Early window TQQQ should be on"
        assert (late["BIL"] > 0.29).all(), "Late window cash should be on"


# ── 6. Parameter validation ───────────────────────────────────────────────────

class TestParameterValidation:
    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match="must sum to 1.0"):
            SimpleBaselineStrategy(mtum_weight=0.5, leveraged_weight=0.3)

    def test_weights_non_negative(self):
        with pytest.raises(ValueError, match="non-negative"):
            SimpleBaselineStrategy(mtum_weight=-0.1, leveraged_weight=1.1)

    def test_sma_window_min(self):
        with pytest.raises(ValueError, match="sma_window must be >= 2"):
            SimpleBaselineStrategy(sma_window=1)


# ── 7. Missing symbol handling ────────────────────────────────────────────────

class TestMissingSymbols:
    def test_raises_when_required_symbol_missing(self):
        strat = SimpleBaselineStrategy()
        prices = _make_prices(400, qqq_above_sma=True).drop(columns=["TQQQ"])
        with pytest.raises(ValueError, match="missing required symbols"):
            strat.generate(prices)


# ── 8. Custom configuration ───────────────────────────────────────────────────

class TestCustomConfig:
    def test_custom_weights(self):
        """80/20 split instead of 70/30."""
        strat = SimpleBaselineStrategy(
            mtum_weight=0.80, leveraged_weight=0.20,
        )
        prices = _make_prices(400, qqq_above_sma=True)
        result = strat.generate(prices)
        warmup = 250
        assert np.allclose(result["MTUM"].iloc[warmup:], 0.80, atol=1e-6)
        assert (result["TQQQ"].iloc[warmup:] > 0.19).all()

    def test_custom_cash_symbol(self):
        """Use SHV instead of BIL as cash leg."""
        strat = SimpleBaselineStrategy(cash_symbol="SHV")
        prices = _make_prices(400, qqq_above_sma=False)
        prices["SHV"] = prices["BIL"]  # same cash profile
        result = strat.generate(prices)
        warmup = 250
        assert (result["SHV"].iloc[warmup:] > 0.29).all()
        assert (result["BIL"].iloc[warmup:].abs() < 1e-10).all()


# ── 9. VIX circuit-breaker ────────────────────────────────────────────────────

class TestVIXCircuitBreaker:
    def test_vix_above_exit_forces_cash(self):
        """VIX > 30 → cash leg even when QQQ above 200SMA."""
        strat = SimpleBaselineStrategy()
        prices = _make_prices(400, qqq_above_sma=True, vix_level=35.0)
        result = strat.generate(prices)
        warmup = 250
        assert (result["TQQQ"].iloc[warmup:] == 0.0).all(), \
            "VIX>30 should force TQQQ to 0"
        assert (result["BIL"].iloc[warmup:] > 0.29).all(), \
            "VIX>30 should fill BIL"

    def test_vix_below_reentry_with_above_sma_holds_leveraged(self):
        """VIX < 20 AND QQQ > SMA → leveraged on."""
        strat = SimpleBaselineStrategy()
        prices = _make_prices(400, qqq_above_sma=True, vix_level=15.0)
        result = strat.generate(prices)
        warmup = 250
        assert (result["TQQQ"].iloc[warmup:] > 0.29).all()

    def test_hysteresis_band_maintains_state(self):
        """VIX between 20 and 30 with no SMA change → maintains prior state.

        Start with VIX=15 (risk-on), then move VIX into [20, 30] band.
        Expect: risk-on state persists.
        """
        strat = SimpleBaselineStrategy(rebalance_monthly=False)
        n = 600
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        # QQQ uptrending throughout
        qqq = 100.0 * np.cumprod(1 + np.full(n, 0.20 / 252))
        mtum = 100.0 * np.cumprod(1 + np.full(n, 0.10 / 252))
        tqqq = 100.0 * np.cumprod(1 + np.full(n, 0.30 / 252))
        bil = 100.0 * np.cumprod(1 + np.full(n, 0.04 / 252))
        spy = 100.0 * np.cumprod(1 + np.full(n, 0.10 / 252))
        # VIX starts at 15 (risk-on), then drifts up to 25 (in hysteresis band)
        vix = np.concatenate([np.full(300, 15.0), np.full(300, 25.0)])
        prices = pd.DataFrame({
            "MTUM": mtum, "TQQQ": tqqq, "BIL": bil,
            "QQQ": qqq, "SPY": spy, "VIX": vix,
        }, index=idx)
        result = strat.generate(prices)
        # After warmup + hysteresis band entry, should STILL be risk-on
        late = result.iloc[450:]
        assert (late["TQQQ"] > 0.29).all(), \
            "Hysteresis band should maintain risk-on state"

    def test_vix_spike_triggers_exit_even_above_sma(self):
        """VIX spike to 35 → exit despite QQQ above SMA."""
        strat = SimpleBaselineStrategy(rebalance_monthly=False)
        n = 600
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        qqq = 100.0 * np.cumprod(1 + np.full(n, 0.20 / 252))
        mtum = 100.0 * np.cumprod(1 + np.full(n, 0.10 / 252))
        tqqq = 100.0 * np.cumprod(1 + np.full(n, 0.30 / 252))
        bil = 100.0 * np.cumprod(1 + np.full(n, 0.04 / 252))
        spy = 100.0 * np.cumprod(1 + np.full(n, 0.10 / 252))
        vix = np.concatenate([np.full(400, 15.0), np.full(200, 35.0)])
        prices = pd.DataFrame({
            "MTUM": mtum, "TQQQ": tqqq, "BIL": bil,
            "QQQ": qqq, "SPY": spy, "VIX": vix,
        }, index=idx)
        result = strat.generate(prices)
        # Post-spike → BIL should fill
        post_spike = result.iloc[450:]
        assert (post_spike["TQQQ"] == 0.0).all()
        assert (post_spike["BIL"] > 0.29).all()

    def test_vix_exit_threshold_validation(self):
        with pytest.raises(ValueError, match="vix_exit.*must be > vix_reentry"):
            SimpleBaselineStrategy(vix_exit=20.0, vix_reentry=25.0)

    def test_vix_none_disables_filter(self):
        """vix_symbol=None → SMA-only mode, no VIX column required."""
        strat = SimpleBaselineStrategy(vix_symbol=None)
        # No VIX column in price_df
        idx = pd.date_range("2018-01-02", periods=400, freq="B")
        qqq = 100.0 * np.cumprod(1 + np.full(400, 0.20 / 252))
        prices = pd.DataFrame({
            "MTUM": 100.0 * np.cumprod(1 + np.full(400, 0.10 / 252)),
            "TQQQ": 100.0 * np.cumprod(1 + np.full(400, 0.30 / 252)),
            "BIL":  100.0 * np.cumprod(1 + np.full(400, 0.04 / 252)),
            "QQQ":  qqq,
            "SPY":  100.0 * np.cumprod(1 + np.full(400, 0.10 / 252)),
        }, index=idx)
        result = strat.generate(prices)
        warmup = 250
        # QQQ above SMA + no VIX filter → risk-on
        assert (result["TQQQ"].iloc[warmup:] > 0.29).all()


# ── 10. State machine + recovery ──────────────────────────────────────────────

class TestStateMachineRecovery:
    def test_vix_drop_below_reentry_recovers_leveraged(self):
        """VIX spike to 35 then drop to 15 (with QQQ above SMA throughout) → recover."""
        strat = SimpleBaselineStrategy(rebalance_monthly=False)
        n = 900
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        qqq = 100.0 * np.cumprod(1 + np.full(n, 0.20 / 252))
        mtum = 100.0 * np.cumprod(1 + np.full(n, 0.10 / 252))
        tqqq = 100.0 * np.cumprod(1 + np.full(n, 0.30 / 252))
        bil = 100.0 * np.cumprod(1 + np.full(n, 0.04 / 252))
        spy = 100.0 * np.cumprod(1 + np.full(n, 0.10 / 252))
        # VIX: 15 → 35 → 15 (spike then calm)
        vix = np.concatenate([
            np.full(300, 15.0), np.full(200, 35.0), np.full(400, 15.0),
        ])
        prices = pd.DataFrame({
            "MTUM": mtum, "TQQQ": tqqq, "BIL": bil,
            "QQQ": qqq, "SPY": spy, "VIX": vix,
        }, index=idx)
        result = strat.generate(prices)
        # Far after recovery → risk-on again
        recovery = result.iloc[700:]
        assert (recovery["TQQQ"] > 0.29).all()
        assert (recovery["BIL"].abs() < 1e-10).all()
