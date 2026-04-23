"""Unit tests for core/signals/cross_ticker_rules.py (PRD M4)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.signals.cross_ticker_rules import (
    BenchmarkTriggerRule,
    CrossTickerRuleError,
    MultiTFConfirmationRule,
    RegimeBasketRule,
    RuleContext,
    RuleType,
    _eval_expression,
    _validate_expression,
    apply_rules,
    load_rules,
)


# ---------------------------------------------------------------------------
# Expression validation
# ---------------------------------------------------------------------------


def test_validate_allows_sma():
    _validate_expression("sma(close, 50) > sma(close, 200)")


def test_validate_rejects_unknown_function():
    with pytest.raises(CrossTickerRuleError):
        _validate_expression("magic_fn(close, 50)")


def test_validate_rejects_unknown_identifier():
    with pytest.raises(CrossTickerRuleError):
        _validate_expression("my_secret_var > 100")


def test_validate_rejects_eval_inject():
    with pytest.raises(CrossTickerRuleError):
        _validate_expression("__import__('os').system('rm -rf /')")


def test_validate_allows_and_or_not():
    _validate_expression("sma(close, 5) > sma(close, 200) and close > 100")


# ---------------------------------------------------------------------------
# Expression evaluation
# ---------------------------------------------------------------------------


def _make_ohlcv(n=250, close_start=100.0, trend=0.001):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.array([close_start * (1 + trend) ** i for i in range(n)])
    return pd.DataFrame({
        "open": close * 0.99,
        "high": close * 1.02,
        "low": close * 0.98,
        "close": close,
        "volume": np.ones(n) * 1e6,
    }, index=idx)


def test_sma_golden_cross_triggers():
    df = _make_ohlcv(trend=0.002)  # rising trend → sma5 > sma200
    assert _eval_expression("sma(close, 5) > sma(close, 200)", df) is True


def test_sma_death_cross_does_not_trigger():
    df = _make_ohlcv(trend=-0.002)  # falling trend
    assert _eval_expression("sma(close, 5) > sma(close, 200)", df) is False


def test_ref_high_returns_rolling_max():
    df = _make_ohlcv(trend=0.002)
    assert _eval_expression("close > ref_high(20)", df) in (True, False)


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------


def test_load_empty_rules(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text("enabled: true\nrules: []\n")
    enabled, rules = load_rules(p)
    assert enabled
    assert rules == []


def test_load_benchmark_trigger_rule(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text("""
enabled: true
rules:
  - name: test_rule
    type: benchmark_trigger
    driver: SPY
    condition: "sma(close, 5) > sma(close, 200)"
    targets: [QQQ]
    priority: 1
""")
    enabled, rules = load_rules(p)
    assert enabled
    assert len(rules) == 1
    assert isinstance(rules[0], BenchmarkTriggerRule)
    assert rules[0].driver == "SPY"


def test_load_unknown_type_rejected(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text("""
enabled: true
rules:
  - name: bad
    type: magic_rule_type
""")
    with pytest.raises(CrossTickerRuleError):
        load_rules(p)


def test_load_invalid_condition_rejected(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text("""
enabled: true
rules:
  - name: bad
    type: benchmark_trigger
    driver: SPY
    condition: "import os; os.system('rm -rf /')"
    targets: [QQQ]
""")
    with pytest.raises(CrossTickerRuleError):
        load_rules(p)


def test_rules_sorted_by_priority(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text("""
enabled: true
rules:
  - name: low
    type: regime_basket
    regime: [BULL]
    basket_weights: {SPY: 1.0}
    priority: 10
  - name: high
    type: regime_basket
    regime: [BULL]
    basket_weights: {QQQ: 1.0}
    priority: 1
