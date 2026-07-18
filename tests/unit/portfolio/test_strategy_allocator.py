from __future__ import annotations

import pandas as pd

from core.portfolio.strategy_allocator import (
    PortfolioAllocator,
    StrategyRiskBudget,
)


def _allocator() -> PortfolioAllocator:
    return PortfolioAllocator(
        {
            "adaptive_core_v1": StrategyRiskBudget("adaptive_core_v1", 0.60),
            "sector_rotation_v1": StrategyRiskBudget("sector_rotation_v1", 0.40),
        }
    )


def test_allocator_caps_overlap_and_gross() -> None:
    decision = _allocator().allocate(
        {
            "adaptive_core_v1": pd.Series({"SPY": 0.35, "BIL": 0.35}),
            "sector_rotation_v1": pd.Series({"SPY": 0.50, "XLK": 0.35}),
        },
        regime_label="RISK_ON",
        regime_confidence=0.8,
        data_fresh=True,
        reconciled=True,
    )
    assert decision.accepted
    assert decision.weights["SPY"] <= 0.35
    assert decision.approved_gross <= 1.0
    assert "SPY" in decision.clipped_symbols


def test_allocator_final_veto_is_fail_closed() -> None:
    decision = _allocator().allocate(
        {"adaptive_core_v1": pd.Series({"SPY": 0.35})},
        regime_label="UNKNOWN",
        regime_confidence=0.0,
        data_fresh=True,
        reconciled=True,
    )
    assert not decision.accepted
    assert decision.weights.sum() == 0.0
    assert "REGIME_UNKNOWN_OR_LOW_CONFIDENCE" in decision.veto_reasons


def test_allocator_rejects_short_strategy_target() -> None:
    decision = _allocator().allocate(
        {"adaptive_core_v1": pd.Series({"SPY": -0.1})},
        regime_label="RISK_ON",
        regime_confidence=0.9,
        data_fresh=True,
        reconciled=True,
    )
    assert not decision.accepted
    assert decision.weights.sum() == 0.0
