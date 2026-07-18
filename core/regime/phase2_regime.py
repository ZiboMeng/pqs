"""Eight-state, quality-aware regime adapter for phase-two PAPER selection.

The existing detector remains the source of its six historical labels.  This
adapter makes the selection contract explicit: it adds SIDEWAYS,
STRONG_BULL_TREND, STRESSED and UNKNOWN semantics, confidence, hysteresis,
minimum duration and a post-stress cooldown.  Confidence is a deterministic
quality/boundary score, not a calibrated probability.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

import numpy as np
import pandas as pd


class Phase2Regime(str, Enum):
    RISK_OFF = "RISK_OFF"
    DEFENSIVE = "DEFENSIVE"
    NEUTRAL = "NEUTRAL"
    SIDEWAYS = "SIDEWAYS"
    RISK_ON = "RISK_ON"
    STRONG_BULL_TREND = "STRONG_BULL_TREND"
    STRESSED = "STRESSED"
    UNKNOWN = "UNKNOWN"


_DEFENSIVENESS: Mapping[Phase2Regime, int] = {
    Phase2Regime.STRONG_BULL_TREND: 0,
    Phase2Regime.RISK_ON: 1,
    Phase2Regime.NEUTRAL: 2,
    Phase2Regime.SIDEWAYS: 2,
    Phase2Regime.DEFENSIVE: 3,
    Phase2Regime.RISK_OFF: 4,
    Phase2Regime.STRESSED: 5,
    Phase2Regime.UNKNOWN: 6,
}


@dataclass(frozen=True)
class RegimeAdapterConfig:
    minimum_duration: int = 3
    improvement_hysteresis: int = 3
    post_stress_cooldown: int = 10
    minimum_history: int = 200
    strong_trend_return_126: float = 0.08
    sideways_abs_return_63: float = 0.03
    max_quality_volatility: float = 0.60


@dataclass(frozen=True)
class Phase2RegimeSeries:
    state: pd.Series
    raw_state: pd.Series
    confidence: pd.Series
    switch_count: int
    frequent_switch_windows: int
    confusion: dict[str, dict[str, int]]


class Phase2RegimeAdapter:
    def __init__(self, config: RegimeAdapterConfig | None = None) -> None:
        self.config = config or RegimeAdapterConfig()

    def classify(self, legacy_state: pd.Series, spy_close: pd.Series) -> Phase2RegimeSeries:
        index = legacy_state.index.union(spy_close.index).sort_values()
        legacy = legacy_state.reindex(index)
        spy = spy_close.reindex(index)
        ma200 = spy.rolling(200).mean()
        ret63 = spy.pct_change(63)
        ret126 = spy.pct_change(126)
        vol20 = spy.pct_change().rolling(20).std() * np.sqrt(252.0)
        history = spy.expanding().count()

        raw_values: list[str] = []
        confidence_values: list[float] = []
        legacy_map = {
            "CRISIS": Phase2Regime.STRESSED,
            "RISK_OFF": Phase2Regime.RISK_OFF,
            "CAUTIOUS": Phase2Regime.DEFENSIVE,
            "NEUTRAL": Phase2Regime.NEUTRAL,
            "RISK_ON": Phase2Regime.RISK_ON,
            "BULL": Phase2Regime.RISK_ON,
        }
        for date in index:
            label = legacy.loc[date]
            values = (spy.loc[date], ma200.loc[date], ret63.loc[date], ret126.loc[date], vol20.loc[date])
            if (
                pd.isna(label)
                or history.loc[date] < self.config.minimum_history
                or any(not np.isfinite(float(value)) for value in values)
                or float(vol20.loc[date]) > self.config.max_quality_volatility
            ):
                raw = Phase2Regime.UNKNOWN
                confidence = 0.0
            else:
                raw = legacy_map.get(str(label), Phase2Regime.UNKNOWN)
                if raw is Phase2Regime.NEUTRAL and abs(float(ret63.loc[date])) <= self.config.sideways_abs_return_63:
                    raw = Phase2Regime.SIDEWAYS
                if (
                    str(label) == "BULL"
                    and float(spy.loc[date]) > float(ma200.loc[date])
                    and float(ret126.loc[date]) >= self.config.strong_trend_return_126
                ):
                    raw = Phase2Regime.STRONG_BULL_TREND
                trend_distance = abs(float(spy.loc[date]) / float(ma200.loc[date]) - 1.0)
                boundary_score = min(trend_distance / 0.08, 1.0)
                history_score = min(float(history.loc[date]) / 252.0, 1.0)
                volatility_score = max(0.0, 1.0 - float(vol20.loc[date]) / self.config.max_quality_volatility)
                confidence = float(np.clip(0.25 + 0.35 * boundary_score + 0.20 * history_score + 0.20 * volatility_score, 0.0, 1.0))
            raw_values.append(raw.value)
            confidence_values.append(confidence)

        raw_series = pd.Series(raw_values, index=index, dtype=str)
        confidence_series = pd.Series(confidence_values, index=index, dtype=float)
        state_values: list[str] = []
        current = Phase2Regime.UNKNOWN
        current_age = 0
        pending: Phase2Regime | None = None
        pending_age = 0
        cooldown = 0
        for date in index:
            raw = Phase2Regime(raw_series.loc[date])
            if cooldown > 0:
                cooldown -= 1
            if raw is Phase2Regime.UNKNOWN:
                current = raw
                current_age = 1
                pending = None
                pending_age = 0
            elif current is Phase2Regime.UNKNOWN or _DEFENSIVENESS[raw] > _DEFENSIVENESS[current]:
                current = raw
                current_age = 1
                pending = None
                pending_age = 0
                if raw in {Phase2Regime.STRESSED, Phase2Regime.RISK_OFF}:
                    cooldown = self.config.post_stress_cooldown
            elif raw == current:
                current_age += 1
                pending = None
                pending_age = 0
            else:
                if pending != raw:
                    pending = raw
                    pending_age = 1
                else:
                    pending_age += 1
                can_improve = (
                    current_age >= self.config.minimum_duration
                    and pending_age >= self.config.improvement_hysteresis
                    and cooldown == 0
                )
                if can_improve:
                    current = raw
                    current_age = 1
                    pending = None
                    pending_age = 0
                else:
                    current_age += 1
            state_values.append(current.value)

        state_series = pd.Series(state_values, index=index, dtype=str)
        switches = int(state_series.ne(state_series.shift()).sum() - (1 if len(state_series) else 0))
        switch_flag = state_series.ne(state_series.shift()).astype(int)
        frequent = int((switch_flag.rolling(20).sum() > 4).sum())
        cross = pd.crosstab(raw_series.rename("raw"), state_series.rename("stable"))
        confusion = {
            str(raw): {str(stable): int(value) for stable, value in row.items()}
            for raw, row in cross.to_dict(orient="index").items()
        }
        return Phase2RegimeSeries(
            state=state_series,
            raw_state=raw_series,
            confidence=confidence_series,
            switch_count=switches,
            frequent_switch_windows=frequent,
            confusion=confusion,
        )


def fail_closed_regime_scale(regime: pd.Series, confidence: pd.Series, minimum_confidence: float = 0.50) -> pd.Series:
    """Return a conservative gross-exposure cap for PAPER allocation."""
    caps = {
        Phase2Regime.STRONG_BULL_TREND.value: 1.00,
        Phase2Regime.RISK_ON.value: 0.95,
        Phase2Regime.NEUTRAL.value: 0.80,
        Phase2Regime.SIDEWAYS.value: 0.75,
        Phase2Regime.DEFENSIVE.value: 0.55,
        Phase2Regime.RISK_OFF.value: 0.30,
        Phase2Regime.STRESSED.value: 0.15,
        Phase2Regime.UNKNOWN.value: 0.0,
    }
    aligned_confidence = confidence.reindex(regime.index).fillna(0.0)
    result = regime.map(lambda value: caps.get(str(value), 0.0)).astype(float)
    result.loc[aligned_confidence < minimum_confidence] = 0.0
    return result


__all__ = [
    "Phase2Regime",
    "Phase2RegimeAdapter",
    "Phase2RegimeSeries",
    "RegimeAdapterConfig",
    "fail_closed_regime_scale",
]
