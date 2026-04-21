"""Runtime alignment verification (PRD M3).

Exports AlignmentReport + check_alignment().
"""
from core.alignment.alignment_check import (
    AlignmentMode,
    AlignmentReport,
    AlignmentCheckError,
    check_alignment,
    write_alignment_report,
)

__all__ = [
    "AlignmentMode",
    "AlignmentReport",
    "AlignmentCheckError",
    "check_alignment",
    "write_alignment_report",
]
