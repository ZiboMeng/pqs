"""Unit tests for core/ml/chart_cnn.py — chart-structure P3·R3.
3A image-CNN builds + trains on smoke data."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.ml.chart_cnn import build_gaf_panel, gaf_image
from core.ml.transformer_encoder import is_torch_available
from core.ml.window_embedding import WINDOW_LEN

_RNG = np.random.default_rng(0)


def test_gaf_image_shape_and_bounds():
    img = gaf_image(_RNG.standard_normal(WINDOW_LEN))
    assert img.shape == (2, WINDOW_LEN, WINDOW_LEN)
    assert img.dtype == np.float32
    assert img.min() >= -1.0 - 1e-6 and img.max() <= 1.0 + 1e-6


def test_build_gaf_panel_shape_and_causal_warmup():
    close = pd.DataFrame(
        100 + np.cumsum(_RNG.standard_normal((200, 2)) * 0.5, axis=0),
        columns=["AAA", "BBB"])
    imgs, keys = build_gaf_panel(
        close, {"AAA": [30, 100, 150], "BBB": [80, 199]})
    # AAA@30 is dropped (needs >=63 prior bars); 4 valid keys remain
    assert imgs.shape == (4, 2, WINDOW_LEN, WINDOW_LEN)
    assert ("AAA", 30) not in keys
    assert ("AAA", 100) in keys and ("BBB", 199) in keys


def test_build_gaf_panel_empty():
    close = pd.DataFrame({"AAA": np.arange(200.0)})
    imgs, keys = build_gaf_panel(close, {"AAA": [10]})  # too-early only
    assert imgs.shape == (0, 2, WINDOW_LEN, WINDOW_LEN)
    assert keys == []


def test_gaf_image_is_causal():
    """The GAF image at t depends only on the trailing window — altering
    bars after t cannot change it."""
    series = 100 + np.cumsum(_RNG.standard_normal(200) * 0.5)
    t = 120
    win = series[t - WINDOW_LEN + 1: t + 1]
    img_a = gaf_image(win)
    series2 = series.copy()
    series2[t + 1:] = _RNG.standard_normal(len(series) - t - 1)  # perturb future
    win2 = series2[t - WINDOW_LEN + 1: t + 1]
    assert np.array_equal(img_a, gaf_image(win2))


torch_only = pytest.mark.skipif(not is_torch_available(), reason="torch absent")


@torch_only
def test_chart_cnn_forward_shape_and_size():
    import torch
    from core.ml.chart_cnn import ChartCNN, count_cnn_params
    m = ChartCNN()
    out = m(torch.zeros(4, 2, WINDOW_LEN, WINDOW_LEN))
    assert tuple(out.shape) == (4,)
    assert count_cnn_params(m) < 100_000  # 4GB-VRAM-safe


@torch_only
def test_chart_cnn_smoke_train_learns():
    from core.ml.chart_cnn import ChartCNN, smoke_train_cnn
    rng = np.random.default_rng(1)
    x = rng.standard_normal((128, 2, WINDOW_LEN, WINDOW_LEN)).astype(np.float32)
    # learnable target: mean of channel 0
    y = x[:, 0].mean(axis=(1, 2)) * 5.0 + rng.standard_normal(128) * 0.01
    m = ChartCNN()
    traj = smoke_train_cnn(m, x, y, steps=30, batch=64)
    assert len(traj) == 30 and all(np.isfinite(traj))
    assert traj[-1] < traj[0]
