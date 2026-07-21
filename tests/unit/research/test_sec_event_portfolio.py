from __future__ import annotations

import pandas as pd

from core.research.sec_event_portfolio import build_event_overlay_weights
from dev.scripts.mining_v4.run_sec_event_portfolio import _gate_checks


def test_event_overlay_holds_five_sessions_caps_names_and_routes_prior_session():
    sessions = pd.bdate_range("2024-01-02", periods=8)
    predictions = pd.DataFrame(
        {"A": [1.0], "B": [0.8], "C": [0.7]},
        index=pd.DatetimeIndex([sessions[2]]),
    )
    result = build_event_overlay_weights(
        predictions, sessions, holding_sessions=5,
        score_threshold=0.8, active_target=0.65, single_name_cap=0.10,
    )
    assert result.execution_dates.tolist() == list(sessions[2:8])
    assert result.decision_weights.index.tolist() == list(sessions[1:7])
    assert (result.decision_weights.iloc[:5][["A", "B"]] == 0.10).all().all()
    assert (result.decision_weights.iloc[-1][["A", "B", "C"]] == 0.0).all()
    assert (result.decision_weights["C"] == 0.0).all()
    assert (result.decision_weights.iloc[:5]["SPY"] == 0.80).all()
    assert result.decision_weights.iloc[-1]["SPY"] == 1.0
    assert result.active_signal_cells == 10
    assert result.dropped_incomplete_round_trip_dates == ()


def test_event_overlay_adds_and_expires_overlapping_signals():
    sessions = pd.bdate_range("2024-01-02", periods=10)
    predictions = pd.DataFrame(
        {"A": [1.0, float("nan")], "B": [float("nan"), 1.0]},
        index=pd.DatetimeIndex([sessions[2], sessions[4]]),
    )
    result = build_event_overlay_weights(
        predictions, sessions, holding_sessions=3,
        score_threshold=0.8, active_target=0.65, single_name_cap=0.10,
    )
    weights = result.decision_weights
    assert weights.iloc[0]["A"] == 0.10
    assert weights.iloc[2]["A"] == 0.10
    assert weights.iloc[2]["B"] == 0.10
    assert weights.iloc[-1]["A"] == 0.0
    assert weights.iloc[-1]["B"] == 0.0


def test_event_overlay_reports_and_excludes_events_without_exit_session():
    sessions = pd.bdate_range("2024-01-02", periods=8)
    predictions = pd.DataFrame(
        {"A": [1.0, 1.0]},
        index=pd.DatetimeIndex([sessions[2], sessions[6]]),
    )
    result = build_event_overlay_weights(
        predictions, sessions, holding_sessions=2,
        score_threshold=0.8, active_target=0.65, single_name_cap=0.10,
    )
    assert result.dropped_incomplete_round_trip_dates == (
        str(sessions[6].date()),
    )
    assert result.decision_weights.iloc[-1]["A"] == 0.0


def test_gate_checks_keep_near_miss_for_review_without_passing():
    result = _gate_checks(
        strategy_metrics={"max_drawdown": -0.20},
        spy_metrics={"max_drawdown": -0.20},
        cagr_excess=-0.005,
        rolling_excess_fraction=0.70,
        gate_config={
            "min_after_cost_excess_vs_spy": 0.0,
            "min_positive_rolling_window_fraction": 0.60,
            "max_drawdown_vs_spy_multiplier": 1.25,
            "near_miss_min_annualized_excess": -0.01,
        },
    )
    assert result["checks"]["after_cost_cagr_excess_vs_spy"] is False
    assert result["all_primary_gates_pass"] is False
    assert result["near_miss_review_eligible"] is True
