"""
LeftSideTrading: controlled contrarian entry during drawdowns.

Enhancement module only — never the default engine. Generates small
position signals when multiple factors agree the market is oversold
and regime allows it.

Rules (from risk.yaml):
  - Only in allowed_regimes (default: RISK_OFF)
  - Market drawdown > min_drawdown_from_peak (-15%)
  - Factor consensus >= min_factor_consensus (3+ factors agree)
  - VIX < max_vix (40)
  - Kill switch not active
  - Max single position 5%, build in 3 tranches
  - Time stop (15d) and loss stop (-8%)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import numpy as np
import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class LeftSideConfig:
    enabled: bool = False
    allowed_regimes: List[str] = field(default_factory=lambda: ["RISK_OFF"])
    min_drawdown_from_peak: float = -0.15
    min_factor_consensus: int = 3
    max_vix: float = 40.0
    no_active_kill_switch: bool = True
    max_single_position: float = 0.05
    build_in_tranches: int = 3
    tranche_interval_days: int = 3
    time_stop_days: int = 15
    loss_stop_pct: float = -0.08
    profit_target_pct: float = 0.15
    auto_disable_on_consecutive_loss: int = 3

    @classmethod
    def from_risk_config(cls, risk_cfg) -> "LeftSideConfig":
        """Create from cfg.risk.left_side_trading (pydantic model)."""
        ls = risk_cfg.left_side_trading
        return cls(
            enabled=ls.enabled,
            allowed_regimes=list(ls.allowed_regimes),
            min_drawdown_from_peak=ls.min_drawdown_from_peak,
            min_factor_consensus=ls.min_factor_consensus,
            max_vix=ls.max_vix,
            no_active_kill_switch=ls.no_active_kill_switch,
            max_single_position=ls.max_single_position,
            build_in_tranches=ls.build_in_tranches,
            tranche_interval_days=ls.tranche_interval_days,
            time_stop_days=ls.time_stop_days,
            loss_stop_pct=ls.loss_stop_pct,
            profit_target_pct=ls.profit_target_pct,
            auto_disable_on_consecutive_loss=ls.auto_disable_on_consecutive_loss,
        )


@dataclass
class LeftSidePosition:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    tranches_filled: int
    target_weight: float


class LeftSideTrading:
    """
    Controlled left-side (contrarian) entry module.

    Generates overlay signals to add to the main strategy weights.
    """

    def __init__(self, config: Optional[LeftSideConfig] = None):
        self._cfg = config or LeftSideConfig()
        self._positions: Dict[str, LeftSidePosition] = {}
        self._consecutive_losses: int = 0
        self._disabled: bool = not self._cfg.enabled

    def generate_overlay(
        self,
        date: pd.Timestamp,
        price_df: pd.DataFrame,
        regime: str,
        vix: float,
        kill_switch_active: bool,
        spy_series: pd.Series,
    ) -> Dict[str, float]:
        """
        Generate left-side overlay weights for the current date.

        Returns dict of {symbol: additional_weight} to add to main strategy.
        """
        if self._disabled or not self._cfg.enabled:
            return {}

        overlay: Dict[str, float] = {}

        self._manage_exits(date, price_df, overlay)

        if not self._should_enter(regime, vix, kill_switch_active, spy_series, date):
            return overlay

        candidates = self._find_candidates(date, price_df, spy_series)
        if len(candidates) < self._cfg.min_factor_consensus:
            return overlay

        for sym in candidates[:2]:
            if sym in self._positions:
                pos = self._positions[sym]
                if pos.tranches_filled < self._cfg.build_in_tranches:
                    w = self._cfg.max_single_position / self._cfg.build_in_tranches
                    overlay[sym] = w
                    pos.tranches_filled += 1
            else:
                w = self._cfg.max_single_position / self._cfg.build_in_tranches
                overlay[sym] = w
                price = float(price_df.loc[date, sym]) if sym in price_df.columns else 0
                self._positions[sym] = LeftSidePosition(
                    symbol=sym, entry_date=date, entry_price=price,
                    tranches_filled=1, target_weight=w,
                )

        return overlay

    def _should_enter(
        self, regime: str, vix: float, ks_active: bool, spy: pd.Series, date: pd.Timestamp,
    ) -> bool:
        if regime not in self._cfg.allowed_regimes:
            return False
        if vix > self._cfg.max_vix:
            return False
        if self._cfg.no_active_kill_switch and ks_active:
            return False
        if self._consecutive_losses >= self._cfg.auto_disable_on_consecutive_loss:
            return False

        spy_to_date = spy.loc[:date]
        if len(spy_to_date) < 20:
            return False
        peak = spy_to_date.max()
        dd = (spy_to_date.iloc[-1] / peak) - 1
        return dd <= self._cfg.min_drawdown_from_peak

    def _find_candidates(
        self, date: pd.Timestamp, price_df: pd.DataFrame, spy: pd.Series,
    ) -> List[str]:
        """Find symbols with multiple bullish factor signals during drawdown."""
        candidates = []
        for sym in price_df.columns:
            if sym in ("SPY", "QQQ"):
                continue
            p = price_df[sym].loc[:date].dropna()
            if len(p) < 63:
                continue

            score = 0
            ret_63 = float(p.iloc[-1] / p.iloc[-63] - 1) if len(p) >= 63 else 0
            ret_21 = float(p.iloc[-1] / p.iloc[-21] - 1) if len(p) >= 21 else 0
            spy_ret_63 = float(spy.iloc[-1] / spy.iloc[-63] - 1) if len(spy) >= 63 else 0

            if ret_63 > spy_ret_63:
                score += 1
            if ret_21 > -0.05:
                score += 1

            vol = p.pct_change().tail(21).std() * np.sqrt(252)
            if vol < 0.30:
                score += 1

            peak = p.rolling(252, min_periods=63).max().iloc[-1]
            dd = (p.iloc[-1] / peak) - 1 if peak > 0 else -1
            if dd > -0.20:
                score += 1

            if score >= self._cfg.min_factor_consensus:
                candidates.append((sym, score))

        candidates.sort(key=lambda x: -x[1])
        return [c[0] for c in candidates]

    def _manage_exits(
        self, date: pd.Timestamp, price_df: pd.DataFrame, overlay: Dict[str, float],
    ) -> None:
        """Check time stops and loss stops for existing positions."""
        to_close = []
        for sym, pos in self._positions.items():
            if sym not in price_df.columns:
                continue
            current = float(price_df.loc[date, sym]) if date in price_df.index else 0
            if current <= 0 or pos.entry_price <= 0:
                continue

            ret = current / pos.entry_price - 1
            days_held = (date - pos.entry_date).days

            if ret <= self._cfg.loss_stop_pct:
                to_close.append((sym, "loss_stop"))
                self._consecutive_losses += 1
            elif ret >= self._cfg.profit_target_pct:
                to_close.append((sym, "profit_target"))
                self._consecutive_losses = 0
            elif days_held >= self._cfg.time_stop_days:
                to_close.append((sym, "time_stop"))
                if ret < 0:
                    self._consecutive_losses += 1
                else:
                    self._consecutive_losses = 0

        for sym, reason in to_close:
            overlay[sym] = 0.0
            del self._positions[sym]
            logger.info("Left-side exit %s: %s", sym, reason)

    @property
    def is_disabled(self) -> bool:
        return self._disabled

    def reset(self) -> None:
        self._positions.clear()
        self._consecutive_losses = 0
        self._disabled = not self._cfg.enabled
