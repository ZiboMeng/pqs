"""3C fusion model — chart-structure P3·R5.

Per chart-structure ralph-loop execution PRD §7 round P3·R5 (P3-d3;
主 PRD §4.4 model 3C). Combines the two chart-native branches:

  - 3B ``StructureSequenceEncoder`` over the swing-segment token sequence
  - 3A ``ChartCNN`` over the GASF/GADF chart image

via LATE fusion — each branch produces a scalar score, and a small
fusion MLP combines ``[score_3b, score_3a]`` into the final prediction.
Late fusion keeps the sub-encoders unmodified and composable; the
fusion MLP can be trained end-to-end or on frozen branches.

Causality is inherited: both branches are leak-free (the segment
sequence and the GAF image of bar ``t`` use only bars ≤ t), so the
fused score at ``t`` is leak-free too.
"""
from __future__ import annotations

from typing import List

import numpy as np

from core.ml.transformer_encoder import get_best_device, is_torch_available

if is_torch_available():
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    from core.ml.chart_cnn import ChartCNN
    from core.ml.structure_sequence_encoder import StructureSequenceEncoder

    class FusionModel(nn.Module):
        """3C late-fusion model: [3B score, 3A score] → fusion MLP → score.

        forward(seg, img):
          seg : (batch, max_segments, 4)  — swing-segment token sequence
          img : (batch, 2, W, W)          — GASF/GADF chart image
          → (batch,) fused forward-return score.
        """

        def __init__(self, freeze_branches: bool = False):
            super().__init__()
            self.branch_3b = StructureSequenceEncoder()
            self.branch_3a = ChartCNN()
            self.fuse = nn.Sequential(
                nn.Linear(2, 8), nn.GELU(), nn.Linear(8, 1),
            )
            self.freeze_branches = freeze_branches
            if freeze_branches:
                for p in self.branch_3b.parameters():
                    p.requires_grad_(False)
                for p in self.branch_3a.parameters():
                    p.requires_grad_(False)

        def forward(self, seg, img):
            s3b = self.branch_3b(seg)            # (B,)
            s3a = self.branch_3a(img)            # (B,)
            stacked = torch.stack([s3b, s3a], dim=1)  # (B, 2)
            return self.fuse(stacked).squeeze(-1)

    def smoke_train_fusion(model: "FusionModel",
                           seg: np.ndarray, img: np.ndarray, y: np.ndarray,
                           steps: int = 30, lr: float = 1e-3,
                           batch: int = 128) -> List[float]:
        """Smoke train the fusion model; return the MSE loss trajectory."""
        device = get_best_device()
        model = model.to(device).train()
        st = torch.tensor(np.asarray(seg, np.float32), device=device)
        it = torch.tensor(np.asarray(img, np.float32), device=device)
        yt = torch.tensor(np.asarray(y, np.float32), device=device)
        params = [p for p in model.parameters() if p.requires_grad]
        opt = torch.optim.Adam(params, lr=lr)
        n = len(yt)
        traj: List[float] = []
        for _ in range(steps):
            perm = torch.randperm(n, device=device)
            ep = 0.0
            for b in range(0, n, batch):
                bi = perm[b:b + batch]
                opt.zero_grad()
                loss = torch.mean((model(st[bi], it[bi]) - yt[bi]) ** 2)
                loss.backward()
                opt.step()
                ep += float(loss.detach().cpu()) * len(bi)
            traj.append(ep / n)
        return traj

    def count_fusion_params(model: "FusionModel") -> int:
        return sum(p.numel() for p in model.parameters() if p.requires_grad)

else:  # pragma: no cover - torch absent
    class FusionModel:  # type: ignore[no-redef]
        def __init__(self, *a, **k):
            raise ImportError("FusionModel requires torch")

    def smoke_train_fusion(*a, **k):  # type: ignore[no-redef]
        raise ImportError("smoke_train_fusion requires torch")

    def count_fusion_params(*a, **k):  # type: ignore[no-redef]
        raise ImportError("count_fusion_params requires torch")
