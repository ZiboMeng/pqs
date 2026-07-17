from __future__ import annotations

from datetime import UTC, datetime

from core.trading.controls import TradingControlStore
from core.trading.reconciliation import AccountSnapshot, ReconciliationService


def snapshot(**overrides) -> AccountSnapshot:
    values = {
        "cash": 50_000.0,
        "positions": {"SPY": 100.0},
        "open_order_ids": frozenset({"broker-1"}),
        "observed_at": datetime.now(UTC),
        "source": "internal",
    }
    values.update(overrides)
    return AccountSnapshot(**values)


def test_matching_cash_positions_and_orders_pass_without_pause(tmp_path):
    controls = TradingControlStore(tmp_path / "state.db")
    result = ReconciliationService(controls).reconcile(snapshot(), snapshot(source="broker"))
    assert result.passed
    assert not controls.is_paused(strategy_id="paper-runtime", symbol="SPY")


def test_any_mismatch_fails_and_automatically_sets_global_pause(tmp_path):
    controls = TradingControlStore(tmp_path / "state.db")
    result = ReconciliationService(controls).reconcile(
        snapshot(),
        snapshot(
            cash=49_900,
            positions={"SPY": 99, "QQQ": 2},
            open_order_ids=frozenset({"broker-unknown"}),
            source="broker",
        ),
    )
    assert not result.passed
    assert result.cash_difference == -100
    assert result.position_differences == {"SPY": -1, "QQQ": 2}
    assert result.missing_open_orders == frozenset({"broker-1"})
    assert result.unexpected_open_orders == frozenset({"broker-unknown"})
    assert controls.is_paused(strategy_id="any", symbol="ANY")
    event = controls.events()[-1]
    assert event["updated_by"] == "system:reconciliation"
    assert "automatic reconciliation isolation" in event["reason"]
