"""Tests for LeftSideTrading module."""

import numpy as np
import pandas as pd
import pytest

from core.signals.left_side import LeftSideTrading, LeftSideConfig


def _make_data(n=300, drop_pct=0.20):
    idx = pd.bdate_range("2020-01-01", periods=n)
    spy_vals = np.concatenate([
        np.linspace(300, 300 * (1 - drop_pct), n // 3),
        np.linspace(300 * (1 - drop_pct), 350, n - n // 3),
    ])
    spy = pd.Series(spy_vals, index=idx)
    prices = pd.DataFrame({
        "AAPL": spy * 0.8,
        "MSFT": spy * 1.1,
        "SPY": spy,
    }, index=idx)
    return spy, prices, idx


class TestLeftSideConfig:
    def test_default_disabled(self):
        cfg = LeftSideConfig()
        assert cfg.enabled is False

    def test_custom_config(self):
        cfg = LeftSideConfig(enabled=True, max_vix=35.0)
        assert cfg.max_vix == 35.0


class TestLeftSideDisabled:
    def test_returns_empty_when_disabled(self):
        lst = LeftSideTrading(LeftSideConfig(enabled=False))
        spy, prices, idx = _make_data()
        result = lst.generate_overlay(idx[100], prices, "RISK_OFF", 25, False, spy)
        assert result == {}

    def test_is_disabled_property(self):
        lst = LeftSideTrading(LeftSideConfig(enabled=False))
        assert lst.is_disabled is True


class TestLeftSideEntry:
    def test_no_entry_in_bull(self):
        lst = LeftSideTrading(LeftSideConfig(enabled=True, min_factor_consensus=2))
        spy, prices, idx = _make_data()
        result = lst.generate_overlay(idx[100], prices, "BULL", 25, False, spy)
        assert result == {}

    def test_no_entry_high_vix(self):
        lst = LeftSideTrading(LeftSideConfig(enabled=True, max_vix=30))
        spy, prices, idx = _make_data()
        result = lst.generate_overlay(idx[100], prices, "RISK_OFF", 35, False, spy)
        assert result == {}

    def test_no_entry_kill_switch(self):
        lst = LeftSideTrading(LeftSideConfig(enabled=True))
        spy, prices, idx = _make_data()
        result = lst.generate_overlay(idx[100], prices, "RISK_OFF", 25, True, spy)
        assert result == {}

    def test_entry_on_drawdown(self):
        n = 400
        idx = pd.bdate_range("2019-01-01", periods=n)
        spy_vals = np.concatenate([np.linspace(300, 220, 200), np.linspace(220, 350, 200)])
        spy = pd.Series(spy_vals, index=idx)
        aapl_vals = np.concatenate([np.linspace(200, 190, 200), np.linspace(190, 300, 200)])
        prices = pd.DataFrame({"AAPL": aapl_vals, "MSFT": spy_vals * 0.9, "SPY": spy_vals}, index=idx)
        lst = LeftSideTrading(LeftSideConfig(enabled=True, min_factor_consensus=2))
        result = lst.generate_overlay(idx[199], prices, "RISK_OFF", 25, False, spy)
        assert isinstance(result, dict)
        for w in result.values():
            assert w >= 0
            assert w <= 0.05


class TestLeftSideReset:
    def test_reset_clears_state(self):
        lst = LeftSideTrading(LeftSideConfig(enabled=True, min_factor_consensus=2))
        spy, prices, idx = _make_data(drop_pct=0.25)
        lst.generate_overlay(idx[99], prices, "RISK_OFF", 25, False, spy)
        lst.reset()
        assert len(lst._positions) == 0
        assert lst._consecutive_losses == 0
