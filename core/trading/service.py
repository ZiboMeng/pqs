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
