"""S5 (supplement PRD 2026-05-22) — rank-IC significance TDD.

Audit O1: `walk_forward_rank_sign._overfit_control` fed per-fold
rank-IC into `deflated_sharpe_ratio` (which expects a per-period RETURN
series). The S5 fix replaces that with `_rank_ic_significance` — the
t-stat of the mean IC, the correct test for a rank-IC series.
"""
import sys
from pathlib import Path

import pytest

_PROJ = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_PROJ / "dev/scripts/ml"))

from walk_forward_rank_sign import _rank_ic_significance  # noqa: E402


class TestRankICSignificance:
    def test_n_below_2_is_na(self):
        out = _rank_ic_significance([0.05], n_trials=3)
        assert out["n"] == 1 and "N/A" in out["note"]

    def test_positive_ic_positive_tstat(self):
        # a tight positive IC series → large positive t-stat
        out = _rank_ic_significance([0.04, 0.05, 0.045, 0.05, 0.04],
                                    n_trials=3)
        assert out["mean_ic"] > 0
        assert out["ic_tstat"] > 2.0
        assert out["significant_uncorrected_2sigma"] is True
        assert out["n_trials"] == 3

    def test_zero_mean_ic_near_zero_tstat(self):
        out = _rank_ic_significance([0.05, -0.05, 0.05, -0.05], n_trials=2)
        assert abs(out["ic_tstat"]) < 1.0
        assert out["significant_uncorrected_2sigma"] is False

    def test_no_misused_dsr_key(self):
        """The fix: the result must NOT carry a 'dsr' field — rank-IC is
        not a return series; deflated_sharpe_ratio must not be applied."""
        out = _rank_ic_significance([0.04, 0.05, 0.045], n_trials=3)
        assert "dsr" not in out
        assert "ic_tstat" in out

    def test_nan_ic_dropped(self):
        out = _rank_ic_significance([0.04, float("nan"), 0.05], n_trials=2)
        assert out["n"] == 2          # NaN fold dropped

    def test_deterministic(self):
        ics = [0.03, 0.05, 0.04, 0.06]
        assert _rank_ic_significance(ics, 3) == _rank_ic_significance(ics, 3)
