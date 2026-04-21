"""Minimal transformer encoder for time-series forward-return prediction.

PRD M8 Phase 1 — research scaffold. Scope strictly bounded per PRD:
  - 1-layer encoder only (no deep stacks — 4GB VRAM constraint)
  - daily horizon only (no intraday sequence — too much RAM)
  - CPU fallback automatic
  - research-only; never wired to production_strategy.yaml

Usage:
    from core.ml.transformer_encoder import SmallEncoder, is_torch_available
    if not is_torch_available():
        print("Install torch: pip install -r requirements-gpu.txt")
        exit(1)
    model = SmallEncoder(n_features=32, seq_len=63)
    ...
"""
from __future__ import annotations

from typing import Optional


def is_torch_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def get_best_device() -> str:
    """Returns 'cuda' if GPU available + VRAM fits, else 'cpu'."""
    if not is_torch_available():
        return "cpu"
    import torch
    if torch.cuda.is_available():
        try:
            # Check VRAM; 1650 has 4GB → any free memory OK for our tiny model
            torch.cuda.get_device_properties(0)
            return "cuda"
        except Exception:
            return "cpu"
    return "cpu"


if is_torch_available():
    import torch
    import torch.nn as nn

    class SmallEncoder(nn.Module):
        """1-layer transformer encoder for scalar forward-return prediction.

        Architecture (designed for 4GB VRAM):
          - Linear projection: n_features → d_model
          - Positional encoding: sinusoidal, fixed
          - 1 TransformerEncoderLayer (d_model=64, nhead=4, dim_ff=128)
          - Global avg pool over seq_len
          - Linear → scalar

        Param count ~50k. Fits comfortably in 4GB VRAM.
        """

        def __init__(
            self,
            n_features: int,
            seq_len: int = 63,
            d_model: int = 64,
            nhead: int = 4,
            dim_feedforward: int = 128,
            dropout: float = 0.1,
        ):
            super().__init__()
            self.n_features = n_features
            self.seq_len = seq_len
            self.d_model = d_model
            self.proj = nn.Linear(n_features, d_model)
            self.pos_encoding = _build_positional_encoding(seq_len, d_model)
            self.encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=nhead,
                dim_feedforward=dim_feedforward,
                dropout=dropout,
                batch_first=True,
            )
            self.head = nn.Linear(d_model, 1)

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            """x: (batch, seq_len, n_features) → out: (batch,)"""
            # Register pos_encoding as buffer on first forward (device-correct)
            if self.pos_encoding.device != x.device:
                self.pos_encoding = self.pos_encoding.to(x.device)
            h = self.proj(x)
            h = h + self.pos_encoding[: h.size(1)].unsqueeze(0)
            h = self.encoder_layer(h)
            h = h.mean(dim=1)  # global average pool
            out = self.head(h).squeeze(-1)
            return out

    def _build_positional_encoding(seq_len: int, d_model: int) -> "torch.Tensor":
        import math
        pe = torch.zeros(seq_len, d_model)
        position = torch.arange(0, seq_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2, dtype=torch.float)
            * -(math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        return pe

    def count_params(model) -> int:
        return sum(p.numel() for p in model.parameters() if p.requires_grad)

else:
    # Torch not installed — provide stub signatures so downstream imports
    # can at least check availability without crashing at import time.
    class SmallEncoder:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "SmallEncoder requires torch. Install via "
                "`pip install -r requirements-gpu.txt`."
            )

    def count_params(model) -> int:  # type: ignore[no-redef]
        raise RuntimeError("torch not installed")
