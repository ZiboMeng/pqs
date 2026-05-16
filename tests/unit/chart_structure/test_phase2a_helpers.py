"""Unit tests for the Phase 2A incremental-IC harness pure helpers.

Per ralph-loop execution PRD §5 round P2A·R1. The harness lives in
dev/scripts/ (not a package) so it is loaded via importlib.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

_HARNESS = (Path(__file__).resolve().parents[3]
            / "dev" / "scripts" / "chart_structure" / "phase2a_incremental_ic.py")


def _load_harness():
    spec = importlib.util.spec_from_file_location("phase2a_harness", _HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_per_year_rank_ic_perfect_and_zero():
    """_per_year_rank_ic ≈ +1 when y_pred perfectly ranks fwd_return,
    and is bounded in [-1, 1]."""
    h = _load_harness()
    rows = []
    for d in pd.date_range("2020-01-01", periods=20, freq="D"):
        for s in range(8):
            rows.append({"date": d, "symbol": f"S{s}",
                         "fwd_return": float(s), "y_pred": float(s)})
    ic = h._per_year_rank_ic(pd.DataFrame(rows))
    assert 2020 in ic
    assert ic[2020] > 0.99  # perfect rank alignment
    assert all(-1.0 <= v <= 1.0 for v in ic.values())


def test_paired_t_positive_deltas():
    """_paired_t on consistently-positive deltas → mean>0, small p,
    CI excludes 0."""
    h = _load_harness()
    stat = h._paired_t([0.011, 0.013, 0.009, 0.012, 0.010, 0.014])
    assert stat["n_years"] == 6
    assert stat["mean_delta_ic"] > 0
    assert stat["p_value"] < 0.05
    assert stat["ci95"][0] > 0  # CI lower bound above zero


def test_paired_t_zero_centered():
    """_paired_t on zero-centered deltas → not significant."""
    h = _load_harness()
    stat = h._paired_t([0.01, -0.011, 0.009, -0.008, 0.002, -0.003])
    assert stat["p_value"] > 0.05
