from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.research.dynamic_universe import (
    DynamicEligibilityConfig,
    build_dynamic_eligibility_mask,
    eligible_symbols,
)


def _panels(n: int = 12):
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = pd.DataFrame(
        {
            "AAA": np.linspace(10.0, 12.0, n),
            "DEAD": np.linspace(20.0, 22.0, n),
            "LOW": np.linspace(2.0, 3.0, n),
            "BLOCKED": np.linspace(30.0, 35.0, n),
        },
        index=idx,
    )
    volume = pd.DataFrame(1_000_000.0, index=idx, columns=close.columns)
    close.loc[idx[-2]:, "DEAD"] = np.nan
    volume.loc[idx[-2]:, "DEAD"] = np.nan
    return close, volume


def _cfg():
    return DynamicEligibilityConfig(
        min_history_sessions=5,
        lookback_sessions=4,
        min_observation_density=0.75,
        min_price=5.0,
        min_median_dollar_volume=5_000_000.0,
        excluded_symbols=("BLOCKED",),
    )


def test_dynamic_mask_enforces_history_liquidity_price_current_bar_and_exclusion():
    close, volume = _panels()
    mask = build_dynamic_eligibility_mask(close, volume, _cfg())
    assert not mask.iloc[3]["AAA"]
    assert mask.iloc[4]["AAA"]
    assert not mask.iloc[-1]["DEAD"]
    assert not mask["LOW"].any()
    assert not mask["BLOCKED"].any()


def test_dynamic_mask_is_prefix_invariant_when_future_rows_are_appended():
    close, volume = _panels(20)
    full = build_dynamic_eligibility_mask(close, volume, _cfg())
    prefix = build_dynamic_eligibility_mask(close.iloc[:14], volume.iloc[:14], _cfg())
    pd.testing.assert_frame_equal(full.iloc[:14], prefix)


def test_decision_date_slice_keeps_session_lookback_semantics():
    close, volume = _panels(20)
    decisions = close.index[[9, 14, 19]]
    sliced = build_dynamic_eligibility_mask(
        close, volume, _cfg(), decision_dates=decisions)
    assert sliced.index.equals(decisions)
    assert sliced.loc[decisions[0], "AAA"]
    with pytest.raises(KeyError, match="absent"):
        build_dynamic_eligibility_mask(
            close, volume, _cfg(), decision_dates=[pd.Timestamp("1999-01-01")])


def test_eligible_symbols_respects_frozen_pool_order():
    close, volume = _panels()
    mask = build_dynamic_eligibility_mask(close, volume, _cfg())
    assert eligible_symbols(
        mask, close.index[-1], ordered_pool=["LOW", "AAA", "DEAD"]
    ) == ["AAA"]


def test_panel_shape_and_config_fail_closed():
    close, volume = _panels()
    with pytest.raises(ValueError, match="indexes"):
        build_dynamic_eligibility_mask(close, volume.iloc[:-1], _cfg())
    with pytest.raises(ValueError, match="density"):
        DynamicEligibilityConfig(min_observation_density=0.0)