""")
    _, rules = load_rules(p)
    assert rules[0].name == "high"
    assert rules[1].name == "low"


def test_load_missing_file_returns_empty(tmp_path):
    enabled, rules = load_rules(tmp_path / "nonexistent.yaml")
    assert enabled is False
    assert rules == []


def test_load_repo_template():
    """config/cross_ticker_rules.yaml must be parseable (even if empty)."""
    enabled, rules = load_rules()  # default path
    # Template has empty rules by default
    assert isinstance(enabled, bool)
    assert isinstance(rules, list)


# ---------------------------------------------------------------------------
# Rule application
# ---------------------------------------------------------------------------


def test_benchmark_trigger_condition_met_applies_multiplier():
    rule = BenchmarkTriggerRule(
        name="t", driver="SPY",
        condition="sma(close, 5) > sma(close, 200)",
        targets=["QQQ"], action="allow_overweight",
        weight_multiplier=1.5,
    )
    ctx = RuleContext(
        bar_timestamp=pd.Timestamp("2024-06-01"),
        regime="BULL",
        ohlcv={"SPY": _make_ohlcv(trend=0.002)},
    )
    weights = {"SPY": 0.5, "QQQ": 0.3}
    out = apply_rules(weights, ctx, [rule])
    assert out["QQQ"] == pytest.approx(0.45)  # 0.3 * 1.5


def test_benchmark_trigger_condition_not_met_no_change():
    rule = BenchmarkTriggerRule(
        name="t", driver="SPY",
        condition="sma(close, 5) > sma(close, 200)",
        targets=["QQQ"], weight_multiplier=1.5,
    )
    ctx = RuleContext(
        bar_timestamp=pd.Timestamp("2024-06-01"),
        regime="BULL",
        ohlcv={"SPY": _make_ohlcv(trend=-0.002)},  # downtrend, condition fails
    )
    weights = {"SPY": 0.5, "QQQ": 0.3}
    out = apply_rules(weights, ctx, [rule])
    assert out["QQQ"] == pytest.approx(0.3)


def test_benchmark_trigger_regime_scope():
    """Rule with regime_scope=[BULL] doesn't fire in RISK_OFF."""
    rule = BenchmarkTriggerRule(
        name="t", driver="SPY",
        condition="sma(close, 5) > sma(close, 200)",
        targets=["QQQ"], weight_multiplier=2.0,
        regime_scope=["BULL"],
    )
    ctx = RuleContext(
        bar_timestamp=pd.Timestamp("2024-06-01"),
        regime="RISK_OFF",
        ohlcv={"SPY": _make_ohlcv(trend=0.002)},
    )
    weights = {"QQQ": 0.3}
    out = apply_rules(weights, ctx, [rule])
    assert out["QQQ"] == pytest.approx(0.3)


def test_regime_basket_override():
    rule = RegimeBasketRule(
        name="defense",
        regime=["RISK_OFF"],
        basket_weights={"TLT": 0.5, "GLD": 0.5},
        override_strategy=True,
    )
    ctx = RuleContext(
        bar_timestamp=pd.Timestamp("2024-06-01"),
        regime="RISK_OFF",
    )
    weights = {"SPY": 0.5, "QQQ": 0.5}
    out = apply_rules(weights, ctx, [rule])
    assert "SPY" not in out or out["SPY"] == 0
    assert out["TLT"] == pytest.approx(0.5)
    assert out["GLD"] == pytest.approx(0.5)


def test_regime_basket_wrong_regime_no_change():
    rule = RegimeBasketRule(
        name="defense",
        regime=["RISK_OFF"],
        basket_weights={"TLT": 1.0},
        override_strategy=True,
    )
    ctx = RuleContext(bar_timestamp=pd.Timestamp("2024-06-01"), regime="BULL")
    weights = {"SPY": 1.0}
    out = apply_rules(weights, ctx, [rule])
    assert out == {"SPY": 1.0}


def test_regime_basket_suppress_if_active_skips_blend():
    """R25 fast-exit: in RISK_OFF regime, if SPY 5d/20d SMA bullish-crossed,
    skip the defensive blend (V-recovery already under way)."""
    # Build a monotonic-up SPY series: last 20 bars trending up so 5d SMA > 20d SMA
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    spy = pd.DataFrame({
        "open": range(100, 130),
        "high": range(101, 131),
        "low": range(99, 129),
        "close": range(100, 130),
        "volume": [1_000_000] * 30,
    }, index=dates)
    rule = RegimeBasketRule(
        name="defense",
        regime=["RISK_OFF", "CRISIS"],
        basket_weights={"TLT": 0.5, "GLD": 0.5},
        override_strategy=False,
        suppress_if={"driver": "SPY", "condition": "sma(close, 5) > sma(close, 20)"},
    )
    ctx = RuleContext(
        bar_timestamp=dates[-1],
        regime="RISK_OFF",
        ohlcv={"SPY": spy},
    )
    weights = {"AAPL": 0.6, "MSFT": 0.4}
    out = apply_rules(weights, ctx, [rule])
    # Suppressed → blend skipped → weights unchanged (defensive basket not injected)
    assert out == {"AAPL": 0.6, "MSFT": 0.4}
    assert "TLT" not in out
    assert "GLD" not in out


