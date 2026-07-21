from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.research.mining_v4_portfolio import (
    build_decision_weights,
    expand_decision_signals,
)


def _scores(n_symbols: int = 12):
    index = pd.DatetimeIndex(["2024-01-31", "2024-02-29"])
    columns = [f"S{i:02d}" for i in range(n_symbols)]
    scores = pd.DataFrame(
        np.tile(np.arange(n_symbols, dtype=float), (2, 1)),
        index=index,
        columns=columns,
    )
    volatility = pd.DataFrame(
        np.tile(np.linspace(0.1, 0.5, n_symbols), (2, 1)),
        index=index,
        columns=columns,
    )
    return scores, volatility


@pytest.mark.parametrize(
    "construction",
    [
        "active_top10_control",
        "spy35_active65_equal_top10",
        "spy35_active65_rank_vol_top10",
    ],
)
def test_constructions_are_long_only_capped_and_fully_invested(construction):
    scores, volatility = _scores()
    weights = build_decision_weights(scores, volatility, construction)
    assert (weights >= 0).all().all()
    active = weights.drop(columns="SPY") if "SPY" in weights else weights
    assert active.max().max() <= 0.10 + 1e-12
    assert np.allclose(weights.sum(axis=1), 1.0)
    if construction.startswith("spy35"):
        assert (weights["SPY"] == 0.35).all()


def test_too_few_names_leaves_cash_instead_of_breaking_cap():
    scores, volatility = _scores(n_symbols=3)
    weights = build_decision_weights(
        scores, volatility, "active_top10_control")
    assert np.allclose(weights.sum(axis=1), 0.30)
    assert weights.max().max() == pytest.approx(0.10)


def test_expanded_signals_trade_only_on_decision_rows():
    scores, volatility = _scores()
    weights = build_decision_weights(
        scores, volatility, "spy35_active65_equal_top10")
    daily = pd.bdate_range("2024-01-02", "2024-03-01")
    signals = expand_decision_signals(weights, daily)
    assert (signals.loc[weights.index] == weights).all().all()
    assert (signals.drop(index=weights.index) == 0.0).all().all()
