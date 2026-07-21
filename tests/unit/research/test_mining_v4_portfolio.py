from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.research.mining_v4_portfolio import (
    build_buffered_membership_weights,
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


def test_rank_buffer_retains_incumbent_until_it_falls_below_exit_rank():
    dates = pd.date_range("2024-01-31", periods=3, freq="ME")
    columns = [f"S{i:02d}" for i in range(16)]
    scores = pd.DataFrame(
        np.tile(np.arange(16, 0, -1, dtype=float), (3, 1)),
        index=dates,
        columns=columns,
    )
    # S09 starts at rank 10, then remains inside the rank-15 exit buffer.
    scores.loc[dates[1], "S09"] = 4.5
    # It finally drops to rank 16 and must be replaced by the best outsider.
    scores.loc[dates[2], "S09"] = 0.0
    result = build_buffered_membership_weights(scores)

    assert result.evaluated_decision_dates == 3
    assert result.membership_change_dates == 2
    assert result.decision_weights.index.tolist() == [dates[0], dates[2]]
    first = result.decision_weights.loc[dates[0]]
    final = result.decision_weights.loc[dates[2]]
    assert first["S09"] == pytest.approx(0.065)
    assert final["S09"] == 0.0
    assert final["S10"] == pytest.approx(0.065)
    assert np.allclose(result.decision_weights.sum(axis=1), 1.0)
    assert (result.decision_weights["SPY"] == 0.35).all()


def test_rank_buffer_rejects_active_spy_and_invalid_exit_rank():
    scores, _ = _scores()
    with pytest.raises(ValueError, match="exit_rank"):
        build_buffered_membership_weights(scores, top_k=10, exit_rank=9)
    with pytest.raises(ValueError, match="anchor"):
        build_buffered_membership_weights(scores.assign(SPY=1.0))
