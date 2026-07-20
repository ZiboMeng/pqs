"""Cash/position/open-order reconciliation with automatic global isolation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .controls import ControlScope, TradingControlStore


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    cash: float
    positions: dict[str, float]
    open_order_ids: frozenset[str]
    observed_at: datetime
    source: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.cash) or self.cash < -0.01:
            raise ValueError("snapshot cash must be finite and non-negative")
        invalid_positions = {
            symbol: quantity
            for symbol, quantity in self.positions.items()
            if not math.isfinite(float(quantity)) or float(quantity) < 0
        }
        if invalid_positions:
            raise ValueError(
                "snapshot positions must be finite and long-only: "
                f"{invalid_positions}"
            )
        if any(not str(order_id).strip() for order_id in self.open_order_ids):
            raise ValueError("snapshot open-order identities must be non-empty")
        if not self.source.strip():
            raise ValueError("snapshot source is required")


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    passed: bool
    cash_difference: float
    position_differences: dict[str, float]
    missing_open_orders: frozenset[str]
    unexpected_open_orders: frozenset[str]


class ReconciliationService:
    def __init__(
        self,
        controls: TradingControlStore,
        *,
        cash_tolerance: float = 0.01,
        quantity_tolerance: float = 1e-6,
    ) -> None:
        self._controls = controls
        self._cash_tolerance = cash_tolerance
        self._quantity_tolerance = quantity_tolerance

    def reconcile(
        self,
        expected: AccountSnapshot,
        actual: AccountSnapshot,
    ) -> ReconciliationResult:
        if not math.isfinite(expected.cash) or not math.isfinite(actual.cash):
            raise ValueError("reconciliation cash values must be finite")
        cash_difference = actual.cash - expected.cash
        position_differences: dict[str, float] = {}
        for symbol in set(expected.positions) | set(actual.positions):
            difference = actual.positions.get(symbol, 0.0) - expected.positions.get(
                symbol, 0.0
            )
            if abs(difference) > self._quantity_tolerance:
                position_differences[symbol] = difference
        missing = expected.open_order_ids - actual.open_order_ids
        unexpected = actual.open_order_ids - expected.open_order_ids
        passed = (
            abs(cash_difference) <= self._cash_tolerance
            and not position_differences
            and not missing
            and not unexpected
        )
        result = ReconciliationResult(
            passed,
            cash_difference,
            position_differences,
            missing,
            unexpected,
        )
        if not passed:
            self._controls.set_paused(
                ControlScope.GLOBAL,
                "*",
                paused=True,
                reason=(
                    "automatic reconciliation isolation: "
                    f"cash_diff={cash_difference:.4f}; "
                    f"positions={sorted(position_differences)}; "
                    f"missing_orders={sorted(missing)}; "
                    f"unexpected_orders={sorted(unexpected)}"
                ),
                updated_by="system:reconciliation",
            )
        return result
