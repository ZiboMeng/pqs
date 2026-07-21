"""Portfolio construction helpers for governed rank-mining candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

Construction = Literal[
    "active_top10_control",
    "spy35_active65_equal_top10",
    "spy35_active65_rank_vol_top10",
]


@dataclass(frozen=True, slots=True)
class BufferedConstruction:
    decision_weights: pd.DataFrame
    evaluated_decision_dates: int
    membership_change_dates: int


def _capped_allocate(
    preference: pd.Series,
    target: float,
    cap: float,
) -> pd.Series:
    weights = pd.Series(0.0, index=preference.index)
    available = preference[preference > 0].astype(float).copy()
    remaining = float(target)
    while len(available) and remaining > 1e-12:
        proposal = remaining * available / available.sum()
        room = cap - weights.loc[available.index]
        binding = proposal >= room - 1e-12
        if not binding.any():
            weights.loc[available.index] += proposal
            remaining = 0.0
            break
        bound_names = available.index[binding]
        addition = room.loc[bound_names].clip(lower=0.0)
        weights.loc[bound_names] += addition
        remaining -= float(addition.sum())
        available = available.drop(bound_names)
    return weights


def build_decision_weights(
    scores: pd.DataFrame,
    volatility: pd.DataFrame,
    construction: Construction,
    *,
    top_k: int = 10,
    spy_symbol: str = "SPY",
    spy_weight: float = 0.35,
    active_single_name_cap: float = 0.10,
) -> pd.DataFrame:
    """Map validation-only ranks to long-only decision-date weights."""

    allowed = {
        "active_top10_control",
        "spy35_active65_equal_top10",
        "spy35_active65_rank_vol_top10",
    }
    if construction not in allowed:
        raise ValueError(f"unknown construction: {construction}")
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if not 0 <= spy_weight <= 1 or not 0 < active_single_name_cap <= 1:
        raise ValueError("invalid portfolio weight constraint")
    volatility = volatility.reindex(index=scores.index, columns=scores.columns)
    columns = list(scores.columns)
    if spy_symbol not in columns:
        columns.append(spy_symbol)
    weights = pd.DataFrame(0.0, index=scores.index, columns=columns)
    hybrid = construction != "active_top10_control"
    active_target = 1.0 - spy_weight if hybrid else 1.0

    for date in scores.index:
        row = scores.loc[date].replace([np.inf, -np.inf], np.nan).dropna()
        selected = row.nlargest(top_k, keep="first")
        if len(selected):
            if construction == "spy35_active65_rank_vol_top10":
                vol = volatility.loc[date, selected.index]
                valid = vol.notna() & np.isfinite(vol) & (vol > 0)
                selected = selected.loc[valid]
                vol = vol.loc[valid]
                preference = selected.rank(method="average") / vol
            else:
                preference = pd.Series(1.0, index=selected.index)
            active = _capped_allocate(
                preference,
                target=active_target,
                cap=active_single_name_cap,
            )
            weights.loc[date, active.index] = active
        if hybrid:
            weights.loc[date, spy_symbol] = spy_weight
    return weights


def expand_decision_signals(
    decision_weights: pd.DataFrame,
    daily_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Place targets only on explicit decision rows; other rows stay zero."""

    missing = decision_weights.index.difference(daily_index)
    if len(missing):
        raise KeyError(f"decision dates absent from daily index: {list(missing[:5])}")
    signals = pd.DataFrame(
        0.0,
        index=daily_index,
        columns=decision_weights.columns,
    )
    signals.loc[decision_weights.index] = decision_weights
    return signals


def build_buffered_membership_weights(
    scores: pd.DataFrame,
    *,
    top_k: int = 10,
    exit_rank: int = 15,
    spy_symbol: str = "SPY",
    spy_weight: float = 0.35,
    active_single_name_cap: float = 0.10,
) -> BufferedConstruction:
    """Build a rank-buffered book and rebalance only on membership changes.

    At the first decision the highest ``top_k`` names enter. At later
    decisions an incumbent remains while its deterministic cross-sectional
    rank is at most ``exit_rank``; vacancies are filled from the best-ranked
    non-incumbents. A target row is emitted only when the membership set
    changes, so the backtest does not rebalance merely to undo weight drift.
    """

    if top_k < 1 or exit_rank < top_k:
        raise ValueError("exit_rank must be at least top_k")
    if not 0 <= spy_weight <= 1 or not 0 < active_single_name_cap <= 1:
        raise ValueError("invalid portfolio weight constraint")
    if not isinstance(scores.index, pd.DatetimeIndex):
        raise TypeError("scores require DatetimeIndex")
    if scores.index.has_duplicates or not scores.index.is_monotonic_increasing:
        raise ValueError("score dates must be sorted and unique")
    if spy_symbol in scores.columns:
        raise ValueError("SPY anchor cannot also be an active score column")

    columns = [*scores.columns, spy_symbol]
    emitted: list[pd.Series] = []
    emitted_dates: list[pd.Timestamp] = []
    incumbents: list[str] = []
    previous_members: frozenset[str] = frozenset()
    active_target = 1.0 - spy_weight
    for date in scores.index:
        row = scores.loc[date].replace([np.inf, -np.inf], np.nan).dropna()
        ranked = row.sort_values(ascending=False, kind="mergesort")
        rank_by_symbol = pd.Series(
            np.arange(1, len(ranked) + 1), index=ranked.index)
        retained = [
            symbol for symbol in incumbents
            if symbol in rank_by_symbol
            and int(rank_by_symbol.loc[symbol]) <= exit_rank
        ]
        selected = list(retained)
        for symbol in ranked.index:
            if symbol not in selected:
                selected.append(str(symbol))
            if len(selected) == top_k:
                break
        incumbents = selected
        members = frozenset(selected)
        if emitted_dates and members == previous_members:
            continue
        target = pd.Series(0.0, index=columns, name=date)
        if selected:
            preference = pd.Series(1.0, index=selected)
            active = _capped_allocate(
                preference,
                target=active_target,
                cap=active_single_name_cap,
            )
            target.loc[active.index] = active
        target.loc[spy_symbol] = spy_weight
        emitted.append(target)
        emitted_dates.append(pd.Timestamp(date))
        previous_members = members
    decision_weights = pd.DataFrame(
        emitted,
        index=pd.DatetimeIndex(emitted_dates),
        columns=columns,
    )
    return BufferedConstruction(
        decision_weights=decision_weights,
        evaluated_decision_dates=len(scores),
        membership_change_dates=len(decision_weights),
    )


__all__ = [
    "BufferedConstruction",
    "Construction",
    "build_buffered_membership_weights",
    "build_decision_weights",
    "expand_decision_signals",
]
