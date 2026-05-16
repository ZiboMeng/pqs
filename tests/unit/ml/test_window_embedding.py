"""Unit tests for core/ml/window_embedding.py — chart-structure P2B·R2.

Gate P2-A4: named unit tests + GASF/GADF/patch numerical sanity tests.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.ml.window_embedding import (
    EMBEDDING_DIM,
    REPRESENTATION_VIEWS,
    WINDOW_LEN,
    WindowEmbeddingConfig,
    build_representation,
    gramian_angular_field,
    patchify,
    rescale_to_unit,
    to_gasf_gadf,
)
from core.ml.transformer_encoder import is_torch_available

_RNG = np.random.default_rng(0)


# --------------------------- numpy transforms -----------------------------
def test_rescale_to_unit_range_and_constant():
    x = _RNG.standard_normal(63) * 5 + 100
    s = rescale_to_unit(x)
    assert s.min() >= -1.0 - 1e-9 and s.max() <= 1.0 + 1e-9
    assert abs(s.min() + 1.0) < 1e-9 and abs(s.max() - 1.0) < 1e-9
    assert np.allclose(rescale_to_unit(np.full(10, 7.0)), 0.0)  # constant → 0


def test_gasf_symmetric_and_diagonal():
    """GASF[i,j] = cos(φ_i+φ_j) is symmetric; diagonal = cos(2φ_i) = 2x̃²−1."""
    x = _RNG.standard_normal(20)
    gasf = gramian_angular_field(x, "summation")
    assert np.allclose(gasf, gasf.T)                       # symmetric
    xt = rescale_to_unit(x)
    assert np.allclose(np.diag(gasf), 2.0 * xt * xt - 1.0)  # diagonal identity


def test_gadf_antisymmetric_zero_diagonal():
    """GADF[i,j] = sin(φ_i−φ_j) is anti-symmetric with a zero diagonal."""
    x = _RNG.standard_normal(20)
    gadf = gramian_angular_field(x, "difference")
    assert np.allclose(gadf, -gadf.T)
    assert np.allclose(np.diag(gadf), 0.0)


def test_gaf_entries_bounded():
    x = _RNG.standard_normal(30) * 3
    for kind in ("summation", "difference"):
        f = gramian_angular_field(x, kind)
        assert f.min() >= -1.0 - 1e-9 and f.max() <= 1.0 + 1e-9


def test_gaf_constant_series():
    """Constant series → x̃=0 → φ=π/2 → GASF=cos(π)=−1, GADF=sin(0)=0."""
    c = np.full(8, 3.0)
    assert np.allclose(gramian_angular_field(c, "summation"), -1.0)
    assert np.allclose(gramian_angular_field(c, "difference"), 0.0)


def test_gaf_known_small_input():
    """x=[0,0.5,1] → x̃=[-1,0,1]; check two hand-computed entries."""
    gasf = gramian_angular_field(np.array([0.0, 0.5, 1.0]), "summation")
    assert abs(gasf[0, 2] - (-1.0)) < 1e-9   # x̃_0·x̃_2 − sin·sin = −1
    assert abs(gasf[1, 1] - (-1.0)) < 1e-9   # diagonal at x̃=0
    gadf = gramian_angular_field(np.array([0.0, 0.5, 1.0]), "difference")
    assert abs(gadf[0, 1] - 1.0) < 1e-9      # sin_0·x̃_1 − x̃_0·sin_1 = 1


def test_gaf_rejects_bad_kind():
    with pytest.raises(ValueError, match="summation|difference"):
        gramian_angular_field(np.zeros(5), "nonsense")


def test_to_gasf_gadf_shape():
    img = to_gasf_gadf(_RNG.standard_normal(63))
    assert img.shape == (2, 63, 63)


def test_patchify_nonoverlapping_reconstruction():
    x = np.arange(36, dtype=float)
    patches = patchify(x, patch_len=9)            # stride defaults to 9
    assert patches.shape == (4, 9)
    assert np.array_equal(patches.reshape(-1), x)  # tiles back exactly


def test_patchify_strided_and_short():
    x = np.arange(20, dtype=float)
    strided = patchify(x, patch_len=8, stride=4)
    assert strided.shape == (4, 8)                 # (20-8)//4 + 1
    assert np.array_equal(strided[1], x[4:12])
    assert patchify(np.arange(3.0), patch_len=9).shape == (0, 9)  # too short


def test_patchify_rejects_bad_args():
    with pytest.raises(ValueError):
        patchify(np.arange(10.0), patch_len=0)
    with pytest.raises(ValueError):
        patchify(np.arange(10.0), patch_len=5, stride=0)


def test_config_constants_and_validation():
    assert WINDOW_LEN == 63 and EMBEDDING_DIM == 64
    assert REPRESENTATION_VIEWS == ("raw_window", "GASF_GADF", "patch_tokens")
    WindowEmbeddingConfig(representation_view="GASF_GADF")  # ok
    with pytest.raises(ValueError, match="representation_view"):
        WindowEmbeddingConfig(representation_view="bad")


def test_build_representation_dispatch():
    x = _RNG.standard_normal(63)
    raw = build_representation(x, WindowEmbeddingConfig(representation_view="raw_window"))
    assert raw.shape == (63,)
    img = build_representation(x, WindowEmbeddingConfig(representation_view="GASF_GADF"))
    assert img.shape == (2, 63, 63)
    pat = build_representation(x, WindowEmbeddingConfig(
        representation_view="patch_tokens", patch_len=9, patch_stride=9))
    assert pat.shape == (7, 9)


# ----------------------------- encoder (torch) ----------------------------
torch_only = pytest.mark.skipif(not is_torch_available(), reason="torch absent")


@torch_only
def test_encoder_output_shape():
    import torch
    from core.ml.window_embedding import TS2VecEncoder
    enc = TS2VecEncoder(n_features=5, cfg=WindowEmbeddingConfig())
    out = enc(torch.zeros(4, 63, 5))
    assert tuple(out.shape) == (4, 63, EMBEDDING_DIM)
    assert tuple(enc.encode_last(torch.zeros(4, 63, 5)).shape) == (4, EMBEDDING_DIM)


@torch_only
def test_encoder_is_causal():
    """Representation at timestamp k must not change when inputs at
    timestamps > k are altered — the leak-free guarantee."""
    import torch
    from core.ml.window_embedding import TS2VecEncoder
    torch.manual_seed(0)
    enc = TS2VecEncoder(n_features=3, cfg=WindowEmbeddingConfig()).eval()
    x = torch.randn(2, 63, 3)
    k = 30
    x2 = x.clone()
    x2[:, k + 1:, :] = torch.randn(2, 63 - k - 1, 3)  # perturb the future
    with torch.no_grad():
        a = enc(x)[:, : k + 1, :]
        b = enc(x2)[:, : k + 1, :]
    assert torch.allclose(a, b, atol=1e-5), "causality violated"


@torch_only
def test_encoder_deterministic():
    import torch
    from core.ml.window_embedding import TS2VecEncoder
    torch.manual_seed(7)
    e1 = TS2VecEncoder(n_features=4, cfg=WindowEmbeddingConfig()).eval()
    torch.manual_seed(7)
    e2 = TS2VecEncoder(n_features=4, cfg=WindowEmbeddingConfig()).eval()
    x = torch.randn(3, 63, 4)
    with torch.no_grad():
        assert torch.allclose(e1(x), e2(x))


@torch_only
def test_hierarchical_contrastive_loss_finite():
    import torch
    from core.ml.window_embedding import hierarchical_contrastive_loss
    torch.manual_seed(1)
    z1, z2 = torch.randn(6, 32, 8), torch.randn(6, 32, 8)
    loss = hierarchical_contrastive_loss(z1, z2)
    assert torch.isfinite(loss) and loss.item() > 0.0


@torch_only
def test_smoke_pretrain_runs():
    from core.ml.window_embedding import TS2VecEncoder, smoke_pretrain
    enc = TS2VecEncoder(n_features=4, cfg=WindowEmbeddingConfig())
    panel = _RNG.standard_normal((8, 63, 4))
    traj = smoke_pretrain(enc, panel, steps=10, seed=0)
    assert len(traj) == 10
    assert all(np.isfinite(traj))
