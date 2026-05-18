"""G3-A3 — Minimum Backtest Length guard tests.

PRD docs/prd/20260517-backtest_robustness_completion_prd.md §4 G3.
"""
import math

import numpy as np

from core.research.overfit_metrics import (
    check_min_backtest_length,
    minimum_backtest_length,
)


def test_minbtl_closed_form():
    # MinBTL = 2 ln N / SR^2
    m = minimum_backtest_length(observed_sr_annual=1.0, n_trials=200)
    assert m["min_btl_years"] == \
        np.float64(2.0 * math.log(200) / 1.0 ** 2)
    # higher SR ⇒ less history needed; more trials ⇒ more needed
    assert minimum_backtest_length(2.0, 200)["min_btl_years"] < \
        minimum_backtest_length(1.0, 200)["min_btl_years"]
    assert minimum_backtest_length(1.0, 1000)["min_btl_years"] > \
        minimum_backtest_length(1.0, 200)["min_btl_years"]


def test_minbtl_undefined_inputs_nan():
    assert np.isnan(minimum_backtest_length(0.0, 200)["min_btl_years"])
    assert np.isnan(minimum_backtest_length(1.0, 1)["min_btl_years"])
    assert np.isnan(
        minimum_backtest_length(float("nan"), 200)["min_btl_years"])


def test_gate_fail_closed_when_short():
    # SR 0.5, N=200 → MinBTL = 2 ln200 / 0.25 ≈ 42.4y; 17y backtest fails
    r = check_min_backtest_length(0.5, 200, actual_years=17.0)
    assert r["passed"] is False
    assert r["reason"] == "backtest_shorter_than_min_btl"
    # very strong SR clears with the same history
    r2 = check_min_backtest_length(2.0, 200, actual_years=17.0)
    assert r2["passed"] is True


def test_gate_fail_closed_on_undefined():
    r = check_min_backtest_length(0.0, 200, actual_years=17.0)
    assert r["passed"] is False
    assert r["reason"] == "undefined_inputs_fail_closed"
    r2 = check_min_backtest_length(1.0, 200, actual_years=float("nan"))
    assert r2["passed"] is False


def test_safety_multiple_scales_requirement():
    base = check_min_backtest_length(1.0, 200, 20.0, safety_multiple=1.0)
    strict = check_min_backtest_length(1.0, 200, 20.0, safety_multiple=3.0)
    assert strict["min_btl_years"] == 3.0 * base["min_btl_years"]
    assert base["passed"] is True and strict["passed"] is False
