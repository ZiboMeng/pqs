from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.research.feature_clustering import fit_feature_correlation_clusters
from core.research.mining_v4_features import (
    build_causal_numeric_features,
    month_end_decision_dates,
)


def _panel(n_days: int = 400, n_symbols: int = 5, seed: int = 42):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2020-01-02", periods=n_days)
    columns = [f"S{i}" for i in range(n_symbols)]
    returns = rng.normal(0.0003, 0.01, size=(n_days, n_symbols))
    close = pd.DataFrame(
        100 * np.exp(np.cumsum(returns, axis=0)), index=index, columns=columns)
    open_ = close.shift(1).fillna(close.iloc[0]) * (
        1 + rng.normal(0, 0.002, size=close.shape))
    high = pd.DataFrame(
        np.maximum(open_, close) * 1.005, index=index, columns=columns)
    low = pd.DataFrame(
        np.minimum(open_, close) * 0.995, index=index, columns=columns)
    volume = pd.DataFrame(
        rng.integers(1_000_000, 5_000_000, size=close.shape),
        index=index,
        columns=columns,
    )
    return {
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    }


def test_numeric_features_are_prefix_invariant():
    original = _panel()
    market = original["close"]["S0"]
    original_features = build_causal_numeric_features(original, market)
    future = _panel(n_days=5, seed=7)
    future_index = pd.bdate_range(
        original["close"].index[-1] + pd.offsets.BDay(), periods=5)
    extended = {}
    for name, frame in original.items():
        tail = future[name].copy()
        tail.index = future_index
        tail *= 100.0
        extended[name] = pd.concat([frame, tail])
    extended_market = extended["close"]["S0"]
    extended_features = build_causal_numeric_features(extended, extended_market)
    for name, frame in original_features.items():
        pd.testing.assert_frame_equal(
            frame,
            extended_features[name].loc[frame.index],
            check_freq=False,
        )


def test_month_end_dates_require_available_benchmark():
    index = pd.bdate_range("2024-01-01", "2024-03-31")
    market = pd.Series(100.0, index=index)
    market.loc[index[index.month == 2][-1]] = np.nan
    dates = month_end_decision_dates(index, market)
    assert dates[0] == index[index.month == 1][-1]
    assert dates[1] == index[index.month == 2][-2]
    assert dates[2] == index[index.month == 3][-1]


def test_numeric_features_use_exact_cash_returns_without_faking_liquidity():
    panel = _panel(n_days=80, n_symbols=2)
    event_date = panel["close"].index[40]
    previous_date = panel["close"].index[39]
    panel["close"].loc[previous_date, "S1"] = 100.0
    panel["open"].loc[event_date, "S1"] = 90.0
    panel["high"].loc[event_date, "S1"] = 91.0
    panel["low"].loc[event_date, "S1"] = 89.0
    panel["close"].loc[event_date, "S1"] = 90.0
    panel["cash_distribution"] = pd.DataFrame(
        0.0, index=panel["close"].index, columns=panel["close"].columns,
    )
    panel["cash_distribution"].loc[event_date, "S1"] = 10.0
    exact_return_close = panel["close"].copy()
    exact_return_close.loc[event_date:, "S1"] *= 100.0 / 90.0
    panel["total_return_close"] = exact_return_close

    features = build_causal_numeric_features(
        panel, exact_return_close["S0"],
    )

    assert features["mom_5"].loc[event_date, "S1"] == pytest.approx(
        exact_return_close.loc[event_date, "S1"]
        / exact_return_close.loc[panel["close"].index[35], "S1"]
        - 1.0
    )
    expected_gap = (
        panel["open"]["S1"].add(panel["cash_distribution"]["S1"])
        .div(panel["close"]["S1"].shift(1))
        .sub(1.0)
        .rolling(5, min_periods=5)
        .mean()
    )
    assert features["overnight_gap_mean_5"].loc[event_date, "S1"] == pytest.approx(
        expected_gap.loc[event_date]
    )


def test_feature_clustering_is_fit_only_on_supplied_training_dates():
    index = pd.bdate_range("2020-01-01", periods=20)
    columns = ["A", "B", "C", "D", "E", "F"]
    base = pd.DataFrame(
        np.arange(len(index) * len(columns)).reshape(len(index), -1),
        index=index,
        columns=columns,
    )
    features = {
        "alpha": base,
        "alpha_copy": base * 2.0,
        "independent": pd.DataFrame(
            np.random.default_rng(9).normal(size=base.shape),
            index=index,
            columns=columns,
        ),
    }
    mask = pd.DataFrame(True, index=index, columns=columns)
    train_dates = index[:12]
    fit_one = fit_feature_correlation_clusters(
        features, mask, train_dates, min_pair_observations=20)
    changed = dict(features)
    changed["alpha_copy"] = changed["alpha_copy"].copy()
    changed["alpha_copy"].loc[index[12:]] = np.random.default_rng(1).normal(
        size=(8, len(columns)))
    fit_two = fit_feature_correlation_clusters(
        changed, mask, train_dates, min_pair_observations=20)
    assert fit_one == fit_two
    assert any(set(cluster) == {"alpha", "alpha_copy"} for cluster in fit_one.clusters)
