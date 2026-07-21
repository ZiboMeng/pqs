"""Causal portfolio construction for sparse SEC event-rank predictions."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class EventOverlayWeights:
    decision_weights: pd.DataFrame
    execution_dates: pd.DatetimeIndex
    active_signal_cells: int
    dropped_incomplete_round_trip_dates: tuple[str, ...]


def build_event_overlay_weights(
    predictions: pd.DataFrame,
    trading_sessions: pd.DatetimeIndex,
    *,
    holding_sessions: int = 5,
    score_threshold: float = 0.8,
    active_target: float = 0.65,
    single_name_cap: float = 0.10,
    benchmark_symbol: str = "SPY",
) -> EventOverlayWeights:
    """Build daily next-open targets from overlapping event signals.

    Predictions are indexed by their governed execution session.  Targets are
    placed on the immediately preceding session as an order-routing slot for
    the backtest engine, whose explicit contract fills T signals at T+1 open.
    SEC acceptance may occur after that session's close but must precede the
    execution open; the prediction itself never uses close-to-open returns.
    """

    if holding_sessions < 1:
        raise ValueError("holding_sessions must be positive")
    if not 0 < score_threshold <= 1:
        raise ValueError("score_threshold must be in (0, 1]")
    if not 0 <= active_target <= 1 or not 0 < single_name_cap <= 1:
        raise ValueError("event overlay weights are invalid")
    if not isinstance(predictions.index, pd.DatetimeIndex):
        raise TypeError("event predictions require DatetimeIndex")
    if predictions.empty:
        raise ValueError("event predictions must not be empty")
    if not predictions.index.is_unique:
        raise ValueError("event prediction dates must be unique")
    if predictions.columns.has_duplicates:
        raise ValueError("event prediction symbols must be unique")
    finite_scores = predictions.to_numpy()[np.isfinite(predictions.to_numpy())]
    if len(finite_scores) and (
        float(finite_scores.min()) < 0.0 or float(finite_scores.max()) > 1.0
    ):
        raise ValueError("event prediction scores must be percentile ranks in [0, 1]")
    missing_dates = predictions.index.difference(trading_sessions)
    if len(missing_dates):
        raise KeyError(f"event dates absent from sessions: {list(missing_dates[:5])}")
    event_positions = trading_sessions.get_indexer(predictions.index)
    if (event_positions <= 0).any():
        raise ValueError("every event execution needs a preceding routing session")
    complete = event_positions + holding_sessions < len(trading_sessions)
    dropped_dates = tuple(
        str(value.date()) for value in predictions.index[~complete]
    )
    predictions = predictions.loc[predictions.index[complete]]
    event_positions = event_positions[complete]
    if predictions.empty:
        raise ValueError("no event has a complete holding period and exit session")
    first_position = int(event_positions.min())
    # Include the open immediately after the fifth holding-session close so
    # every event is a complete round trip and pays its exit cost.
    last_position = int(event_positions.max()) + holding_sessions
    execution_dates = trading_sessions[first_position:last_position + 1]
    columns = list(predictions.columns)
    if benchmark_symbol in columns:
        raise ValueError("benchmark must not appear in active predictions")
    decision_rows: list[pd.Series] = []
    decision_dates: list[pd.Timestamp] = []
    active_signal_cells = 0
    for execution_date in execution_dates:
        position = trading_sessions.get_loc(execution_date)
        active_dates = trading_sessions[
            max(first_position, position - holding_sessions + 1):position + 1
        ]
        active = predictions.reindex(active_dates).max(axis=0, skipna=True)
        selected = active[
            active.notna() & np.isfinite(active) & (active >= score_threshold)
        ]
        active_signal_cells += len(selected)
        weights = pd.Series(0.0, index=columns + [benchmark_symbol])
        if len(selected):
            per_name = min(single_name_cap, active_target / len(selected))
            weights.loc[selected.index] = per_name
        weights.loc[benchmark_symbol] = 1.0 - float(weights.loc[columns].sum())
        decision_rows.append(weights)
        decision_dates.append(trading_sessions[position - 1])
    decision_weights = pd.DataFrame(
        decision_rows,
        index=pd.DatetimeIndex(decision_dates, name="decision_date"),
    )
    if decision_weights.index.has_duplicates:
        raise ValueError("event execution sessions map to duplicate routing dates")
    if not np.allclose(decision_weights.sum(axis=1), 1.0):
        raise ValueError("event overlay targets must sum to one")
    return EventOverlayWeights(
        decision_weights=decision_weights,
        execution_dates=pd.DatetimeIndex(execution_dates),
        active_signal_cells=active_signal_cells,
        dropped_incomplete_round_trip_dates=dropped_dates,
    )


__all__ = ["EventOverlayWeights", "build_event_overlay_weights"]
