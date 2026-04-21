"""Integration tests for PRD M1 single-source-of-truth contract.

Verifies that all production entrypoints build the same MultiFactorStrategy
instance from config/production_strategy.yaml, with identical factor_weights
and identical constructor params. No script should still have inline
hardcoded factor_weights.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.config.loader import load_config
from core.config.production_strategy import (
    build_strategy_from_config,
    load_production_strategy,
)


# ---------------------------------------------------------------------------
# Contract: weights come only from the artifact
# ---------------------------------------------------------------------------


def test_no_hardcoded_factor_weights_in_production_scripts():
    """grep assertion: production scripts must NOT contain literal factor_weights dicts.

    Passes only if run_backtest.py / run_paper.py / run_multi_tf_backtest.py
    no longer have lines matching `factor_weights={"low_vol":...` or similar
    patterns. The live artifact is the only place these live.
    """
    import re
    scripts_to_check = [
        ROOT / "scripts" / "run_backtest.py",
        ROOT / "scripts" / "run_paper.py",
        ROOT / "scripts" / "run_multi_tf_backtest.py",
    ]
    # Match inline dicts assigning factor_weights with at least 3 factor keys.
    # This regex catches any literal dict with factor_weights= and 3+ common
    # factor names inline. False-positive-resistant.
    bad_pattern = re.compile(
        r'factor_weights\s*=\s*\{[^}]*("low_vol"|"momentum"|"quality"|"rel_strength")'
        r'[^}]*("low_vol"|"momentum"|"quality"|"rel_strength")[^}]*'
        r'("low_vol"|"momentum"|"quality"|"rel_strength")',
        re.DOTALL,
    )
    violations = []
    for p in scripts_to_check:
        if not p.exists():
            continue
        text = p.read_text()
        # strip comments that LOOK like dicts but aren't runtime
        if bad_pattern.search(text):
            violations.append(str(p.relative_to(ROOT)))
    assert not violations, (
        f"Scripts with hardcoded factor_weights (PRD M1 violation): "
        f"{violations}. Use load_production_strategy() instead."
    )


def test_artifact_yaml_is_valid_and_tracked():
    """config/production_strategy.yaml must exist and be loadable."""
    artifact = ROOT / "config" / "production_strategy.yaml"
    assert artifact.exists(), "config/production_strategy.yaml missing (PRD M1)"
    cfg = load_production_strategy(artifact)
    assert cfg.status in ("active", "conservative_default", "no_validated_best")


# ---------------------------------------------------------------------------
# Contract: same artifact produces identical strategies
# ---------------------------------------------------------------------------


def _build_from_artifact(symbols: list) -> object:
    """Helper mirroring what production scripts do."""
    config_dir = ROOT / "config"
    cfg = load_config(config_dir)
    ps_cfg = load_production_strategy()
    return build_strategy_from_config(ps_cfg, cfg.risk, symbols)


def test_repeated_builds_produce_equal_weights():
    """Two calls with same inputs → identical strategy weights / params."""
    symbols = ["SPY", "QQQ", "AAPL", "MSFT"]
    s1 = _build_from_artifact(symbols)
    s2 = _build_from_artifact(symbols)
    assert s1._weights == s2._weights
    assert s1._top_n == s2._top_n
    assert s1._mom_lb == s2._mom_lb
    assert s1._qual_lb == s2._qual_lb
    assert s1._vol_lb == s2._vol_lb
    assert s1._min_hold == s2._min_hold


def test_artifact_weights_match_yaml_literally():
    """Loaded strategy's weights must equal what YAML says."""
    symbols = ["SPY", "QQQ", "AAPL"]
    strat = _build_from_artifact(symbols)
    ps_cfg = load_production_strategy()
    assert strat._weights == ps_cfg.factor_weights


# ---------------------------------------------------------------------------
# Contract: backtest + paper + multi_tf all pull from the same source
# ---------------------------------------------------------------------------


def test_backtest_build_strategies_uses_artifact():
    """scripts/run_backtest.py::build_strategies must honor the artifact."""
    from scripts.run_backtest import build_strategies
    import pandas as pd

    config_dir = ROOT / "config"
    cfg = load_config(config_dir)
    empty = pd.DataFrame()
    strategies = build_strategies(cfg, empty, ["SPY", "QQQ", "AAPL"], ["TLT"])
    assert "multi_factor" in strategies
    # The multi_factor instance must have weights from the yaml artifact
    ps_cfg = load_production_strategy()
    assert strategies["multi_factor"]._weights == ps_cfg.factor_weights


def test_scripts_import_loader():
    """Sanity: each entrypoint imports production_strategy module."""
    scripts = {
        "scripts/run_backtest.py": "load_production_strategy",
        "scripts/run_paper.py": "load_production_strategy",
        "scripts/run_multi_tf_backtest.py": "load_production_strategy",
    }
    for rel, symbol in scripts.items():
        text = (ROOT / rel).read_text()
        assert symbol in text, f"{rel} does not import {symbol}"


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


def test_no_validated_best_blocks_builder(tmp_path):
    """If status is no_validated_best, builder refuses to construct."""
    yaml_text = """
schema_version: "1.0"
status: "no_validated_best"
strategy_type: "multi_factor"
source:
  mode: "manual"
  spec_id: ""
  lineage_tag: ""
  promoted_at: ""
  rationale: ""
params:
  top_n: 4
  rebalance_monthly: false
  score_weighted: true
  min_holding_days: 3
  lookback_mom: 189
  lookback_quality: 189
  lookback_vol: 84
  apply_extra_shift: false
factor_weights:
  low_vol: 0.20
  momentum: 0.20
  quality: 0.20
  pv_div: 0.10
  rel_strength: 0.20
  market_trend: 0.05
  drawup_from_252d_low: 0.05
validation:
  post_fix_validated: false
  passed_oos_gate: false
  passed_qqq_gate: false
  passed_paper_backtest_alignment: false
  notes: ""
fingerprints:
  universe_hash: ""
  factor_registry_hash: ""
  config_hash: ""
"""
    p = tmp_path / "nvb.yaml"
    p.write_text(yaml_text)
    ps_cfg = load_production_strategy(p)
    assert ps_cfg.status == "no_validated_best"
    config_dir = ROOT / "config"
    cfg = load_config(config_dir)
    from core.config.production_strategy import ProductionStrategyError
    with pytest.raises(ProductionStrategyError) as exc_info:
        build_strategy_from_config(ps_cfg, cfg.risk, ["SPY"])
    assert "no_validated_best" in str(exc_info.value)
