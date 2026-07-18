"""Aggregate allocator and final risk veto for multiple PAPER strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StrategyRiskBudget:
    strategy_id: str
    capital_fraction: float
    max_gross_exposure: float = 1.0
    max_turnover: float = 1.0
    priority: int = 100

    def __post_init__(self) -> None:
        if not 0.0 < self.capital_fraction <= 1.0:
            raise ValueError("capital_fraction must be in (0, 1]")
        if not 0.0 < self.max_gross_exposure <= 1.0:
            raise ValueError("max_gross_exposure must be in (0, 1]")


@dataclass(frozen=True)
class AggregateExposurePolicy:
    max_gross_exposure: float = 1.0
    max_single_position: float = 0.35
    symbol_caps: Mapping[str, float] = field(default_factory=lambda: {"QQQ": 0.30, "TQQQ": 0.10})


@dataclass(frozen=True)
class AllocationDecision:
    weights: pd.Series
    accepted: bool
    veto_reasons: tuple[str, ...]
    clipped_symbols: tuple[str, ...]
    requested_gross: float
    approved_gross: float


def conflict_resolver(strategy_targets: Mapping[str, pd.Series]) -> tuple[dict[str, pd.Series], tuple[str, ...]]:
    """Reject shorts/non-finite targets; long-only overlap is additive."""
    clean: dict[str, pd.Series] = {}
    reasons: list[str] = []
    for strategy_id, target in strategy_targets.items():
        numeric = pd.to_numeric(target, errors="coerce")
        if numeric.isna().any():
            reasons.append(f"{strategy_id}:NON_FINITE_TARGET")
            continue
        if (numeric < -1e-12).any():
            reasons.append(f"{strategy_id}:SHORT_TARGET")
            continue
        clean[strategy_id] = numeric.clip(lower=0.0)
    return clean, tuple(reasons)


def aggregate_exposure_check(weights: pd.Series, policy: AggregateExposurePolicy) -> tuple[pd.Series, tuple[str, ...]]:
    """Clip symbol/gross limits conservatively; never redistribute overflow."""
    approved = weights.copy().clip(lower=0.0)
    clipped: list[str] = []
    for symbol in approved.index:
        cap = min(policy.max_single_position, float(policy.symbol_caps.get(symbol, policy.max_single_position)))
        if approved.loc[symbol] > cap:
            approved.loc[symbol] = cap
            clipped.append(str(symbol))
    gross = float(approved.sum())
    if gross > policy.max_gross_exposure:
        approved *= policy.max_gross_exposure / gross
        clipped.append("__GROSS__")
    return approved, tuple(clipped)


class PortfolioAllocator:
    """Apply per-strategy budgets, resolve conflicts, then enforce final caps."""

    def __init__(
        self,
        budgets: Mapping[str, StrategyRiskBudget],
        policy: AggregateExposurePolicy | None = None,
    ) -> None:
        self.budgets = dict(budgets)
        self.policy = policy or AggregateExposurePolicy()
        if sum(b.capital_fraction for b in self.budgets.values()) > 1.0 + 1e-12:
            raise ValueError("strategy capital fractions exceed 100%")

    def allocate(
        self,
        strategy_targets: Mapping[str, pd.Series],
        *,
        regime_label: str,
        regime_confidence: float,
        data_fresh: bool,
        reconciled: bool,
        global_kill_switch: bool = False,
    ) -> AllocationDecision:
        universe = sorted({symbol for target in strategy_targets.values() for symbol in target.index})
        zero = pd.Series(0.0, index=universe, dtype=float)
        veto: list[str] = []
        if global_kill_switch:
            veto.append("GLOBAL_KILL_SWITCH")
        if not data_fresh:
            veto.append("STALE_OR_INCOMPLETE_DATA")
        if not reconciled:
            veto.append("ACCOUNT_NOT_RECONCILED")
        if regime_label == "UNKNOWN" or not np.isfinite(regime_confidence) or regime_confidence < 0.50:
            veto.append("REGIME_UNKNOWN_OR_LOW_CONFIDENCE")
        if veto:
            return AllocationDecision(zero, False, tuple(veto), (), 0.0, 0.0)

        clean, conflicts = conflict_resolver(strategy_targets)
        if conflicts:
            return AllocationDecision(zero, False, conflicts, (), 0.0, 0.0)

        aggregate = zero.copy()
        for strategy_id, target in sorted(
            clean.items(),
            key=lambda item: self.budgets.get(item[0], StrategyRiskBudget(item[0], 1.0)).priority,
        ):
            if strategy_id not in self.budgets:
                return AllocationDecision(zero, False, (f"UNKNOWN_STRATEGY:{strategy_id}",), (), 0.0, 0.0)
            budget = self.budgets[strategy_id]
            gross = float(target.sum())
            if gross > budget.max_gross_exposure + 1e-12:
                target = target * (budget.max_gross_exposure / gross)
            aggregate = aggregate.add(target.reindex(universe, fill_value=0.0) * budget.capital_fraction, fill_value=0.0)

        requested = float(aggregate.sum())
        approved, clipped = aggregate_exposure_check(aggregate, self.policy)
        return AllocationDecision(
            weights=approved,
            accepted=True,
            veto_reasons=(),
            clipped_symbols=clipped,
            requested_gross=requested,
            approved_gross=float(approved.sum()),
        )


# Names used in the governing mandate and external integrations.
strategy_risk_budget = StrategyRiskBudget
portfolio_allocator = PortfolioAllocator


__all__ = [
    "AggregateExposurePolicy",
    "AllocationDecision",
    "PortfolioAllocator",
    "StrategyRiskBudget",
    "aggregate_exposure_check",
    "conflict_resolver",
    "portfolio_allocator",
    "strategy_risk_budget",
]
