"""Unit tests for core/research/taa/asset_class_builder.py (PRD-E §4.4)."""

from __future__ import annotations

import pandas as pd
import pytest

from core.regime.regime_detector import RegimeState
from core.research.taa.asset_class_builder import (
    build_class_to_symbols,
    build_target_weights_for_regime,
    build_target_wts_panel,
)
from core.research.taa.regime_rules import (
    DEFAULT_TAA_RULES_V0_MINIMAL,
    DEFAULT_TAA_RULES_V1,
    RegimeAllocation,
)


# ── build_class_to_symbols ───────────────────────────────────────────────────


def _stub_lookup(sym: str) -> str:
    """Minimal asset_class_lookup stub for unit tests."""
    return {
        "AAPL": "equities", "MSFT": "equities",
        "TLT": "bonds", "IEF": "bonds",
        "GLD": "commodities",
        "BIL": "cash_anchor", "SHV": "cash_anchor",
    }.get(sym, "equities")


def test_build_class_to_symbols_groups_correctly():
    out = build_class_to_symbols(
        ["AAPL", "MSFT", "TLT", "GLD", "BIL"],
        asset_class_lookup=_stub_lookup,
    )
    assert sorted(out["equities"]) == ["AAPL", "MSFT"]
    assert sorted(out["bonds"]) == ["TLT"]
    assert sorted(out["commodities"]) == ["GLD"]
    assert sorted(out["cash_anchor"]) == ["BIL"]


def test_build_class_to_symbols_empty_class_present():
    out = build_class_to_symbols(["AAPL"], asset_class_lookup=_stub_lookup)
    assert out["bonds"] == []
    assert out["commodities"] == []
    assert out["cash_anchor"] == []


# ── build_target_weights_for_regime ──────────────────────────────────────────


def test_build_target_weights_for_regime_equal_weights_within_class():
    """V1 BULL = 70/20/5/5: 2 equity + 2 bond + 1 commodity + 1 cash =
    each equity gets 35%, each bond 10%, gold 5%, cash 5%. All sum to 1."""
    alloc = DEFAULT_TAA_RULES_V1[RegimeState.BULL]
    syms = {
        "equities": ["AAPL", "MSFT"],
        "bonds": ["TLT", "IEF"],
        "commodities": ["GLD"],
        "cash_anchor": ["BIL"],
    }
    w = build_target_weights_for_regime(alloc, syms)
    assert abs(w["AAPL"] - 0.35) < 1e-9
    assert abs(w["MSFT"] - 0.35) < 1e-9
    assert abs(w["TLT"] - 0.10) < 1e-9
    assert abs(w["IEF"] - 0.10) < 1e-9
    assert abs(w["GLD"] - 0.05) < 1e-9
    assert abs(w["BIL"] - 0.05) < 1e-9
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_build_target_weights_for_regime_zero_class_skipped():
    """V0_MINIMAL has commodities=0 + cash=0 → those classes contribute 0
    symbols (not raising)."""
    alloc = DEFAULT_TAA_RULES_V0_MINIMAL[RegimeState.BULL]
    syms = {
        "equities": ["AAPL", "MSFT"],
        "bonds": ["TLT"],
        "commodities": [],
        "cash_anchor": [],
    }
    w = build_target_weights_for_regime(alloc, syms)
    # 60% equity / 30 each / 40% bond / TLT only
    assert abs(w["AAPL"] - 0.30) < 1e-9
    assert abs(w["MSFT"] - 0.30) < 1e-9
    assert abs(w["TLT"] - 0.40) < 1e-9
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_build_target_weights_for_regime_missing_class_raises():
    """V1 requires non-zero commodities + cash → raise if universe lacks them."""
    alloc = DEFAULT_TAA_RULES_V1[RegimeState.BULL]
    syms = {
        "equities": ["AAPL"], "bonds": ["TLT"],
        "commodities": [], "cash_anchor": [],
    }
    with pytest.raises(ValueError, match="no .* symbols"):
        build_target_weights_for_regime(alloc, syms)


# ── build_target_wts_panel ───────────────────────────────────────────────────


def test_build_target_wts_panel_full_pipeline():
    """End-to-end: regime_labels (3 rebalance dates) + V0_MINIMAL +
    minimal universe → produces 3-row × 3-col DataFrame with each row
    summing to 1."""
    idx = pd.DatetimeIndex(["2020-01-01", "2020-02-01", "2020-03-01"])
    labels = pd.Series(["BULL", "RISK_OFF", "CRISIS"], index=idx, dtype=str)
    universe = ["AAPL", "MSFT", "TLT"]
    panel = build_target_wts_panel(
        labels, DEFAULT_TAA_RULES_V0_MINIMAL, universe,
        asset_class_lookup=_stub_lookup,
    )
    assert panel.shape == (3, 3)
    assert list(panel.columns) == sorted(universe)
    for date in idx:
        assert abs(panel.loc[date].sum() - 1.0) < 1e-9


def test_build_target_wts_panel_invalid_label_raises():
    idx = pd.DatetimeIndex(["2020-01-01"])
    labels = pd.Series(["NOT_A_REGIME"], index=idx, dtype=str)
    universe = ["AAPL", "TLT"]
    with pytest.raises(ValueError, match="not a valid"):
        build_target_wts_panel(
            labels, DEFAULT_TAA_RULES_V0_MINIMAL, universe,
            asset_class_lookup=_stub_lookup,
        )


def test_build_target_wts_panel_columns_aligned():
    """Universe symbols not in any allocation still appear with 0 weights
    (harness alignment)."""
    idx = pd.DatetimeIndex(["2020-01-01"])
    labels = pd.Series(["BULL"], index=idx, dtype=str)
    universe = ["AAPL", "TLT", "ZZZ"]  # ZZZ not in stub lookup → defaults equities
    panel = build_target_wts_panel(
        labels, DEFAULT_TAA_RULES_V0_MINIMAL, universe,
        asset_class_lookup=_stub_lookup,
    )
    assert "ZZZ" in panel.columns
