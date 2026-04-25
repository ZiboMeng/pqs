"""Robustness eval runner skeleton.

R1 ships only the signature and a ``NotImplementedError`` stub. R2 fills
in the real eval logic (load frozen spec, replay candidate over the
window, compute cum_ret/sharpe/max_dd/vs_spy/vs_qqq/turnover/fill_count,
emit ``robustness_eval.{json,md}``).

PRD: docs/prd/20260425-oos_mvp_ralph_loop_execution.md §3 R1 / §3 R2
"""
from __future__ import annotations

from .window_spec import CandidateRobustnessWindow


def evaluate(spec: CandidateRobustnessWindow):
    """Run robustness eval for a candidate over the given window.

    R1 stub: not implemented; full implementation lands in Round 2.
    """
    raise NotImplementedError(
        "robustness_eval runner not implemented yet (R1 ships schema only); "
        "full implementation lands in R2"
    )
