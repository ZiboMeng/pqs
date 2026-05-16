"""3A image-CNN over Gramian Angular Field chart images — P3·R3.

Per chart-structure ralph-loop execution PRD §7 round P3·R3 (P3-d1;
主 PRD §4.4 model 3A). A chart-native model whose input is the price
window rendered as a 2-channel image — GASF + GADF (execution PRD §3
q3: GAF first, deterministic, no plotting ambiguity).

Causality: the GAF image of bar ``t`` is built from the trailing window
``[t-W+1, t]`` only — it never reads a bar after ``t``. The CNN is a
pure function of that image.

Kept small (2 conv blocks, ~30k params) for the 4GB-VRAM constraint
that already bounds ``transformer_encoder.SmallEncoder``.
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from core.ml.transformer_encoder import get_best_device, is_torch_available
from core.ml.window_embedding import WINDOW_LEN, to_gasf_gadf


def gaf_image(window: np.ndarray) -> np.ndarray:
    """One price window → (2, W, W) GASF+GADF image."""
    return to_gasf_gadf(window).astype(np.float32)


def build_gaf_panel(
    close_panel: pd.DataFrame,
    t_indices_by_symbol: dict[str, list[int]],
    window_len: int = WINDOW_LEN,
) -> tuple[np.ndarray, list[tuple[str, int]]]:
    """Build GAF images for the requested (symbol, bar-index) pairs.

    Returns ``(images, keys)`` — ``images`` is ``(N, 2, W, W)`` and
    ``keys[i]`` is the ``(symbol, bar_index)`` of image ``i``. A pair is
    skipped when fewer than ``window_len`` prior bars exist (causal
    warmup).
    """
    imgs: list[np.ndarray] = []
    keys: list[tuple[str, int]] = []
    for sym, idxs in t_indices_by_symbol.items():
        if sym not in close_panel.columns:
            continue
        series = close_panel[sym].to_numpy(dtype=float)
        for t in idxs:
            if t < window_len - 1 or t >= len(series):
                continue
            win = series[t - window_len + 1: t + 1]
            if not np.isfinite(win).all():
                continue
            imgs.append(gaf_image(win))
            keys.append((sym, t))
    if not imgs:
        return np.empty((0, 2, window_len, window_len), np.float32), keys
    return np.stack(imgs, axis=0), keys


if is_torch_available():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class ChartCNN(nn.Module):
        """Small 2-channel CNN over GASF/GADF chart images.

        forward: (batch, 2, W, W) → (batch,) forward-return score.
        """

        def __init__(self, in_channels: int = 2):
            super().__init__()
            self.conv1 = nn.Conv2d(in_channels, 16, 3, padding=1)
            self.conv2 = nn.Conv2d(16, 32, 3, padding=1)
            self.head = nn.Linear(32, 1)

        def forward(self, x):
            h = F.max_pool2d(F.gelu(self.conv1(x)), 2)
            h = F.max_pool2d(F.gelu(self.conv2(h)), 2)
            h = F.adaptive_avg_pool2d(h, 1).flatten(1)  # (B, 32)
            return self.head(h).squeeze(-1)

    def smoke_train_cnn(model: "ChartCNN", x: np.ndarray, y: np.ndarray,
                        steps: int = 30, lr: float = 1e-3,
                        batch: int = 256) -> List[float]:
        """Smoke train the CNN on a (N, 2, W, W) panel; return the MSE
        loss trajectory."""
        device = get_best_device()
        model = model.to(device).train()
        xt = torch.tensor(np.asarray(x, np.float32), device=device)
        yt = torch.tensor(np.asarray(y, np.float32), device=device)
        opt = torch.optim.Adam(model.parameters(), lr=lr)
        n = len(xt)
        traj: List[float] = []
        for _ in range(steps):
            perm = torch.randperm(n, device=device)
            ep = 0.0
            for b in range(0, n, batch):
                bi = perm[b:b + batch]
                opt.zero_grad()
                loss = torch.mean((model(xt[bi]) - yt[bi]) ** 2)
                loss.backward()
                opt.step()
                ep += float(loss.detach().cpu()) * len(bi)
            traj.append(ep / n)
        return traj

    def count_cnn_params(model: "ChartCNN") -> int:
        return sum(p.numel() for p in model.parameters() if p.requires_grad)

else:  # pragma: no cover - torch absent
    class ChartCNN:  # type: ignore[no-redef]
        def __init__(self, *a, **k):
            raise ImportError("ChartCNN requires torch")

    def smoke_train_cnn(*a, **k):  # type: ignore[no-redef]
        raise ImportError("smoke_train_cnn requires torch")

    def count_cnn_params(*a, **k):  # type: ignore[no-redef]
        raise ImportError("count_cnn_params requires torch")
