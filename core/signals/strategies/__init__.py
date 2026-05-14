"""core.signals.strategies — 交易信号生成策略。"""

from core.signals.strategies.trend_following import TrendFollowingStrategy
from core.signals.strategies.dual_momentum import DualMomentumStrategy
from core.signals.strategies.simple_baseline import SimpleBaselineStrategy

__all__ = ["TrendFollowingStrategy", "DualMomentumStrategy", "SimpleBaselineStrategy"]
