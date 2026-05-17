"""R2 — Combinatorial Purged Cross-Validation (supplementary PRD §5).

Per literature review §1.C [S6][S10][S11] (López de Prado). Standard
k-fold is invalid for financial ML (labels overlap → leakage). This
module provides:

- ``purged_embargoed_folds``: k-fold where training samples whose label
  window overlaps a test fold are PURGED (before AND after), plus an
  EMBARGO of the first ``embargo_frac`` of observations *after* each
  test fold removed from training.
- ``cpcv_splits``: N contiguous non-overlapping groups; every size-k
  combination is a test set → C(N,k) splits → φ[N,k]=(k/N)·C(N,k)
  reconstructable backtest paths (a DISTRIBUTION of OOS estimates, not
  one point).

Train-only fail-closed: ``assert_train_only`` raises if the panel
index contains any validation/sealed year (mirrors the forward-runner
``validate_no_holdout_leakage`` discipline established this session).
"""
from __future__ import annotations

from itertools import combinations
from math import comb
from typing import Iterable, Iterator, Optional

import numpy as np


def _overlap_purge(train_idx, test_lo, test_hi, horizon):
    """Drop train samples whose label window [i, i+horizon] overlaps the
    closed test span [test_lo, test_hi] (purge both sides)."""
    keep = []
    for i in train_idx:
        if i + horizon < test_lo or i > test_hi:
            keep.append(i)
    return np.array(keep, dtype=int)


def purged_embargoed_folds(
    n: int,
    k_folds: int,
    horizon: int,
    embargo_frac: float = 0.01,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Yield (train_idx, test_idx) for purged + embargoed k-fold.

    Contiguous test folds (time order preserved). Embargo removes the
    first ``ceil(embargo_frac*n)`` observations AFTER each test fold
    from training (only after — never before). [S6][S11]
    """
    if k_folds < 2:
        raise ValueError("k_folds >= 2")
    bounds = np.linspace(0, n, k_folds + 1, dtype=int)
    emb = int(np.ceil(embargo_frac * n))
    all_idx = np.arange(n)
    for j in range(k_folds):
        lo, hi = bounds[j], bounds[j + 1] - 1
        test = all_idx[lo: hi + 1]
        train = all_idx[(all_idx < lo) | (all_idx > hi)]
        train = _overlap_purge(train, lo, hi, horizon)
        if emb > 0:  # embargo: drop [hi+1, hi+emb] from training
            train = train[(train < lo) | (train > hi + emb)]
        yield train, test


def cpcv_n_splits(n_groups: int, k_test: int) -> int:
    """Number of CPCV splits = C(N, k)."""
    return comb(n_groups, k_test)


def cpcv_n_paths(n_groups: int, k_test: int) -> int:
    """Number of reconstructable backtest paths = (k/N)·C(N,k) = φ[N,k]."""
    return (k_test * comb(n_groups, k_test)) // n_groups


def cpcv_splits(
    n: int,
    n_groups: int,
    k_test: int,
    horizon: int,
    embargo_frac: float = 0.01,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Yield (train_idx, test_idx) for all C(N,k) combinatorial purged
    test sets. Each test set = k contiguous groups; training = the rest,
    purged of label-overlap with ANY test group + embargoed. [S6][S10]
    """
    if not (1 <= k_test < n_groups):
        raise ValueError("1 <= k_test < n_groups")
    bounds = np.linspace(0, n, n_groups + 1, dtype=int)
    emb = int(np.ceil(embargo_frac * n))
    all_idx = np.arange(n)
    for combo in combinations(range(n_groups), k_test):
        test_mask = np.zeros(n, dtype=bool)
        spans = []
        for g in combo:
            lo, hi = bounds[g], bounds[g + 1] - 1
            test_mask[lo: hi + 1] = True
            spans.append((lo, hi))
        test = all_idx[test_mask]
        train = all_idx[~test_mask]
        for lo, hi in spans:
            train = _overlap_purge(train, lo, hi, horizon)
            if emb > 0:
                train = train[(train < lo) | (train > hi + emb)]
        yield train, test


def assert_train_only(
    years: Iterable[int],
    validation_years: Iterable[int],
    sealed_years: Iterable[int],
) -> None:
    """Fail-closed: raise if the panel contains validation/sealed-year
    rows. Mirrors forward-runner ``validate_no_holdout_leakage``;
    enforces PRD §9.2 (CPCV only on train-only panel)."""
    yr = set(int(y) for y in years)
    holdout = set(int(y) for y in validation_years) | set(
        int(y) for y in sealed_years)
    leaked = sorted(yr & holdout)
    if leaked:
        raise ValueError(
            f"CPCV panel contains holdout-year rows {leaked} — must run on "
            f"partition_for_role(role='miner') train-only panel "
            f"(temporal_split discipline)")
