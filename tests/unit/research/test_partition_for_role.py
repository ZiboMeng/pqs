"""Tests for core/research/temporal_split.py::partition_for_role
(cycle #02 audit WARN #2 fix; cycle #03 prep — eval stage needs
validation-year visibility, miner stage doesn't).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.research.temporal_split import (
    load_temporal_split,
    partition_for_role,
    restrict_frames_to_train,
)


ROOT = Path("/home/zibo/Documents/projects/pqs")


def _build_panel(start="2007-01-02", end="2026-12-31"):
    """Synthetic panel covering reference + train + validation + sealed."""
    idx = pd.bdate_range(start, end)
    syms = ["AAA", "BBB", "SPY"]
    return {
        "close":  pd.DataFrame(
            {s: 100.0 + pd.RangeIndex(len(idx)) for s in syms}, index=idx
        ),
        "open":   pd.DataFrame({s: 99.0 for s in syms}, index=idx),
        "high":   pd.DataFrame({s: 101.0 for s in syms}, index=idx),
        "low":    pd.DataFrame({s: 98.0 for s in syms}, index=idx),
        "volume": pd.DataFrame({s: 1_000_000 for s in syms}, index=idx),
    }


def _split_cfg():
    return load_temporal_split(ROOT / "config" / "temporal_split.yaml")


# ── miner role ────────────────────────────────────────────────────────


def test_miner_role_returns_train_only():
    """Mining stage gets train years only; identical output to legacy
    restrict_frames_to_train."""
    cfg = _split_cfg()
    frames = _build_panel()
    miner_out = partition_for_role(frames, cfg, role="miner")
    legacy_out = restrict_frames_to_train(frames, cfg)
    pd.testing.assert_frame_equal(miner_out["close"], legacy_out["close"])
    pd.testing.assert_frame_equal(miner_out["open"], legacy_out["open"])
    # Miner panel must NOT contain validation/sealed years
    miner_years = set(miner_out["close"].index.year.unique())
    assert 2018 not in miner_years and 2025 not in miner_years
    assert 2026 not in miner_years
    # But MUST contain train years
    assert {2009, 2010, 2017, 2020, 2022, 2024}.issubset(miner_years)


# ── selector role ─────────────────────────────────────────────────────


def test_selector_role_includes_train_and_validation():
    """Eval stage gets train + validation; sealed stays excluded."""
    cfg = _split_cfg()
    frames = _build_panel()
    sel_out = partition_for_role(frames, cfg, role="selector")
    sel_years = set(sel_out["close"].index.year.unique())
    # train years
    assert {2009, 2017, 2020, 2024}.issubset(sel_years)
    # validation years
    assert {2018, 2019, 2021, 2023, 2025}.issubset(sel_years)
    # sealed years EXCLUDED
    assert 2026 not in sel_years
    # reference years (2007/2008) excluded by access rules
    assert 2007 not in sel_years and 2008 not in sel_years


def test_selector_panel_strictly_larger_than_miner_panel():
    """Selector includes everything miner sees PLUS validation years."""
    cfg = _split_cfg()
    frames = _build_panel()
    miner_out = partition_for_role(frames, cfg, role="miner")
    sel_out = partition_for_role(frames, cfg, role="selector")
    assert len(sel_out["close"]) > len(miner_out["close"])
    # Every miner row must be in selector
    assert miner_out["close"].index.isin(sel_out["close"].index).all()


# ── sealed_test_runner role ───────────────────────────────────────────


def test_sealed_test_runner_role_returns_sealed_years_only():
    """Sealed evaluation panel = sealed years only."""
    cfg = _split_cfg()
    frames = _build_panel()
    seal_out = partition_for_role(frames, cfg, role="sealed_test_runner")
    seal_years = set(seal_out["close"].index.year.unique())
    assert seal_years == {2026}


# ── invariants ─────────────────────────────────────────────────────────


def test_unknown_role_raises():
    cfg = _split_cfg()
    frames = _build_panel()
    with pytest.raises(ValueError, match="unknown role"):
        partition_for_role(frames, cfg, role="some_random_role")


def test_none_frames_pass_through():
    """None values (for absent attributes) survive the filter as None."""
    cfg = _split_cfg()
    base = _build_panel()
    base["high"] = None  # simulate missing high panel
    out = partition_for_role(base, cfg, role="selector")
    assert out["high"] is None
    assert out["close"] is not None


def test_non_datetime_index_raises():
    cfg = _split_cfg()
    df_bad = pd.DataFrame({"AAA": [1, 2, 3]})  # RangeIndex
    frames = {"close": df_bad}
    with pytest.raises(TypeError, match="lacks .year attribute"):
        partition_for_role(frames, cfg, role="miner")


def test_selector_role_2026_NEVER_in_panel():
    """Critical sealed-window protection: regardless of yaml content,
    selector role MUST NOT see sealed year rows."""
    cfg = _split_cfg()
    frames = _build_panel()
    sel_out = partition_for_role(frames, cfg, role="selector")
    n_2026 = (sel_out["close"].index.year == 2026).sum()
    assert n_2026 == 0, (
        f"selector role leaked {n_2026} sealed-year rows; this is "
        f"the cycle-#02-style data isolation breach"
    )
