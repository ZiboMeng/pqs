"""PRD-3 RB1 — component-B (intraday signal ML) prerequisite gate.

build / 🛑 gated round. AC (PRD-3 ralph-loop RB1): guard test —
when prerequisites are not met the B impl path REFUSES/RAISES
(gated-off evidence); prerequisite STATUS is reported explicitly;
loop NEVER starts RB2+ until the gate passes. Upstream directional
items (PRD-2 P2.3 EXECUTED, 15m boundary ratify) are NOT decided
inside B — RB1 only ASSERTS state, never overrides it.

Grounded scope (honest, R4/R6/R7): the four prerequisites are
ALREADY existing artifacts —

  1. PRD-1 leakage-correct evaluation foundation
     (``core.research.label_leakage``: ``average_uniqueness_weights``
     + ``purge_embargo_mask``, PRD-1 P1.1 canonical SoT).
  2. PRD-2 P2.3 EXECUTED — multi-TF cascade construction
     (``core.research.cascade_overlay.apply_cascade_overlay`` R12 +
     R10 leakage rules + R11 intraday cost sensitivity knob +
     R13 acceptance ran/recorded/root-caused).
  3. R11 intraday cost hardening
     (``CostModelConfig.get_slippage_bps(..., sensitivity_multiplier)``
     + ``CostModel.cost_bps(..., sensitivity_multiplier)``).
  4. RA7 R6 expanded-universe guard
     (``core.research.a4_universe_guard.assert_universe_safe_for_a4``).

RB1 = the consolidated CHECKER (no prereq machinery is
reimplemented here) + the naive-archetype REFUSER (the CLAUDE.md /
multi_timescale documented losing path: naive bar-direction voting
strictly loses to 60m-only). Per RB2 AC "archetype 限
differentiated 非 naive": this module refuses naive 15m momentum
mining and naive bar-direction voting BEFORE any B impl can run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

__all__ = [
    "assert_component_b_prerequisites",
    "assert_archetype_differentiated",
    "b_gate_status",
    "GateStatus",
    "DIFFERENTIATED_ARCHETYPES",
    "NAIVE_ARCHETYPES",
]

# differentiated intraday archetypes (PRD-3 §2 component B): the
# value bet of intraday signal ML is to find structure the daily
# arm can't see (intraday reversal / microstructure / event windows
# / VWAP-deviation / realized-vol regime). NOT naive bar-direction
# momentum (the CLAUDE.md Multi-TF Timing Contract result + Phase-D
# negative bar-IC documented losing path).
DIFFERENTIATED_ARCHETYPES = frozenset({
    "intraday_reversal", "open_range_breakout", "vwap_deviation",
    "realized_vol_regime", "volume_distribution", "event_window",
    "microstructure",
})

NAIVE_ARCHETYPES = frozenset({
    "bar_direction_voting", "naive_15m_momentum",
    "naive_bar_momentum", "naive_intraday_alpha",
})


@dataclass(frozen=True)
class GateStatus:
    """Explicit prerequisite status report for upstream reasoning."""
    prd1_leakage_correct: bool
    prd2_p2_3_executed: bool
    r11_intraday_cost_hardened: bool
    ra7_r6_expanded_guard: bool
    all_met: bool
    missing: List[str]


def _probe_imports() -> Dict[str, bool]:
    """Smoke-import the canonical artifacts of each prerequisite.
    A missing/broken import → that prereq is NOT met. Read-only;
    no module is constructed/mutated."""
    s: Dict[str, bool] = {}
    try:
        from core.research.label_leakage import (
            average_uniqueness_weights, purge_embargo_mask,
        )
        s["prd1_leakage_correct"] = bool(
            average_uniqueness_weights and purge_embargo_mask)
    except Exception:
        s["prd1_leakage_correct"] = False
    try:
        from core.research.cascade_overlay import apply_cascade_overlay
        s["prd2_p2_3_executed"] = bool(apply_cascade_overlay)
    except Exception:
        s["prd2_p2_3_executed"] = False
    try:
        from core.config.schemas.cost_model import CostModelConfig
        import inspect
        sig = inspect.signature(CostModelConfig.get_slippage_bps)
        s["r11_intraday_cost_hardened"] = (
            "sensitivity_multiplier" in sig.parameters)
    except Exception:
        s["r11_intraday_cost_hardened"] = False
    try:
        from core.research.a4_universe_guard import (
            assert_universe_safe_for_a4,
        )
        s["ra7_r6_expanded_guard"] = bool(assert_universe_safe_for_a4)
    except Exception:
        s["ra7_r6_expanded_guard"] = False
    return s


def b_gate_status() -> GateStatus:
    """Explicit prerequisite status (per RB1 AC '前置状态显式上报')."""
    s = _probe_imports()
    missing = [k for k, v in s.items() if not v]
    return GateStatus(
        prd1_leakage_correct=s["prd1_leakage_correct"],
        prd2_p2_3_executed=s["prd2_p2_3_executed"],
        r11_intraday_cost_hardened=s["r11_intraday_cost_hardened"],
        ra7_r6_expanded_guard=s["ra7_r6_expanded_guard"],
        all_met=not missing,
        missing=missing,
    )


def assert_component_b_prerequisites() -> GateStatus:
    """RB1 gate. Returns the GateStatus when all prereqs are met;
    raises ``RuntimeError`` listing missing items otherwise.

    **Loop discipline (PRD-3 §3 / ralph-loop RB1)**: this gate is
    the only path through which RB2+ may proceed. Upstream
    directional items (P2.3 EXECUTED, 15m ratify) are NOT decided
    here — RB1 only ASSERTS state.
    """
    st = b_gate_status()
    if not st.all_met:
        raise RuntimeError(
            f"PRD-3 component-B prerequisites NOT met "
            f"(missing={st.missing}). Component B is gated until "
            f"PRD-1 leakage-correct + PRD-2 P2.3 EXECUTED + R11 "
            f"intraday cost hardening + RA7 R6 expanded-universe "
            f"guard are ALL in place. RB2+ MUST NOT start.")
    return st


def assert_archetype_differentiated(archetype: str) -> None:
    """Reject naive intraday archetypes BEFORE any B impl can run.

    Naive bar-direction voting strictly loses to 60m-only per the
    CLAUDE.md Multi-TF Timing Contract + Phase-D negative bar-IC
    finding — this guard refuses the documented losing path
    upstream of any RB2+ pipeline build.
    """
    a = (archetype or "").strip().lower()
    if a in NAIVE_ARCHETYPES:
        raise ValueError(
            f"archetype={archetype!r} is a NAIVE 老路子 (CLAUDE.md "
            f"Multi-TF Timing Contract: naive bar-direction voting "
            f"strictly loses to 60m-only; Phase-D bar-IC negative). "
            f"Component B is restricted to DIFFERENTIATED intraday "
            f"archetypes (intraday reversal / microstructure / event "
            f"/ VWAP-dev / realized-vol regime / volume distribution)."
        )
    if a not in DIFFERENTIATED_ARCHETYPES:
        raise ValueError(
            f"unknown intraday archetype {archetype!r}; valid set = "
            f"{sorted(DIFFERENTIATED_ARCHETYPES)}")
