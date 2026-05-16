"""Window-level self-supervised representations — chart-structure P2B·R2.

Per chart-structure ralph-loop execution PRD §6 round P2B·R2 (主 PRD §4.3).
Three representation views of a fixed PAST price window, plus a TS2Vec-style
self-supervised encoder:

  representation_view ∈ {"raw_window", "GASF_GADF", "patch_tokens"}

  - raw_window   : the normalized length-W window itself.
  - GASF_GADF    : Gramian Angular Summation / Difference Fields — two
                   W×W images (Wang & Oates 2015). Deterministic.
  - patch_tokens : PatchTST-style non-overlapping / strided patches.

Encoder: ``TS2VecEncoder`` — dilated *causal* convolution stack trained
with the TS2Vec hierarchical contrastive loss (Yue et al. 2022). Causal
convolutions mean the representation at the last timestamp depends only
on that timestamp and earlier ones; combined with feeding a window that
ends at bar ``t`` and contains no future bars, the window embedding used
as a feature at ``t`` is leak-free.

Locked design (execution PRD §3): window_len=63, embedding_dim=64 — the
``SmallEncoder`` seq_len / d_model defaults, not invented numbers.

Torch is OPTIONAL: GASF/GADF/patchify are pure numpy and always work;
the encoder + contrastive loss are guarded by ``is_torch_available()``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from core.ml.transformer_encoder import get_best_device, is_torch_available

WINDOW_LEN = 63
EMBEDDING_DIM = 64
REPRESENTATION_VIEWS = ("raw_window", "GASF_GADF", "patch_tokens")


# --------------------------------------------------------------------------
# pure-numpy deterministic transforms (no torch dependency)
# --------------------------------------------------------------------------
def rescale_to_unit(series: np.ndarray) -> np.ndarray:
    """Rescale a 1-D series into [-1, 1] (the GAF polar-encoding domain).

    ``x̃ = ((x - max) + (x - min)) / (max - min)``; a constant series maps
    to all-zeros (φ = π/2) rather than dividing by zero.
    """
    x = np.asarray(series, dtype=float).ravel()
    lo, hi = np.nanmin(x), np.nanmax(x)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-12:
        return np.zeros_like(x)
    scaled = ((x - hi) + (x - lo)) / (hi - lo)
    return np.clip(scaled, -1.0, 1.0)


def gramian_angular_field(series: np.ndarray, kind: str = "summation") -> np.ndarray:
    """Gramian Angular Field of a 1-D window.

    ``kind="summation"`` → GASF[i,j] = cos(φ_i + φ_j) (symmetric).
    ``kind="difference"`` → GADF[i,j] = sin(φ_i − φ_j) (anti-symmetric).
    Entries lie in [-1, 1]; the series is rescaled to [-1, 1] first.
    """
    if kind not in ("summation", "difference"):
        raise ValueError(f"kind must be summation|difference, got {kind!r}")
    x = rescale_to_unit(series)
    sin = np.sqrt(np.clip(1.0 - x * x, 0.0, 1.0))
    if kind == "summation":
        # cos(a+b) = cos a cos b − sin a sin b
        field = np.outer(x, x) - np.outer(sin, sin)
    else:
        # sin(a−b) = sin a cos b − cos a sin b
        field = np.outer(sin, x) - np.outer(x, sin)
    return np.clip(field, -1.0, 1.0)


def to_gasf_gadf(series: np.ndarray) -> np.ndarray:
    """Stack GASF + GADF into a (2, W, W) image tensor (CNN-ready)."""
    return np.stack([
        gramian_angular_field(series, "summation"),
        gramian_angular_field(series, "difference"),
    ], axis=0)


def patchify(series: np.ndarray, patch_len: int, stride: int | None = None
             ) -> np.ndarray:
    """Split a 1-D window into patches → (n_patches, patch_len).

    ``stride`` defaults to ``patch_len`` (non-overlapping). The trailing
    remainder that does not fill a whole patch is dropped — every patch
    has exactly ``patch_len`` samples.
    """
    x = np.asarray(series, dtype=float).ravel()
    if patch_len <= 0:
        raise ValueError("patch_len must be positive")
    stride = patch_len if stride is None else stride
    if stride <= 0:
        raise ValueError("stride must be positive")
    if len(x) < patch_len:
        return np.empty((0, patch_len), dtype=float)
    starts = range(0, len(x) - patch_len + 1, stride)
    return np.stack([x[s:s + patch_len] for s in starts], axis=0)


@dataclass(frozen=True)
class WindowEmbeddingConfig:
    """Config for the window representation + encoder."""
    window_len: int = WINDOW_LEN
    embedding_dim: int = EMBEDDING_DIM
    representation_view: str = "raw_window"
    patch_len: int = 9
    patch_stride: int = 9
    encoder_hidden: int = 64
    encoder_depth: int = 4  # dilations 1,2,4,8 — shallow (4GB VRAM bound)

    def __post_init__(self) -> None:
        if self.representation_view not in REPRESENTATION_VIEWS:
            raise ValueError(
                f"representation_view must be one of {REPRESENTATION_VIEWS}, "
                f"got {self.representation_view!r}")


def build_representation(series: np.ndarray, cfg: WindowEmbeddingConfig):
    """Materialize the configured representation_view of a price window."""
    if cfg.representation_view == "raw_window":
        return rescale_to_unit(series)
    if cfg.representation_view == "GASF_GADF":
        return to_gasf_gadf(series)
    return patchify(series, cfg.patch_len, cfg.patch_stride)


# --------------------------------------------------------------------------
# TS2Vec-style encoder + hierarchical contrastive loss (torch-guarded)
# --------------------------------------------------------------------------
if is_torch_available():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class _CausalConv1d(nn.Module):
        """Dilated causal 1-D conv — output[t] depends only on inputs ≤ t."""

        def __init__(self, ch_in: int, ch_out: int, kernel: int, dilation: int):
            super().__init__()
            self.left_pad = (kernel - 1) * dilation
            self.conv = nn.Conv1d(ch_in, ch_out, kernel, dilation=dilation)

        def forward(self, x):  # x: (B, C, T)
            return self.conv(F.pad(x, (self.left_pad, 0)))

    class _ResidualBlock(nn.Module):
        def __init__(self, ch_in: int, ch_out: int, dilation: int):
            super().__init__()
            self.conv1 = _CausalConv1d(ch_in, ch_out, 3, dilation)
            self.conv2 = _CausalConv1d(ch_out, ch_out, 3, dilation)
            self.proj = (nn.Conv1d(ch_in, ch_out, 1)
                         if ch_in != ch_out else None)

        def forward(self, x):
            residual = x if self.proj is None else self.proj(x)
            h = F.gelu(self.conv1(x))
            h = self.conv2(h)
            return F.gelu(h + residual)

    class TS2VecEncoder(nn.Module):
        """Dilated causal-conv encoder (TS2Vec-style, Yue et al. 2022).

        forward: (batch, seq_len, n_features) → (batch, seq_len, embed_dim).
        ``encode_last`` returns the causal last-timestamp embedding —
        the leak-free per-window feature vector.
        """

        def __init__(self, n_features: int, cfg: WindowEmbeddingConfig):
            super().__init__()
            self.cfg = cfg
            h = cfg.encoder_hidden
            self.input_fc = nn.Linear(n_features, h)
            blocks = []
            for i in range(cfg.encoder_depth):
                blocks.append(_ResidualBlock(h, h, dilation=2 ** i))
            self.blocks = nn.Sequential(*blocks)
            self.output_fc = nn.Conv1d(h, cfg.embedding_dim, 1)

        def forward(self, x):  # (B, T, F)
            h = self.input_fc(x).transpose(1, 2)   # (B, H, T)
            h = self.blocks(h)
            return self.output_fc(h).transpose(1, 2)  # (B, T, embed)

        def encode_last(self, x):
            """Causal per-window embedding — repr at the final timestamp."""
            return self.forward(x)[:, -1, :]

    def _instance_contrastive_loss(z1, z2):
        """Contrast each sample against the other samples in the batch."""
        b, t = z1.size(0), z1.size(1)
        if b == 1:
            return z1.new_zeros(())
        z = torch.cat([z1, z2], dim=0).transpose(0, 1)   # (T, 2B, C)
        sim = torch.matmul(z, z.transpose(1, 2))         # (T, 2B, 2B)
        logits = torch.tril(sim, -1)[:, :, :-1]
        logits = logits + torch.triu(sim, 1)[:, :, 1:]
        logits = F.log_softmax(logits, dim=-1)           # (T, 2B, 2B-1)
        idx = torch.arange(b, device=z1.device)
        loss = (logits[:, idx, b + idx - 1].mean()
                + logits[:, b + idx, idx].mean()) / 2
        return -loss

    def _temporal_contrastive_loss(z1, z2):
        """Contrast each timestamp against the other timestamps."""
        b, t = z1.size(0), z1.size(1)
        if t == 1:
            return z1.new_zeros(())
        z = torch.cat([z1, z2], dim=1)                   # (B, 2T, C)
        sim = torch.matmul(z, z.transpose(1, 2))         # (B, 2T, 2T)
        logits = torch.tril(sim, -1)[:, :, :-1]
        logits = logits + torch.triu(sim, 1)[:, :, 1:]
        logits = F.log_softmax(logits, dim=-1)
        idx = torch.arange(t, device=z1.device)
        loss = (logits[:, idx, t + idx - 1].mean()
                + logits[:, t + idx, idx].mean()) / 2
        return -loss

    def hierarchical_contrastive_loss(z1, z2):
        """TS2Vec hierarchical contrastive loss — instance + temporal at
        progressively max-pooled time resolutions. ``z1``/``z2`` are two
        augmented views, each (batch, seq_len, embed_dim)."""
        loss = z1.new_zeros(())
        d = 0
        while z1.size(1) > 1:
            loss = loss + _instance_contrastive_loss(z1, z2)
            loss = loss + _temporal_contrastive_loss(z1, z2)
            d += 1
            z1 = F.max_pool1d(z1.transpose(1, 2), 2).transpose(1, 2)
            z2 = F.max_pool1d(z2.transpose(1, 2), 2).transpose(1, 2)
        if z1.size(1) == 1:
            loss = loss + _instance_contrastive_loss(z1, z2)
            d += 1
        return loss / max(d, 1)

    def _augment(x, seed_gen):
        """Cheap TS2Vec-style augmentation: jitter + random scaling."""
        noise = torch.randn(x.shape, generator=seed_gen, device=x.device) * 0.05
        scale = 1.0 + (torch.rand((), generator=seed_gen, device=x.device)
                       - 0.5) * 0.2
        return x * scale + noise

    def smoke_pretrain(encoder: "TS2VecEncoder", panel: np.ndarray,
                       steps: int = 20, lr: float = 1e-3, seed: int = 0
                       ) -> List[float]:
        """Run a few self-supervised steps on a (n_windows, T, F) panel and
        return the loss trajectory. Smoke-scale only — not a full pretrain.
        """
        device = get_best_device()
        encoder = encoder.to(device).train()
        x = torch.tensor(np.asarray(panel, dtype=np.float32), device=device)
        opt = torch.optim.Adam(encoder.parameters(), lr=lr)
        g = torch.Generator(device=device).manual_seed(seed)
        traj: List[float] = []
        for _ in range(steps):
            opt.zero_grad()
            z1 = encoder(_augment(x, g))
            z2 = encoder(_augment(x, g))
            loss = hierarchical_contrastive_loss(z1, z2)
            loss.backward()
            opt.step()
            traj.append(float(loss.detach().cpu()))
        return traj

else:  # pragma: no cover - torch absent
    class TS2VecEncoder:  # type: ignore[no-redef]
        def __init__(self, *a, **k):
            raise ImportError("TS2VecEncoder requires torch")

    def hierarchical_contrastive_loss(*a, **k):  # type: ignore[no-redef]
        raise ImportError("hierarchical_contrastive_loss requires torch")

    def smoke_pretrain(*a, **k):  # type: ignore[no-redef]
        raise ImportError("smoke_pretrain requires torch")
