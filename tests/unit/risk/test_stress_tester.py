"""Unit tests for StressTester, StressScenario, StressResult, MonteCarloResult."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.risk.stress_tester import (
    StressTester, StressScenario, StressResult, MonteCarloResult,
)


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _equity(n: int = 300, cagr: float = 0.10) -> pd.Series:
    idx     = pd.bdate_range("2020-01-02", periods=n)
    daily_r = (1 + cagr) ** (1 / 252) - 1
    vals    = 100_000.0 * np.cumprod(1 + np.full(n, daily_r))
    return pd.Series(vals, index=idx)


# ── StressScenario / StressResult ─────────────────────────────────────────────

class TestStressScenario:
    def test_dataclass_creation(self):
        s = StressScenario(
            name="test", description="desc",
            asset_shocks={"SPY": -0.30}, duration_days=100,
        )
        assert s.name == "test"
        assert s.asset_shocks["SPY"] == pytest.approx(-0.30)

    def test_default_duration(self):
        s = StressScenario(name="x", description="y", asset_shocks={})
        assert s.duration_days == 252


class TestStressResult:
    def test_str_representation(self):
        r = StressResult(
            scenario_name="test", portfolio_return=-0.30,
            estimated_pnl=-30_000.0, worst_asset="SPY",
            worst_asset_shock=-0.30,
        )
        text = str(r)
        assert "test" in text
        assert "-30.00%" in text

    def test_str_contains_pnl(self):
        r = StressResult(
            scenario_name="gfc", portfolio_return=-0.50,
            estimated_pnl=-50_000.0, worst_asset="SPY",
            worst_asset_shock=-0.57,
        )
        assert "$" in str(r)


# ── StressTester: 内置情景 ────────────────────────────────────────────────────

class TestBuiltinScenarios:
    def test_has_4_builtin_scenarios(self):
        tester = StressTester()
        assert len(tester.scenario_names) == 4

    def test_scenario_names_correct(self):
        tester = StressTester()
        names  = tester.scenario_names
        assert "gfc_2008" in names
        assert "covid_2020" in names
        assert "rate_hike_2022" in names
        assert "dot_com_2000" in names

    def test_get_scenario_returns_scenario(self):
        tester = StressTester()
        s = tester.get_scenario("gfc_2008")
        assert s is not None
        assert s.name == "gfc_2008"

    def test_get_nonexistent_returns_none(self):
        tester = StressTester()
        assert tester.get_scenario("nonexistent") is None

    def test_custom_scenario_added(self):
        custom = StressScenario("custom", "test", {"SPY": -0.10})
        tester = StressTester(custom_scenarios=[custom])
        assert "custom" in tester.scenario_names
        assert len(tester.scenario_names) == 5


# ── apply_scenario ────────────────────────────────────────────────────────────

class TestApplyScenario:
    def test_returns_stress_result(self):
        tester = StressTester(equity=100_000.0)
        s      = tester.get_scenario("gfc_2008")
        res    = tester.apply_scenario({"SPY": 1.0}, s)
        assert isinstance(res, StressResult)

    def test_portfolio_return_negative_for_crash(self):
        tester = StressTester(equity=100_000.0)
        s      = tester.get_scenario("gfc_2008")
        res    = tester.apply_scenario({"SPY": 0.6, "QQQ": 0.4}, s)
        assert res.portfolio_return < 0

    def test_estimated_pnl_equals_equity_times_return(self):
        tester = StressTester(equity=100_000.0)
        s      = tester.get_scenario("gfc_2008")
        res    = tester.apply_scenario({"SPY": 1.0}, s)
        assert res.estimated_pnl == pytest.approx(
            100_000.0 * res.portfolio_return, rel=1e-6
        )

    def test_single_asset_portfolio(self):
        """单标的组合：收益 = 该标的冲击值。"""
        tester = StressTester(equity=100_000.0)
        s      = tester.get_scenario("gfc_2008")
        res    = tester.apply_scenario({"SPY": 1.0}, s)
        assert res.portfolio_return == pytest.approx(
            s.asset_shocks["SPY"], rel=1e-6
        )

    def test_weights_normalized(self):
        """权重 {SPY: 2, QQQ: 2} 等同于 {SPY: 0.5, QQQ: 0.5}。"""
        tester = StressTester(equity=100_000.0)
        s      = tester.get_scenario("gfc_2008")
        res1   = tester.apply_scenario({"SPY": 2.0, "QQQ": 2.0}, s)
        res2   = tester.apply_scenario({"SPY": 0.5, "QQQ": 0.5}, s)
        assert res1.portfolio_return == pytest.approx(res2.portfolio_return, rel=1e-6)

    def test_unknown_symbol_uses_default(self):
        """未知标的使用 'default' 冲击值。"""
        tester  = StressTester(equity=100_000.0)
        s       = tester.get_scenario("gfc_2008")   # default=-0.55
        res     = tester.apply_scenario({"UNKN": 1.0}, s)
        assert res.portfolio_return == pytest.approx(-0.55, rel=1e-6)

    def test_empty_weights_handled(self):
        tester = StressTester(equity=100_000.0)
        s      = tester.get_scenario("gfc_2008")
        res    = tester.apply_scenario({}, s)
        assert res.portfolio_return == pytest.approx(0.0)

    def test_tlt_positive_in_gfc(self):
        """GFC 中 TLT（长债）上涨。"""
        tester = StressTester(equity=100_000.0)
        s      = tester.get_scenario("gfc_2008")
        res    = tester.apply_scenario({"TLT": 1.0}, s)
        assert res.portfolio_return > 0

    def test_scenario_name_in_result(self):
        tester = StressTester(equity=100_000.0)
        s      = tester.get_scenario("covid_2020")
        res    = tester.apply_scenario({"SPY": 1.0}, s)
        assert res.scenario_name == "covid_2020"


# ── run_all ────────────────────────────────────────────────────────────────────

class TestRunAll:
    def test_returns_list(self):
        tester  = StressTester()
        results = tester.run_all({"SPY": 1.0})
        assert isinstance(results, list)

    def test_length_equals_n_scenarios(self):
        tester  = StressTester()
        results = tester.run_all({"SPY": 1.0})
        assert len(results) == len(tester.scenario_names)

    def test_all_crashes_negative_for_spy_only(self):
        """纯 SPY 组合在所有情景下均亏损。"""
        tester  = StressTester()
        results = tester.run_all({"SPY": 1.0})
        for r in results:
            assert r.portfolio_return < 0, f"情景 {r.scenario_name} 预期亏损"

    def test_dot_com_worst_for_qqq_heavy(self):
        """QQQ 重仓组合在 dot_com 情景损失最大。"""
        tester  = StressTester(equity=100_000.0)
        results = tester.run_all({"QQQ": 1.0})
        returns = {r.scenario_name: r.portfolio_return for r in results}
        assert returns["dot_com_2000"] == min(returns.values())


# ── Monte Carlo ───────────────────────────────────────────────────────────────

class TestMonteCarlo:
    def test_returns_monte_carlo_result(self):
        eq  = _equity(300)
        res = StressTester().monte_carlo(eq, n_sims=200, horizon=60)
        assert isinstance(res, MonteCarloResult)

    def test_insufficient_data_returns_nan(self):
        eq  = _equity(10)
        res = StressTester().monte_carlo(eq, n_sims=100, horizon=30)
        assert np.isnan(res.median_return)
        assert np.isnan(res.prob_loss)

    def test_pct_5_less_than_pct_95(self):
        eq  = _equity(300)
        res = StressTester().monte_carlo(eq, n_sims=500, horizon=60)
        assert res.pct_5 < res.pct_95

    def test_prob_loss_between_0_and_1(self):
        eq  = _equity(300)
        res = StressTester().monte_carlo(eq, n_sims=500, horizon=60)
        assert 0.0 <= res.prob_loss <= 1.0

    def test_cvar_less_than_or_equal_var(self):
        """CVaR 是尾部均值，应 ≤ VaR（均为负值时均值更小）。"""
        eq  = _equity(300)
        res = StressTester().monte_carlo(eq, n_sims=500, horizon=60)
        assert res.cvar_95 <= res.var_95

    def test_rising_equity_positive_median(self):
        """单调上涨的权益曲线 → 中位模拟收益应为正。"""
        eq  = _equity(300, cagr=0.20)
        res = StressTester().monte_carlo(eq, n_sims=1000, horizon=252)
        assert res.median_return > 0

    def test_n_sims_stored(self):
        eq  = _equity(300)
        res = StressTester().monte_carlo(eq, n_sims=123, horizon=30)
        assert res.n_sims == 123

    def test_horizon_stored(self):
        eq  = _equity(300)
        res = StressTester().monte_carlo(eq, n_sims=200, horizon=45)
        assert res.horizon_days == 45

    def test_reproducible_with_seed(self):
        """相同 seed → 相同结果。"""
        eq   = _equity(300)
        res1 = StressTester().monte_carlo(eq, n_sims=200, horizon=60, seed=0)
        res2 = StressTester().monte_carlo(eq, n_sims=200, horizon=60, seed=0)
        assert res1.median_return == pytest.approx(res2.median_return)

    def test_different_seeds_differ(self):
        """不同 seed → 结果应不同（使用随机游走权益保证收益率有方差）。"""
        rng  = np.random.default_rng(7)
        idx  = pd.bdate_range("2020-01-02", periods=300)
        eq   = pd.Series(
            100_000.0 * np.cumprod(1 + rng.normal(0.0003, 0.012, 300)),
            index=idx,
        )
        res1 = StressTester().monte_carlo(eq, n_sims=500, horizon=60, seed=0)
        res2 = StressTester().monte_carlo(eq, n_sims=500, horizon=60, seed=99)
        assert res1.median_return != pytest.approx(res2.median_return, abs=1e-8)

    def test_str_representation(self):
        eq  = _equity(300)
        res = StressTester().monte_carlo(eq, n_sims=100, horizon=30)
        text = str(res)
        assert "Monte Carlo" in text
        assert "亏损概率" in text
