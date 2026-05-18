"""G1 — honest DSR trial-count accounting (single source of truth).

PRD: docs/prd/20260517-backtest_robustness_completion_prd.md §4 G1-A1.
Boundary memo: docs/memos/20260517-dsr_placeholder_n_boundary_memo.md.

Why this module exists
----------------------
`deflated_sharpe_ratio(returns, n_trials=...)`'s selection-bias
correction is governed entirely by ``n_trials`` = the number of
strategy/model configurations compared in the *selection* that
produced the reported number (Bailey & López de Prado). The ML-redo
scripts passed PLACEHOLDER values (hardcoded 3 / ``max(2, len(swing))``)
which understated selection bias → DSR optimistic. This module replaces
those placeholders with **documented, justified per-experiment config
counts** so the number is auditable, not a magic literal.

Scope boundary (do NOT conflate)
--------------------------------
``n_trials`` here = the *per-experiment model-selection* breadth (e.g.
"best of {mae_probe, gaf_tree}" = 2). Program-level multiple testing
across R0-R5 / C1-C5 / D1-D4 is a SEPARATE concern that per-experiment
DSR does not and should not absorb — that is what
``effective_n_trials_onc`` (forward-only) is for. The robust anchor for
the ML-redo landmarks is the IC-sign/magnitude comparison, NOT DSR
(see boundary memo §4).

Honest config counts (justification = ralph-loop PRD §3 locked search
space `docs/prd/20260515-chart_structure_ralph_loop_execution_prd.md`):
"""
from __future__ import annotations

# --- Per-experiment honest model-selection breadth ---------------------

# C3 / D3 / C4 / D4 chart-native arm selection = best of
# {mae_probe, gaf_tree}. Two model configs compared per script run.
ML_REDO_CHART_NATIVE_ARMS: int = 2

# R2.5 P2 family-T re-check selection = the K-sweep over swing lookback
# K ∈ {6, 8, 12} (ralph-loop PRD §3 q5). Three configs. The previous
# `max(2, len(swing))` used the swing *segment count* which is NOT a
# model-selection count (category error) — fixed here.
ML_REDO_P2_RECHECK_K_SWEEP: int = 3


def assert_honest_n(n_trials: int, *, source: str) -> int:
    """Fail-closed guard: a production DSR call must pass an n_trials
    that came from this module (or a runtime-computed config count),
    never a bare magic literal. Callers pass ``source`` for the audit
    trail. Returns ``n_trials`` unchanged when valid.
    """
    if not isinstance(n_trials, int) or n_trials < 2:
        raise ValueError(
            f"DSR n_trials must be an int >= 2 (got {n_trials!r}) "
            f"from {source}; see dsr_trial_accounting docstring")
    return n_trials
