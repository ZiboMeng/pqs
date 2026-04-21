"""Round 4 Topic D (2026-04-20): factor registry strict-mode tests.

Default (strict=False) behavior: WARN + drop unknown names, return
filtered dict. This is back-compat with legacy callers that might
accidentally pass a research name like `vol_63d`.

Strict (strict=True) behavior: raise UnregisteredFactorError. Use
in mining / CI / pre-production checks where silent name drift is
a research-integrity hazard.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from core.config.loader import load_config
from core.config.schemas.risk import FactorRegistryConfig
from core.factors.factor_registry import (
    UnregisteredFactorError,
    enforce_execution_factor_names,
)
from core.signals.strategies.multi_factor import MultiFactorStrategy


class TestEnforceFunction:
    def test_default_warn_and_drop(self, caplog):
        weights = {"momentum": 0.5, "NONEXISTENT": 0.3, "typo_name": 0.2}
        with caplog.at_level(logging.WARNING, logger="factor_registry"):
            out = enforce_execution_factor_names(weights)
        assert out == {"momentum": 0.5}
        assert any("NONEXISTENT" in r.message for r in caplog.records)
        assert any("typo_name" in r.message for r in caplog.records)

    def test_strict_raises(self):
        weights = {"momentum": 0.5, "NONEXISTENT": 0.3}
        with pytest.raises(UnregisteredFactorError) as exc_info:
            enforce_execution_factor_names(weights, strict=True)
        # Error message mentions the offender AND lists known factors
        assert "NONEXISTENT" in str(exc_info.value)
        assert "momentum" in str(exc_info.value) or "PRODUCTION" in str(exc_info.value).upper()

    def test_all_registered_passes_through(self):
        weights = {"momentum": 0.5, "quality": 0.5}
        # Both strict and non-strict should return the same dict
        assert enforce_execution_factor_names(weights) == weights
        assert enforce_execution_factor_names(weights, strict=True) == weights

    def test_empty_weights_no_op(self):
        assert enforce_execution_factor_names({}) == {}
        assert enforce_execution_factor_names({}, strict=True) == {}


class TestMultiFactorStrategyStrictKwarg:
    def test_default_not_strict_keeps_legacy_behavior(self, caplog):
        """Default strict_registry=False → unknown name dropped silently,
        strategy usable. Back-compat is preserved."""
        with caplog.at_level(logging.WARNING):
            s = MultiFactorStrategy(
                symbols=["SPY"],
                factor_weights={"momentum": 0.5, "nonsense": 0.3},
            )
        # Unknown dropped, rest retained
        assert set(s._weights.keys()) == {"momentum"}
        assert s._strict_registry is False

    def test_strict_true_raises_on_unknown(self):
        with pytest.raises(UnregisteredFactorError):
            MultiFactorStrategy(
                symbols=["SPY"],
                factor_weights={"momentum": 0.5, "nonsense": 0.3},
                strict_registry=True,
            )

    def test_strict_true_with_clean_weights_succeeds(self):
        s = MultiFactorStrategy(
            symbols=["SPY"],
            factor_weights={"momentum": 0.5, "quality": 0.5},
            strict_registry=True,
        )
        assert set(s._weights.keys()) == {"momentum", "quality"}
        assert s._strict_registry is True


class TestConfigSchema:
    def test_factor_registry_config_present(self):
        cfg = load_config(Path("config"))
        assert hasattr(cfg.risk, "factor_registry")
        assert isinstance(cfg.risk.factor_registry, FactorRegistryConfig)
        # Default yaml should ship strict=False (preserves legacy)
        assert cfg.risk.factor_registry.strict_mode is False

    def test_schema_default_is_false(self):
        frc = FactorRegistryConfig()
        assert frc.strict_mode is False


class TestMiningSpaceIntegration:
    """Mining's _registry_kwargs() pulls config; when strict_mode=True in
    config, every MultiFactorSpace.instantiate() call should build a
    strict strategy."""

    def test_mining_kwargs_uses_config(self, monkeypatch):
        from core.mining import strategy_space as ss

        # Fake a strict config
        class _FakeRisk:
            factor_registry = FactorRegistryConfig(strict_mode=True)
        class _FakeCfg:
            risk = _FakeRisk()

        monkeypatch.setattr(
            "core.config.loader.load_config", lambda *a, **k: _FakeCfg(),
        )
        kw = ss._registry_kwargs()
        assert kw == {"strict_registry": True}

    def test_mining_kwargs_falls_back_on_load_failure(self, monkeypatch):
        from core.mining import strategy_space as ss

        def _boom(*a, **k):
            raise RuntimeError("config broken")
        monkeypatch.setattr("core.config.loader.load_config", _boom)
        kw = ss._registry_kwargs()
        # Silent fallback to empty dict (preserves legacy default=False
        # via MultiFactorStrategy.__init__ default)
        assert kw == {}
