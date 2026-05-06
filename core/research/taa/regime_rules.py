"""PRD-E v1.1 §4.3 regime → asset class allocation rules.

Defines ``RegimeAllocation`` dataclass + the two default rule sets:
  * ``DEFAULT_TAA_RULES_V1``: 6 regimes × 4 asset classes = 24 free numbers.
    Informed averaging of 60/40 (Bogle/Vanguard MPT), Permanent Portfolio
    (Browne 25/25/25/25), and Swensen "Unconventional Success" (30/30/20/20
    individual-investor framework adapted to our 4-class model).
  * ``DEFAULT_TAA_RULES_V0_MINIMAL``: 6 regimes × 2 active asset classes
    (equities + bonds) = 12 free numbers. Sanity baseline for I13 Occam
    test: if v0_minimal NAV ≥ v1 NAV in Phase 2 backtest, accept
    v0_minimal as default and deprecate v1.

Asset classes mirror ``core/research/risk_cluster_map.py::ASSET_CLASS_BY_CLUSTER``
output strings: ``equities``, ``bonds``, ``commodities``, ``cash_anchor``.

Rule sets are versioned (v0_minimal / v1 / v2 / ...). Adding a new
version creates a new dict keyed by RegimeState; the default selector
helper is ``get_default_rule_set(name="v1")``.

PRD references:
  * §4.3 Regime → asset class rules (data + policy)
  * §5.2 Phase 2 I13 fix (V1 vs V0_MINIMAL Occam test)
  * §7 risks: rule-set over-fit mitigation via V0_MINIMAL fallback
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping

from core.regime.regime_detector import RegimeState


# Asset-class string constants. Mirror risk_cluster_map.ASSET_CLASS_BY_CLUSTER
# values; the TAA harness uses these to fan target_wts back out across
# symbols within each class via equal-weighting.
ASSET_CLASS_EQUITIES = "equities"
ASSET_CLASS_BONDS = "bonds"
ASSET_CLASS_COMMODITIES = "commodities"
ASSET_CLASS_CASH_ANCHOR = "cash_anchor"

VALID_ASSET_CLASSES = frozenset({
    ASSET_CLASS_EQUITIES, ASSET_CLASS_BONDS,
    ASSET_CLASS_COMMODITIES, ASSET_CLASS_CASH_ANCHOR,
})


@dataclass(frozen=True)
class RegimeAllocation:
    """Per-regime asset-class allocation. All four pcts sum to 1.0.

    The TAA harness reads ``regime_label[t]`` at each rebalance day,
    looks up the corresponding ``RegimeAllocation`` from the active
    rule set, and constructs target_wts by equal-weighting symbols
    within each asset class.

    Long-only invariant: all four fields ≥ 0.0 (no shorts, no leverage).
    """

    regime: RegimeState
    equities_pct: float
    bonds_pct: float
    commodities_pct: float
    cash_anchor_pct: float

    def __post_init__(self) -> None:
        for name, val in (
            ("equities_pct", self.equities_pct),
            ("bonds_pct", self.bonds_pct),
            ("commodities_pct", self.commodities_pct),
            ("cash_anchor_pct", self.cash_anchor_pct),
        ):
            if val < 0.0:
                raise ValueError(
                    f"{name}={val} violates long-only invariant (must be >= 0)"
                )
            if val > 1.0:
                raise ValueError(
                    f"{name}={val} > 1.0 — invalid allocation pct"
                )
        total = (
            self.equities_pct + self.bonds_pct
            + self.commodities_pct + self.cash_anchor_pct
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"regime={self.regime.value} allocation must sum to 1.0, "
                f"got {total} (diff {total-1.0:+.2e})"
            )

    def to_dict(self) -> Dict[str, float]:
        """Serialize to {asset_class_str: pct} for downstream consumers."""
        return {
            ASSET_CLASS_EQUITIES: self.equities_pct,
            ASSET_CLASS_BONDS: self.bonds_pct,
            ASSET_CLASS_COMMODITIES: self.commodities_pct,
            ASSET_CLASS_CASH_ANCHOR: self.cash_anchor_pct,
        }


# ── Default rule sets ──────────────────────────────────────────────────────


# PRD-E §4.3 v1: full 6-state × 4-class allocation. v1 numbers are
# informed averaging of:
#   * 60/40 portfolio (Bogle / Vanguard MPT default)
#   * Permanent Portfolio (Browne — 25/25/25/25 stocks/bonds/gold/cash)
#   * Swensen "Unconventional Success" (30/30/20/20 stocks/bonds/REIT/TIPS
#     individual-investor framework, adapted to our 4-class equities/
#     bonds/commodities/cash_anchor model)
# v1 numbers are NOT mined; they're a pre-data design choice. PRD-E
# Phase 2 backtests v1 against V0_MINIMAL (Occam baseline) — if
# V0_MINIMAL ≥ v1, deprecate v1 (I13 fix).
DEFAULT_TAA_RULES_V1: Dict[RegimeState, RegimeAllocation] = {
    RegimeState.BULL:     RegimeAllocation(RegimeState.BULL,     0.70, 0.20, 0.05, 0.05),
    RegimeState.RISK_ON:  RegimeAllocation(RegimeState.RISK_ON,  0.60, 0.30, 0.05, 0.05),
    RegimeState.NEUTRAL:  RegimeAllocation(RegimeState.NEUTRAL,  0.40, 0.40, 0.10, 0.10),
    RegimeState.CAUTIOUS: RegimeAllocation(RegimeState.CAUTIOUS, 0.30, 0.50, 0.10, 0.10),
    RegimeState.RISK_OFF: RegimeAllocation(RegimeState.RISK_OFF, 0.20, 0.55, 0.05, 0.20),
    RegimeState.CRISIS:   RegimeAllocation(RegimeState.CRISIS,   0.05, 0.65, 0.00, 0.30),
}

# PRD-E §4.3 V0_MINIMAL (I13 Occam test): only equities + bonds active,
# 6 regimes × 2 active classes = 12 free numbers. Tests whether the
# 24-free-number v1 added complexity is justified. If V0_MINIMAL NAV
# ≥ v1 NAV, simpler wins (Phase 2 closeout marks v1 deprecated).
DEFAULT_TAA_RULES_V0_MINIMAL: Dict[RegimeState, RegimeAllocation] = {
    RegimeState.BULL:     RegimeAllocation(RegimeState.BULL,     0.60, 0.40, 0.0, 0.0),
    RegimeState.RISK_ON:  RegimeAllocation(RegimeState.RISK_ON,  0.60, 0.40, 0.0, 0.0),
    RegimeState.NEUTRAL:  RegimeAllocation(RegimeState.NEUTRAL,  0.50, 0.50, 0.0, 0.0),
    RegimeState.CAUTIOUS: RegimeAllocation(RegimeState.CAUTIOUS, 0.30, 0.70, 0.0, 0.0),
    RegimeState.RISK_OFF: RegimeAllocation(RegimeState.RISK_OFF, 0.30, 0.70, 0.0, 0.0),
    RegimeState.CRISIS:   RegimeAllocation(RegimeState.CRISIS,   0.30, 0.70, 0.0, 0.0),
}


_RULE_SET_REGISTRY: Dict[str, Mapping[RegimeState, RegimeAllocation]] = {
    "v0_minimal": DEFAULT_TAA_RULES_V0_MINIMAL,
    "v1": DEFAULT_TAA_RULES_V1,
}


def get_default_rule_set(
    name: str = "v1",
) -> Mapping[RegimeState, RegimeAllocation]:
    """Return the named default rule set.

    Parameters
    ----------
    name : str
        One of ``"v0_minimal"`` (I13 Occam baseline) or ``"v1"`` (PRD-E
        §4.3 default; informed averaging of 60/40 + Permanent Portfolio +
        Swensen).

    Returns
    -------
    Mapping[RegimeState, RegimeAllocation]
        Frozen mapping (caller should not mutate).

    Raises
    ------
    KeyError if ``name`` is not registered.
    """
    if name not in _RULE_SET_REGISTRY:
        raise KeyError(
            f"unknown rule set {name!r}; registered: "
            f"{sorted(_RULE_SET_REGISTRY)}"
        )
    return _RULE_SET_REGISTRY[name]


def validate_rule_set(
    rule_set: Mapping[RegimeState, RegimeAllocation],
) -> None:
    """Assert that a rule set covers all 6 RegimeState values exactly.

    Useful as a pre-flight check when mining produces or yaml loads a
    custom rule set: missing a regime would silently fall through to
    "no allocation" at the harness layer.
    """
    expected = set(RegimeState)
    actual = set(rule_set.keys())
    missing = expected - actual
    extra = actual - expected
    if missing:
        raise ValueError(
            f"rule set missing regimes: {sorted(s.value for s in missing)}"
        )
    if extra:
        raise ValueError(
            f"rule set has unrecognized regimes: {sorted(repr(s) for s in extra)}"
        )
