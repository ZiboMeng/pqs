"""Unit tests for core/ml/fusion_model.py — chart-structure P3·R5.
3C fusion model builds + trains on smoke data."""
from __future__ import annotations

import numpy as np
import pytest

from core.ml.structure_sequence_encoder import MAX_SEGMENTS, SEGMENT_FEATURE_DIM
from core.ml.transformer_encoder import is_torch_available
from core.ml.window_embedding import WINDOW_LEN

torch_only = pytest.mark.skipif(not is_torch_available(), reason="torch absent")


@torch_only
def test_fusion_forward_shape():
    import torch
    from core.ml.fusion_model import FusionModel
    m = FusionModel()
    seg = torch.zeros(5, MAX_SEGMENTS, SEGMENT_FEATURE_DIM)
    img = torch.zeros(5, 2, WINDOW_LEN, WINDOW_LEN)
    assert tuple(m(seg, img).shape) == (5,)


@torch_only
def test_fusion_freeze_branches():
    from core.ml.fusion_model import FusionModel, count_fusion_params
    full = count_fusion_params(FusionModel(freeze_branches=False))
    frozen = count_fusion_params(FusionModel(freeze_branches=True))
    # frozen → only the fusion MLP is trainable (2*8+8 + 8*1+1 = 33)
    assert frozen == 33
    assert full > frozen


@torch_only
def test_fusion_smoke_train_learns():
    from core.ml.fusion_model import FusionModel, smoke_train_fusion
    rng = np.random.default_rng(0)
    n = 96
    seg = rng.standard_normal((n, MAX_SEGMENTS, SEGMENT_FEATURE_DIM)).astype("f4")
    img = rng.standard_normal((n, 2, WINDOW_LEN, WINDOW_LEN)).astype("f4")
    y = (seg[:, -1, 2] * 1.5 + rng.standard_normal(n) * 0.05).astype("f4")
    m = FusionModel()
    traj = smoke_train_fusion(m, seg, img, y, steps=25, batch=32)
    assert len(traj) == 25 and all(np.isfinite(traj))
    assert traj[-1] < traj[0]
