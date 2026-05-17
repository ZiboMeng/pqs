"""R3 — self-supervised pretraining (supplementary PRD §6).

Per literature review §1.D [S2]. Phase 3 trained chart-native models
supervised-from-scratch on tiny data — exactly the regime the SSL-for-TS
literature predicts will fail. This module adds the proven path:

  pretrain (unlabeled, train-only corpus) → linear-probe / fine-tune.

- ``MAEEncoder``: masked autoencoder with **segment-wise masking**
  (the SSL-for-TS survey's recommended low-label generative pretext;
  segment masking captures semantics + shortens effective input).
- TS-specific augmentations only (jitter / scaling / permutation /
  segment-mask). **NOT** CV/NLP transforms (rotation/crop break the
  temporal dependency [S2]).
- ``linear_probe`` / ``fine_tune``: the two downstream protocols.

Causal: the MAE reconstructs a masked window from its own visible bars;
the encoder is the same dilated causal-conv stack as TS2Vec, so the
last-timestamp embedding never reads future bars. FULL pretraining
(not smoke) is enforced downstream by an ``is_full_pretrain`` artifact
flag (PRD R3-A2 / G11).

Torch-guarded (mirrors window_embedding.py / transformer_encoder.py).
"""
from __future__ import annotations

import numpy as np

from core.ml.transformer_encoder import get_best_device, is_torch_available
from core.ml.window_embedding import WINDOW_LEN


# ── TS-specific augmentations (numpy; no CV/NLP transforms) ────────────
def aug_jitter(x: np.ndarray, sigma: float, rng) -> np.ndarray:
    return x + rng.normal(0.0, sigma, size=x.shape)


def aug_scaling(x: np.ndarray, sigma: float, rng) -> np.ndarray:
    f = rng.normal(1.0, sigma, size=(x.shape[0], 1))
    return x * f


def aug_permutation(x: np.ndarray, n_seg: int, rng) -> np.ndarray:
    """Split each window into ``n_seg`` contiguous segments and shuffle
    their order (TS-TCC strong aug [S2]). Temporal *within* segment is
    preserved; this is a TS-valid permutation, not a CV crop/rotation."""
    out = x.copy()
    T = x.shape[1]
    bnds = np.linspace(0, T, n_seg + 1, dtype=int)
    for i in range(x.shape[0]):
        segs = [x[i, bnds[j]:bnds[j + 1]] for j in range(n_seg)]
        order = rng.permutation(n_seg)
        out[i] = np.concatenate([segs[o] for o in order])
    return out


def segment_mask(x: np.ndarray, mask_frac: float, n_seg: int, rng):
    """Segment-wise mask: zero out ``mask_frac`` of ``n_seg`` contiguous
    segments. Returns (masked_x, mask) where mask=1 on masked bars. [S2]"""
    T = x.shape[1]
    bnds = np.linspace(0, T, n_seg + 1, dtype=int)
    masked = x.copy()
    mask = np.zeros_like(x)
    n_mask = max(1, int(round(mask_frac * n_seg)))
    for i in range(x.shape[0]):
        pick = rng.choice(n_seg, size=n_mask, replace=False)
        for p in pick:
            masked[i, bnds[p]:bnds[p + 1]] = 0.0
            mask[i, bnds[p]:bnds[p + 1]] = 1.0
    return masked, mask


_FORBIDDEN_AUGS = ("rotation", "crop", "flip", "cutout_2d")  # CV/NLP: banned


