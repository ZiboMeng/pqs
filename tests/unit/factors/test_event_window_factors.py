"""Tests for event window factors (Round D)."""

from __future__ import annotations

import pandas as pd
import pytest

from core.data.macro_event_calendar import (
    first_friday_of_month, second_tuesday_of_month,
    generate_nfp_dates, generate_cpi_dates,
    generate_fomc_dates_heuristic, load_calendar, window_flag_panel,
)
from core.factors.factor_registry import RESEARCH_FACTORS
from core.factors.event_window_factors import (
    EVENT_WINDOW_FACTOR_NAMES,
    compute_event_window_factors,
)


class TestNFPExactRule:
    def test_first_friday_known(self):
        """NFP rule: first Friday of month. Verified manually."""
        cases = [
            (2024, 1, "2024-01-05"),
            (2024, 2, "2024-02-02"),
            (2024, 12, "2024-12-06"),
            (2025, 5, "2025-05-02"),
            (2009, 1, "2009-01-02"),
        ]
        for y, m, exp in cases:
            assert first_friday_of_month(y, m).date() == pd.Timestamp(exp).date()

    def test_count(self):
        nfp = generate_nfp_dates(2020, 2024)
        assert len(nfp) == 12 * 5


class TestCPIApprox:
    def test_second_tuesday(self):
        # 2024 Feb: real CPI release was Tue 2024-02-13 (matches our approx)
        # 2024 Jun: real CPI 2024-06-12 (Wed); approx is Tue 2024-06-11 (1d off)
        t = second_tuesday_of_month(2024, 2)
        assert t.day_name() == "Tuesday"
        assert t.date() == pd.Timestamp("2024-02-13").date()


class TestRegistration:
    def test_all_4_in_research_factors(self):
        for name in EVENT_WINDOW_FACTOR_NAMES:
            assert name in RESEARCH_FACTORS


class TestComputeFactors:
    def test_factors_produced(self):
        idx = pd.bdate_range("2024-01-01", "2024-12-31")
        out = compute_event_window_factors(idx, ["AAPL", "MSFT"])
        for n in EVENT_WINDOW_FACTOR_NAMES:
            assert n in out
            assert out[n].shape == (len(idx), 2)

    def test_pre_nfp_marks_thu_friday(self):
        idx = pd.bdate_range("2024-01-01", "2024-01-31")
        out = compute_event_window_factors(idx, ["AAPL"])
        nfp = out["pre_nfp_window_flag"]["AAPL"]
        # 2024-01-05 is first Friday → bars [Thu Jan 4, Fri Jan 5] flagged
        assert nfp.loc["2024-01-04"] == 1.0
        assert nfp.loc["2024-01-05"] == 1.0
        assert nfp.loc["2024-01-08"] == 0.0  # Mon post-NFP

    def test_broadcast_identical(self):
        idx = pd.bdate_range("2024-01-01", "2024-03-31")
        out = compute_event_window_factors(idx, ["A", "B", "C"])
        for n, df in out.items():
            for col in df.columns[1:]:
                assert (df[col] == df[df.columns[0]]).all()


class TestYAMLOverride:
    def test_yaml_overrides_heuristic(self, tmp_path):
        import yaml
        yaml_path = tmp_path / "macro.yaml"
        custom_fomc = ["2024-06-12", "2024-09-18"]
        with open(yaml_path, "w") as f:
            yaml.safe_dump({"fomc": custom_fomc}, f)
        cal = load_calendar(yaml_path=str(yaml_path), start_year=2024, end_year=2024)
        assert len(cal["fomc"]) == 2
        assert cal["fomc"][0] == pd.Timestamp("2024-06-12")
