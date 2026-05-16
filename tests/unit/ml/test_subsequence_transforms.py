"""Unit tests for core/ml/subsequence_transforms.py — P2B·R1 (MiniROCKET
bridge). Per ralph-loop execution PRD §6, AC P2-A3."""
from __future__ import annotations

import numpy as np

from core.ml.subsequence_transforms import (
    _KERNELS,
    MiniRocketConfig,
    minirocket_features,
    minirocket_transform,
    rolling_minirocket_ppv_mean,
)


def test_kernels_are_the_84_minirocket_kernels():
    """84 fixed length-9 kernels, weights {-1,2}, exactly three +2, mean-zero."""
    assert _KERNELS.shape == (84, 9)
    for k in _KERNELS:
        assert set(np.unique(k)).issubset({-1.0, 2.0})
        assert int((k == 2.0).sum()) == 3
        assert int((k == -1.0).sum()) == 6
        assert abs(k.sum()) < 1e-12  # mean-zero
    # all 84 kernels distinct
    assert len({tuple(k) for k in _KERNELS}) == 84


def test_minirocket_features_shape_and_range():
    rng = np.random.default_rng(0)
    cfg = MiniRocketConfig()
    feats = minirocket_features(rng.standard_normal(120), cfg)
    assert feats.shape == (cfg.n_features,)
    finite = feats[np.isfinite(feats)]
    assert finite.size > 0
    assert (finite >= 0.0).all() and (finite <= 1.0).all()  # PPV in [0,1]


def test_minirocket_features_short_series_all_nan():
    feats = minirocket_features(np.array([1.0, 2.0, 3.0]))
    assert np.isnan(feats).all()


def test_minirocket_transform_stack():
    rng = np.random.default_rng(1)
    cfg = MiniRocketConfig(dilations=(1, 2), quantile_biases=(0.5,))
    panel = rng.standard_normal((4, 80))
    out = minirocket_transform(panel, cfg)
    assert out.shape == (4, cfg.n_features)
    assert cfg.n_features == 84 * 2 * 1


def test_rolling_minirocket_causal():
    """rolling_minirocket_ppv_mean at bar t is identical whether computed on
    the full series or a series truncated to t — strictly causal."""
    rng = np.random.default_rng(2)
    close = 100.0 + np.cumsum(rng.standard_normal(260) * 0.5)
    cfg = MiniRocketConfig(dilations=(1, 2), quantile_biases=(0.5,))
    full = rolling_minirocket_ppv_mean(close, window=80, cfg=cfg)
    for t in range(90, 260, 30):
        trunc = rolling_minirocket_ppv_mean(close[: t + 1], window=80, cfg=cfg)
        a, b = full[t], trunc[t]
        assert (np.isnan(a) and np.isnan(b)) or abs(a - b) < 1e-12, \
            f"causality violated at t={t}"
    assert np.isfinite(full[120:]).any()  # non-vacuous
