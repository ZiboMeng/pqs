"""
Unit tests for UniverseManager.

全部使用合成数据，无网络调用。
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.config.schemas.universe import UniverseConfig, UniverseLiquidityConfig
from core.universe.universe_manager import FilterResult, UniverseManager


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _make_config(
    seed_pool: list[str] | None = None,
    blacklist: list[str] | None = None,
    min_history_days: int = 60,    # pydantic ge=60
    min_price: float = 5.0,
    min_volume: int = 1_000_000,
) -> UniverseConfig:
    return UniverseConfig(
        seed_pool=seed_pool or ["SPY", "QQQ", "IWM"],
        blacklist=blacklist or ["SQQQ"],
        liquidity=UniverseLiquidityConfig(
            min_avg_volume_30d=min_volume,
            min_price_usd=min_price,
            min_history_days=min_history_days,
        ),
    )


def _make_ohlcv(
    periods: int = 80,             # > 60 → 默认通过历史天数过滤
    close: float = 100.0,
    volume: float = 5_000_000.0,
) -> pd.DataFrame:
    idx = pd.bdate_range("2022-01-03", periods=periods)
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": volume},
        index=idx,
    )


# ── 初始化 ─────────────────────────────────────────────────────────────────────

class TestInit:
    def test_watchlist_equals_seed_pool(self):
        cfg = _make_config(seed_pool=["SPY", "QQQ"])
        mgr = UniverseManager(cfg)
        assert set(mgr.get_watchlist()) == {"SPY", "QQQ"}

    def test_extra_watchlist_appended(self):
        cfg = _make_config(seed_pool=["SPY"])
        mgr = UniverseManager(cfg, extra_watchlist=["GLD"])
        assert "GLD" in mgr.get_watchlist()

    def test_candidate_empty_before_refresh(self):
        cfg = _make_config()
        mgr = UniverseManager(cfg)
        assert mgr.get_candidate_symbols() == []

    def test_active_empty_before_set(self):
        cfg = _make_config()
        mgr = UniverseManager(cfg)
        assert mgr.get_active_symbols() == []


# ── refresh 过滤 ───────────────────────────────────────────────────────────────

class TestRefresh:
    def test_all_symbols_pass_with_clean_data(self):
        cfg    = _make_config(seed_pool=["SPY", "QQQ"])   # min_history_days=60
        mgr    = UniverseManager(cfg)
        frames = {"SPY": _make_ohlcv(80), "QQQ": _make_ohlcv(80)}   # 80 > 60
        mgr.refresh(frames)
        assert set(mgr.get_candidate_symbols()) == {"SPY", "QQQ"}

    def test_blacklisted_symbol_excluded(self):
        # blacklist 中的 symbol 不能在 seed_pool 里（pydantic 校验）
        # 验证：add_to_watchlist 对黑名单 symbol 拒绝，refresh 不产生 candidate
        cfg = _make_config(seed_pool=["SPY"], blacklist=["SQQQ"])
        mgr = UniverseManager(cfg)
        ok  = mgr.add_to_watchlist("SQQQ")   # 应被拒绝
        assert ok is False
        mgr.refresh({"SPY": _make_ohlcv(80), "SQQQ": _make_ohlcv(80)})
        assert "SQQQ" not in mgr.get_candidate_symbols()

    def test_missing_data_excluded(self):
        cfg    = _make_config(seed_pool=["SPY", "QQQ"])
        mgr    = UniverseManager(cfg)
        frames = {"SPY": _make_ohlcv(80)}   # QQQ 无数据
        mgr.refresh(frames)
        assert "QQQ" not in mgr.get_candidate_symbols()
        assert "SPY" in mgr.get_candidate_symbols()

    def test_short_history_excluded(self):
        # min_history_days=100，提供 65 bars（< 100 且 >= 60）
        cfg    = _make_config(seed_pool=["SPY"], min_history_days=100)
        mgr    = UniverseManager(cfg)
        frames = {"SPY": _make_ohlcv(65)}   # 65 < 100
        mgr.refresh(frames)
        assert "SPY" not in mgr.get_candidate_symbols()

    def test_low_price_excluded(self):
        cfg    = _make_config(seed_pool=["LOWP"], min_price=5.0)
        mgr    = UniverseManager(cfg)
        frames = {"LOWP": _make_ohlcv(80, close=2.0)}
        mgr.refresh(frames)
        assert "LOWP" not in mgr.get_candidate_symbols()

    def test_low_volume_excluded(self):
        cfg    = _make_config(seed_pool=["LOWV"], min_volume=1_000_000)
        mgr    = UniverseManager(cfg)
        frames = {"LOWV": _make_ohlcv(80, volume=100_000)}   # 100k < 1M
        mgr.refresh(frames)
        assert "LOWV" not in mgr.get_candidate_symbols()

    def test_returns_filter_results(self):
        cfg     = _make_config(seed_pool=["SPY"])
        mgr     = UniverseManager(cfg)
        results = mgr.refresh({"SPY": _make_ohlcv(80)})
        assert len(results) == 1
        assert isinstance(results[0], FilterResult)

    def test_filter_log_populated_after_refresh(self):
        cfg = _make_config(seed_pool=["SPY"])
        mgr = UniverseManager(cfg)
        mgr.refresh({"SPY": _make_ohlcv(80)})
        log = mgr.get_filter_log()
        assert "SPY" in log


# ── active 管理 ───────────────────────────────────────────────────────────────

class TestActive:
    def _refreshed_mgr(self) -> UniverseManager:
        cfg = _make_config(seed_pool=["SPY", "QQQ"])   # min_history_days=60
        mgr = UniverseManager(cfg)
        mgr.refresh({"SPY": _make_ohlcv(80), "QQQ": _make_ohlcv(80)})
        return mgr

    def test_set_active_valid_symbols(self):
        mgr = self._refreshed_mgr()
        mgr.set_active(["SPY"])
        assert "SPY" in mgr.get_active_symbols()

    def test_set_active_non_candidate_ignored(self):
        mgr = self._refreshed_mgr()
        mgr.set_active(["GHOST"])    # 不在 candidate 中
        assert "GHOST" not in mgr.get_active_symbols()

    def test_is_active_correct(self):
        mgr = self._refreshed_mgr()
        mgr.set_active(["SPY"])
        assert mgr.is_active("SPY")
        assert not mgr.is_active("QQQ")


# ── watchlist / blacklist 动态操作 ────────────────────────────────────────────

class TestDynamicOps:
    def test_add_to_watchlist(self):
        cfg = _make_config(seed_pool=["SPY"])
        mgr = UniverseManager(cfg)
        mgr.add_to_watchlist("GLD")
        assert "GLD" in mgr.get_watchlist()

    def test_add_blacklisted_symbol_rejected(self):
        cfg = _make_config(seed_pool=["SPY"], blacklist=["SQQQ"])
        mgr = UniverseManager(cfg)
        ok  = mgr.add_to_watchlist("SQQQ")
        assert ok is False
        assert "SQQQ" not in mgr.get_watchlist()

    def test_add_duplicate_watchlist_noop(self):
        cfg = _make_config(seed_pool=["SPY"])
        mgr = UniverseManager(cfg)
        mgr.add_to_watchlist("SPY")
        assert mgr.get_watchlist().count("SPY") == 1

    def test_add_to_blacklist_removes_from_pools(self):
        cfg = _make_config(seed_pool=["SPY", "QQQ"])
        mgr = UniverseManager(cfg)
        mgr.refresh({"SPY": _make_ohlcv(80), "QQQ": _make_ohlcv(80)})
        mgr.set_active(["SPY"])

        mgr.add_to_blacklist("SPY")

        assert "SPY" not in mgr.get_watchlist()
        assert "SPY" not in mgr.get_candidate_symbols()
        assert "SPY" not in mgr.get_active_symbols()

    def test_is_blacklisted(self):
        cfg = _make_config(blacklist=["SQQQ"])
        mgr = UniverseManager(cfg)
        assert mgr.is_blacklisted("SQQQ")
        assert not mgr.is_blacklisted("SPY")

    def test_is_high_risk(self):
        from core.config.schemas.universe import HighRiskSymbolConfig
        cfg = UniverseConfig(
            seed_pool=["TQQQ", "SPY"],
            blacklist=[],
            high_risk_symbols=HighRiskSymbolConfig(symbols=["TQQQ"]),
        )
        mgr = UniverseManager(cfg)
        assert mgr.is_high_risk("TQQQ")
        assert not mgr.is_high_risk("SPY")


# ── summary ───────────────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_no_exception(self):
        cfg = _make_config()
        mgr = UniverseManager(cfg)
        s   = mgr.summary()
        assert "watchlist" in s
        assert "candidate" in s