if is_torch_available():
    import torch
    import torch.nn as nn

    from core.ml.window_embedding import TS2VecEncoder, WindowEmbeddingConfig

    class MAEEncoder(nn.Module):
        """Masked autoencoder over a 1-D window (segment-wise masking).

        Encoder = TS2Vec dilated causal-conv stack (shared inductive
        bias); decoder = small conv head reconstructing the full window.
        forward(masked, ) → reconstruction (B, T). ``embed(x)`` returns
        the causal last-timestamp embedding for downstream use.
        """

        def __init__(self, cfg: "WindowEmbeddingConfig | None" = None):
            super().__init__()
            self.cfg = cfg or WindowEmbeddingConfig()
            self.enc = TS2VecEncoder(n_features=1, cfg=self.cfg)
            h = self.cfg.encoder_hidden
            self.dec = nn.Sequential(
                nn.Linear(self.cfg.embedding_dim, h), nn.GELU(),
                nn.Linear(h, 1))

        def forward(self, x):  # x: (B, T) masked window
            z = self.enc(x.unsqueeze(-1))            # (B, T, embed)
            return self.dec(z).squeeze(-1)           # (B, T)

        def embed(self, x):
            z = self.enc(x.unsqueeze(-1))
            return z[:, -1, :]                        # causal last-step

    def pretrain_mae(
        windows: np.ndarray,
        steps: int,
        batch: int = 256,
        lr: float = 1e-3,
        mask_frac: float = 0.5,
        n_seg: int = 6,
        seed: int = 42,
        full: bool = False,
    ) -> tuple["MAEEncoder", list]:
        """Pretrain the MAE on (N, T) unlabeled windows; reconstruction
        loss on masked bars only. ``full=True`` marks a real full run
        (vs a smoke). Returns (model, loss_trajectory)."""
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        device = get_best_device()
        model = MAEEncoder().to(device).train()
        opt = torch.optim.Adam(model.parameters(), lr=lr)
        W = np.asarray(windows, np.float32)
        n = len(W)
        traj = []
        for s in range(steps):
            idx = rng.integers(0, n, size=min(batch, n))
            xb = W[idx]
            mxb, mk = segment_mask(xb, mask_frac, n_seg, rng)
            xt = torch.tensor(xb, device=device)
            mt = torch.tensor(mxb, device=device)
            mk_t = torch.tensor(mk, device=device)
            opt.zero_grad()
            rec = model(mt)
            denom = mk_t.sum().clamp_min(1.0)
            loss = (((rec - xt) ** 2) * mk_t).sum() / denom
            loss.backward()
            opt.step()
            traj.append(float(loss.detach().cpu()))
        return model, traj

    def linear_probe(emb_train, y_train, emb_test):
        """Frozen-encoder linear probe (ridge closed-form). emb_* are
        (N, D) embeddings; returns test predictions."""
        Xtr = np.asarray(emb_train, float)
        ytr = np.asarray(y_train, float)
        Xte = np.asarray(emb_test, float)
        A = Xtr.T @ Xtr + 1e-3 * np.eye(Xtr.shape[1])
        w = np.linalg.solve(A, Xtr.T @ ytr)
        return Xte @ w

    def fine_tune(model: "MAEEncoder", windows, y, steps=50,
                  batch=128, lr=1e-4, seed=42):
        """Fine-tune encoder + a linear head end-to-end (small lr)."""
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        device = get_best_device()
        head = nn.Linear(model.cfg.embedding_dim, 1).to(device)
        model = model.to(device).train()
        opt = torch.optim.Adam(
            list(model.parameters()) + list(head.parameters()), lr=lr)
        W = np.asarray(windows, np.float32)
        Y = np.asarray(y, np.float32)
        n = len(W)
        traj = []
        for _ in range(steps):
            idx = rng.integers(0, n, size=min(batch, n))
            xt = torch.tensor(W[idx], device=device)
            yt = torch.tensor(Y[idx], device=device)
            opt.zero_grad()
            pred = head(model.embed(xt)).squeeze(-1)
            loss = torch.mean((pred - yt) ** 2)
            loss.backward()
            opt.step()
            traj.append(float(loss.detach().cpu()))
        return model, head, traj

else:  # pragma: no cover - torch absent
    class MAEEncoder:  # type: ignore[no-redef]
        def __init__(self, *a, **k):
            raise ImportError("MAEEncoder requires torch")

    def pretrain_mae(*a, **k):  # type: ignore[no-redef]
        raise ImportError("pretrain_mae requires torch")

    def linear_probe(*a, **k):  # type: ignore[no-redef]
        raise ImportError("linear_probe requires torch")

    def fine_tune(*a, **k):  # type: ignore[no-redef]
        raise ImportError("fine_tune requires torch")
