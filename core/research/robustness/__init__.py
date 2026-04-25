"""Robustness eval module for OOS MVP.

PRD: docs/prd/20260425-oos_mvp_ralph_loop_execution.md §3 R1 / §3 R2
"""
from .window_spec import (
    CandidateRobustnessWindow,
    DataIntegritySnapshot,
    EvidenceClass,
    ShrinkReason,
    ShrinkReasonCode,
)

__all__ = [
    "CandidateRobustnessWindow",
    "DataIntegritySnapshot",
    "EvidenceClass",
    "ShrinkReason",
    "ShrinkReasonCode",
]
