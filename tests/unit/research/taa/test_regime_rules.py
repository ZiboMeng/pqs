"""Unit tests for core/research/taa/regime_rules.py (PRD-E v1.1 §4.3)."""

from __future__ import annotations

import pytest

from core.regime.regime_detector import RegimeState
from core.research.taa.regime_rules import (
    ASSET_CLASS_BONDS,
    ASSET_CLASS_CASH_ANCHOR,
    ASSET_CLASS_COMMODITIES,
    ASSET_CLASS_EQUITIES,
    DEFAULT_TAA_RULES_V0_MINIMAL,
    DEFAULT_TAA_RULES_V1,
    RegimeAllocation,
    VALID_ASSET_CLASSES,
    get_default_rule_set,
    validate_rule_set,
)


# ── RegimeAllocation dataclass invariants ───────────────────────────────────


def test_regime_allocation_valid_sum_passes():
    a = RegimeAllocation(RegimeState.BULL, 0.60, 0.30, 0.05, 0.05)
    assert a.equities_pct == 0.60


def test_regime_allocation_sum_must_be_one():
    with pytest.raises(ValueError, match="must sum to 1.0"):
        RegimeAllocation(RegimeState.BULL, 0.50, 0.30, 0.10, 0.05)  # = 0.95


def test_regime_allocation_negative_fails_long_only():
    with pytest.raises(ValueError, match="long-only invariant"):
        RegimeAllocation(RegimeState.BULL, 0.50, -0.10, 0.30, 0.30)


def test_regime_allocation_above_one_fails():
    with pytest.raises(ValueError, match="> 1.0"):
        RegimeAllocation(RegimeState.BULL, 1.01, 0.0, 0.0, 0.0)


def test_regime_allocation_to_dict_keys_match_asset_classes():
    a = RegimeAllocation(RegimeState.BULL, 0.70, 0.20, 0.05, 0.05)
    d = a.to_dict()
    assert set(d.keys()) == VALID_ASSET_CLASSES
    assert d[ASSET_CLASS_EQUITIES] == 0.70
    assert d[ASSET_CLASS_BONDS] == 0.20
    assert d[ASSET_CLASS_COMMODITIES] == 0.05
    assert d[ASSET_CLASS_CASH_ANCHOR] == 0.05


# ── DEFAULT_TAA_RULES_V1 sanity ─────────────────────────────────────────────


def test_v1_covers_all_six_regimes():
    expected = set(RegimeState)
    assert set(DEFAULT_TAA_RULES_V1.keys()) == expected


def test_v1_each_allocation_sums_to_one():
    """All 6 regime allocations sum to 1.0 within float tolerance.
    Caught at __post_init__ but verify defaults survived edits."""
    for regime, alloc in DEFAULT_TAA_RULES_V1.items():
        total = (
            alloc.equities_pct + alloc.bonds_pct
            + alloc.commodities_pct + alloc.cash_anchor_pct
        )
        assert abs(total - 1.0) < 1e-6, f"{regime.value} allocation {total}"


def test_v1_monotonic_defensiveness_in_equities():
    """As regime becomes more defensive (BULL → CRISIS), equity pct
    should monotonically decrease (this is the design intent)."""
    order = [
        RegimeState.BULL, RegimeState.RISK_ON, RegimeState.NEUTRAL,
        RegimeState.CAUTIOUS, RegimeState.RISK_OFF, RegimeState.CRISIS,
    ]
    eq_pcts = [DEFAULT_TAA_RULES_V1[r].equities_pct for r in order]
    for i in range(len(eq_pcts) - 1):
        assert eq_pcts[i] >= eq_pcts[i + 1], (
            f"v1 equity pct not monotonic: {order[i].value}={eq_pcts[i]} "
            f"vs {order[i+1].value}={eq_pcts[i+1]}"
        )


def test_v1_crisis_has_low_equity_high_defensive():
    """CRISIS regime allocation: ≤ 10% equities, ≥ 80% defensive
    (bonds + cash_anchor)."""
    crisis = DEFAULT_TAA_RULES_V1[RegimeState.CRISIS]
    assert crisis.equities_pct <= 0.10
    defensive = crisis.bonds_pct + crisis.cash_anchor_pct
    assert defensive >= 0.80, f"CRISIS defensive only {defensive}"


# ── DEFAULT_TAA_RULES_V0_MINIMAL sanity ─────────────────────────────────────


def test_v0_minimal_covers_all_six_regimes():
    assert set(DEFAULT_TAA_RULES_V0_MINIMAL.keys()) == set(RegimeState)


def test_v0_minimal_uses_only_equities_and_bonds():
    """V0_MINIMAL has 0 commodities + 0 cash_anchor across all regimes
    (the I13 Occam baseline isolates equities/bonds tradeoff)."""
    for alloc in DEFAULT_TAA_RULES_V0_MINIMAL.values():
        assert alloc.commodities_pct == 0.0
        assert alloc.cash_anchor_pct == 0.0
        assert alloc.equities_pct + alloc.bonds_pct == 1.0


def test_v0_minimal_bull_60_40():
    """V0_MINIMAL BULL = 60/40 (Bogle/Vanguard default)."""
    bull = DEFAULT_TAA_RULES_V0_MINIMAL[RegimeState.BULL]
    assert bull.equities_pct == 0.60
    assert bull.bonds_pct == 0.40


def test_v0_minimal_crisis_30_70():
    """V0_MINIMAL CRISIS = 30/70 (defensive but no cash sleeve)."""
    crisis = DEFAULT_TAA_RULES_V0_MINIMAL[RegimeState.CRISIS]
    assert crisis.equities_pct == 0.30
    assert crisis.bonds_pct == 0.70


# ── get_default_rule_set + validate_rule_set ────────────────────────────────


def test_get_default_rule_set_v1():
    rs = get_default_rule_set("v1")
    assert rs is DEFAULT_TAA_RULES_V1


def test_get_default_rule_set_v0_minimal():
    rs = get_default_rule_set("v0_minimal")
    assert rs is DEFAULT_TAA_RULES_V0_MINIMAL


def test_get_default_rule_set_unknown_raises():
    with pytest.raises(KeyError, match="unknown rule set"):
        get_default_rule_set("v99")


def test_validate_rule_set_complete_passes():
    validate_rule_set(DEFAULT_TAA_RULES_V1)
    validate_rule_set(DEFAULT_TAA_RULES_V0_MINIMAL)


def test_validate_rule_set_missing_regime_raises():
    incomplete = {
        r: a for r, a in DEFAULT_TAA_RULES_V1.items()
        if r != RegimeState.CRISIS
    }
    with pytest.raises(ValueError, match="missing regimes"):
        validate_rule_set(incomplete)
