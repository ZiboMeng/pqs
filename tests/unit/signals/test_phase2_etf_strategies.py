from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.signals.strategies.phase2_etf import (
    AdaptiveCoreStrategy,
    ControlledGrowthStrategy,
    EtfReversionStrategy,
    SectorRotationStrategy,
    SectorRotationV2Strategy,
)


def _panel(rows: int = 420) -> pd.DataFrame:
    index = pd.bdate_range("2018-01-02", periods=rows)
    symbols = {
        "SPY",
        "QQQ",
        "TQQQ",
        "IEF",
        "GLD",
        "BIL",
        "SHY",
        "SHV",
        "XLK",
        "XLF",
        "XLE",
        "XLV",
        "XLI",
        "XLY",
        "XLP",
        "XLU",
        "XLB",
    }
    data = {}
    for offset, symbol in enumerate(sorted(symbols)):
        trend = np.linspace(100.0 + offset, 155.0 + offset, rows)
        cycle = np.sin(np.arange(rows) / (13.0 + offset / 5.0)) * (1.0 + offset / 30.0)
        data[symbol] = trend + cycle
    return pd.DataFrame(data, index=index)


@pytest.mark.parametrize(
    "strategy",
    [
        AdaptiveCoreStrategy(),
        ControlledGrowthStrategy(),
        SectorRotationStrategy(),
        EtfReversionStrategy(),
    ],
)
def test_phase2_strategy_weight_contract(strategy) -> None:
    panel = _panel()
    weights = strategy.generate(panel)
    assert weights.index.equals(panel.index)
    assert weights.columns.equals(panel.columns)
    assert np.isfinite(weights.to_numpy()).all()
    assert float(weights.min().min()) >= 0.0
    assert float(weights.max().max()) <= 0.35 + 1e-12
    assert float(weights.sum(axis=1).max()) <= 1.0 + 1e-12
    assert (weights.iloc[:150].sum(axis=1) == 0.0).all()


def test_phase2_strategies_fail_on_unsorted_or_missing_panel() -> None:
    panel = _panel()
    with pytest.raises(ValueError, match="missing required"):
        AdaptiveCoreStrategy().generate(panel.drop(columns="SPY"))
    with pytest.raises(ValueError, match="sorted and unique"):
        SectorRotationStrategy().generate(panel.sort_index(ascending=False))


def test_controlled_growth_tqqq_never_exceeds_frozen_cap() -> None:
    weights = ControlledGrowthStrategy().generate(_panel(600))
    assert float(weights["TQQQ"].max()) <= 0.10


def test_sector_rotation_v2_caps_a_single_eligible_sector() -> None:
    panel = _panel(520)
    panel["SPY"] = np.linspace(100.0, 220.0, len(panel))
    panel["XLK"] = np.linspace(100.0, 260.0, len(panel))
    for symbol in ("XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB"):
        panel[symbol] = np.linspace(220.0, 80.0, len(panel))
    weights = SectorRotationV2Strategy().generate(panel)
    sparse = weights[weights["XLK"] > 0.34]
    assert not sparse.empty
    assert np.allclose(sparse["XLK"], 0.35)
    assert np.allclose(sparse["BIL"], 0.325)
    assert np.allclose(sparse["SHY"], 0.325)
    assert float(weights.max().max()) <= 0.35
