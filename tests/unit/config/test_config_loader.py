"""Unit tests for ConfigSystem: loader, deep_merge, and pydantic validation."""

import pytest
from pathlib import Path

from core.config.loader import load_config, _deep_merge, PQSConfig


CONFIG_DIR = Path(__file__).parents[3] / "config"


# ── deep_merge tests ──────────────────────────────────────────────────────────

class TestDeepMerge:
    def test_flat_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 99}

    def test_nested_merge(self):
        base = {"system": {"env": "local", "logging": {"level": "INFO"}}}
        override = {"system": {"logging": {"level": "DEBUG"}}}
        result = _deep_merge(base, override)
        assert result["system"]["env"] == "local"
        assert result["system"]["logging"]["level"] == "DEBUG"

    def test_does_not_mutate_inputs(self):
        base = {"x": {"y": 1}}
        override = {"x": {"z": 2}}
        result = _deep_merge(base, override)
        assert "z" not in base["x"]
        assert result["x"] == {"y": 1, "z": 2}

    def test_list_override_replaces(self):
        base = {"symbols": ["SPY", "QQQ"]}
        override = {"symbols": ["AAPL"]}
        result = _deep_merge(base, override)
        assert result["symbols"] == ["AAPL"]

    def test_new_key_added(self):
        base = {"a": 1}
        override = {"b": 2}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 2}


# ── load_config tests ─────────────────────────────────────────────────────────

class TestLoadConfig:
    def test_loads_successfully(self):
        cfg = load_config(config_dir=CONFIG_DIR)
        assert isinstance(cfg, PQSConfig)

    def test_repr(self):
        cfg = load_config(config_dir=CONFIG_DIR)
        assert "PQSConfig" in repr(cfg)
        assert "local" in repr(cfg)

    def test_hard_constraints_enforced(self):
        cfg = load_config(config_dir=CONFIG_DIR)
        assert cfg.risk.long_only is True
        assert cfg.risk.allow_margin is False
        assert cfg.risk.allow_short is False

    def test_blacklist_does_not_contain_SQQQ_in_seed(self):
        cfg = load_config(config_dir=CONFIG_DIR)
        assert "SQQQ" in cfg.universe.blacklist
        assert "SQQQ" not in cfg.universe.seed_pool

    def test_budget_sums_to_lte_one(self):
        cfg = load_config(config_dir=CONFIG_DIR)
        total = cfg.risk.budget.core + cfg.risk.budget.tactical + cfg.risk.budget.enhancer
        assert total <= 1.0

    def test_all_regimes_have_constraints(self):
        cfg = load_config(config_dir=CONFIG_DIR)
        required = {"BULL", "RISK_ON", "NEUTRAL", "CAUTIOUS", "RISK_OFF", "CRISIS"}
        assert required == set(cfg.regime.position_constraints.keys())

    def test_cost_model_has_default_tier(self):
        cfg = load_config(config_dir=CONFIG_DIR)
        assert "default" in cfg.cost_model.tiers

    def test_runtime_override_applied(self):
        cfg = load_config(
            config_dir=CONFIG_DIR,
            overrides={"system": {"account": {"initial_capital_usd": 50000.0}}}
        )
        assert cfg.system.account.initial_capital_usd == 50_000.0

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("PQS_LOG_LEVEL", "DEBUG")
        cfg = load_config(config_dir=CONFIG_DIR)
        assert cfg.system.logging.level == "DEBUG"

    def test_missing_config_dir_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config(config_dir=Path("/nonexistent/path/config"))


# ── cost model helper tests ───────────────────────────────────────────────────

class TestCostModel:
    @pytest.fixture
    def cfg(self):
        return load_config(config_dir=CONFIG_DIR)

    def test_spy_uses_liquid_etf_tier(self, cfg):
        tier = cfg.cost_model.get_tier_for_symbol("SPY")
        assert tier == cfg.cost_model.tiers["liquid_etf"]

    def test_tqqq_uses_leveraged_tier(self, cfg):
        tier = cfg.cost_model.get_tier_for_symbol("TQQQ")
        assert tier == cfg.cost_model.tiers["leveraged_etf"]

    def test_unknown_symbol_uses_default(self, cfg):
        tier = cfg.cost_model.get_tier_for_symbol("UNKNOWN_XYZ")
        assert tier == cfg.cost_model.tiers["default"]

    def test_stress_multiplier_applied_above_threshold(self, cfg):
        normal = cfg.cost_model.get_slippage_bps("SPY", "interday", vix=15.0)
        stress = cfg.cost_model.get_slippage_bps("SPY", "interday", vix=40.0)
        assert stress == pytest.approx(normal * cfg.cost_model.stress_slippage_multiplier)

    def test_intraday_slippage_gt_interday(self, cfg):
        for tier in cfg.cost_model.tiers.values():
            assert tier.slippage_intraday_bps >= tier.slippage_interday_bps


# ── regime config tests ───────────────────────────────────────────────────────

class TestRegimeConfig:
    @pytest.fixture
    def cfg(self):
        return load_config(config_dir=CONFIG_DIR)

    def test_vix_thresholds_ascending(self, cfg):
        v = cfg.regime.vix_thresholds
        vals = [v.bull, v.risk_on, v.neutral, v.cautious, v.risk_off, v.crisis]
        assert vals == sorted(vals)

    def test_crisis_allows_no_leveraged_etf(self, cfg):
        crisis = cfg.regime.position_constraints["CRISIS"]
        assert crisis.leveraged_etf_allowed is False

    def test_bull_allows_leveraged_etf(self, cfg):
        bull = cfg.regime.position_constraints["BULL"]
        assert bull.leveraged_etf_allowed is True

    def test_crisis_requires_high_cash(self, cfg):
        crisis = cfg.regime.position_constraints["CRISIS"]
        assert crisis.target_cash_pct_min >= 0.80

    def test_left_side_only_in_risk_off(self, cfg):
        for name, constraint in cfg.regime.position_constraints.items():
            if name == "RISK_OFF":
                assert constraint.left_side_trading_allowed is True
            else:
                assert constraint.left_side_trading_allowed is False


# ── pydantic validation guard tests ──────────────────────────────────────────

class TestValidationGuards:
    def test_cannot_set_allow_short_true(self):
        from core.config.schemas.risk import RiskConfig
        with pytest.raises(Exception):
            RiskConfig(long_only=True, allow_margin=False, allow_short=True)

    def test_budget_over_one_raises(self):
        from core.config.schemas.risk import BudgetConfig
        with pytest.raises(Exception):
            BudgetConfig(core=0.70, tactical=0.20, enhancer=0.20)

    def test_drawdown_limits_must_be_ascending(self):
        from core.config.schemas.risk import DrawdownLimitsConfig
        with pytest.raises(Exception):
            DrawdownLimitsConfig(warning_pct=0.20, reduce_pct=0.10,
                                 defensive_pct=0.25, halt_pct=0.30)

    def test_vix_thresholds_must_be_ascending(self):
        from core.config.schemas.regime import VixThresholdsConfig
        with pytest.raises(Exception):
            VixThresholdsConfig(bull=25.0, risk_on=20.0, neutral=25.0,
                                cautious=30.0, risk_off=35.0, crisis=45.0)

    def test_blacklist_not_in_seed_pool(self):
        from core.config.schemas.universe import UniverseConfig
        with pytest.raises(Exception):
            UniverseConfig(seed_pool=["SPY", "SQQQ"], blacklist=["SQQQ"])
