"""Unit tests for core/ml/transformer_encoder.py (PRD M8 Phase 1).

Tests skip cleanly if torch is not installed (graceful degradation).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.ml.transformer_encoder import is_torch_available, get_best_device


def test_torch_availability_reported_consistently():
    """is_torch_available() returns a bool without raising."""
    assert isinstance(is_torch_available(), bool)


def test_get_best_device_never_raises():
    """Regardless of GPU/torch state, returns a string."""
    dev = get_best_device()
    assert dev in ("cpu", "cuda")


def test_no_torch_encoder_raises_helpful_error():
    """If torch is missing, SmallEncoder() should raise with install hint."""
    if is_torch_available():
        pytest.skip("torch available, this test checks the no-torch path")
    from core.ml.transformer_encoder import SmallEncoder
    with pytest.raises(RuntimeError) as exc_info:
        SmallEncoder(n_features=10)
    assert "torch" in str(exc_info.value).lower()


# Torch-dependent tests (skip if unavailable)


@pytest.mark.skipif(not is_torch_available(), reason="torch not installed")
def test_encoder_instantiates_and_counts_params():
    from core.ml.transformer_encoder import SmallEncoder, count_params
    model = SmallEncoder(n_features=32, seq_len=63)
    n = count_params(model)
    # ~50k params with default config
    assert 20_000 < n < 200_000


@pytest.mark.skipif(not is_torch_available(), reason="torch not installed")
def test_encoder_forward_shape():
    import torch
    from core.ml.transformer_encoder import SmallEncoder
    model = SmallEncoder(n_features=32, seq_len=63)
    x = torch.randn(4, 63, 32)
    out = model(x)
    assert out.shape == (4,)
    assert torch.isfinite(out).all()


@pytest.mark.skipif(not is_torch_available(), reason="torch not installed")
def test_encoder_cpu_fallback():
    import torch
    from core.ml.transformer_encoder import SmallEncoder
    model = SmallEncoder(n_features=10, seq_len=21)
    model.to("cpu")
    x = torch.randn(2, 21, 10)
    out = model(x)
    assert out.device.type == "cpu"
