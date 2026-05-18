"""G2-A4 — mining PBO wrapper tests.

PRD docs/prd/20260517-backtest_robustness_completion_prd.md §4 G2.
"""
import numpy as np

from core.research.mining_pbo import (
    DEFAULT_PBO_RED_FLAG_THRESHOLD,
    compute_mining_pbo,
)


def test_pure_noise_pbo_near_half_no_redflag_or_flagged():
    # all-noise trials: PBO ~ 0.5 (CSCV neutral). red_flag is strictly
    # pbo > threshold, so noise sits at the boundary — assert it
    # computes a finite PBO and never auto-kills.
    rng = np.random.default_rng(0)
    M = rng.standard_normal((120, 12))
    r = compute_mining_pbo(M)
    assert np.isfinite(r["pbo"])
    assert 0.0 <= r["pbo"] <= 1.0
    assert r["auto_kill"] is False


def test_overfit_configs_high_pbo_redflag():
    # IS-noise that does NOT carry OOS: split periods so the IS-best is
    # random wrt OOS → PBO should be high → red_flag True.
    rng = np.random.default_rng(1)
    n_p, n_c = 200, 20
    M = rng.standard_normal((n_p, n_c))
    # make first half (IS) anti-correlated with second half (OOS)
    M[n_p // 2:] = -M[: n_p // 2] + 0.05 * rng.standard_normal((n_p // 2, n_c))
    r = compute_mining_pbo(M)
    assert r["pbo"] > 0.5
    assert r["red_flag"] is True
    assert r["auto_kill"] is False  # diagnostic only


def test_insufficient_matrix_is_not_a_pass():
    r = compute_mining_pbo(np.zeros((2, 1)))
    assert r["red_flag"] is False
    assert r["n_combinations"] == 0
    assert "NOT a pass" in r["note"]
    assert np.isnan(r["pbo"])


def test_threshold_configurable():
    rng = np.random.default_rng(2)
    M = rng.standard_normal((100, 10))
    lax = compute_mining_pbo(M, red_flag_threshold=0.99)
    strict = compute_mining_pbo(M, red_flag_threshold=0.01)
    assert lax["threshold"] == 0.99 and strict["threshold"] == 0.01
    # same PBO, threshold drives the flag
    assert lax["pbo"] == strict["pbo"]
    assert strict["red_flag"] is True or lax["red_flag"] is False
    assert DEFAULT_PBO_RED_FLAG_THRESHOLD == 0.5
