"""PRD-3 RA7 — A4 SSL→frozen-probe scaffold + expanded-universe guard.

A4 arm (iTransformer/PatchTST-style in-domain masked SSL → frozen
probe). Honest scope (R4/R6/R7): the MAE masked-SSL pretrain +
causal frozen embedding ALREADY exist
(``core.ml.ssl_pretrain.pretrain_mae`` / ``MAEEncoder.embed``,
tested) — DELEGATED, NOT reimplemented. The genuinely-new RA7
surface is:

  1. ``assert_universe_safe_for_a4`` — the **R6 hard-precondition
     safety gate**. The SPY off-by-one tz fix (2026-05-13) was only
     applied to the 3 active names, NOT propagated to the ~1000
     bulk ``expanded_v2`` parquet (weekend-row pollution + stale,
     C-lite finding `docs/memos/20260519-clite_pass_plus_weekend_
     row_finding.md` §2). So A4 (or any future >curated run) on
     ``expanded_v2`` / ``expanded_v1`` is REFUSED unless the bulk
     weekend-row fix + re-fetch is explicitly certified done.
     ``executable`` (curated) is always safe. Default refuses → the
     loop can never silently train A4 on polluted bulk data.
  2. ``a4_ssl_frozen_probe_scaffold`` — guard-gated thin scaffold
     that pretrains the MAE (train-only) then returns the FROZEN
     causal embedding for a downstream probe (deterministic, fixed
     seed).
"""
from __future__ import annotations

from typing import Optional

import numpy as np

__all__ = [
    "assert_universe_safe_for_a4",
    "a4_ssl_frozen_probe_scaffold",
    "CURATED_UNIVERSE",
    "BULK_UNIVERSES",
]

CURATED_UNIVERSE = "executable"
BULK_UNIVERSES = ("expanded_v1", "expanded_v2")


def assert_universe_safe_for_a4(
    universe_name: str,
    bulk_weekend_fixed: bool = False,
) -> None:
    """R6 hard-precondition gate. Raises if A4 would run on a
    >curated (bulk) universe whose weekend-row pollution is not
    certified fixed.

    ``executable`` (curated) → always OK. ``expanded_v1`` /
    ``expanded_v2`` → REFUSE unless ``bulk_weekend_fixed=True``
    (the SPY off-by-one fix propagated to all ~1000 bulk parquet +
    re-fetched, per the C-lite finding). Unknown name → raise.
    """
    valid = (CURATED_UNIVERSE,) + BULK_UNIVERSES
    if universe_name not in valid:
        raise ValueError(
            f"unknown universe {universe_name!r}; expected {valid}")
    if universe_name == CURATED_UNIVERSE:
        return
    if not bulk_weekend_fixed:
        raise RuntimeError(
            f"A4 REFUSED on bulk universe {universe_name!r}: the R6 "
            f"bulk expanded_v2 weekend-row pollution (SPY off-by-one "
            f"fix not propagated to ~1000 bulk parquet; stale at "
            f"2026-04-17) is a HARD precondition. Fix + re-fetch the "
            f"bulk parquet and pass bulk_weekend_fixed=True (an "
            f"explicit certification), or use the curated "
            f"{CURATED_UNIVERSE!r} universe. See "
            f"docs/memos/20260519-clite_pass_plus_weekend_row_"
            f"finding.md §2.")


def a4_ssl_frozen_probe_scaffold(
    train_windows: np.ndarray,
    steps: int = 200,
    *,
    universe_name: str = CURATED_UNIVERSE,
    bulk_weekend_fixed: bool = False,
    seed: int = 42,
):
    """Guard-gated SSL→frozen-probe scaffold.

    1. ``assert_universe_safe_for_a4`` FIRST (refuse polluted bulk
       BEFORE any pretrain — no wasted compute on bad data).
    2. Delegate to ``ssl_pretrain.pretrain_mae`` on the TRAIN-ONLY
       windows (single SoT — not reimplemented).
    3. Return ``(frozen_encoder, embed_fn)`` where ``embed_fn(x)``
       gives the causal last-timestamp embedding (frozen, eval).

    Deterministic for a fixed ``seed`` (pretrain_mae seeds torch +
    numpy). Raises ``RuntimeError`` if torch is unavailable.
    """
    assert_universe_safe_for_a4(universe_name, bulk_weekend_fixed)

    from core.ml.transformer_encoder import is_torch_available
    if not is_torch_available():
        raise RuntimeError(
            "a4_ssl_frozen_probe_scaffold needs torch (GPU 4GB "
            "serial per PRD-3 RA7); not available in this env")

    import torch
    from core.ml.ssl_pretrain import pretrain_mae

    W = np.asarray(train_windows, np.float32)
    model, _losses = pretrain_mae(W, steps=steps, seed=seed)
    model = model.eval()
    for p in model.parameters():
        p.requires_grad_(False)

    # the encoder lives on whatever device pretrain_mae chose
    # (GPU when available) — inputs MUST be moved to it.
    _dev = next(model.parameters()).device

    def embed_fn(x: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            t = torch.tensor(np.asarray(x, np.float32), device=_dev)
            return model.embed(t).cpu().numpy()

    return model, embed_fn
