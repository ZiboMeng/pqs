"""Unit tests for CostModel."""

import pytest
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.cost_model import CostModel, CostBreakdown


def _make_config() -> CostModelConfig:
    return CostModelConfig(
        vix_stress_threshold=30.0,
        stress_slippage_multiplier=2.5,
        tiers={
            "liquid_etf": CostTierConfig(
                symbols=["SPY", "QQQ"],
                commission_bps=0.5,
                slippage_interday_bps=4.0,
                slippage_intraday_bps=7.0,
            ),
            "default": CostTierConfig(
                symbols=[],
                commission_bps=1.0,
                slippage_interday_bps=8.0,
                slippage_intraday_bps=12.0,
            ),
        },
    )


class TestCostBps:
    def test_known_symbol_uses_tier(self):
        m = CostModel(_make_config())
        bps = m.cost_bps("SPY", "interday", vix=15.0)
        assert bps == pytest.approx(0.5 + 4.0)  # commission + interday slippage

    def test_unknown_symbol_uses_default(self):
        m = CostModel(_make_config())
        bps = m.cost_bps("UNKNOWN", "interday", vix=15.0)
        assert bps == pytest.approx(1.0 + 8.0)

    def test_intraday_higher_than_interday(self):
        m = CostModel(_make_config())
        inter = m.cost_bps("SPY", "interday", vix=15.0)
        intra = m.cost_bps("SPY", "intraday", vix=15.0)
        assert intra > inter

    def test_stress_vix_multiplies_slippage(self):
        m    = CostModel(_make_config())
        norm = m.cost_bps("SPY", "interday", vix=15.0)
        high = m.cost_bps("SPY", "interday", vix=35.0)   # VIX > 30
        # 成本应该更高（滑点放大 2.5×）
        assert high > norm


class TestEstimateCost:
    def test_returns_cost_breakdown(self):
        m  = CostModel(_make_config())
        bd = m.estimate_cost("SPY", 10_000.0, "interday", 15.0)
        assert isinstance(bd, CostBreakdown)

    def test_zero_notional_all_zeros(self):
        m  = CostModel(_make_config())
        bd = m.estimate_cost("SPY", 0.0, "interday", 15.0)
        assert bd.total_cost_usd == 0.0

    def test_total_cost_equals_commission_plus_slippage(self):
        m  = CostModel(_make_config())
        bd = m.estimate_cost("SPY", 10_000.0, "interday", 15.0)
        assert bd.total_cost_usd == pytest.approx(bd.commission_usd + bd.slippage_usd)

    def test_cost_ratio_matches_bps(self):
        m        = CostModel(_make_config())
        notional = 100_000.0
        bd       = m.estimate_cost("SPY", notional, "interday", 15.0)
        expected_bps = m.cost_bps("SPY", "interday", 15.0)
        assert bd.total_bps == pytest.approx(expected_bps)
        assert bd.total_cost_usd == pytest.approx(notional * expected_bps / 10_000)


class TestApplyCost:
    def test_buy_costs_more_than_notional(self):
        m              = CostModel(_make_config())
        net, bd        = m.apply_cost("SPY", 10_000.0, "interday", 15.0, is_buy=True)
        assert net > 10_000.0

    def test_sell_receives_less_than_notional(self):
        m              = CostModel(_make_config())
        net, bd        = m.apply_cost("SPY", 10_000.0, "interday", 15.0, is_buy=False)
        assert net < 10_000.0
