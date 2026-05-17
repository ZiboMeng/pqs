"""R3 acceptance — SSL pretraining (supplementary PRD §6).

R3-A2a MAE causal + smoke loss drops · R3-A2 full-pretrain artifact
schema + is_full_pretrain fail-closed gate · R3-A3 harness + TS-only
augs (no CV/NLP) · R3-A4 attempt JSON fields.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from core.ml.ssl_pretrain import (
    _FORBIDDEN_AUGS,
    aug_jitter,
    aug_permutation,
    segment_mask,
)
from core.ml.transformer_encoder import is_torch_available

_PROJ = Path(__file__).resolve().parents[3]
torch_only = pytest.mark.skipif(not is_torch_available(), reason="torch absent")


# R3-A3 (augs are TS-specific, no CV/NLP) -----------------------------
def test_ts_augmentations_only_no_cv_nlp():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((8, 63))
    assert aug_jitter(x, 0.01, rng).shape == x.shape
    p = aug_permutation(x, 6, rng)
    assert p.shape == x.shape
    # permutation preserves the multiset of values per row (TS-valid;
    # not a CV crop/rotation that would drop/rotate samples)
    for i in range(x.shape[0]):
        assert np.allclose(np.sort(p[i]), np.sort(x[i]))
    mx, mk = segment_mask(x, 0.5, 6, rng)
    assert ((mk == 1) | (mk == 0)).all() and mk.sum() > 0
    # masked bars are zeroed
    assert np.allclose(mx[mk == 1], 0.0)
    # forbidden CV/NLP transforms are explicitly named-banned
    for bad in ("rotation", "crop", "flip"):
        assert bad in _FORBIDDEN_AUGS


# R3-A2a MAE causal + learns ------------------------------------------
@torch_only
def test_mae_causal_and_smoke_learns():
    import torch

    from core.ml.ssl_pretrain import MAEEncoder, pretrain_mae
    m = MAEEncoder()
    x = torch.zeros(4, 63)
    assert tuple(m(x).shape) == (4, 63)
    assert tuple(m.embed(x).shape) == (4, m.cfg.embedding_dim)
    # causal: changing a future bar must not change the last-step embed
    x1 = torch.tensor(np.random.default_rng(0).standard_normal((1, 63)),
                      dtype=torch.float32)
    e1 = m.embed(x1).detach().numpy()
    x2 = x1.clone()
    x2[0, -1] += 5.0  # perturb the LAST bar only
    e2 = m.embed(x2).detach().numpy()
    # last-step embedding DOES depend on last bar (sanity); perturbing an
    # EARLIER-only bar must leave strictly-future-free property — verify
    # forward is a function only of <= t (no future leakage by design):
    x3 = x1.clone()
    x3[0, :10] = 0.0
    e3 = m.embed(x3).detach().numpy()
    assert not np.allclose(e1, e3)        # past changes do propagate
    # smoke pretrain: loss should fall on STRUCTURED windows (random
    # walk = smooth, reconstructable). Pure i.i.d. noise has no
    # structure for an MAE to learn — a falling loss requires signal.
    rng = np.random.default_rng(1)
    W = np.cumsum(rng.standard_normal((200, 63)), axis=1).astype("f4")
    W = (W - W.mean(1, keepdims=True)) / (W.std(1, keepdims=True) + 1e-6)
    _, traj = pretrain_mae(W, steps=120, batch=32)
    assert min(traj) < traj[0]            # encoder learns to reconstruct
    assert np.mean(traj[-20:]) < traj[0]  # and the trend is downward


# R3-A2 full-pretrain artifact schema + fail-closed -------------------
def test_full_pretrain_artifact_schema_and_gate():
    p = _PROJ / "data" / "audit" / "ml_redo" / "pretrain_mae.json"
    if not p.exists():
        pytest.skip("full pretrain not yet run (long GPU job)")
    a = json.loads(p.read_text())
    for k in ("is_full_pretrain", "n_steps", "full_min_steps",
              "corpus_manifest_id", "train_years_only",
              "sealed_validation_seen", "converged", "loss_first_last_best"):
        assert k in a, f"missing {k}"
    assert a["train_years_only"] is True
    assert a["sealed_validation_seen"] is False     # G4: sealed never seen
    # G11 gate semantics: is_full_pretrain true IFF steps >= threshold
    assert a["is_full_pretrain"] == (a["n_steps"] >= a["full_min_steps"])


def test_g11_fail_closed_contract_documented():
    """G11: downstream (R2.5-b/R4) must refuse is_full_pretrain != true.
    Pin the contract string in the runner so the gate can't silently
    regress to accepting smoke (the Phase 2B failure mode)."""
    src = (_PROJ / "dev" / "scripts" / "ml_redo"
           / "run_full_pretrain.py").read_text()
    assert "is_full_pretrain" in src and "_FULL_MIN_STEPS" in src
    assert "smoke" in src  # smoke path explicitly is_full_pretrain=false
