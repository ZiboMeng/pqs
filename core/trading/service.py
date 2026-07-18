"""Order registration service that makes the risk veto unavoidable."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable, Iterable

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

    @property
    def db_path(self):
        return self._store.db_path

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

    def mark_submitted(
        self,
        order_id: str,
        *,
        broker_order_id: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> StoredOrder:
        return self._store.transition(
            order_id,
            OrderState.SUBMITTED,
            reason="execution_submit",
            broker_order_id=broker_order_id,
            connection=connection,
        )

    def mark_acknowledged(
        self,
        order_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> StoredOrder:
        return self._store.transition(
            order_id,
            OrderState.ACKNOWLEDGED,
            reason="execution_acknowledged",
            connection=connection,
        )

    def mark_fill(
        self,
        order_id: str,
        filled_quantity: float,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> StoredOrder:
        current = self._store.get(order_id, connection=connection)
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
            connection=connection,
        )

    def mark_rejected(
        self,
        order_id: str,
        reason: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> StoredOrder:
        return self._store.transition(
            order_id,
            OrderState.REJECTED,
            reason=reason,
            connection=connection,
        )

    def commit_simulated_execution(
        self,
        outcomes: Iterable[tuple[str, float | None]],
        *,
        persist: Callable[[sqlite3.Connection], None],
    ) -> None:
        """Atomically commit local fills and the PAPER account projection."""
        with self._store.transaction() as conn:
            for order_id, filled_quantity in outcomes:
                current = self._store.get(order_id, connection=conn)
                if current is None:
                    raise KeyError(f"unknown order_id {order_id}")
                if filled_quantity is None:
                    self.mark_rejected(
                        order_id,
                        reason="execution_simulator_declined",
                        connection=conn,
                    )
                    continue
                if current.state is OrderState.VALIDATED:
                    self.mark_submitted(order_id, connection=conn)
                self.mark_acknowledged(order_id, connection=conn)
                self.mark_fill(
                    order_id,
                    float(filled_quantity),
                    connection=conn,
                )
            persist(conn)

    def quarantine_after_restart(
        self,
        *,
        retry_validated_local_orders: bool = False,
    ) -> list[StoredOrder]:
        """Fail closed on unresolved orders before broker reconciliation.

        Orders known not to have been submitted are rejected safely. Orders
        that may exist at a broker become UNKNOWN and must be reconciled before
        any retry; they are never blindly resubmitted.
        """
        recovered: list[StoredOrder] = []
        for order in self._store.list_nonterminal():
            if order.state is OrderState.VALIDATED and retry_validated_local_orders:
                # The local simulator has no external side effect before the
                # atomic execution transaction.  VALIDATED is therefore safe
                # to retry with the same idempotency key after a crash.
                recovered.append(order)
            elif order.state in {OrderState.CREATED, OrderState.VALIDATED}:
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
