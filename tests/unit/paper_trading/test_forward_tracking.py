from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from core.paper_trading.forward_tracking import (
    ForwardTrackingError,
    ForwardTrackingObservation,
    ForwardTrackingPolicy,
    ForwardTrackingStore,
)


def _policy(**changes) -> ForwardTrackingPolicy:
    values = {
        "policy_id": "tracking-v1",
        "benchmark": "QQQ",
        "annualization_sessions": 252,
        "minimum_performance_sessions": 2,
        "minimum_promotion_sessions": 252,
        "max_drawdown_abs": 0.25,
        "max_annualized_volatility": 5.0,
        "max_tracking_error": 5.0,
        "max_reconciliation_failures": 0,
        "max_missing_rate": 0.0,
        "max_reject_rate": 0.20,
    }
    values.update(changes)
    return ForwardTrackingPolicy(**values)


def _observation(session: date, **changes) -> ForwardTrackingObservation:
    values = {
        "session": session,
        "decision_id": f"decision-{session.isoformat()}",
        "starting_equity": 100_000.0,
        "ending_equity": 101_000.0,
        "benchmark_return": 0.005,
        "turnover_usd": 20_000.0,
        "order_count": 2,
        "fill_count": 2,
        "rejected_order_count": 0,
        "partial_fill_count": 0,
        "total_cost_usd": 20.0,
        "slippage_usd": 15.0,
        "event_latency_seconds": 2.0,
        "missing_data_count": 0,
        "downtime_seconds": 0.0,
        "reconciliation_passed": True,
        "regime": "RISK_ON",
        "gross_target": 0.7,
        "positions": {"QQQ": 10.0},
        "backtest_reference_return": 0.009,
    }
    values.update(changes)
    return ForwardTrackingObservation(**values)


def test_tracking_policy_is_frozen_before_observations(tmp_path) -> None:
    database = tmp_path / "forward.db"
    store = ForwardTrackingStore(database, _policy())
    assert store.report()["n_forward_sessions"] == 0

    with pytest.raises(ForwardTrackingError, match="policy drift"):
        ForwardTrackingStore(database, _policy(max_drawdown_abs=0.30))


def test_observations_are_immutable_and_duplicate_exactly(tmp_path) -> None:
    store = ForwardTrackingStore(tmp_path / "forward.db", _policy())
    observation = _observation(date(2026, 7, 20))
    assert store.record(observation) is False
    assert store.record(observation) is True
    with pytest.raises(ForwardTrackingError, match="conflicting"):
        store.record(replace(observation, ending_equity=99_000.0))


def test_report_separates_engineering_execution_and_market_evidence(tmp_path) -> None:
    store = ForwardTrackingStore(tmp_path / "forward.db", _policy())
    store.record(_observation(date(2026, 7, 20), ending_equity=110_000.0))
    store.record(
        _observation(
            date(2026, 7, 21),
            starting_equity=110_000.0,
            ending_equity=77_000.0,
            benchmark_return=-0.01,
            rejected_order_count=1,
            reconciliation_passed=False,
            regime="STRESSED",
            backtest_reference_return=-0.02,
        )
    )
    report = store.report()
    controls = {
        (item["category"], item["control"])
        for item in report["control_breaches"]
    }
    assert report["sample_status"] == "PERFORMANCE_READY"
    assert ("ENGINEERING", "reconciliation_failures") in controls
    assert ("EXECUTION_MODEL", "reject_rate") in controls
    assert ("MARKET_PERFORMANCE", "max_drawdown") in controls
    assert report["execution_model"]["tracking_error_status"] == "AVAILABLE"
    assert report["exposure"]["regime_distribution"] == {
        "RISK_ON": 1,
        "STRESSED": 1,
    }
    assert report["promotion"]["automatic_promotion_enabled"] is False
    assert report["promotion"]["eligible"] is False


def test_missing_reference_is_not_reported_as_zero_tracking_error(tmp_path) -> None:
    store = ForwardTrackingStore(tmp_path / "forward.db", _policy())
    store.record(
        _observation(
            date(2026, 7, 20),
            backtest_reference_return=None,
        )
    )
    execution = store.report()["execution_model"]
    assert execution["backtest_to_forward_tracking_error"] is None
    assert execution["tracking_error_status"] == "INSUFFICIENT_REFERENCE"


def test_tracking_rejects_nonfinite_observations() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        _observation(date(2026, 7, 20), ending_equity=float("nan"))
