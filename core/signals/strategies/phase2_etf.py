"""Preregistered phase-two ETF strategy candidates.

These implementations deliberately expose a small parameter surface matching
``docs/STRATEGY_RESEARCH_PLAN.md``.  They produce close-time target weights;
the shared backtest/PAPER engine is responsible for next-tradable-open
execution.  Every strategy is long-only, fully collateralized, and keeps each
explicit position at or below the current account-level symbol cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

_CASH = ("BIL", "SHY", "SHV")
_SECTORS = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB")


def _validate_panel(price_df: pd.DataFrame, required: Iterable[str]) -> None:
    if price_df.empty:
        raise ValueError("price panel is empty")
    if not isinstance(price_df.index, pd.DatetimeIndex):
        raise TypeError("price panel index must be a DatetimeIndex")
    if not price_df.index.is_monotonic_increasing or not price_df.index.is_unique:
        raise ValueError("price panel dates must be sorted and unique")
    missing = sorted(set(required) - set(price_df.columns))
    if missing:
        raise ValueError(f"price panel is missing required symbols: {missing}")


def _period_end_mask(index: pd.DatetimeIndex, period: str) -> pd.Series:
    periods = pd.Series(index.to_period(period), index=index)
    return periods.ne(periods.shift(-1)).fillna(True)


def _carry_rebalance_targets(raw: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    out = pd.DataFrame(np.nan, index=raw.index, columns=raw.columns, dtype=float)
    out.loc[mask.astype(bool)] = raw.loc[mask.astype(bool)]
    return out.ffill().fillna(0.0)


def _put_cash(row: pd.Series, amount: float, cash_symbols: Sequence[str] = _CASH) -> None:
    amount = max(float(amount), 0.0)
    per_symbol = amount / len(cash_symbols)
    if per_symbol > 0.35 + 1e-12:
        raise ValueError("cash allocation would breach the 35% symbol cap")
    for symbol in cash_symbols:
        row[symbol] = per_symbol


def _assert_weight_contract(weights: pd.DataFrame) -> pd.DataFrame:
    values = weights.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("strategy emitted a non-finite target weight")
    if (values < -1e-12).any():
        raise ValueError("strategy emitted a short target")
    if (values > 0.35 + 1e-10).any():
        raise ValueError("strategy emitted a target above the 35% symbol cap")
    if (weights.sum(axis=1) > 1.0 + 1e-10).any():
        raise ValueError("strategy emitted gross exposure above 100%")
    return weights.clip(lower=0.0)


@dataclass(frozen=True)
class AdaptiveCoreParams:
    trend_windows: tuple[int, int, int] = (63, 126, 252)
    volatility_target: float = 0.12

    def __post_init__(self) -> None:
        if tuple(sorted(self.trend_windows)) != self.trend_windows:
            raise ValueError("trend windows must be increasing")
        if not 0.05 <= self.volatility_target <= 0.20:
            raise ValueError("volatility_target outside preregistered safety bounds")


class AdaptiveCoreStrategy:
    """Multi-timescale trend plus volatility-scaled diversified core."""

    strategy_id = "adaptive_core_v1"
    strategy_type = "stable_core"
    required_symbols = ("SPY", "QQQ", "IEF", "GLD", *_CASH)

    def __init__(self, params: AdaptiveCoreParams | None = None) -> None:
        self.params = params or AdaptiveCoreParams()

    def generate(
        self,
        price_df: pd.DataFrame,
        regime_series: pd.Series | None = None,
    ) -> pd.DataFrame:
        del regime_series  # independent control; regime value is evaluated separately
        _validate_panel(price_df, self.required_symbols)
        px = price_df
        windows = self.params.trend_windows

        def trend_strength(symbol: str) -> pd.Series:
            components: list[pd.Series] = []
            for window in windows:
                components.append((px[symbol] > px[symbol].rolling(window).mean()).astype(float))
                components.append((px[symbol].pct_change(window) > 0.0).astype(float))
            strength = sum(components) / len(components)
            history = px[symbol].rolling(max(windows)).count().fillna(0.0)
            strength[history < max(windows)] = np.nan
            return strength

        spy_strength = trend_strength("SPY")
        qqq_strength = trend_strength("QQQ")
        combined = 0.70 * spy_strength + 0.30 * qqq_strength
        # Four of six confirmations corresponds to a full trend budget.  This
        # avoids a binary threshold without permanently underinvesting.
        trend_budget = (combined / (2.0 / 3.0)).clip(0.0, 1.0)

        spy_ret = px["SPY"].pct_change()
        vol20 = spy_ret.rolling(20).std() * np.sqrt(252.0)
        vol63 = spy_ret.rolling(63).std() * np.sqrt(252.0)
        conservative_vol = pd.concat([vol20, vol63], axis=1).max(axis=1)
        vol_scale = (self.params.volatility_target / conservative_vol).clip(0.25, 1.0)

        drawdown = px["SPY"] / px["SPY"].rolling(252).max() - 1.0
        dd_scale = pd.Series(1.0, index=px.index)
        dd_scale.loc[drawdown <= -0.10] = 0.60
        dd_scale.loc[drawdown <= -0.20] = 0.20
        equity_budget = (0.65 * trend_budget * vol_scale * dd_scale).clip(0.0, 0.65)

        raw = pd.DataFrame(0.0, index=px.index, columns=px.columns)
        valid = equity_budget.notna()
        for date in px.index[valid]:
            budget = float(equity_budget.loc[date])
            spy_weight = min(0.35, budget * (7.0 / 13.0))
            qqq_weight = min(0.30, budget - spy_weight)
            row = raw.loc[date]
            row["SPY"] = spy_weight
            row["QQQ"] = qqq_weight
            row["IEF"] = 0.20
            row["GLD"] = 0.15
            _put_cash(row, 1.0 - float(row.sum()))
            raw.loc[date] = row

        weights = _carry_rebalance_targets(raw, _period_end_mask(px.index, "M"))
        return _assert_weight_contract(weights)


@dataclass(frozen=True)
class ControlledGrowthParams:
    slow_trend: int = 210
    breadth_threshold: float = 0.65
    qqq_volatility_ceiling: float = 0.28
    cooldown_sessions: int = 10
    tqqq_cap: float = 0.10

    def __post_init__(self) -> None:
        if self.slow_trend not in {168, 210, 252}:
            raise ValueError("slow_trend is outside the preregistered grid")
        if self.breadth_threshold not in {0.55, 0.65}:
            raise ValueError("breadth_threshold is outside the preregistered grid")
        if self.qqq_volatility_ceiling not in {0.22, 0.28}:
            raise ValueError("qqq_volatility_ceiling is outside the preregistered grid")
        if self.cooldown_sessions != 10 or self.tqqq_cap != 0.10:
            raise ValueError("cooldown and TQQQ cap are frozen in v1")


class ControlledGrowthStrategy:
    """Bounded QQQ/SPY growth with breadth-gated, cooled-down TQQQ."""

    strategy_id = "controlled_growth_v1"
    strategy_type = "growth_engine"
    required_symbols = ("SPY", "QQQ", "TQQQ", *_SECTORS, *_CASH)

    def __init__(self, params: ControlledGrowthParams | None = None) -> None:
        self.params = params or ControlledGrowthParams()

    def generate(
        self,
        price_df: pd.DataFrame,
        regime_series: pd.Series | None = None,
    ) -> pd.DataFrame:
        del regime_series
        _validate_panel(price_df, self.required_symbols)
        px = price_df
        qqq = px["QQQ"]
        slow = self.params.slow_trend
        trend_windows = (63, 126, slow)
        confirmations: list[pd.Series] = []
        for window in trend_windows:
            confirmations.append((qqq > qqq.rolling(window).mean()).astype(float))
            confirmations.append((qqq.pct_change(window) > 0.0).astype(float))
        strength = sum(confirmations) / len(confirmations)
        strength[qqq.rolling(slow).count().fillna(0.0) < slow] = np.nan

        sector_trend = pd.DataFrame(
            {
                symbol: px[symbol] > px[symbol].rolling(slow).mean()
                for symbol in _SECTORS
            }
        )
        breadth = sector_trend.mean(axis=1)
        realized_vol = qqq.pct_change().rolling(20).std() * np.sqrt(252.0)
        vol_scale = (0.20 / realized_vol).clip(0.25, 1.0)
        base_budget = (0.50 * ((strength - 0.25) / 0.75).clip(0.0, 1.0) * vol_scale).clip(0.0, 0.50)

        fast_mean = qqq.rolling(50).mean()
        rolling_dd = qqq / qqq.rolling(63).max() - 1.0
        exit_now = (qqq < fast_mean) | (rolling_dd <= -0.08)
        strong = (
            (strength >= 0.80)
            & (breadth >= self.params.breadth_threshold)
            & (realized_vol <= self.params.qqq_volatility_ceiling)
            & px["TQQQ"].notna()
            & ~exit_now
        )
        week_end = _period_end_mask(px.index, "W-FRI")

        weights = pd.DataFrame(0.0, index=px.index, columns=px.columns)
        current = pd.Series(0.0, index=px.columns)
        cooldown = 0
        tqqq_active = False
        for date in px.index:
            if cooldown > 0:
                cooldown -= 1
            forced_exit = bool(exit_now.loc[date]) and tqqq_active
            if forced_exit:
                current["TQQQ"] = 0.0
                tqqq_active = False
                cooldown = self.params.cooldown_sessions
                non_cash = float(current.drop(labels=list(_CASH)).sum())
                current.loc[list(_CASH)] = 0.0
                _put_cash(current, 1.0 - non_cash)

            if bool(week_end.loc[date]) and pd.notna(base_budget.loc[date]):
                row = pd.Series(0.0, index=px.columns)
                budget = float(base_budget.loc[date])
                row["QQQ"] = min(0.30, budget * 0.60)
                row["SPY"] = min(0.20, budget - row["QQQ"])
                if bool(strong.loc[date]) and cooldown == 0:
                    row["TQQQ"] = min(
                        self.params.tqqq_cap,
                        self.params.tqqq_cap * float(min(1.0, 0.18 / realized_vol.loc[date])),
                    )
                    tqqq_active = row["TQQQ"] > 0.0
                else:
                    tqqq_active = False
                _put_cash(row, 1.0 - float(row.sum()))
                current = row
            weights.loc[date] = current

        return _assert_weight_contract(weights)


@dataclass(frozen=True)
class SectorRotationParams:
    momentum_weights: tuple[float, float, float] = (0.3, 0.4, 0.3)
    top_n: int = 2
    slow_trend: int = 252

    def __post_init__(self) -> None:
        allowed = {(0.2, 0.3, 0.5), (0.3, 0.4, 0.3), (0.4, 0.3, 0.3)}
        if self.momentum_weights not in allowed:
            raise ValueError("momentum_weights are outside the preregistered grid")
        if self.top_n not in {2, 3} or self.slow_trend not in {168, 252}:
            raise ValueError("rotation parameters are outside the preregistered grid")


class SectorRotationStrategy:
    """Monthly, risk-adjusted, multi-horizon sector ETF rotation."""

    strategy_id = "sector_rotation_v1"
    strategy_type = "etf_rotation"
    required_symbols = ("SPY", "IEF", "GLD", "BIL", "SHY", *_SECTORS)

    def __init__(self, params: SectorRotationParams | None = None) -> None:
        self.params = params or SectorRotationParams()

    def _allocate_selected(self, row: pd.Series, selected: pd.Series) -> None:
        """V1 allocation retained exactly for historical reproducibility."""
        per_sector = 0.70 / len(selected)
        for symbol in selected.index:
            row[symbol] = per_sector
        row["BIL"] = 0.15
        row["SHY"] = 0.15

    def generate(
        self,
        price_df: pd.DataFrame,
        regime_series: pd.Series | None = None,
    ) -> pd.DataFrame:
        del regime_series
        _validate_panel(price_df, self.required_symbols)
        px = price_df
        horizons = (63, 126, 252)
        scores = pd.DataFrame(0.0, index=px.index, columns=_SECTORS)
        for horizon, weight in zip(horizons, self.params.momentum_weights):
            trailing = px.loc[:, _SECTORS].shift(21) / px.loc[:, _SECTORS].shift(21 + horizon) - 1.0
            scores = scores + trailing * weight
        annual_vol = px.loc[:, _SECTORS].pct_change().rolling(63).std() * np.sqrt(252.0)
        scores = scores / annual_vol.replace(0.0, np.nan)
        sector_trend = px.loc[:, _SECTORS] > px.loc[:, _SECTORS].rolling(self.params.slow_trend).mean()
        scores = scores.where(sector_trend & (scores > 0.0))

        spy = px["SPY"]
        risk_on = (spy > spy.rolling(self.params.slow_trend).mean()) & (spy.pct_change(252) > 0.0)
        raw = pd.DataFrame(0.0, index=px.index, columns=px.columns)
        valid = scores.notna().sum(axis=1) > 0
        ready = spy.rolling(max(252, self.params.slow_trend)).count().fillna(0.0) >= max(252, self.params.slow_trend)
        for date in px.index[ready]:
            row = raw.loc[date]
            if bool(risk_on.loc[date]) and valid.loc[date]:
                selected = scores.loc[date].dropna().nlargest(self.params.top_n)
                if not selected.empty:
                    self._allocate_selected(row, selected)
            if float(row.sum()) == 0.0:
                row["IEF"] = 0.30
                row["GLD"] = 0.20
                row["BIL"] = 0.25
                row["SHY"] = 0.25
            raw.loc[date] = row

        weights = _carry_rebalance_targets(raw, _period_end_mask(px.index, "M"))
        return _assert_weight_contract(weights)


class SectorRotationV2Strategy(SectorRotationStrategy):
    """Safety repair that preserves v1 signals and caps sparse selections."""

    strategy_id = "sector_rotation_v2"

    def _allocate_selected(self, row: pd.Series, selected: pd.Series) -> None:
        sector_budget = min(0.70, 0.35 * len(selected))
        per_sector = sector_budget / len(selected)
        for symbol in selected.index:
            row[symbol] = per_sector
        defensive_weight = (1.0 - sector_budget) / 2.0
        row["BIL"] = defensive_weight
        row["SHY"] = defensive_weight


@dataclass(frozen=True)
class EtfReversionParams:
    loss_threshold: float = -0.035
    rsi_cutoff: int = 10
    hold_sessions: int = 4

    def __post_init__(self) -> None:
        if self.loss_threshold not in {-0.025, -0.035}:
            raise ValueError("loss_threshold is outside the preregistered grid")
        if self.rsi_cutoff not in {5, 10} or self.hold_sessions not in {2, 4}:
            raise ValueError("reversion parameters are outside the preregistered grid")


class EtfReversionStrategy:
    """Daily oversold rebound strategy restricted to healthy ETF trends."""

    strategy_id = "etf_reversion_v1"
    strategy_type = "daily_mean_reversion"
    trade_symbols = ("SPY", "QQQ", *_SECTORS)
    required_symbols = (*trade_symbols, *_CASH)

    def __init__(self, params: EtfReversionParams | None = None) -> None:
        self.params = params or EtfReversionParams()

    def generate(
        self,
        price_df: pd.DataFrame,
        regime_series: pd.Series | None = None,
    ) -> pd.DataFrame:
        del regime_series
        _validate_panel(price_df, self.required_symbols)
        px = price_df
        risky = px.loc[:, self.trade_symbols]
        delta = risky.diff()
        avg_gain = delta.clip(lower=0.0).ewm(alpha=0.5, adjust=False).mean()
        avg_loss = (-delta.clip(upper=0.0)).ewm(alpha=0.5, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi2 = 100.0 - 100.0 / (1.0 + rs)
        loss = risky.pct_change(3)
        trend_ok = risky > risky.rolling(200).mean()
        vol_ok = risky.pct_change().rolling(20).std() * np.sqrt(252.0) < 0.35
        trigger = (loss <= self.params.loss_threshold) & (rsi2 <= self.params.rsi_cutoff) & trend_ok & vol_ok
        recovery = risky >= risky.rolling(5).mean()

        weights = pd.DataFrame(0.0, index=px.index, columns=px.columns)
        held_days: dict[str, int] = {}
        for date in px.index:
            for symbol in list(held_days):
                held_days[symbol] += 1
                if held_days[symbol] >= self.params.hold_sessions or bool(recovery.at[date, symbol]):
                    held_days.pop(symbol)

            slots = 3 - len(held_days)
            if slots > 0:
                candidates = [
                    symbol
                    for symbol in self.trade_symbols
                    if symbol not in held_days and bool(trigger.at[date, symbol])
                ]
                candidates.sort(key=lambda symbol: float(loss.at[date, symbol]))
                for symbol in candidates[:slots]:
                    held_days[symbol] = 0

            row = pd.Series(0.0, index=px.columns)
            for symbol in held_days:
                row[symbol] = 0.20
            _put_cash(row, 1.0 - float(row.sum()))
            weights.loc[date] = row

        # Do not invest before all filters have their 200-session history.
        history = risky.rolling(200).count().min(axis=1).fillna(0.0)
        weights.loc[history < 200] = 0.0
        return _assert_weight_contract(weights)


__all__ = [
    "AdaptiveCoreParams",
    "AdaptiveCoreStrategy",
    "ControlledGrowthParams",
    "ControlledGrowthStrategy",
    "EtfReversionParams",
    "EtfReversionStrategy",
    "SectorRotationParams",
    "SectorRotationStrategy",
    "SectorRotationV2Strategy",
]
