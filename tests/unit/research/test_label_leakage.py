"""PRD-1 P1.1 — canonical leakage-correct label helpers (TDD).

López de Prado Ch.4 (average uniqueness for overlapping labels) +
Ch.7 (purge/embargo). Hand-computed expected values; this is the
RED→GREEN spec for core/research/label_leakage.py.
"""
import numpy as np
import pytest

from core.research.label_leakage import (
    average_uniqueness_weights,
    purge_embargo_mask,
)


class TestAverageUniquenessWeights:
    def test_three_overlapping_h1_single_group(self):
        # samples at positions 0,1,2; horizon 1 → windows [0,1],[1,2],[2,3]
        # concurrency: pos0=1,pos1=2,pos2=2,pos3=1
        # uniq = [mean(1,1/2), mean(1/2,1/2), mean(1/2,1)] = [.75,.5,.75]
        # mean=.6667 → normalized = [1.125,.75,1.125]
        w = average_uniqueness_weights(
            start_pos=np.array([0, 1, 2]), horizon=1)
        np.testing.assert_allclose(w, [1.125, 0.75, 1.125], rtol=1e-9)
        assert abs(w.mean() - 1.0) < 1e-9  # mean-normalized

    def test_non_overlapping_all_unique(self):
        # gap >= horizon → no concurrency → all uniqueness equal → all 1
        w = average_uniqueness_weights(
            start_pos=np.array([0, 5, 10]), horizon=2)
        np.testing.assert_allclose(w, [1.0, 1.0, 1.0], rtol=1e-9)

    def test_groups_are_independent(self):
        # two symbols, each = the 3-overlap pattern; concurrency must
        # NOT cross groups → same per-group result as single-group case
        w = average_uniqueness_weights(
            start_pos=np.array([0, 1, 2, 0, 1, 2]),
            horizon=1,
            groups=np.array(["A", "A", "A", "B", "B", "B"]))
        np.testing.assert_allclose(
            w, [1.125, .75, 1.125, 1.125, .75, 1.125], rtol=1e-9)

    def test_empty_and_singleton(self):
        assert average_uniqueness_weights(np.array([]), 1).shape == (0,)
        np.testing.assert_allclose(
            average_uniqueness_weights(np.array([3]), 5), [1.0])

    def test_weights_reduce_overlapping_inflation_direction(self):
        # heavier overlap (h large) → interior samples downweighted
        w = average_uniqueness_weights(np.array([0, 1, 2, 3, 4]), horizon=3)
        assert w[2] < w[0]            # interior more concurrent → lower
        assert abs(w.mean() - 1.0) < 1e-9


class TestPurgeEmbargoMask:
    def test_purges_label_window_reaching_holdout_year(self):
        # pos→year: 0..2=2017(train), 3..5=2018(holdout)
        yrs = [2017, 2017, 2017, 2018, 2018, 2018]
        # horizon=1, embargo=0: sample p kept iff [p,p+1] all non-holdout
        keep = purge_embargo_mask(
            t_pos=np.array([0, 1, 2]), year_of_pos=yrs,
            horizon=1, holdout_years={2018}, embargo=0)
        # p=2 → window [2,3], pos3=2018 → purged
        np.testing.assert_array_equal(keep, [True, True, False])

    def test_embargo_extends_purge(self):
        yrs = [2017] * 6 + [2018] * 3
        keep = purge_embargo_mask(
            t_pos=np.array([3, 4, 5]), year_of_pos=yrs,
            horizon=0, holdout_years={2018}, embargo=2)
        # p=5 → [5,5+0+2]=[5,7], pos6=2018 → purged; p=4→[4,6]→purged;
        # p=3→[3,5] all 2017 → kept
        np.testing.assert_array_equal(keep, [True, False, False])

    def test_no_holdout_keeps_all(self):
        keep = purge_embargo_mask(
            t_pos=np.array([0, 1, 2]), year_of_pos=[2017, 2017, 2017],
            horizon=2, holdout_years={2018}, embargo=1)
        assert keep.all()

    def test_clips_at_panel_end(self):
        # window past end must not IndexError
        keep = purge_embargo_mask(
            t_pos=np.array([0]), year_of_pos=[2017, 2017],
            horizon=10, holdout_years={2018}, embargo=10)
        assert keep.tolist() == [True]

    def test_empty(self):
        keep = purge_embargo_mask(
            t_pos=np.array([], dtype=int), year_of_pos=[2017],
            horizon=1, holdout_years={2018}, embargo=0)
        assert keep.shape == (0,)
