"""Unit tests for core/ml/chart_structure_injection.py — chart-structure
P2B·R4. Gate P2-A6: post-injection build_ml_panel regression green."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.ml.chart_structure_injection import (
    embedding_factor_frames,
    inject_chart_structure_factors,
    rolling_minirocket_factor_frame,
)
from core.ml.feature_panel_builder import build_ml_panel

_RNG = np.random.default_rng(0)


def _toy_factors_and_fwd():
    dates = pd.bdate_range("2020-01-01", periods=120)
    syms = ["AAA", "BBB", "CCC"]
    f1 = pd.DataFrame(_RNG.standard_normal((120, 3)), index=dates, columns=syms)
    f2 = pd.DataFrame(_RNG.standard_normal((120, 3)), index=dates, columns=syms)
    fwd = pd.DataFrame(_RNG.standard_normal((120, 3)) * 0.01,
                       index=dates, columns=syms)
    return {"mom": f1, "vol": f2}, fwd


def test_inject_nothing_is_identity_for_build_ml_panel():
    """P2-A6: injecting no representation leaves build_ml_panel bit-identical."""
    factors, fwd = _toy_factors_and_fwd()
    base_panel, base_cols = build_ml_panel(factors, fwd)
    merged = inject_chart_structure_factors(factors)  # no repr dicts
    inj_panel, inj_cols = build_ml_panel(merged, fwd)
    assert inj_cols == base_cols
    pd.testing.assert_frame_equal(inj_panel, base_panel)


def test_inject_minirocket_adds_exactly_one_column():
    factors, fwd = _toy_factors_and_fwd()
    close = pd.DataFrame(
        100 + np.cumsum(_RNG.standard_normal((120, 3)) * 0.5, axis=0),
        index=fwd.index, columns=fwd.columns)
    mr = rolling_minirocket_factor_frame(close, window=60)
    merged = inject_chart_structure_factors(factors, mr)
    panel, cols = build_ml_panel(merged, fwd)
    assert cols == ["cs_minirocket_ppv_mean", "mom", "vol"]
    # base panel rows unchanged — same (date,symbol) keys
    base_panel, _ = build_ml_panel(factors, fwd)
    assert len(panel) == len(base_panel)


def test_inject_name_collision_raises():
    factors, _ = _toy_factors_and_fwd()
    clash = {"mom": factors["mom"]}
    with pytest.raises(ValueError, match="collides"):
        inject_chart_structure_factors(factors, clash)


def test_rolling_minirocket_factor_frame_causal_shape():
    close = pd.DataFrame(
        100 + np.cumsum(_RNG.standard_normal((150, 2)) * 0.5, axis=0),
        index=pd.bdate_range("2020-01-01", periods=150), columns=["X", "Y"])
    out = rolling_minirocket_factor_frame(close, window=80)
    frame = out["cs_minirocket_ppv_mean"]
    assert frame.shape == (150, 2)
    assert frame.iloc[0].isna().all()            # warmup → leading NaN
    assert frame.iloc[-1].notna().any()          # non-vacuous after warmup
    # PPV-mean values are bounded in [0, 1]
    fin = frame.to_numpy(float)
    fin = fin[np.isfinite(fin)]
    assert (fin >= 0.0).all() and (fin <= 1.0).all()


def test_rolling_minirocket_rejects_non_cs_name():
    close = pd.DataFrame({"X": [1.0] * 100},
                         index=pd.bdate_range("2020-01-01", periods=100))
    with pytest.raises(ValueError, match="cs_"):
        rolling_minirocket_factor_frame(close, factor_name="bad_name")


def test_embedding_factor_frames_one_per_dim():
    dates = pd.bdate_range("2020-01-01", periods=40)
    emb = {s: pd.DataFrame(_RNG.standard_normal((40, 8)), index=dates)
           for s in ("AAA", "BBB")}
    frames = embedding_factor_frames(emb, dims=8, prefix="cs_emb")
    assert len(frames) == 8
    assert set(frames) == {f"cs_emb_{d}" for d in range(8)}
    assert frames["cs_emb_0"].shape == (40, 2)
    assert embedding_factor_frames({}, dims=8) == {}  # empty → empty
