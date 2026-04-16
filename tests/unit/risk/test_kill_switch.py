"""Unit tests for KillSwitch and KillSwitchResult."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.risk.kill_switch import KillSwitch, KillSwitchConfig, KillSwitchResult


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _rising_equity(n: int = 300) -> pd.Series:
    idx     = pd.bdate_range("2022-01-03", periods=n)
    daily_r = (1.12 ** (1 / 252)) - 1
    vals    = 100_000.0 * np.cumprod(1 + np.full(n, daily_r))
    return pd.Series(vals, index=idx)


def _crashing_equity(crash_pct: float = -0.25, n_before: int = 50) -> pd.Series:
    n   = n_before + 30
    idx = pd.bdate_range("2022-01-03", periods=n)
    v   = [100_000.0] * n_before
    v  += list(np.linspace(100_000.0, 100_000.0 * (1 + crash_pct), 30))
    return pd.Series(v, index=idx)


def _losing_equity(n_loss: int = 6, pad: int = 20) -> pd.Series:
    """pad 天平稳 + n_loss 天连续亏损。"""
    idx  = pd.bdate_range("2022-01-03", periods=pad + n_loss)
    vals = [100_000.0] * pad
    for _ in range(n_loss):
        vals.append(vals[-1] * 0.995)
    return pd.Series(vals, index=idx)


# ── KillSwitchResult ──────────────────────────────────────────────────────────

class TestKillSwitchResult:
    def test_str_triggered(self):
        r = KillSwitchResult(triggered=True, active_rules=["max_drawdown"])
        assert "TRIGGERED" in str(r)
        assert "max_drawdown" in str(r)

    def test_str_not_triggered(self):
        r = KillSwitchResult(triggered=False)
        assert "正常" in str(r)

    def test_triggered_bool(self):
        r = KillSwitchResult(triggered=True)
        assert r.triggered is True

    def test_active_rules_list(self):
        r = KillSwitchResult(triggered=True, active_rules=["vix_spike", "loss_streak"])
        assert len(r.active_rules) == 2


# ── KillSwitch.evaluate ───────────────────────────────────────────────────────

class TestEvaluate:
    def test_returns_kill_switch_result(self):
        eq  = _rising_equity()
        ks  = KillSwitch()
        res = ks.evaluate(eq)
        assert isinstance(res, KillSwitchResult)

    def test_not_triggered_for_normal_equity(self):
        eq  = _rising_equity()
        ks  = KillSwitch()
        assert ks.evaluate(eq).triggered is False

    def test_triggered_by_drawdown(self):
        """回撤 -25% 超阈值 -20% → 触发。"""
        eq  = _crashing_equity(crash_pct=-0.25)
        ks  = KillSwitch(KillSwitchConfig(max_drawdown=-0.20))
        res = ks.evaluate(eq)
        assert res.triggered is True
        assert "max_drawdown" in res.active_rules

    def test_triggered_by_loss_streak(self):
        """连续 5 天亏损 → 触发。"""
        eq  = _losing_equity(n_loss=5)
        ks  = KillSwitch(KillSwitchConfig(loss_streak=5, max_drawdown=-0.90))
        res = ks.evaluate(eq)
        assert res.triggered is True
        assert "loss_streak" in res.active_rules

    def test_triggered_by_vix(self):
        """VIX ≥ 阈值 → 触发 vix_spike 规则。"""
        eq  = _rising_equity()
        ks  = KillSwitch(KillSwitchConfig(vix_threshold=40.0))
        res = ks.evaluate(eq, vix=45.0)
        assert res.triggered is True
        assert "vix_spike" in res.active_rules

    def test_not_triggered_by_vix_below_threshold(self):
        """VIX < 阈值 → vix_spike 不触发。"""
        eq  = _rising_equity()
        ks  = KillSwitch(KillSwitchConfig(vix_threshold=40.0))
        res = ks.evaluate(eq, vix=25.0)
        assert "vix_spike" not in res.active_rules

    def test_triggered_by_position_concentration(self):
        """单标的权重 > 阈值 → 触发 position_concentration。"""
        eq      = _rising_equity()
        ks      = KillSwitch(KillSwitchConfig(max_position_conc=0.80))
        weights = {"SPY": 0.95}   # > 0.80
        res     = ks.evaluate(eq, weights=weights)
        assert res.triggered is True
        assert "position_concentration" in res.active_rules

    def test_not_triggered_by_normal_concentration(self):
        eq      = _rising_equity()
        ks      = KillSwitch(KillSwitchConfig(max_position_conc=0.80))
        weights = {"SPY": 0.6, "QQQ": 0.4}   # 均未超 0.80
        res     = ks.evaluate(eq, weights=weights)
        assert "position_concentration" not in res.active_rules

    def test_multiple_rules_can_trigger_simultaneously(self):
        """多项规则同时触发时，active_rules 包含所有触发项。"""
        eq  = _crashing_equity(crash_pct=-0.25)
        ks  = KillSwitch(KillSwitchConfig(max_drawdown=-0.20, vix_threshold=40.0))
        res = ks.evaluate(eq, vix=50.0)
        assert res.triggered is True
        assert len(res.active_rules) >= 2

    def test_signals_list_length_without_optionals(self):
        """无 vix / weights → signals 数量等于 FailureDetector 检测项数（4）。"""
        eq  = _rising_equity()
        ks  = KillSwitch()
        res = ks.evaluate(eq)
        assert len(res.signals) == 4

    def test_signals_list_length_with_vix_and_weights(self):
        """提供 vix 和 weights → signals 数量 = 4 + 2 = 6。"""
        eq      = _rising_equity()
        ks      = KillSwitch()
        weights = {"SPY": 0.5, "QQQ": 0.5}
        res     = ks.evaluate(eq, vix=20.0, weights=weights)
        assert len(res.signals) == 6

    def test_active_rules_empty_when_not_triggered(self):
        eq  = _rising_equity()
        ks  = KillSwitch()
        res = ks.evaluate(eq)
        assert res.active_rules == []

    def test_config_custom_thresholds(self):
        """自定义严苛阈值（回撤 -1%）→ 正常回测也会触发。"""
        eq  = _crashing_equity(crash_pct=-0.05)
        cfg = KillSwitchConfig(max_drawdown=-0.01)
        ks  = KillSwitch(cfg)
        assert ks.evaluate(eq).triggered is True


# ── KillSwitch.is_triggered ───────────────────────────────────────────────────

class TestIsTriggered:
    def test_returns_bool(self):
        eq  = _rising_equity()
        ks  = KillSwitch()
        assert isinstance(ks.is_triggered(eq), bool)

    def test_false_for_normal(self):
        eq = _rising_equity()
        ks = KillSwitch()
        assert ks.is_triggered(eq) is False

    def test_true_for_crash(self):
        eq = _crashing_equity(crash_pct=-0.25)
        ks = KillSwitch(KillSwitchConfig(max_drawdown=-0.20))
        assert ks.is_triggered(eq) is True

    def test_consistent_with_evaluate(self):
        eq  = _rising_equity()
        ks  = KillSwitch()
        assert ks.is_triggered(eq) == ks.evaluate(eq).triggered


# ── KillSwitchConfig ──────────────────────────────────────────────────────────

class TestKillSwitchConfig:
    def test_default_values(self):
        cfg = KillSwitchConfig()
        assert cfg.max_drawdown == pytest.approx(-0.20)
        assert cfg.loss_streak == 5
        assert cfg.vix_threshold == pytest.approx(40.0)
        assert cfg.max_position_conc == pytest.approx(0.80)

    def test_custom_values(self):
        cfg = KillSwitchConfig(max_drawdown=-0.10, vix_threshold=30.0)
        assert cfg.max_drawdown == pytest.approx(-0.10)
        assert cfg.vix_threshold == pytest.approx(30.0)
