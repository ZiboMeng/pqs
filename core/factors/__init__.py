"""core.factors — 因子研究框架（IC / IR / 衰减 / 分层回测）。"""

from core.factors.factor_engine import FactorEngine, FactorStats
from core.factors.factor_evaluator import FactorEvaluator, FactorReport

__all__ = [
    "FactorEngine", "FactorStats",
    "FactorEvaluator", "FactorReport",
]
