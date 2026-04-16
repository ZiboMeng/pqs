"""
UniverseManager: 四层股票池管理。

四层结构
--------
  watchlist  → 系统关注的所有 symbol（来自 seed_pool 配置 + 动态加入）
  candidate  → 通过流动性/历史长度过滤、不在 blacklist 中
  active     → 当前持仓或今日信号触发
  blacklist  → 永久禁止交易（如做空 ETF）

每次 refresh() 时：
  1. 从 watchlist 中逐一过滤 → candidate
  2. 调用方可进一步从 candidate 中选出 active

线程安全：本类不做并发写，适用于单进程批跑场景。

用法示例
--------
    mgr = UniverseManager(config=universe_cfg)
    mgr.refresh(ohlcv_frames)           # 传入 {sym: DataFrame}
    symbols = mgr.get_candidate_symbols()
    mgr.set_active(["SPY", "QQQ"])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Set

import pandas as pd

from core.config.schemas.universe import UniverseConfig
from core.logging_setup import get_logger

logger = get_logger(__name__)


# ── 过滤结果 ──────────────────────────────────────────────────────────────────

@dataclass
class FilterResult:
    """单个 symbol 的过滤诊断信息。"""
    symbol:   str
    eligible: bool
    reasons:  List[str] = field(default_factory=list)   # 被踢出的原因

    def __str__(self) -> str:
        status = "OK" if self.eligible else f"SKIP({', '.join(self.reasons)})"
        return f"{self.symbol}: {status}"


# ── 核心类 ────────────────────────────────────────────────────────────────────

class UniverseManager:
    """
    管理四层股票池：watchlist / candidate / active / blacklist。

    Parameters
    ----------
    config : UniverseConfig
        来自 YAML 加载的 pydantic 配置对象。
    extra_watchlist : list[str]
        程序化追加的关注标的（不影响配置文件）。
    """

    def __init__(
        self,
        config:           UniverseConfig,
        extra_watchlist:  Optional[List[str]] = None,
    ):
        self._config     = config
        self._watchlist: List[str]  = list(config.seed_pool) + list(extra_watchlist or [])
        self._candidate: List[str]  = []
        self._active:    Set[str]   = set()
        self._filter_log: Dict[str, FilterResult] = {}

    # ── 公开 API ──────────────────────────────────────────────────────────────

    def refresh(
        self,
        ohlcv_frames: Dict[str, pd.DataFrame],
        as_of: Optional[date] = None,
    ) -> List[FilterResult]:
        """
        重新计算 candidate 池。

        传入当前各 symbol 的日频 OHLCV DataFrame，逐一做流动性 / 历史 / blacklist 检查。

        Returns
        -------
        list[FilterResult]  每个 watchlist symbol 的过滤结果（包含通过和不通过）。
        """
        results: List[FilterResult] = []

        for sym in self._watchlist:
            df  = ohlcv_frames.get(sym)
            res = self._filter_symbol(sym, df)
            results.append(res)
            self._filter_log[sym] = res

        self._candidate = [r.symbol for r in results if r.eligible]

        passed = len(self._candidate)
        total  = len(self._watchlist)
        logger.info(
            "Universe refresh: %d/%d symbols passed filters → candidate pool",
            passed, total,
        )
        return results

    def get_watchlist(self) -> List[str]:
        """返回完整 watchlist（seed_pool + extra）。"""
        return list(self._watchlist)

    def get_candidate_symbols(self) -> List[str]:
        """返回通过过滤的候选 symbol 列表（调用 refresh 后有效）。"""
        return list(self._candidate)

    def get_active_symbols(self) -> List[str]:
        """返回当前活跃（持仓或今日信号触发）的 symbol 列表。"""
        return sorted(self._active)

    def set_active(self, symbols: List[str]) -> None:
        """
        设置活跃 symbol 集合。
        只允许将 candidate 中的 symbol 设为 active；其余被忽略并记警告。
        """
        candidate_set = set(self._candidate)
        valid   = [s for s in symbols if s in candidate_set]
        invalid = [s for s in symbols if s not in candidate_set]
        if invalid:
            logger.warning(
                "set_active: %d symbols not in candidate pool (ignored): %s",
                len(invalid), invalid,
            )
        self._active = set(valid)

    def add_to_watchlist(self, symbol: str) -> bool:
        """
        动态加入 watchlist。
        若已在 blacklist 中则拒绝，返回 False；否则加入并返回 True。
        """
        if self._config.is_blacklisted(symbol):
            logger.warning("add_to_watchlist: %s is blacklisted, rejected", symbol)
            return False
        if symbol not in self._watchlist:
            self._watchlist.append(symbol)
        return True

    def add_to_blacklist(self, symbol: str) -> None:
        """
        临时将 symbol 加入黑名单（内存级，不修改配置文件）。
        同时从 watchlist / candidate / active 中移除。
        """
        if symbol not in self._config.blacklist:
            # 修改运行时黑名单（不修改 pydantic 配置）
            self._config.blacklist.append(symbol)
        self._watchlist  = [s for s in self._watchlist  if s != symbol]
        self._candidate  = [s for s in self._candidate  if s != symbol]
        self._active.discard(symbol)
        logger.info("add_to_blacklist: %s added to blacklist", symbol)

    def is_candidate(self, symbol: str) -> bool:
        return symbol in self._candidate

    def is_active(self, symbol: str) -> bool:
        return symbol in self._active

    def is_blacklisted(self, symbol: str) -> bool:
        return self._config.is_blacklisted(symbol)

    def is_high_risk(self, symbol: str) -> bool:
        return self._config.is_high_risk(symbol)

    def get_filter_log(self) -> Dict[str, FilterResult]:
        """返回最近一次 refresh 的逐 symbol 过滤结果。"""
        return dict(self._filter_log)

    def summary(self) -> str:
        """返回当前状态摘要字符串（便于日志输出）。"""
        lines = [
            f"UniverseManager summary",
            f"  watchlist : {len(self._watchlist)} symbols",
            f"  candidate : {len(self._candidate)} symbols → {self._candidate}",
            f"  active    : {len(self._active)} symbols → {sorted(self._active)}",
            f"  blacklist : {self._config.blacklist}",
        ]
        return "\n".join(lines)

    # ── 内部过滤逻辑 ──────────────────────────────────────────────────────────

    def _filter_symbol(
        self,
        symbol: str,
        df:     Optional[pd.DataFrame],
    ) -> FilterResult:
        """对单个 symbol 执行全部过滤规则，返回 FilterResult。"""
        res = FilterResult(symbol=symbol, eligible=True)
        liq = self._config.liquidity

        # 1. Blacklist
        if self._config.is_blacklisted(symbol):
            res.eligible = False
            res.reasons.append("blacklisted")
            return res   # 黑名单直接返回，不再做后续检查

        # 2. 数据是否存在
        if df is None or df.empty:
            res.eligible = False
            res.reasons.append("no_data")
            return res

        # 3. 最少历史天数
        if len(df) < liq.min_history_days:
            res.eligible = False
            res.reasons.append(
                f"history_too_short({len(df)}<{liq.min_history_days})"
            )

        # 4. 最低价格（用最近 close 判断）
        last_close = df["close"].iloc[-1] if "close" in df.columns else None
        if last_close is not None and last_close < liq.min_price_usd:
            res.eligible = False
            res.reasons.append(
                f"price_too_low({last_close:.2f}<{liq.min_price_usd})"
            )

        # 5. 最低成交量（30 日均量）
        if "volume" in df.columns:
            vol_window = min(30, len(df))
            avg_vol = df["volume"].iloc[-vol_window:].mean()
            if avg_vol < liq.min_avg_volume_30d:
                res.eligible = False
                res.reasons.append(
                    f"volume_too_low({avg_vol:.0f}<{liq.min_avg_volume_30d})"
                )

        return res
