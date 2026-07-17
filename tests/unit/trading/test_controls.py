from __future__ import annotations

import pytest

from core.trading.controls import ControlScope, TradingControlStore


@pytest.mark.parametrize(
    ("scope", "key", "strategy", "symbol"),
    [
        (ControlScope.GLOBAL, "ignored", "stable-base", "SPY"),
        (ControlScope.STRATEGY, "stable-base", "stable-base", "SPY"),
        (ControlScope.SYMBOL, "spy", "other", "SPY"),
    ],
)
def test_pause_applies_at_global_strategy_and_symbol_scope(
    tmp_path, scope, key, strategy, symbol
):
    store = TradingControlStore(tmp_path / "controls.db")
    control = store.set_paused(
        scope,
        key,
        paused=True,
        reason="operator incident containment",
        updated_by="operator@example.com",
    )
    assert control.version == 1
    assert store.is_paused(strategy_id=strategy, symbol=symbol)


def test_resume_requires_identity_and_reason_and_is_audited(tmp_path):
    store = TradingControlStore(tmp_path / "controls.db")
    store.set_paused(
        ControlScope.GLOBAL,
        "*",
        paused=True,
        reason="reconciliation mismatch",
        updated_by="oncall-a",
    )
    with pytest.raises(ValueError, match="reason"):
        store.set_paused(
            ControlScope.GLOBAL,
            "*",
            paused=False,
            reason="",
            updated_by="oncall-b",
        )
    resumed = store.set_paused(
        ControlScope.GLOBAL,
        "*",
        paused=False,
        reason="broker and internal ledger reconciled",
        updated_by="oncall-b",
    )
    assert resumed.version == 2
    assert not store.is_paused(strategy_id="any", symbol="SPY")
    assert [event["paused"] for event in store.events()] == [1, 0]