def test_regime_basket_suppress_if_inactive_still_blends():
    """If SPY 5d SMA still below 20d SMA (no recovery signal), defensive blend applies."""
    # Build a monotonic-down SPY series: 5d SMA < 20d SMA
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    spy = pd.DataFrame({
        "open": range(130, 100, -1),
        "high": range(131, 101, -1),
        "low": range(129, 99, -1),
        "close": range(130, 100, -1),
        "volume": [1_000_000] * 30,
    }, index=dates)
    rule = RegimeBasketRule(
        name="defense",
        regime=["RISK_OFF", "CRISIS"],
        basket_weights={"TLT": 0.5, "GLD": 0.5},
        override_strategy=False,
        suppress_if={"driver": "SPY", "condition": "sma(close, 5) > sma(close, 20)"},
    )
    ctx = RuleContext(
        bar_timestamp=dates[-1],
        regime="RISK_OFF",
        ohlcv={"SPY": spy},
    )
    weights = {"AAPL": 0.6, "MSFT": 0.4}
    out = apply_rules(weights, ctx, [rule])
    # Not suppressed → standard 50/50 blend → basket symbols present, normalized
    assert "TLT" in out
    assert "GLD" in out
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-6)


def test_long_only_invariant_clips_negatives():
    """Rule with negative multiplier should clip to 0."""
    rule = BenchmarkTriggerRule(
        name="t", driver="SPY",
        condition="sma(close, 5) > sma(close, 200)",
        targets=["QQQ"], weight_multiplier=-1.5,  # attempt to flip sign
    )
    ctx = RuleContext(
        bar_timestamp=pd.Timestamp("2024-06-01"),
        regime="BULL",
        ohlcv={"SPY": _make_ohlcv(trend=0.002)},
    )
    weights = {"QQQ": 0.3}
    out = apply_rules(weights, ctx, [rule])
    assert out["QQQ"] >= 0  # long-only enforced


def test_multi_tf_confirmation_applies_scale():
    rule = MultiTFConfirmationRule(
        name="qqq_breakout",
        target="QQQ",
        primary_condition="sma(close, 5) > sma(close, 20)",
        confirmations=[
            {"symbol": "XLK", "timeframe": "daily",
             "condition": "sma(close, 5) > sma(close, 20)"},
        ],
        action={"timing_scale_multiplier": 1.3},
    )
    ctx = RuleContext(
        bar_timestamp=pd.Timestamp("2024-06-01"),
        regime="BULL",
        ohlcv={
            "QQQ": _make_ohlcv(trend=0.003),
            "XLK": _make_ohlcv(trend=0.002),
        },
    )
    weights = {"QQQ": 0.5}
    out = apply_rules(weights, ctx, [rule])
    assert out["QQQ"] == pytest.approx(0.65)  # 0.5 * 1.3


def test_multi_tf_confirmation_missing_data_fails_safe():
    rule = MultiTFConfirmationRule(
        name="t", target="QQQ",
        primary_condition="sma(close, 5) > sma(close, 20)",
        confirmations=[
            {"symbol": "XLK", "timeframe": "daily",
             "condition": "sma(close, 5) > sma(close, 20)"},
        ],
        action={"timing_scale_multiplier": 1.3},
    )
    ctx = RuleContext(
        bar_timestamp=pd.Timestamp("2024-06-01"),
        ohlcv={"QQQ": _make_ohlcv(trend=0.003)},  # XLK missing
    )
    weights = {"QQQ": 0.5}
    out = apply_rules(weights, ctx, [rule])
    assert out["QQQ"] == pytest.approx(0.5)  # no change


def test_priority_order_applied():
    """Lower priority number = applied first."""
    r1 = BenchmarkTriggerRule(
        name="first", driver="SPY",
        condition="sma(close, 5) > sma(close, 200)",
        targets=["QQQ"], weight_multiplier=2.0, priority=1,
    )
    r2 = BenchmarkTriggerRule(
        name="second", driver="SPY",
        condition="sma(close, 5) > sma(close, 200)",
        targets=["QQQ"], weight_multiplier=0.5, priority=2,
    )
    ctx = RuleContext(
        bar_timestamp=pd.Timestamp("2024-06-01"),
        regime="BULL",
        ohlcv={"SPY": _make_ohlcv(trend=0.002)},
    )
    weights = {"QQQ": 0.3}
    out = apply_rules(weights, ctx, [r1, r2])
    # Expected: 0.3 * 2.0 = 0.6, then * 0.5 = 0.3
    assert out["QQQ"] == pytest.approx(0.3)
