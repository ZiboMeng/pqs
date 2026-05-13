"""Unit tests for core.ml.feature_panel_builder.

Per `docs/prd/20260512-ml_mining_pipeline_prd.md` §3.6 (15-20 tests).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.ml.feature_panel_builder import (
    build_ml_panel,
    cross_sectional_rank,
)


def _toy_factor(seed: int = 0) -> pd.DataFrame:
    """3 dates × 5 symbols toy factor with one NaN."""
    np.random.seed(seed)
    dates = pd.date_range("2020-01-01", periods=3, freq="D")
    syms = list("ABCDE")
    df = pd.DataFrame(np.random.randn(3, 5), index=dates, columns=syms)
    df.iloc[1, 2] = np.nan
    return df


def test_cross_sectional_rank_basic():
    """Rank produces values in [0, 1] and preserves NaN."""
    df = _toy_factor()
    ranks = cross_sectional_rank(df)
    assert ranks.shape == df.shape
    # All non-NaN ranks should be in [0, 1]
    finite_vals = ranks.values[~np.isnan(ranks.values)]
    assert (finite_vals >= 0).all()
    assert (finite_vals <= 1).all()
    # NaN preserved
    assert pd.isna(ranks.iloc[1, 2])


def test_cross_sectional_rank_monotonic():
    """Higher raw value → higher rank within each row."""
    df = pd.DataFrame(
        [[1.0, 2.0, 3.0, 4.0, 5.0], [5.0, 4.0, 3.0, 2.0, 1.0]],
        index=pd.date_range("2020-01-01", periods=2),
        columns=list("ABCDE"),
    )
    ranks = cross_sectional_rank(df)
    # Row 0: A=lowest, E=highest
    assert ranks.iloc[0, 0] < ranks.iloc[0, 4]
    # Row 1: E=lowest, A=highest
    assert ranks.iloc[1, 0] > ranks.iloc[1, 4]


def test_cross_sectional_rank_ties_average():
    """Ties get averaged rank (default method)."""
    df = pd.DataFrame(
        [[1.0, 1.0, 2.0, 3.0]],
        index=pd.date_range("2020-01-01", periods=1),
        columns=list("ABCD"),
    )
    ranks = cross_sectional_rank(df, method="average")
    # A and B tied at lowest → both get (1+2)/2 / 4 = 0.375
    assert ranks.iloc[0, 0] == ranks.iloc[0, 1]
    assert ranks.iloc[0, 0] == pytest.approx(0.375, abs=0.001)


def test_cross_sectional_rank_all_nan_row():
    """All-NaN row stays all-NaN."""
    df = pd.DataFrame(
        [[np.nan, np.nan, np.nan]],
        index=pd.date_range("2020-01-01", periods=1),
        columns=list("ABC"),
    )
    ranks = cross_sectional_rank(df)
    assert ranks.isna().all().all()


def test_build_ml_panel_basic():
    """build_ml_panel produces long-form panel with expected columns."""
    fac_a = _toy_factor(seed=0)
    fac_b = _toy_factor(seed=1)
    fwd = _toy_factor(seed=2)
    panel, feats = build_ml_panel(
        {"fac_a": fac_a, "fac_b": fac_b}, fwd,
    )
    assert "date" in panel.columns
    assert "symbol" in panel.columns
    assert "fwd_return" in panel.columns
    assert set(feats) == {"fac_a", "fac_b"}
    # Each row should have a non-NaN fwd_return
    assert panel["fwd_return"].notna().all()


def test_build_ml_panel_rank_applied():
    """When apply_rank=True, factor values become ranks in [0, 1]."""
    fac = pd.DataFrame(
        [[1.0, 2.0, 3.0, 4.0]],
        index=pd.date_range("2020-01-01", periods=1),
        columns=list("ABCD"),
    )
    fwd = pd.DataFrame(
        [[0.01, 0.02, 0.03, 0.04]],
        index=pd.date_range("2020-01-01", periods=1),
        columns=list("ABCD"),
    )
    panel, feats = build_ml_panel({"fac": fac}, fwd, apply_rank=True)
    assert len(panel) == 4
    # Ranks should be 0.25, 0.5, 0.75, 1.0
    assert panel["fac"].min() == pytest.approx(0.25)
    assert panel["fac"].max() == pytest.approx(1.0)


def test_build_ml_panel_no_rank():
    """When apply_rank=False, raw factor values preserved."""
    fac = pd.DataFrame(
        [[1.0, 2.0, 3.0]],
        index=pd.date_range("2020-01-01", periods=1),
        columns=list("ABC"),
    )
    fwd = pd.DataFrame(
        [[0.01, 0.02, 0.03]],
        index=pd.date_range("2020-01-01", periods=1),
        columns=list("ABC"),
    )
    panel, _ = build_ml_panel({"fac": fac}, fwd, apply_rank=False)
    assert panel["fac"].tolist() == [1.0, 2.0, 3.0]


def test_build_ml_panel_skip_nan_fwd_return():
    """Rows with NaN forward return are excluded."""
    fac = _toy_factor(seed=0)
    fwd = _toy_factor(seed=2)
    fwd.iloc[0, 0] = np.nan
    panel, _ = build_ml_panel({"fac": fac}, fwd)
    # First date, sym A should be skipped due to NaN fwd
    first_date_a = panel[
        (panel["date"] == fwd.index[0]) & (panel["symbol"] == "A")
    ]
    assert len(first_date_a) == 0


def test_build_ml_panel_research_mask_filters():
    """research_mask=False entries excluded from panel."""
    fac = _toy_factor(seed=0)
    fwd = _toy_factor(seed=2)
    # Mask out date 0 sym A
    mask = pd.DataFrame(
        True, index=fac.index, columns=fac.columns,
    )
    mask.iloc[0, 0] = False
    panel, _ = build_ml_panel({"fac": fac}, fwd, research_mask=mask)
    first_a = panel[
        (panel["date"] == fac.index[0]) & (panel["symbol"] == "A")
    ]
    assert len(first_a) == 0
