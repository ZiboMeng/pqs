"""Tests for ``core.research.ml.labels`` (PRD #4 P4.4 sub-step 3 prereq).

Coverage:
- forward-return label correctness (simple + log)
- horizon validation
- DatetimeIndex requirement
- bar-integrity smoke (weekend / monotone / dup)
- sealed-year guard
- tradeable-mask application + shape alignment
- pipeline _validate_panel_indices integration
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.research.ml.labels import (
    apply_tradeable_mask,
    assert_bar_integrity,
    assert_no_sealed_year,
    assert_panel_datetime_index,
    make_forward_log_return_labels,
    make_forward_return_labels,
)
from core.research.ml.pipeline import (
    WalkForwardConfig,
    run_walk_forward,
)
from core.research.ml.rank_model import LinearBaselineRankModel


def _bday_panel(start="2020-01-01", end="2020-06-30", n_syms=3, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, end)
    cols = [f"S{i}" for i in range(n_syms)]
    # walk price from 100
    rets = rng.normal(0, 0.01, size=(len(idx), n_syms))
    price = pd.DataFrame(100.0 * np.exp(np.cumsum(rets, axis=0)),
                         index=idx, columns=cols)
    return price


# ---------------------------------------------------------------------------
# Forward-return labels
# ---------------------------------------------------------------------------


class TestForwardReturnLabels:
    def test_simple_return_horizon_1(self):
        price = _bday_panel()
        labels = make_forward_return_labels(price, horizon_days=1)
        # label[t] should equal price[t+1]/price[t] - 1
        for t in range(len(price) - 1):
            expected = price.iloc[t + 1] / price.iloc[t] - 1
            actual = labels.iloc[t]
            pd.testing.assert_series_equal(
                actual, expected, check_names=False,
            )
        # last row → NaN (no t+1)
        assert labels.iloc[-1].isna().all()

    def test_simple_return_horizon_5(self):
        price = _bday_panel()
        labels = make_forward_return_labels(price, horizon_days=5)
        # label[0] should be price[5]/price[0] - 1
        expected = price.iloc[5] / price.iloc[0] - 1
        pd.testing.assert_series_equal(
            labels.iloc[0], expected, check_names=False)
        # last 5 rows → NaN
        assert labels.iloc[-5:].isna().all().all()

    def test_log_return_matches_log_of_ratio(self):
        price = _bday_panel()
        labels = make_forward_log_return_labels(price, horizon_days=5)
        ratio = price.shift(-5).div(price)
        expected = np.log(ratio)
        pd.testing.assert_frame_equal(labels, expected)

    def test_horizon_zero_raises(self):
        price = _bday_panel()
        with pytest.raises(ValueError, match="horizon_days"):
            make_forward_return_labels(price, horizon_days=0)

    def test_non_datetime_index_raises(self):
        price = pd.DataFrame({"A": [1, 2, 3]})  # RangeIndex
        with pytest.raises(ValueError, match="DatetimeIndex"):
            make_forward_return_labels(price, horizon_days=1)


# ---------------------------------------------------------------------------
# Bar-integrity smoke
# ---------------------------------------------------------------------------


class TestAssertBarIntegrity:
    def test_clean_bday_panel_passes(self):
        panel = _bday_panel()
        assert_bar_integrity(panel)  # no raise

    def test_weekend_row_raises(self):
        panel = _bday_panel("2020-01-01", "2020-01-10")
        # inject a Saturday row
        sat = pd.Timestamp("2020-01-11")  # Saturday
        new_row = pd.DataFrame(
            {c: [100.0] for c in panel.columns}, index=[sat])
        polluted = pd.concat([panel, new_row]).sort_index()
        with pytest.raises(ValueError, match="weekend"):
            assert_bar_integrity(polluted)

    def test_non_monotone_raises(self):
        panel = _bday_panel("2020-01-01", "2020-01-10")
        shuffled = panel.iloc[::-1]  # reverse
        with pytest.raises(ValueError, match="monotone"):
            assert_bar_integrity(shuffled)

    def test_duplicate_dates_raise(self):
        panel = _bday_panel("2020-01-01", "2020-01-10")
        dup = pd.concat([panel, panel.iloc[[0]]]).sort_index()
        with pytest.raises(ValueError, match="duplicate"):
            assert_bar_integrity(dup)

    def test_range_index_raises(self):
        panel = pd.DataFrame({"A": [1, 2, 3]})  # RangeIndex
        with pytest.raises(ValueError, match="DatetimeIndex"):
            assert_bar_integrity(panel)


# ---------------------------------------------------------------------------
# Sealed-year guard
# ---------------------------------------------------------------------------


class TestAssertNoSealedYear:
    def test_no_sealed_overlap_ok(self):
        panel = _bday_panel("2020-01-01", "2020-12-31")
        assert_no_sealed_year(panel, sealed_years=(2026,))

    def test_sealed_overlap_raises(self):
        panel = _bday_panel("2025-01-01", "2026-06-30")
        with pytest.raises(ValueError, match="sealed year"):
            assert_no_sealed_year(panel, sealed_years=(2026,))

    def test_empty_sealed_years_no_op(self):
        panel = _bday_panel("2025-01-01", "2026-06-30")
        assert_no_sealed_year(panel, sealed_years=())  # no raise

    def test_dict_panel_checks_each_member(self):
        d = {
            "close": _bday_panel("2025-01-01", "2025-12-31"),  # OK
            "volume": _bday_panel("2025-01-01", "2026-06-30"),  # leaks
        }
        with pytest.raises(ValueError, match="sealed year"):
            assert_no_sealed_year(d, sealed_years=(2026,))


# ---------------------------------------------------------------------------
# Tradeable mask
# ---------------------------------------------------------------------------


class TestApplyTradeableMask:
    def test_none_mask_returns_labels_unchanged(self):
        labels = _bday_panel("2020-01-01", "2020-01-31")
        out = apply_tradeable_mask(labels, None)
        pd.testing.assert_frame_equal(out, labels)

    def test_false_mask_yields_all_nan(self):
        labels = _bday_panel("2020-01-01", "2020-01-31")
        mask = pd.DataFrame(False, index=labels.index, columns=labels.columns)
        out = apply_tradeable_mask(labels, mask)
        assert out.isna().all().all()

    def test_partial_mask(self):
        labels = _bday_panel("2020-01-01", "2020-01-15")
        mask = pd.DataFrame(True, index=labels.index, columns=labels.columns)
        mask.iloc[:, 0] = False  # symbol 0 not tradeable
        out = apply_tradeable_mask(labels, mask)
        assert out.iloc[:, 0].isna().all()
        # remaining symbols unchanged
        pd.testing.assert_frame_equal(out.iloc[:, 1:], labels.iloc[:, 1:])

    def test_misaligned_mask_reindexes(self):
        labels = _bday_panel("2020-01-01", "2020-01-15", n_syms=4)
        # mask only has 2 of 4 symbols
        mask = pd.DataFrame(True, index=labels.index, columns=labels.columns[:2])
        out = apply_tradeable_mask(labels, mask)
        # missing-from-mask columns → treated as not tradeable → NaN
        assert out.iloc[:, 2:].isna().all().all()
        # present-in-mask columns unchanged
        pd.testing.assert_frame_equal(out.iloc[:, :2], labels.iloc[:, :2])

    def test_non_dataframe_mask_raises(self):
        labels = _bday_panel()
        with pytest.raises(TypeError, match="DataFrame"):
            apply_tradeable_mask(labels, mask=[True, False])


# ---------------------------------------------------------------------------
# DatetimeIndex helper
# ---------------------------------------------------------------------------


class TestAssertPanelDatetimeIndex:
    def test_dataframe_ok(self):
        panel = _bday_panel()
        assert_panel_datetime_index(panel)

    def test_dataframe_range_index_raises(self):
        with pytest.raises(ValueError, match="DatetimeIndex"):
            assert_panel_datetime_index(pd.DataFrame({"A": [1, 2]}))

    def test_dict_each_member_checked(self):
        d = {"feat1": _bday_panel(), "feat2": pd.DataFrame({"A": [1, 2]})}
        with pytest.raises(ValueError, match="feat2"):
            assert_panel_datetime_index(d)


# ---------------------------------------------------------------------------
# Pipeline integration — _validate_panel_indices closes R23 catch
# ---------------------------------------------------------------------------


class TestPipelineEntryValidation:
    def test_run_walk_forward_rejects_range_index_labels(self):
        cfg = WalkForwardConfig(start_year=2010, end_year=2017)
        with pytest.raises(ValueError, match="DatetimeIndex"):
            run_walk_forward(
                model_factory=LinearBaselineRankModel,
                config=cfg,
                features={"feat1": _bday_panel("2010-01-01", "2017-12-31")},
                labels=pd.DataFrame({"A": [1, 2, 3]}),  # RangeIndex
                sealed_years=(),
            )

    def test_run_walk_forward_rejects_range_index_features(self):
        cfg = WalkForwardConfig(start_year=2010, end_year=2017)
        labels = _bday_panel("2010-01-01", "2017-12-31")
        with pytest.raises(ValueError, match="DatetimeIndex"):
            run_walk_forward(
                model_factory=LinearBaselineRankModel,
                config=cfg,
                features={"feat1": pd.DataFrame({"A": [1, 2]})},  # RangeIndex
                labels=labels,
                sealed_years=(),
            )
