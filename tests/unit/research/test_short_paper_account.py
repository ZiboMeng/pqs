from __future__ import annotations

import pytest

from core.research.short_paper import (
    BorrowSnapshot,
    ShortPaperAccount,
    ShortPaperError,
    ShortPaperOrder,
)

NOW = "2026-07-21T16:00:00Z"


def _borrow(
    *,
    shortable: bool = True,
    quantity: int = 10_000,
    fee: float = 0.036,
    source: str = "SYNTHETIC_ASSUMPTION",
) -> BorrowSnapshot:
    return BorrowSnapshot(
        symbol="XYZ",
        observed_at_utc="2026-07-21T15:55:00Z",
        available_at_utc="2026-07-21T15:56:00Z",
        shortable=shortable,
        available_quantity=quantity,
        annual_borrow_fee=fee,
        source=source,
        source_sha256="a" * 64 if source == "BROKER_PIT" else "",
    )


def _short(account: ShortPaperAccount, quantity: int = 100) -> None:
    account.execute(
        ShortPaperOrder("open-1", "XYZ", "SHORT_SELL", quantity, NOW),
        open_price=10.0,
        borrow=_borrow(),
    )


def test_short_sale_proceeds_do_not_increase_nav_and_loss_is_unbounded_direction() -> None:
    account = ShortPaperAccount(100_000.0, slippage_bps=0.0)
    _short(account)
    assert account.cash == 101_000.0
    assert account.restricted_short_proceeds == 1_000.0
    assert account.equity({"XYZ": 10.0}) == 100_000.0
    assert account.equity({"XYZ": 20.0}) == 99_000.0
    assert account.equity({"XYZ": 1_100.0}) < 0.0


def test_borrow_fee_dividend_and_split_preserve_economic_exposure() -> None:
    account = ShortPaperAccount(100_000.0, slippage_bps=0.0)
    _short(account)
    before = account.equity({"XYZ": 10.0})
    account.accrue_session(
        event_id="day-1",
        marks={"XYZ": 10.0},
        borrow_by_symbol={"XYZ": _borrow()},
        cash_distributions={"XYZ": 0.25},
    )
    assert account.positions["XYZ"].accrued_borrow_fee == pytest.approx(0.10)
    assert account.positions["XYZ"].accrued_dividend_liability == 25.0
    assert account.equity({"XYZ": 10.0}) == pytest.approx(before - 25.10)
    account.apply_split(event_id="split", symbol="XYZ", ratio=2.0)
    assert account.signed_quantity("XYZ") == -200
    assert account.positions["XYZ"].average_entry_price == 5.0
    assert account.equity({"XYZ": 5.0}) == pytest.approx(before - 25.10)


def test_locate_rule201_and_missing_open_fail_closed() -> None:
    account = ShortPaperAccount(100_000.0)
    order = ShortPaperOrder("open", "XYZ", "SHORT_SELL", 100, NOW)
    with pytest.raises(ShortPaperError, match="locate"):
        account.execute(order, open_price=10.0)
    with pytest.raises(ShortPaperError, match="quantity"):
        account.execute(order, open_price=10.0, borrow=_borrow(quantity=10))
    with pytest.raises(ShortPaperError, match="Rule 201"):
        account.execute(
            order, open_price=10.0, borrow=_borrow(),
            rule201_triggered=True, price_above_nbb=False,
        )
    with pytest.raises(ShortPaperError, match="open is missing"):
        account.execute(order, open_price=None, borrow=_borrow())


def test_recall_margin_reconciliation_idempotency_and_evidence_scope(tmp_path) -> None:
    account = ShortPaperAccount(1_000.0, slippage_bps=0.0)
    _short(account, quantity=100)
    assert account.maintenance_breach({"XYZ": 20.0})
    with pytest.raises(ShortPaperError, match="open is missing"):
        account.force_cover(
            event_id="recall", symbol="XYZ", open_price=None,
            reason="RECALL", submitted_at_utc=NOW,
        )
    assert account.force_cover(
        event_id="recall", symbol="XYZ", open_price=20.0,
        reason="RECALL", submitted_at_utc=NOW,
    )
    assert account.signed_quantity("XYZ") == 0
    assert not account.force_cover(
        event_id="recall", symbol="XYZ", open_price=20.0,
        reason="RECALL", submitted_at_utc=NOW,
    )
    account.reconcile({})
    with pytest.raises(ShortPaperError, match="reconciliation"):
        account.reconcile({"XYZ": -1})
    assert account.evidence_status({"XYZ": _borrow()}) == "RESEARCH_INCOMPLETE"
    account.save_atomic(tmp_path / "short-state.json")
    assert (tmp_path / "short-state.json").is_file()
