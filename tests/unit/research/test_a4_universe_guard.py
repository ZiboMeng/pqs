"""PRD-3 RA7 — A4 expanded-universe guard + SSL→frozen-probe
scaffold (TDD).

build round. AC (PRD-3 ralph-loop RA7): SSL-pretrain+frozen-probe
pipeline unit GREEN; expanded-universe guard unit — if A4 uses
>curated universe → assert bulk expanded_v2 weekend-row fixed
(R6 hard precondition) else REFUSE.
"""
import numpy as np
import pytest

from core.ml.transformer_encoder import is_torch_available
from core.research.a4_universe_guard import (
    a4_ssl_frozen_probe_scaffold,
    assert_universe_safe_for_a4,
)


class TestExpandedUniverseGuard:
    def test_curated_executable_always_ok(self):
        assert_universe_safe_for_a4("executable")                 # no raise
        assert_universe_safe_for_a4("executable",
                                    bulk_weekend_fixed=False)     # no raise

    @pytest.mark.parametrize("u", ["expanded_v1", "expanded_v2"])
    def test_bulk_refused_by_default(self, u):
        with pytest.raises(RuntimeError, match="HARD precondition"):
            assert_universe_safe_for_a4(u)                        # default

    @pytest.mark.parametrize("u", ["expanded_v1", "expanded_v2"])
    def test_bulk_allowed_only_when_certified_fixed(self, u):
        # only an explicit certification unlocks the bulk universe
        assert_universe_safe_for_a4(u, bulk_weekend_fixed=True)   # no raise

    def test_unknown_universe_raises(self):
        with pytest.raises(ValueError, match="unknown universe"):
            assert_universe_safe_for_a4("expanded_v3")


class TestScaffoldGuardGatedFirst:
    def test_scaffold_refuses_bulk_BEFORE_pretrain(self):
        # the guard must trip before any (expensive) pretrain on
        # polluted bulk data — no wasted compute, no bad-data train.
        with pytest.raises(RuntimeError, match="HARD precondition"):
            a4_ssl_frozen_probe_scaffold(
                np.zeros((4, 16), np.float32), steps=1,
                universe_name="expanded_v2")  # bulk_weekend_fixed=False

    def test_scaffold_unknown_universe_raises(self):
        with pytest.raises(ValueError, match="unknown universe"):
            a4_ssl_frozen_probe_scaffold(
                np.zeros((4, 16), np.float32), steps=1,
                universe_name="bogus")


@pytest.mark.skipif(not is_torch_available(), reason="torch needed")
class TestSslFrozenProbeScaffold:
    def _windows(self, n=64, T=32, seed=0):
        rng = np.random.default_rng(seed)
        return np.cumsum(rng.standard_normal((n, T)),
                         axis=1).astype(np.float32)

    def test_curated_scaffold_pretrains_and_freezes(self):
        W = self._windows()
        model, embed = a4_ssl_frozen_probe_scaffold(
            W, steps=5, universe_name="executable", seed=7)
        # frozen: no param requires grad
        assert all(not p.requires_grad for p in model.parameters())
        emb = embed(W[:8])
        assert emb.shape[0] == 8 and emb.ndim == 2   # (B, d)

    def test_fixed_seed_reproducible(self):
        # pretrain_mae seeds torch+numpy → seed-reproducible. On GPU,
        # float32 atomic reductions add ~1e-6 jitter (NOT
        # nondeterminism — measured max|Δ|≈1.4e-6, corr==1.0); full
        # bitwise GPU determinism would need a global
        # use_deterministic_algorithms flag (heavy, some ops error).
        # The honest, defensible claim = reproducible at GPU-float32
        # tolerance (atol 1e-5) with correlation ≈ 1.
        W = self._windows(seed=1)
        _, e1 = a4_ssl_frozen_probe_scaffold(W, steps=5, seed=123)
        _, e2 = a4_ssl_frozen_probe_scaffold(W, steps=5, seed=123)
        a, b = e1(W[:6]), e2(W[:6])
        np.testing.assert_allclose(a, b, atol=1e-5)
        assert np.corrcoef(a.ravel(), b.ravel())[0, 1] > 0.999999

    def test_bulk_certified_runs_scaffold(self):
        # with the explicit certification the scaffold proceeds even
        # on a bulk universe name (caller asserted the fix is done).
        W = self._windows(seed=2)
        model, embed = a4_ssl_frozen_probe_scaffold(
            W, steps=3, universe_name="expanded_v2",
            bulk_weekend_fixed=True, seed=9)
        assert embed(W[:4]).shape[0] == 4
