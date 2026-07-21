"""Portfolio construction helpers for governed rank-mining candidates."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

Construction = Literal[
    "active_top10_control",
    "spy35_active65_equal_top10",
    "spy35_active65_rank_vol_top10",
]


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


__all__ = ["Construction", "build_decision_weights", "expand_decision_signals"]
