from __future__ import annotations

import numpy as np
import pandas as pd

from core.regime.phase2_regime import Phase2RegimeAdapter, fail_closed_regime_scale


def test_phase2_regime_unknown_then_hysteretic_and_stressed() -> None:
    index = pd.bdate_range("2020-01-02", periods=280)
    spy = pd.Series(np.linspace(100.0, 150.0, len(index)), index=index)
    legacy = pd.Series("BULL", index=index)
    legacy.iloc[230:235] = "CRISIS"
    result = Phase2RegimeAdapter().classify(legacy, spy)
    assert (result.state.iloc[:199] == "UNKNOWN").all()
    assert result.state.iloc[230] == "STRESSED"
    assert result.state.iloc[235] != "STRONG_BULL_TREND"
    assert result.switch_count >= 2
    assert result.confidence.between(0.0, 1.0).all()


def test_low_confidence_and_unknown_fail_closed() -> None:
    index = pd.bdate_range("2024-01-02", periods=3)
    regime = pd.Series(["RISK_ON", "UNKNOWN", "STRESSED"], index=index)
    confidence = pd.Series([0.8, 1.0, 0.4], index=index)
    scale = fail_closed_regime_scale(regime, confidence)
    assert scale.tolist() == [0.95, 0.0, 0.0]
