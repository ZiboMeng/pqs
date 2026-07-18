"""Phase-two strategy research, evaluation, and promotion controls."""

from core.research.phase2.promotion import CandidateEvidence, PromotionDecision, PromotionPolicy
from core.research.phase2.registry import ExperimentRegistry, ExperimentSpec

__all__ = [
    "CandidateEvidence",
    "ExperimentRegistry",
    "ExperimentSpec",
    "PromotionDecision",
    "PromotionPolicy",
]
