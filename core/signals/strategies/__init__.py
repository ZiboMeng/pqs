"""core.signals.strategies — 交易信号生成策略。"""

from core.signals.strategies.trend_following import TrendFollowingStrategy
from core.signals.strategies.dual_momentum import DualMomentumStrategy
from core.signals.strategies.simple_baseline import SimpleBaselineStrategy

__all__ = ["TrendFollowingStrategy", "DualMomentumStrategy", "SimpleBaselineStrategy"]
from core.signals.strategies.phase2_etf import (
    AdaptiveCoreParams,
    AdaptiveCoreStrategy,
    ControlledGrowthParams,
    ControlledGrowthStrategy,
    EtfReversionParams,
    EtfReversionStrategy,
    SectorRotationParams,
    SectorRotationStrategy,
)

__all__ = [
    "AdaptiveCoreParams",
    "AdaptiveCoreStrategy",
    "ControlledGrowthParams",
    "ControlledGrowthStrategy",
    "EtfReversionParams",
    "EtfReversionStrategy",
    "SectorRotationParams",
    "SectorRotationStrategy",
]
