"""Unit tests for core/ml/structure_sequence_encoder.py — chart-structure
P3·R1. Gate P3-A5: test_phase3b_uses_confirmed_swings + smoke training."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.swing_structure import SwingStructureConfig, detect_raw_swings
from core.ml.structure_sequence_encoder import (
    MAX_SEGMENTS,
    SEGMENT_FEATURE_DIM,
    build_structure_sequences,
    segment_sequence_asof,
)
from core.ml.transformer_encoder import is_torch_available

_CFG = SwingStructureConfig()


def _zigzag_bars(n: int = 240, seed: int = 0) -> pd.DataFrame:
    """A noisy zigzag price series with clear swing structure."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    base = 100 + 12 * np.sin(t / 11.0) + np.cumsum(rng.standard_normal(n) * 0.3)
    high = base + np.abs(rng.standard_normal(n)) * 0.4
    low = base - np.abs(rng.standard_normal(n)) * 0.4
    close = base + rng.standard_normal(n) * 0.1
    return pd.DataFrame({"high": high, "low": low, "close": close,
                         "open": close})


def test_phase3b_uses_confirmed_swings():
    """P3-A5: the segment sequence as of bar t must be IDENTICAL whether
    derived from the full series or the series truncated to t — i.e. it
    routes through the causal confirmed_swings_asof and never reads a
    bar after t."""
    bars = _zigzag_bars(240)
    raw_full = detect_raw_swings(bars, _CFG)
    for t in (80, 130, 180):
        raw_trunc = detect_raw_swings(bars.iloc[: t + 1], _CFG)
        seq_full = segment_sequence_asof(raw_full, t)
        seq_trunc = segment_sequence_asof(raw_trunc, t)
        assert np.array_equal(seq_full, seq_trunc), f"leak at t={t}"


def test_segment_sequence_shape_and_padding():
    bars = _zigzag_bars(240)
    raw = detect_raw_swings(bars, _CFG)
    seq = segment_sequence_asof(raw, 200)
    assert seq.shape == (MAX_SEGMENTS, SEGMENT_FEATURE_DIM)
    # early bar → few/no confirmed segments → front zero-padded
    early = segment_sequence_asof(raw, 25)
    assert np.array_equal(early[0], np.zeros(SEGMENT_FEATURE_DIM))


def test_segment_sequence_empty_when_no_swings_confirmed():
    bars = _zigzag_bars(240)
    raw = detect_raw_swings(bars, _CFG)
    seq = segment_sequence_asof(raw, 3)        # nothing confirmed yet
    assert np.array_equal(seq, np.zeros((MAX_SEGMENTS, SEGMENT_FEATURE_DIM)))


def test_segment_features_direction_sign():
    """A confirmed segment's direction feature ∈ {-1, 0, 1}."""
    bars = _zigzag_bars(240)
    raw = detect_raw_swings(bars, _CFG)
    seq = segment_sequence_asof(raw, 220)
    dirs = seq[:, 3]
    nonzero = dirs[seq.any(axis=1)]            # ignore pad rows
    assert set(np.unique(nonzero)).issubset({-1.0, 1.0})


def test_build_structure_sequences_shape():
    bars = _zigzag_bars(240)
    x = build_structure_sequences(bars, [100, 140, 180, 220], _CFG)
    assert x.shape == (4, MAX_SEGMENTS, SEGMENT_FEATURE_DIM)
    assert build_structure_sequences(bars, [], _CFG).shape == (
        0, MAX_SEGMENTS, SEGMENT_FEATURE_DIM)


torch_only = pytest.mark.skipif(not is_torch_available(), reason="torch absent")


@torch_only
def test_encoder_forward_shape_and_reuses_small_encoder():
    import torch
    from core.ml.structure_sequence_encoder import StructureSequenceEncoder
    from core.ml.transformer_encoder import SmallEncoder
    m = StructureSequenceEncoder()
    assert isinstance(m.encoder, SmallEncoder)
    assert m.encoder.n_features == SEGMENT_FEATURE_DIM
    out = m(torch.zeros(5, MAX_SEGMENTS, SEGMENT_FEATURE_DIM))
    assert tuple(out.shape) == (5,)


@torch_only
def test_encoder_smoke_train_runs_and_learns():
    from core.ml.structure_sequence_encoder import (
        StructureSequenceEncoder,
        smoke_train_3b,
    )
    rng = np.random.default_rng(0)
    bars = _zigzag_bars(240)
    x = build_structure_sequences(bars, list(range(60, 230, 3)), _CFG)
    # target: a learnable function of the last segment's slope
    y = x[:, -1, 2] * 2.0 + rng.standard_normal(len(x)) * 0.01
    m = StructureSequenceEncoder()
    traj = smoke_train_3b(m, x, y, steps=40, lr=1e-3)
    assert len(traj) == 40 and all(np.isfinite(traj))
    assert traj[-1] < traj[0]                  # smoke training reduces loss
