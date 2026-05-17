"""R2 acceptance — CPCV + embargo + DSR/PBO (supplementary PRD §5).

R2-A1 purge+embargo · R2-A2 CPCV split/path counts · R2-A3 DSR/PBO
formulas · R2-A4 train-only fail-closed.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.research.cpcv import (
    assert_train_only,
    cpcv_n_paths,
    cpcv_n_splits,
    cpcv_splits,
    purged_embargoed_folds,
)
from core.research.overfit_metrics import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probability_backtest_overfitting,
)


# R2-A1 ---------------------------------------------------------------
def test_purge_removes_overlap_and_embargo_after_only():
    n, h = 200, 10
    folds = list(purged_embargoed_folds(n, k_folds=5, horizon=h,
                                        embargo_frac=0.05))
    assert len(folds) == 5
    for train, test in folds:
        lo, hi = test.min(), test.max()
        # no train sample's label window [i, i+h] overlaps [lo, hi]
        for i in train:
            assert i + h < lo or i > hi
        # embargo: nothing in (hi, hi+emb] survives in training
        emb = int(np.ceil(0.05 * n))
        assert not ((train > hi) & (train <= hi + emb)).any()
        # purge/embargo only — test+train disjoint, union ⊆ all
        assert set(train).isdisjoint(set(test))


# R2-A2 ---------------------------------------------------------------
def test_cpcv_split_and_path_counts():
    # canonical example N=6,k=2 → C(6,2)=15 splits, φ=(2/6)*15=5 paths
    assert cpcv_n_splits(6, 2) == 15
    assert cpcv_n_paths(6, 2) == 5
    splits = list(cpcv_splits(n=600, n_groups=6, k_test=2, horizon=5))
    assert len(splits) == 15
    for train, test in splits:
        assert set(train).isdisjoint(set(test))
        assert len(test) > 0 and len(train) > 0
    with pytest.raises(ValueError):
        list(cpcv_splits(n=100, n_groups=4, k_test=4, horizon=1))


# R2-A3 ---------------------------------------------------------------
def test_dsr_properties_and_pbo():
    rng = np.random.default_rng(0)
    # strong skill, few trials → DSR high
    good = rng.normal(0.002, 0.01, 500)
    d_good = deflated_sharpe_ratio(good, n_trials=2)
    # same returns but claimed after 5000 trials → DSR deflated lower
    d_many = deflated_sharpe_ratio(good, n_trials=5000)
    assert 0.0 <= d_good["deflated_sharpe"] <= 1.0
    assert d_many["deflated_sharpe"] < d_good["deflated_sharpe"]
    assert d_many["sr0"] > d_good["sr0"]          # threshold rises w/ trials
    # zero-skill noise → DSR near/below 0.5
    noise = rng.normal(0.0, 0.01, 500)
    assert deflated_sharpe_ratio(noise, n_trials=1000)["deflated_sharpe"] < 0.5
    # expected max sharpe grows with n_trials
    assert expected_max_sharpe(10000, 0.1) > expected_max_sharpe(10, 0.1) > 0
    # PBO: overfit configs (random IS winners) → high PBO
    M = rng.normal(0, 1, (60, 20))
    pbo = probability_backtest_overfitting(M)
    assert 0.0 <= pbo["pbo"] <= 1.0 and pbo["n_combinations"] > 0


# R2-A4 ---------------------------------------------------------------
def test_train_only_fail_closed():
    assert_train_only([2009, 2017, 2024], [2018, 2025], [2026])  # ok
    with pytest.raises(ValueError, match="holdout-year"):
        assert_train_only([2017, 2018], [2018, 2025], [2026])  # validation leak
    with pytest.raises(ValueError, match="holdout-year"):
        assert_train_only([2024, 2026], [2018], [2026])         # sealed leak
