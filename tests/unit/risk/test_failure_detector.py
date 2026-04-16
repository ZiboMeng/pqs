"""Unit tests for FailureDetector and FailureSignal."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.risk.failure_detector import FailureDetector, FailureSignal


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _flat_equity(n: int = 100, val: float = 100_000.0) -> pd.Series:
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.Series(val, index=idx)


def _rising_equity(n: int = 300, cagr: float = 0.12) -> pd.Series:
    idx     = pd.bdate_range("2022-01-03", periods=n)
    daily_r = (1 + cagr) ** (1 / 252) - 1
    vals    = 100_000.0 * np.cumprod(1 + np.full(n, daily_r))
    return pd.Series(vals, index=idx)


def _crashing_equity(
    n_before: int = 50,
    n_crash:  int = 30,
    crash_pct: float = -0.25,
) -> pd.Series:
    """峰值后线性下跌指定比例。"""
    n   = n_before + n_crash
    idx = pd.bdate_range("2022-01-03", periods=n)
    v   = [100_000.0] * n_before
    end = 100_000.0 * (1 + crash_pct)
    v  += list(np.linspace(100_000.0, end, n_crash))
    return pd.Series(v, index=idx)


def _consecutive_loss_equity(n_loss: int = 5, base: float = 100_000.0) -> pd.Series:
    """在 n_loss 条亏损日前，先加几天平稳期，保证总数足够。"""
    pad = 20
    idx = pd.bdate_range("2022-01-03", periods=pad + n_loss)
    vals = [base] * pad
    for i in range(n_loss):
        vals.append(vals[-1] * 0.995)   # 每天跌 0.5%
    return pd.Series(vals, index=idx)


# ── FailureSignal ─────────────────────────────────────────────────────────────

class TestFailureSignal:
    def test_str_triggered(self):
        s = FailureSignal("rule", True, -0.25, -0.20, "desc", "critical")
        assert "TRIGGERED" in str(s)

    def test_str_ok(self):
        s = FailureSignal("rule", False, -0.05, -0.20, "desc", "warn")
        assert "OK" in str(s)

    def test_severity_stored(self):
        s = FailureSignal("rule", False, 0.0, 0.0, "", "critical")
        assert s.severity == "critical"

    def test_default_severity_warn(self):
        s = FailureSignal("rule", False, 0.0, 0.0, "")
        assert s.severity == "warn"


# ── check_drawdown ────────────────────────────────────────────────────────────

class TestCheckDrawdown:
    def test_not_triggered_for_rising_equity(self):
        eq = _rising_equity(100)
        fd = FailureDetector(max_drawdown=-0.20)
        sig = fd.check_drawdown(eq)
        assert sig.triggered is False

    def test_not_triggered_for_flat_equity(self):
        eq  = _flat_equity(50)
        fd  = FailureDetector(max_drawdown=-0.20)
        sig = fd.check_drawdown(eq)
        assert sig.triggered is False

    def test_triggered_on_large_drawdown(self):
        """回撤 -25% > 阈值 -20% → 触发。"""
        eq  = _crashing_equity(crash_pct=-0.25)
        fd  = FailureDetector(max_drawdown=-0.20)
        sig = fd.check_drawdown(eq)
        assert sig.triggered is True

    def test_not_triggered_below_threshold(self):
        """回撤 -10% < 阈值 -20% → 不触发。"""
        eq  = _crashing_equity(crash_pct=-0.10)
        fd  = FailureDetector(max_drawdown=-0.20)
        sig = fd.check_drawdown(eq)
        assert sig.triggered is False

    def test_severity_is_critical(self):
        eq  = _rising_equity(50)
        fd  = FailureDetector()
        sig = fd.check_drawdown(eq)
        assert sig.severity == "critical"

    def test_value_approximately_correct(self):
        """check_drawdown.value 应接近实际最大回撤。"""
        eq  = _crashing_equity(n_before=10, n_crash=10, crash_pct=-0.30)
        fd  = FailureDetector(max_drawdown=-0.40)
        sig = fd.check_drawdown(eq)
        assert sig.value == pytest.approx(-0.30, abs=0.02)

    def test_insufficient_data_not_triggered(self):
        eq  = pd.Series([100_000.0])   # 1 个点
        fd  = FailureDetector()
        sig = fd.check_drawdown(eq)
        assert sig.triggered is False


# ── check_loss_streak ─────────────────────────────────────────────────────────

class TestCheckLossStreak:
    def test_not_triggered_for_rising_equity(self):
        eq  = _rising_equity(50)
        fd  = FailureDetector(loss_streak=5)
        sig = fd.check_loss_streak(eq)
        assert sig.triggered is False

    def test_triggered_for_5_consecutive_losses(self):
        eq  = _consecutive_loss_equity(n_loss=5)
        fd  = FailureDetector(loss_streak=5)
        sig = fd.check_loss_streak(eq)
        assert sig.triggered is True

    def test_not_triggered_for_4_consecutive_losses(self):
        eq  = _consecutive_loss_equity(n_loss=4)
        fd  = FailureDetector(loss_streak=5)
        sig = fd.check_loss_streak(eq)
        assert sig.triggered is False

    def test_insufficient_data_not_triggered(self):
        eq  = pd.Series([100_000.0, 99_000.0, 98_000.0])
        fd  = FailureDetector(loss_streak=5)
        sig = fd.check_loss_streak(eq)
        assert sig.triggered is False

    def test_mixed_returns_not_triggered(self):
        """盈亏交替 → 不满足连续亏损条件。"""
        idx = pd.bdate_range("2022-01-03", periods=20)
        vals = [100_000.0]
        for i in range(19):
            vals.append(vals[-1] * (0.99 if i % 2 == 0 else 1.01))
        eq  = pd.Series(vals, index=idx)
        fd  = FailureDetector(loss_streak=5)
        sig = fd.check_loss_streak(eq)
        assert sig.triggered is False

    def test_rule_name_correct(self):
        eq  = _rising_equity(30)
        fd  = FailureDetector()
        sig = fd.check_loss_streak(eq)
        assert sig.rule_name == "loss_streak"


# ── check_rolling_sharpe ──────────────────────────────────────────────────────

class TestCheckRollingSharpe:
    def test_not_triggered_for_rising_equity(self):
        eq  = _rising_equity(200)
        fd  = FailureDetector(rolling_sharpe_thr=-0.5, rolling_sharpe_win=60)
        sig = fd.check_rolling_sharpe(eq)
        assert sig.triggered is False

    def test_triggered_for_severely_declining_equity(self):
        """持续下跌（带随机噪声）→ 滚动 Sharpe 很负 → 应触发。"""
        rng  = np.random.default_rng(42)
        idx  = pd.bdate_range("2022-01-03", periods=200)
        rets = rng.normal(-0.006, 0.003, 200)   # 强负漂移 + 少量噪声
        vals = [100_000.0]
        for r in rets[1:]:
            vals.append(vals[-1] * (1 + r))
        eq   = pd.Series(vals, index=idx)
        fd   = FailureDetector(rolling_sharpe_thr=-0.5, rolling_sharpe_win=60)
        sig  = fd.check_rolling_sharpe(eq)
        assert sig.triggered is True

    def test_insufficient_data_not_triggered(self):
        eq  = _rising_equity(30)   # < 60+1 天
        fd  = FailureDetector(rolling_sharpe_win=60)
        sig = fd.check_rolling_sharpe(eq)
        assert sig.triggered is False

    def test_rule_name_correct(self):
        eq  = _rising_equity(100)
        fd  = FailureDetector(rolling_sharpe_win=60)
        sig = fd.check_rolling_sharpe(eq)
        assert sig.rule_name == "rolling_sharpe"

    def test_value_is_float_or_nan(self):
        eq  = _rising_equity(200)
        fd  = FailureDetector(rolling_sharpe_win=60)
        sig = fd.check_rolling_sharpe(eq)
        assert isinstance(sig.value, float)


# ── check_vol_spike ───────────────────────────────────────────────────────────

class TestCheckVolSpike:
    def test_insufficient_data_not_triggered(self):
        """数据少于 vol_spike_win + vol_baseline_win → 不触发。"""
        eq  = _rising_equity(100)
        fd  = FailureDetector(vol_spike_win=20, vol_baseline_win=252)
        sig = fd.check_vol_spike(eq)
        assert sig.triggered is False

    def test_normal_vol_not_triggered(self):
        """均匀正态收益（无骤升）→ 不触发。"""
        rng = np.random.default_rng(0)
        idx = pd.bdate_range("2020-01-02", periods=400)
        eq  = pd.Series(
            100_000.0 * np.cumprod(1 + rng.normal(0.0003, 0.01, 400)),
            index=idx,
        )
        fd  = FailureDetector(vol_spike_mult=2.0, vol_spike_win=20, vol_baseline_win=252)
        sig = fd.check_vol_spike(eq)
        assert not sig.triggered

    def test_triggered_by_extreme_vol(self):
        """最后 20 天波动率 = 基准期 5x → 应触发。"""
        rng = np.random.default_rng(1)
        n   = 400
        idx = pd.bdate_range("2020-01-02", periods=n)
        low_vol  = rng.normal(0, 0.005, n - 20)    # 低波动率基准期
        high_vol = rng.normal(0, 0.05,  20)         # 高波动率近期
        rets = np.concatenate([low_vol, high_vol])
        eq   = pd.Series(100_000.0 * np.cumprod(1 + rets), index=idx)
        fd   = FailureDetector(vol_spike_mult=2.0, vol_spike_win=20, vol_baseline_win=252)
        sig  = fd.check_vol_spike(eq)
        assert sig.triggered

    def test_rule_name_correct(self):
        eq  = _rising_equity(100)
        fd  = FailureDetector()
        sig = fd.check_vol_spike(eq)
        assert sig.rule_name == "vol_spike"


# ── check_all / 聚合接口 ──────────────────────────────────────────────────────

class TestCheckAll:
    def test_returns_4_signals(self):
        eq      = _rising_equity(100)
        fd      = FailureDetector()
        signals = fd.check_all(eq)
        assert len(signals) == 4

    def test_rule_names_unique(self):
        eq      = _rising_equity(100)
        fd      = FailureDetector()
        names   = [s.rule_name for s in fd.check_all(eq)]
        assert len(set(names)) == 4

    def test_any_triggered_false_for_rising(self):
        eq = _rising_equity(300)
        fd = FailureDetector()
        assert fd.any_triggered(eq) is False

    def test_any_triggered_true_on_crash(self):
        eq = _crashing_equity(crash_pct=-0.25)
        fd = FailureDetector(max_drawdown=-0.20)
        assert fd.any_triggered(eq) is True

    def test_critical_triggered_only_for_drawdown(self):
        """连续亏损不是 critical，不触发 critical_triggered。"""
        eq  = _consecutive_loss_equity(n_loss=5)
        fd  = FailureDetector(loss_streak=5, max_drawdown=-0.80)  # 高回撤阈值
        assert fd.critical_triggered(eq) is False

    def test_critical_triggered_true_on_crash(self):
        eq = _crashing_equity(crash_pct=-0.25)
        fd = FailureDetector(max_drawdown=-0.20)
        assert fd.critical_triggered(eq) is True
