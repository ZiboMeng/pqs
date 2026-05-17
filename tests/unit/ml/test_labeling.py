"""R1 acceptance — labeling layer (supplementary PRD §4).

R1-A1 concurrency weighting · R1-A2 triple-barrier · R1-A3 causal.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from core.ml.labeling import (
    avg_uniqueness,
    concurrency_weights,
    triple_barrier_labels,
)

_PROJ = Path(__file__).resolve().parents[3]


# R1-A1 ---------------------------------------------------------------
def test_uniqueness_independent_is_one_overlap_lt_one():
    idx = pd.bdate_range("2015-01-02", periods=50)
    # horizon 0 → every sample independent → uniqueness exactly 1.0
    u0 = avg_uniqueness(idx, horizon=0)
    assert np.allclose(u0.to_numpy(), 1.0)
    # horizon 20 → heavy overlap → interior uniqueness well below 1
    u20 = avg_uniqueness(idx, horizon=20)
    interior = u20.iloc[20:30].to_numpy()
    assert (interior < 0.2).all() and (interior > 0.0).all()
    # weights normalized to mean ~1
    w = concurrency_weights(idx, horizon=20)
    assert abs(w.mean() - 1.0) < 1e-9


def test_uniqueness_monotone_in_overlap():
    idx = pd.bdate_range("2015-01-02", periods=80)
    means = [avg_uniqueness(idx, h).iloc[10:60].mean() for h in (1, 5, 10, 20)]
    # more overlap (larger horizon) → strictly lower average uniqueness
    assert means[0] > means[1] > means[2] > means[3]


# R1-A2 ---------------------------------------------------------------
def test_triple_barrier_known_path():
    # construct a path that clearly hits the upper barrier
    idx = pd.bdate_range("2015-01-02", periods=60)
    px = pd.Series(np.concatenate([
        100 + np.cumsum(np.random.default_rng(0).normal(0, 0.1, 30)),
        np.linspace(100, 130, 30)]), index=idx)
    out = triple_barrier_labels(px, horizon=10, pt_mult=1.5, sl_mult=1.5,
                                vol_lookback=10)
    assert set(out["label"].dropna().unique()).issubset({-1.0, 0.0, 1.0})
    # a strongly rising tail must yield at least one +1 (upper touched)
    assert (out["label"] == 1.0).sum() >= 1
    # touch_idx never points past the vertical barrier
    valid = out.dropna(subset=["label"])
    for t_pos, row in zip(
            [idx.get_loc(i) for i in valid.index], valid.itertuples()):
        assert row.touch_idx <= min(t_pos + 10, len(idx) - 1)
    cfg = yaml.safe_load((_PROJ / "config" / "ml_labeling.yaml").read_text())
    assert cfg["triple_barrier"]["pt_mult"] == 2.0  # config-sourced


# R1-A3 ---------------------------------------------------------------
def test_labeling_causal():
    idx = pd.bdate_range("2015-01-02", periods=80)
    px = pd.Series(100 + np.cumsum(
        np.random.default_rng(3).normal(0, 0.5, 80)), index=idx)
    h = 10
    full = triple_barrier_labels(px, h, 2.0, 2.0, 10)
    t = 40
    # label/touch of bar t only depends on [t, t+h] — truncating the
    # series at t+h reproduces row t exactly (no bar > t+h read)
    trunc = triple_barrier_labels(px.iloc[: t + h + 1], h, 2.0, 2.0, 10)
    assert full.iloc[t]["label"] == trunc.iloc[t]["label"]
    assert full.iloc[t]["touch_idx"] == trunc.iloc[t]["touch_idx"]
    # uniqueness of bar t uses only its lifespan (≤ t+h)
    u_full = avg_uniqueness(idx, h).iloc[t]
    u_trunc = avg_uniqueness(idx[: t + h + 1], h).iloc[t]
    assert abs(u_full - u_trunc) < 1e-12
