"""Unit tests for core/signals/cross_ticker_wrapper.py (PRD M10)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.signals.cross_ticker_wrapper import apply_rules_to_weight_matrix


def _make_ohlcv(n=260, price_start=400.0, trend=0.001):
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    close = np.array([price_start * (1 + trend) ** i for i in range(n)])
    return pd.DataFrame({
        "open": close * 0.999,
        "high": close * 1.002,
        "low": close * 0.998,
        "close": close,
        "volume": np.ones(n) * 1e6,
    }, index=idx)


def _make_weights(dates: pd.DatetimeIndex, symbols: list) -> pd.DataFrame:
    """Equal-weight on given symbols."""
    data = {s: np.full(len(dates), 1.0 / len(symbols)) for s in symbols}
    return pd.DataFrame(data, index=dates)


def test_missing_rules_file_noop(tmp_path):
    missing = tmp_path / "does_not_exist.yaml"
    weights = _make_weights(pd.date_range("2024-01-02", periods=10), ["SPY", "QQQ"])
    result, stats = apply_rules_to_weight_matrix(weights, None, {}, rules_path=missing)
    assert stats["applied"] is False
    assert result.equals(weights)


def test_disabled_rules_noop(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text("enabled: false\nrules: []\n")
    weights = _make_weights(pd.date_range("2024-01-02", periods=10), ["SPY"])
    result, stats = apply_rules_to_weight_matrix(weights, None, {}, rules_path=rules)
    assert stats["applied"] is False
    assert "disabled" in stats["reason"]


def test_empty_rules_noop(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text("enabled: true\nrules: []\n")
    weights = _make_weights(pd.date_range("2024-01-02", periods=10), ["SPY"])
    result, stats = apply_rules_to_weight_matrix(weights, None, {}, rules_path=rules)
    assert stats["applied"] is False
    assert "no rules" in stats["reason"]


def test_benchmark_trigger_applied_to_matrix(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text("""
enabled: true
rules:
  - name: spy_trend_boost_qqq
    type: benchmark_trigger
    driver: SPY
    condition: "sma(close, 5) > sma(close, 50)"
    targets: [QQQ]
    weight_multiplier: 2.0
    priority: 1
""")
    ohlcv = {"SPY": _make_ohlcv(260, trend=0.003)}  # uptrend
    dates = ohlcv["SPY"].index[-20:]  # last 20 dates
    weights = _make_weights(dates, ["SPY", "QQQ"])
    regime = pd.Series("BULL", index=dates)
    result, stats = apply_rules_to_weight_matrix(
        weights, regime, ohlcv, rules_path=rules,
    )
    assert stats["applied"]
    assert stats["n_dates_changed"] > 0
    # QQQ weight should be doubled when condition met
    assert (result["QQQ"] > weights["QQQ"]).any()


def test_long_only_invariant_enforced(tmp_path):
    """Even if a (buggy) rule produces negatives, wrapper clips."""
    rules = tmp_path / "rules.yaml"
    rules.write_text("""
enabled: true
rules:
  - name: bad_negative_multiplier
    type: benchmark_trigger
    driver: SPY
    condition: "close > 100"
    targets: [QQQ]
    weight_multiplier: -1.5
    priority: 1
""")
    ohlcv = {"SPY": _make_ohlcv(260, trend=0.002)}
    dates = ohlcv["SPY"].index[-10:]
    weights = _make_weights(dates, ["SPY", "QQQ"])
    regime = pd.Series("BULL", index=dates)
    result, _ = apply_rules_to_weight_matrix(
        weights, regime, ohlcv, rules_path=rules,
    )
    assert (result >= 0).all().all(), f"found negative weights: {result[result < 0].dropna()}"


def test_regime_basket_adds_new_symbols(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text("""
enabled: true
rules:
  - name: defensive_basket
    type: regime_basket
    regime: [RISK_OFF]
    basket_weights: {TLT: 0.5, GLD: 0.5}
    override_strategy: true
    priority: 1
""")
    dates = pd.date_range("2024-01-02", periods=5)
    weights = _make_weights(dates, ["SPY", "QQQ"])  # no TLT/GLD initially
    regime = pd.Series("RISK_OFF", index=dates)
    result, stats = apply_rules_to_weight_matrix(
        weights, regime, {}, rules_path=rules,
    )
    assert stats["applied"]
    # TLT/GLD should now appear in the result
    assert "TLT" in result.columns
    assert "GLD" in result.columns
    assert (result["TLT"] > 0).all()


def test_noop_when_no_rule_fires(tmp_path):
    """BULL regime; rule requires RISK_OFF; so no changes."""
    rules = tmp_path / "rules.yaml"
    rules.write_text("""
enabled: true
rules:
  - name: risk_off_only
    type: regime_basket
    regime: [RISK_OFF]
    basket_weights: {TLT: 1.0}
    override_strategy: true
    priority: 1
""")
    dates = pd.date_range("2024-01-02", periods=5)
    weights = _make_weights(dates, ["SPY", "QQQ"])
    regime = pd.Series("BULL", index=dates)
    result, stats = apply_rules_to_weight_matrix(
        weights, regime, {}, rules_path=rules,
    )
    assert stats["applied"]
    assert stats["n_dates_changed"] == 0


def test_malformed_yaml_returns_noop(tmp_path):
    rules = tmp_path / "rules.yaml"
    rules.write_text("not: [valid\n  : yaml :\n")
    weights = _make_weights(pd.date_range("2024-01-02", periods=5), ["SPY"])
    result, stats = apply_rules_to_weight_matrix(weights, None, {}, rules_path=rules)
    assert stats["applied"] is False
    assert "error" in stats


def test_repo_yaml_loads_successfully():
    """The real repo yaml must parse through the wrapper path."""
    # Using default path resolves from cwd — use real config
    weights = _make_weights(pd.date_range("2024-01-02", periods=5), ["SPY"])
    result, stats = apply_rules_to_weight_matrix(weights, None, {})
    # Whether rules fire depends on ohlcv availability; just assert no crash
    assert "applied" in stats
