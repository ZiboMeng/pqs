"""Unit tests for core/config/production_strategy.py (PRD M1).

Covers:
  - YAML parse + schema validation
  - Status enum triad (active | conservative_default | no_validated_best)
  - Factor weights sum-to-one enforcement
  - Factor weights registry membership check
  - Active-status invariants (source / validation / fingerprints all filled)
  - Builder behavior per status
  - Summary line formatting
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.config.production_strategy import (
    ProductionStrategyConfig,
    ProductionStrategyError,
    build_strategy_from_config,
    load_production_strategy,
)


# ---------------------------------------------------------------------------
# Fixtures — minimal valid yamls per status
# ---------------------------------------------------------------------------


@pytest.fixture
def _base_yaml() -> dict:
    return {
        "schema_version": "1.0",
        "status": "conservative_default",
        "strategy_type": "multi_factor",
        "source": {"mode": "manual", "spec_id": "", "lineage_tag": "",
                   "promoted_at": "", "rationale": "test"},
        "params": {
            "top_n": 4,
            "rebalance_monthly": False,
            "score_weighted": True,
            "min_holding_days": 3,
            "lookback_mom": 189,
            "lookback_quality": 189,
            "lookback_vol": 84,
            "apply_extra_shift": False,
        },
        "factor_weights": {
            "low_vol": 0.15,
            "momentum": 0.05,
            "quality": 0.30,
            "pv_div": 0.05,
            "rel_strength": 0.30,
            "market_trend": 0.0,
            "drawup_from_252d_low": 0.15,
        },
        "validation": {
            "post_fix_validated": False,
            "passed_oos_gate": False,
            "passed_qqq_gate": False,
            "passed_paper_backtest_alignment": False,
            "notes": "",
        },
        "fingerprints": {"universe_hash": "", "factor_registry_hash": "", "config_hash": ""},
    }


@pytest.fixture
def _active_yaml(_base_yaml) -> dict:
    y = dict(_base_yaml)
    y["status"] = "active"
    y["source"] = {
        "mode": "promoted_from_archive",
        "spec_id": "abc123def456",
        "lineage_tag": "post-2026-04-21-test",
        "promoted_at": "2026-04-21T12:00:00Z",
        "rationale": "acceptance pack passed",
    }
    y["validation"] = {
        "post_fix_validated": True,
        "passed_oos_gate": True,
        "passed_qqq_gate": True,
        "passed_paper_backtest_alignment": True,
        "notes": "ok",
    }
    y["fingerprints"] = {
        "universe_hash": "u" * 64,
        "factor_registry_hash": "r" * 64,
        "config_hash": "c" * 64,
    }
    return y


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_conservative_default_parses(_base_yaml):
    cfg = ProductionStrategyConfig(**_base_yaml)
    assert cfg.status == "conservative_default"
    assert cfg.strategy_type == "multi_factor"
    assert sum(cfg.factor_weights.values()) == pytest.approx(1.0)


def test_no_validated_best_parses(_base_yaml):
    _base_yaml["status"] = "no_validated_best"
    cfg = ProductionStrategyConfig(**_base_yaml)
    assert cfg.status == "no_validated_best"


def test_invalid_status_rejected(_base_yaml):
    _base_yaml["status"] = "pending_review"  # not in enum
    with pytest.raises(Exception):  # pydantic raises ValidationError
        ProductionStrategyConfig(**_base_yaml)


def test_factor_weights_must_sum_to_one(_base_yaml):
    _base_yaml["factor_weights"]["momentum"] = 0.20  # breaks sum
    with pytest.raises(Exception) as exc_info:
        ProductionStrategyConfig(**_base_yaml)
    assert "sum to 1.0" in str(exc_info.value)


def test_factor_weights_unknown_name_rejected(_base_yaml):
    _base_yaml["factor_weights"] = {
        "low_vol": 0.5,
        "momentum": 0.3,
        "unknown_factor": 0.2,
    }
    with pytest.raises(Exception) as exc_info:
        ProductionStrategyConfig(**_base_yaml)
    assert "unknown" in str(exc_info.value).lower()


def test_active_requires_promoted_source_mode(_base_yaml):
    _base_yaml["status"] = "active"
    _base_yaml["source"]["mode"] = "manual"
    with pytest.raises(Exception) as exc_info:
        ProductionStrategyConfig(**_base_yaml)
    assert "promoted_from_archive" in str(exc_info.value)


def test_active_requires_filled_source_fields(_base_yaml):
    _base_yaml["status"] = "active"
    _base_yaml["source"]["mode"] = "promoted_from_archive"
    # spec_id/lineage_tag/promoted_at empty
    with pytest.raises(Exception) as exc_info:
        ProductionStrategyConfig(**_base_yaml)
    assert "spec_id" in str(exc_info.value) or "lineage_tag" in str(exc_info.value)


def test_active_requires_all_validation_passed(_active_yaml):
    _active_yaml["validation"]["passed_qqq_gate"] = False
    with pytest.raises(Exception) as exc_info:
        ProductionStrategyConfig(**_active_yaml)
    assert "validation" in str(exc_info.value).lower()


def test_active_requires_all_fingerprints(_active_yaml):
    _active_yaml["fingerprints"]["config_hash"] = ""
    with pytest.raises(Exception) as exc_info:
        ProductionStrategyConfig(**_active_yaml)
    assert "fingerprints" in str(exc_info.value).lower()


def test_active_valid_passes(_active_yaml):
    cfg = ProductionStrategyConfig(**_active_yaml)
    assert cfg.status == "active"
    assert cfg.validation.all_passed
    assert cfg.fingerprints.all_filled


def test_summary_line_active(_active_yaml):
    cfg = ProductionStrategyConfig(**_active_yaml)
    line = cfg.summary_line()
    assert "status=active" in line
    assert "abc123def456"[:12] in line


def test_summary_line_conservative(_base_yaml):
    cfg = ProductionStrategyConfig(**_base_yaml)
    line = cfg.summary_line()
    assert "status=conservative_default" in line


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


def test_load_missing_file_raises(tmp_path):
    p = tmp_path / "nonexistent.yaml"
    with pytest.raises(ProductionStrategyError):
        load_production_strategy(p)


def test_load_valid_file(_base_yaml, tmp_path):
    p = tmp_path / "ps.yaml"
    p.write_text(yaml.safe_dump(_base_yaml))
    cfg = load_production_strategy(p)
    assert cfg.status == "conservative_default"


def test_load_malformed_yaml_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("not: [a, b\n  - broken:")
    with pytest.raises(ProductionStrategyError):
        load_production_strategy(p)


def test_load_repo_artifact_exists():
    """The committed config/production_strategy.yaml must parse cleanly.

    This is the live contract test — if someone breaks the repo artifact,
    this fails in CI before any downstream breakage.
    """
    cfg = load_production_strategy()  # default path
    assert cfg.status in ("active", "conservative_default", "no_validated_best")
    assert cfg.strategy_type == "multi_factor"
    assert sum(cfg.factor_weights.values()) == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Builder tests
# ---------------------------------------------------------------------------


class _FakeRiskConcentration:
    enabled = True
    soft_cap_max_single = 0.15
    concentration_warn_threshold = 0.30


class _FakeRiskFactorRegistry:
    strict_mode = False


class _FakeRisk:
    strategy_concentration = _FakeRiskConcentration()
    factor_registry = _FakeRiskFactorRegistry()


def test_builder_returns_multi_factor_strategy(_base_yaml):
    cfg = ProductionStrategyConfig(**_base_yaml)
    strat = build_strategy_from_config(cfg, _FakeRisk(), ["SPY", "QQQ", "AAPL"])
    from core.signals.strategies.multi_factor import MultiFactorStrategy
    assert isinstance(strat, MultiFactorStrategy)
    assert strat._top_n == 4
    assert strat._weights == cfg.factor_weights


def test_builder_rejects_no_validated_best(_base_yaml):
    _base_yaml["status"] = "no_validated_best"
    cfg = ProductionStrategyConfig(**_base_yaml)
    with pytest.raises(ProductionStrategyError) as exc_info:
        build_strategy_from_config(cfg, _FakeRisk(), ["SPY"])
    assert "no_validated_best" in str(exc_info.value)


def test_builder_rejects_unsupported_strategy_type(_base_yaml):
    _base_yaml["strategy_type"] = "dual_momentum"  # artifact currently MFS-only
    cfg = ProductionStrategyConfig(**_base_yaml)
    with pytest.raises(ProductionStrategyError) as exc_info:
        build_strategy_from_config(cfg, _FakeRisk(), ["SPY"])
    assert "multi_factor" in str(exc_info.value)


def test_builder_wires_concentration_from_risk_cfg(_base_yaml):
    cfg = ProductionStrategyConfig(**_base_yaml)
    risk = _FakeRisk()
    strat = build_strategy_from_config(cfg, risk, ["SPY"])
    assert strat._soft_cap_max_single == 0.15
    assert strat._concentration_warn == 0.30


def test_builder_handles_disabled_concentration(_base_yaml):
    class _Disabled:
        enabled = False
        soft_cap_max_single = 0.99
        concentration_warn_threshold = 0.99

    class _R:
        strategy_concentration = _Disabled()
        factor_registry = _FakeRiskFactorRegistry()

    cfg = ProductionStrategyConfig(**_base_yaml)
    strat = build_strategy_from_config(cfg, _R(), ["SPY"])
    assert strat._soft_cap_max_single is None
    assert strat._concentration_warn is None
