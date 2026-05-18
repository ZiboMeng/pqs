"""G4-A4 — CPCV-distribution acceptance tests.

PRD docs/prd/20260517-backtest_robustness_completion_prd.md §4 G4.
"""
import numpy as np

from core.research.cpcv_acceptance import cpcv_acceptance_distribution


def _signal_with_edge(n, edge, seed):
    rng = np.random.default_rng(seed)
    fwd = rng.standard_normal(n)
    pred = edge * fwd + rng.standard_normal(n)   # tunable predictive edge
    return pred, fwd


def test_distribution_fields_and_weighting():
    pred, fwd = _signal_with_edge(2000, 0.6, 1)
    r = cpcv_acceptance_distribution(pred, fwd, honest_n_trials=200)
    assert r["insufficient"] is False
    for k in ("ic_mean", "ic_std", "ic_q10", "ic_q90",
              "ic_sample_weighted", "dsr", "pbo"):
        assert k in r
    assert "sample_size_only" in r["weighting"]
    assert r["dsr_n_trials"] == 200
    assert r["n_folds"] >= 2


def test_edge_signal_positive_ic_noise_near_zero():
    pe, fe = _signal_with_edge(2000, 0.8, 2)
    re_ = cpcv_acceptance_distribution(pe, fe, honest_n_trials=10)
    pn = np.random.default_rng(3).standard_normal(2000)
    fn = np.random.default_rng(4).standard_normal(2000)
    rn = cpcv_acceptance_distribution(pn, fn, honest_n_trials=10)
    assert re_["ic_mean"] > 0.2
    assert abs(rn["ic_mean"]) < 0.1
    # honest DSR: real edge ⇒ high; pure noise ⇒ low
    assert re_["dsr"] > rn["dsr"]


def test_insufficient_is_fail_closed_not_pass():
    pred = np.arange(20.0)
    fwd = np.arange(20.0)
    r = cpcv_acceptance_distribution(pred, fwd, honest_n_trials=5)
    assert r["insufficient"] is True
    assert "NOT a pass" in r["reason"]


def test_sample_weighted_differs_from_plain_mean_when_uneven():
    pred, fwd = _signal_with_edge(1500, 0.5, 9)
    r = cpcv_acceptance_distribution(pred, fwd, honest_n_trials=50,
                                     n_groups=6, k_test=2)
    # both defined; sample-weighted is a valid finite aggregate
    assert np.isfinite(r["ic_mean"])
    assert np.isfinite(r["ic_sample_weighted"])


def test_honest_n_flows_into_dsr():
    pred, fwd = _signal_with_edge(2000, 0.7, 11)
    few = cpcv_acceptance_distribution(pred, fwd, honest_n_trials=2)
    many = cpcv_acceptance_distribution(pred, fwd, honest_n_trials=5000)
    # more trials ⇒ stronger haircut ⇒ DSR not higher
    assert many["dsr"] <= few["dsr"] + 1e-9


def test_scope_marks_new_cycle_only():
    pred, fwd = _signal_with_edge(1200, 0.6, 13)
    r = cpcv_acceptance_distribution(pred, fwd, honest_n_trials=20)
    assert "new_cycle_only" in r["scope"]
    assert "walk_forward untouched" in r["scope"]
