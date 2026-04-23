"""Unit tests for core/factors/base_masks.py (PRD 20260423 Step 1 R05)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.base_masks import (
    price_floor_mask,
    tradable_mask_dollar_vol,
    research_mask,
    apply_research_mask,
)


@pytest.fixture
def panel():
    """6-bar × 3-symbol panel.

    A: high price ($100), high volume
    B: low price ($3 — below $5 floor)
    C: high price, LOW volume (below dollar-vol threshold)
    """
    idx = pd.bdate_range("2024-01-02", periods=6)
    close = pd.DataFrame({
        "A": [100.0] * 6,
        "B": [3.0] * 6,
        "C": [80.0] * 6,
    }, index=idx)
    # Volume: A = 300k → 100 * 300k = 30M > 20M ✓
    #         B = 1M   → 3 * 1M = 3M  < 20M ✗ (but fails price floor anyway)
    #         C = 50k  → 80 * 50k = 4M < 20M ✗
    volume = pd.DataFrame({
        "A": [300_000.0] * 6,
        "B": [1_000_000.0] * 6,
        "C": [50_000.0] * 6,
    }, index=idx)
    return {"close": close, "volume": volume}


# ── price_floor_mask ──────────────────────────────────────────────────────────

def test_price_floor_mask_passes_high_prices(panel):
    m = price_floor_mask(panel["close"], min_price=5.0)
    assert m["A"].all()
    assert not m["B"].any()  # $3 below floor
    assert m["C"].all()


def test_price_floor_mask_custom_threshold(panel):
    m = price_floor_mask(panel["close"], min_price=90.0)
    # Only A ($100) clears $90 floor
    assert m["A"].all()
    assert not m["B"].any()
    assert not m["C"].any()


def test_price_floor_mask_nan_becomes_false():
    idx = pd.bdate_range("2024-01-02", periods=4)
    close = pd.DataFrame({"X": [100, np.nan, 50, 10]}, index=idx)
    m = price_floor_mask(close, min_price=5.0)
    assert m.iloc[0, 0] == True
    assert m.iloc[1, 0] == False  # NaN → False, not NaN
    assert m.iloc[2, 0] == True
    assert m.iloc[3, 0] == True


def test_price_floor_mask_negative_threshold_rejected(panel):
    with pytest.raises(ValueError):
        price_floor_mask(panel["close"], min_price=-1)


# ── tradable_mask_dollar_vol ──────────────────────────────────────────────────

def test_tradable_mask_dollar_vol_basic(panel):
    # window=3 to get valid values early (min_periods defaults to window//2=1)
    m = tradable_mask_dollar_vol(
        panel["close"], panel["volume"], min_usd=20_000_000, window=3,
    )
    # A: $100 × 300k = $30M/day → rolling 3d mean = $30M ≥ $20M → all True
    assert m["A"].all()
    # B: $3 × 1M = $3M → rolling mean = $3M < $20M → all False
    assert not m["B"].any()
    # C: $80 × 50k = $4M → < $20M → all False
    assert not m["C"].any()


def test_tradable_mask_dollar_vol_window_20_warmup(panel):
    """With window=20 and only 6 bars, min_periods=10 (window//2) → all NaN
    → all False (warmup not tradable yet)."""
    # Extend to 15 bars to get some valid rolling windows
    idx = pd.bdate_range("2024-01-02", periods=15)
    close = pd.DataFrame({"A": [100.0] * 15}, index=idx)
    volume = pd.DataFrame({"A": [300_000.0] * 15}, index=idx)
    m = tradable_mask_dollar_vol(close, volume, min_usd=20e6, window=20)
    # min_periods defaults to 10 → bars 0..8 (9 bars) NaN→False; 9..14 valid
    assert not m["A"].iloc[:9].any()
    assert m["A"].iloc[9:].all()


def test_tradable_mask_dollar_vol_negative_threshold_rejected(panel):
    with pytest.raises(ValueError):
        tradable_mask_dollar_vol(
            panel["close"], panel["volume"], min_usd=-1, window=20,
        )


# ── research_mask (combined) ──────────────────────────────────────────────────

def test_research_mask_intersects_both_filters(panel):
    m = research_mask(
        panel["close"], panel["volume"],
        min_price=5.0, min_usd=20_000_000, window=3,
    )
    # A passes both → True
    assert m["A"].all()
    # B fails price → False everywhere
    assert not m["B"].any()
    # C fails volume → False everywhere
    assert not m["C"].any()


def test_research_mask_same_shape_as_price_df(panel):
    m = research_mask(panel["close"], panel["volume"], window=3)
    assert m.shape == panel["close"].shape
    assert list(m.columns) == list(panel["close"].columns)
    assert m.dtypes.eq(bool).all()


# ── apply_research_mask (PRD 20260424 §7 sample-definition hardening) ────────


@pytest.fixture
def factor_and_mask():
    """3-bar × 2-symbol factor panel + matching mask."""
    idx = pd.bdate_range("2024-01-02", periods=3)
    factor = pd.DataFrame(
        {"A": [0.5, 0.7, 0.3], "B": [0.1, 0.9, 0.6]},
        index=idx,
    )
    mask = pd.DataFrame(
        {"A": [True, False, True], "B": [True, True, False]},
        index=idx,
    )
    return factor, mask


def test_apply_research_mask_replaces_false_with_nan(factor_and_mask):
    factor, mask = factor_and_mask
    out = apply_research_mask(factor, mask)
    # True cells keep original value
    assert out.iloc[0, 0] == pytest.approx(0.5)
    assert out.iloc[0, 1] == pytest.approx(0.1)
    # False cells → NaN
    assert np.isnan(out.iloc[1, 0])
    assert np.isnan(out.iloc[2, 1])


def test_apply_research_mask_custom_fill_value(factor_and_mask):
    """Explicit fill=0 is allowed + intentional (unlike implicit fillna(0))."""
    factor, mask = factor_and_mask
    out = apply_research_mask(factor, mask, fill=0.0)
    # False cells → 0 (not NaN)
    assert out.iloc[1, 0] == 0.0
    assert out.iloc[2, 1] == 0.0
    # True cells unchanged
    assert out.iloc[0, 0] == pytest.approx(0.5)


def test_apply_research_mask_preserves_existing_nan(factor_and_mask):
    """Pre-existing NaN in factor (e.g. warmup) stays NaN regardless of mask."""
    factor, mask = factor_and_mask
    # Inject warmup NaN at (0, A)
    factor_with_nan = factor.copy()
    factor_with_nan.iloc[0, 0] = np.nan
    out = apply_research_mask(factor_with_nan, mask)
    # (0, A): factor was NaN; mask was True — still NaN after
    assert np.isnan(out.iloc[0, 0])
    # Other True cells unchanged
    assert out.iloc[0, 1] == pytest.approx(0.1)


def test_apply_research_mask_missing_mask_cells_become_false(factor_and_mask):
    """If mask has fewer columns/rows than factor, missing cells treated as False."""
    factor, mask = factor_and_mask
    # Mask only covers symbol A, not B
    short_mask = mask[["A"]]
    out = apply_research_mask(factor, short_mask)
    # A column: same as before
    assert out.iloc[0, 0] == pytest.approx(0.5)
    assert np.isnan(out.iloc[1, 0])
    # B column: mask absent → treated as all False → all NaN
    assert out["B"].isna().all()


def test_apply_research_mask_shape_preserved(factor_and_mask):
    factor, mask = factor_and_mask
    out = apply_research_mask(factor, mask)
    assert out.shape == factor.shape
    assert list(out.columns) == list(factor.columns)
    assert out.index.equals(factor.index)


def test_apply_research_mask_real_panel_usage(panel):
    """End-to-end with price_floor_mask: low-priced stock B becomes NaN."""
    pf_mask = price_floor_mask(panel["close"], min_price=5.0)
    # Make a fake factor panel: returns
    factor = panel["close"].pct_change().fillna(0)  # deliberate fillna(0)
    # Apply mask — B ($3) fully masked out; A ($100) and C ($80) unchanged
    out = apply_research_mask(factor, pf_mask)
    assert out["A"].notna().all() or out["A"].isna().sum() <= 1  # only possible leading-NaN
    # After pct_change, first row has NaN; after fillna(0) then mask
    # => (0, A) = 0 with mask True stays 0 (not NaN)
    assert out["B"].isna().all()  # all B cells masked (below $5)
    # A and C should have surviving zeros at row 0 (fillna(0) before mask)
    assert out.iloc[0, 0] == 0.0
