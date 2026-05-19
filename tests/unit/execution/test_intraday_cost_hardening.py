"""PRD-2 P2.3 R11 — intraday cost-model hardening (TDD).

build round. AC (PRD-2 ralph-loop R11): intraday cost-model unit
GREEN incl. a 3x tier — the configurable cost-sensitivity knob the
P2.3 R13 acceptance needs ("intraday 3x 成本仍正").

Grounded scope (honest, R4/R6/R7 pattern): the intraday cost model
ALREADY exists and is correct — per-tier ``slippage_intraday_bps``
in config/cost_model.yaml + a VIX-CONDITIONAL
``stress_slippage_multiplier`` (2.5x when vix>=30) in
``CostModelConfig.get_slippage_bps`` + threaded through
``core.execution.cost_model.CostModel`` and the intraday
ExecutionSimulator. NOT reimplemented. The genuinely-missing R11
surface is an UNCONDITIONAL ``sensitivity_multiplier`` (independent
of VIX) so the acceptance sweep can force a uniform 3x stress —
added as a default-1.0, construction-bit-identical keyword (same
additive pattern as RA2's xgb_alpha sample_weight). Commission is
deliberately NOT scaled (slippage is the volatility-sensitive
component; flat commission = conservative-honest, matches the
mining-evaluator cost_multiplier semantics).
"""
import pytest

from core.config.loader import load_config
from core.execution.cost_model import CostModel


@pytest.fixture(scope="module")
def cfg():
    return load_config("config").cost_model


class TestSensitivityMultiplierAdditive:
    def test_default_is_bit_identical(self, cfg):
        # default sensitivity_multiplier=1.0 ≡ prior behaviour.
        for freq in ("interday", "intraday"):
            a = cfg.get_slippage_bps("SPY", freq, 15.0)
            b = cfg.get_slippage_bps("SPY", freq, 15.0,
                                     sensitivity_multiplier=1.0)
            assert a == b
            t = cfg.get_total_cost_bps("SPY", freq, 15.0)
            assert t == cfg.get_total_cost_bps(
                "SPY", freq, 15.0, sensitivity_multiplier=1.0)

    def test_3x_triples_slippage_only(self, cfg):
        base = cfg.get_slippage_bps("SPY", "intraday", 15.0)  # vix<30
        x3 = cfg.get_slippage_bps("SPY", "intraday", 15.0,
                                  sensitivity_multiplier=3.0)
        assert x3 == pytest.approx(3.0 * base)
        # commission is NOT scaled by the sensitivity knob
        comm = cfg.get_commission_bps("SPY")
        tot3 = cfg.get_total_cost_bps("SPY", "intraday", 15.0,
                                      sensitivity_multiplier=3.0)
        assert tot3 == pytest.approx(comm + 3.0 * base)

    def test_stacks_with_vix_stress_multiplier(self, cfg):
        # vix>=30 → 2.5x vix-stress; 3x sensitivity stacks on top.
        base = cfg.get_slippage_bps("SPY", "intraday", 15.0)
        stressed3 = cfg.get_slippage_bps(
            "SPY", "intraday", 35.0, sensitivity_multiplier=3.0)
        assert stressed3 == pytest.approx(
            base * cfg.stress_slippage_multiplier * 3.0)

    def test_intraday_base_higher_than_interday(self, cfg):
        # sanity: intraday slippage tier > interday (yaml invariant)
        assert (cfg.get_slippage_bps("SPY", "intraday", 15.0)
                > cfg.get_slippage_bps("SPY", "interday", 15.0))

    def test_sub_unity_multiplier_rejected(self, cfg):
        # a sensitivity knob must never UNDERSTATE cost (dangerous
        # false-positive); < 1.0 is rejected.
        with pytest.raises(ValueError):
            cfg.get_slippage_bps("SPY", "intraday", 15.0,
                                 sensitivity_multiplier=0.5)


class TestCostModelThreadsSensitivity:
    def test_cost_bps_threads_multiplier(self, cfg):
        cm = CostModel(cfg)
        b = cm.cost_bps("QQQ", "intraday", 15.0)
        x3 = cm.cost_bps("QQQ", "intraday", 15.0,
                         sensitivity_multiplier=3.0)
        comm = cfg.get_commission_bps("QQQ")
        slip = cfg.get_slippage_bps("QQQ", "intraday", 15.0)
        assert b == pytest.approx(comm + slip)
        assert x3 == pytest.approx(comm + 3.0 * slip)

    def test_estimate_cost_scales_slippage_not_commission(self, cfg):
        cm = CostModel(cfg)
        base = cm.estimate_cost("QQQ", 1_000_000, "intraday", 15.0)
        x3 = cm.estimate_cost("QQQ", 1_000_000, "intraday", 15.0,
                              sensitivity_multiplier=3.0)
        assert x3.commission_usd == pytest.approx(base.commission_usd)
        assert x3.slippage_usd == pytest.approx(3.0 * base.slippage_usd)
        assert x3.total_cost_usd > base.total_cost_usd

    def test_estimate_cost_default_bit_identical(self, cfg):
        cm = CostModel(cfg)
        a = cm.estimate_cost("AAPL", 500_000, "intraday", 20.0)
        b = cm.estimate_cost("AAPL", 500_000, "intraday", 20.0,
                             sensitivity_multiplier=1.0)
        assert a.total_cost_usd == pytest.approx(b.total_cost_usd)
