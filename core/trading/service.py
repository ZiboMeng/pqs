"""Order registration service that makes the risk veto unavoidable."""

from __future__ import annotations

from dataclasses import dataclass

from .order import OrderIntent, OrderState
from .risk import PreTradeRiskEngine, RiskDecision, RiskSnapshot
from .store import OrderStore, StoredOrder


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    order: StoredOrder
    risk_decision: RiskDecision | None
    duplicate: bool


class OrderRegistrationService:
    """Persist an intent once and atomically record the independent veto."""

    def __init__(self, store: OrderStore, risk_engine: PreTradeRiskEngine):
        self._store = store
        self._risk_engine = risk_engine

    def register(
        self,
        intent: OrderIntent,
        snapshot: RiskSnapshot,
    ) -> RegistrationResult:
        stored, created = self._store.create_or_get(intent)
        if not created:
            return RegistrationResult(stored, None, duplicate=True)

        decision = self._risk_engine.evaluate(intent, snapshot)
        if decision.approved:
            stored = self._store.transition(
                intent.order_id,
                OrderState.VALIDATED,
                reason="pre_trade_risk_approved",
            )
        else:
            stored = self._store.transition(
                intent.order_id,
                OrderState.REJECTED,
                reason="pre_trade_risk_rejected",
                metadata={"reason_codes": decision.reason_codes},
            )
        return RegistrationResult(stored, decision, duplicate=False)

    def mark_submitted(self, order_id: str, *, broker_order_id: str | None = None) -> StoredOrder:
        return self._store.transition(
            order_id,
            OrderState.SUBMITTED,
            reason="execution_submit",
            broker_order_id=broker_order_id,
        )

    def mark_acknowledged(self, order_id: str) -> StoredOrder:
        return self._store.transition(
            order_id,
            OrderState.ACKNOWLEDGED,
            reason="execution_acknowledged",
        )

    def mark_fill(self, order_id: str, filled_quantity: float) -> StoredOrder:
        current = self._store.get(order_id)
        if current is None:
            raise KeyError(f"unknown order_id {order_id}")
        to_state = (
            OrderState.FILLED
            if filled_quantity == current.intent.quantity
            else OrderState.PARTIALLY_FILLED
        )
        return self._store.transition(
            order_id,
            to_state,
            reason="execution_fill",
            filled_quantity=filled_quantity,
        )

    def mark_rejected(self, order_id: str, reason: str) -> StoredOrder:
        return self._store.transition(
            order_id,
            OrderState.REJECTED,
            reason=reason,
        )

    def quarantine_after_restart(self) -> list[StoredOrder]:
        """Fail closed on unresolved orders before broker reconciliation.

        Orders known not to have been submitted are rejected safely. Orders
        that may exist at a broker become UNKNOWN and must be reconciled before
        any retry; they are never blindly resubmitted.
        """
        recovered: list[StoredOrder] = []
        for order in self._store.list_nonterminal():
            if order.state in {OrderState.CREATED, OrderState.VALIDATED}:
                recovered.append(
                    self._store.transition(
                        order.intent.order_id,
                        OrderState.REJECTED,
                        reason="restart_before_submission",
                    )
                )
            elif order.state is not OrderState.UNKNOWN:
                recovered.append(
                    self._store.transition(
                        order.intent.order_id,
                        OrderState.UNKNOWN,
                        reason="restart_requires_broker_reconciliation",
                    )
                )
            else:
                recovered.append(order)
        return recovered
