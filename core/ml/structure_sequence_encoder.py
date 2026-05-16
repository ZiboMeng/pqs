"""3B structure-sequence encoder — chart-structure P3·R1.

Per chart-structure ralph-loop execution PRD §7 round P3·R1 (P3-d2;
主 PRD §4.4 model 3B). A *chart-native* model whose input is not the
daily bar series but the **family-T swing-segment sequence**: each
segment (the leg between two consecutive confirmed swings) is a token
``[len_pct, dur, slope_pct, direction]``.

Causality: segments are derived from ``confirmed_swings_asof`` — a swing
only enters the sequence once its ``confirmation_idx <= t``. The segment
sequence as-of bar ``t`` therefore never depends on any bar after ``t``;
``test_phase3b_uses_confirmed_swings`` pins this.

The encoder REUSES ``transformer_encoder.SmallEncoder`` (1-layer
transformer, ~50k params, 4GB-VRAM-safe) with ``n_features=4`` and
``seq_len=max_segments`` — i.e. Phase 3B is SmallEncoder applied to the
structure-token sequence rather than the raw bar sequence.
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from core.factors.swing_structure import (
    SwingStructureConfig,
    _Seg,
    _segments,
    confirmed_swings_asof,
    detect_raw_swings,
)
from core.ml.transformer_encoder import SmallEncoder, get_best_device, is_torch_available

SEGMENT_FEATURE_DIM = 4   # [len_pct, dur, slope_pct, direction]
MAX_SEGMENTS = 16         # most recent N segments kept (front zero-padded)
_DUR_SCALE = 21.0         # ~1 trading month — keeps dur O(1)


def _segment_features(seg: _Seg) -> List[float]:
    """One swing segment → [len_pct, dur_norm, slope_pct, direction]."""
    sp = seg.start_price
    if sp <= 0 or not np.isfinite(sp):
        return [0.0, 0.0, 0.0, 0.0]
    len_pct = abs(seg.end_price - sp) / sp
    dur_norm = seg.dur / _DUR_SCALE
    slope_pct = ((seg.end_price - sp) / sp) / seg.dur * _DUR_SCALE if seg.dur else 0.0
    return [float(len_pct), float(dur_norm), float(slope_pct), float(seg.direction)]


def segment_sequence_asof(
    raw_swings: list,
    t_idx: int,
    max_segments: int = MAX_SEGMENTS,
) -> np.ndarray:
    """Causal swing-segment feature sequence as of bar ``t_idx``.

    Returns ``(max_segments, 4)``: the most recent ``max_segments``
    segments, front zero-padded if fewer exist. Routes through
    ``confirmed_swings_asof`` — segments past ``t_idx`` cannot appear.
    """
    window = confirmed_swings_asof(raw_swings, t_idx)
    segs = _segments(window)
    feats = [_segment_features(s) for s in segs]
    out = np.zeros((max_segments, SEGMENT_FEATURE_DIM), dtype=np.float32)
    if feats:
        recent = feats[-max_segments:]
        out[max_segments - len(recent):] = np.asarray(recent, dtype=np.float32)
    return out


def build_structure_sequences(
    bars: pd.DataFrame,
    t_indices: list[int],
    cfg: SwingStructureConfig,
    max_segments: int = MAX_SEGMENTS,
) -> np.ndarray:
    """Stack segment sequences for one symbol at many bar indices →
    ``(len(t_indices), max_segments, 4)``. ``detect_raw_swings`` runs
    once (compute-once contract)."""
    raw = detect_raw_swings(bars, cfg)
    return np.stack(
        [segment_sequence_asof(raw, t, max_segments) for t in t_indices],
        axis=0,
    ) if t_indices else np.empty((0, max_segments, SEGMENT_FEATURE_DIM),
                                 dtype=np.float32)


if is_torch_available():
    import torch

    class StructureSequenceEncoder(torch.nn.Module):
        """3B model — SmallEncoder over the swing-segment token sequence.

        forward: (batch, max_segments, 4) → (batch,) forward-return score.
        """

        def __init__(self, max_segments: int = MAX_SEGMENTS, d_model: int = 64):
            super().__init__()
            self.max_segments = max_segments
            self.encoder = SmallEncoder(
                n_features=SEGMENT_FEATURE_DIM,
                seq_len=max_segments,
                d_model=d_model,
            )

        def forward(self, x):
            return self.encoder(x)

    def smoke_train_3b(model: "StructureSequenceEncoder",
                       x: np.ndarray, y: np.ndarray,
                       steps: int = 30, lr: float = 1e-3) -> List[float]:
        """Smoke train on a (N, max_segments, 4) panel against scalar
        targets ``y``; returns the MSE loss trajectory."""
        device = get_best_device()
        model = model.to(device).train()
        xt = torch.tensor(np.asarray(x, np.float32), device=device)
        yt = torch.tensor(np.asarray(y, np.float32), device=device)
        opt = torch.optim.Adam(model.parameters(), lr=lr)
        traj: List[float] = []
        for _ in range(steps):
            opt.zero_grad()
            pred = model(xt)
            loss = torch.mean((pred - yt) ** 2)
            loss.backward()
            opt.step()
            traj.append(float(loss.detach().cpu()))
        return traj

else:  # pragma: no cover - torch absent
    class StructureSequenceEncoder:  # type: ignore[no-redef]
        def __init__(self, *a, **k):
            raise ImportError("StructureSequenceEncoder requires torch")

    def smoke_train_3b(*a, **k):  # type: ignore[no-redef]
        raise ImportError("smoke_train_3b requires torch")
