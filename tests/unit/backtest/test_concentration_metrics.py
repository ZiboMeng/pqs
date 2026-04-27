"""M12 concentration metric + validator unit tests.

Per codex Round-5 audit
(`docs/claude_review_loop.md` §Round 5 Audit, Implementation Bar #2):

  - pass case under both thresholds
  - fail on top-1 > 0.40
  - fail on top-3 > 0.70
  - absolute-weight handling
  - zero/empty weights handled deterministically
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.backtest.concentration_metrics import (
    DEFAULT_TOP1_CEILING,
    DEFAULT_TOP3_CEILING,
    compute_concentration_metrics,
    validate_concentration,
)


# ── compute_concentration_metrics ──────────────────────────────────────


def test_compute_metrics_pass_case_under_both_thresholds():
    """Diversified weight matrix: every date <= 0.20 in any single name,
    <= 0.50 in top-3. Both metrics under defaults."""
    weights = pd.DataFrame(
        [
            [0.20, 0.20, 0.20, 0.20, 0.20],
            [0.15, 0.20, 0.25, 0.20, 0.20],
            [0.20, 0.20, 0.20, 0.20, 0.20],
        ],
        columns=list("ABCDE"),
    )
    result = compute_concentration_metrics(weights)
    assert result["m12_top1_weight_max"] == pytest.approx(0.25)
    assert result["m12_top3_weight_max"] == pytest.approx(0.65)
    assert result["m12_n_dates_with_weights"] == 3

    passed, breaches = validate_concentration(
        top1_observed=result["m12_top1_weight_max"],
        top3_observed=result["m12_top3_weight_max"],
    )
    assert passed is True
    assert breaches == []


def test_compute_metrics_fail_top1_over_40_pct():
    """A single-name weight of 0.45 must trip top-1 > 0.40 ceiling."""
    weights = pd.DataFrame(
        [
            [0.45, 0.15, 0.15, 0.15, 0.10],     # top1 = 0.45, top3 = 0.75
        ],
        columns=list("ABCDE"),
    )
    result = compute_concentration_metrics(weights)
    assert result["m12_top1_weight_max"] == pytest.approx(0.45)

    passed, breaches = validate_concentration(
        top1_observed=result["m12_top1_weight_max"],
        top3_observed=result["m12_top3_weight_max"],
    )
    assert passed is False
    assert any("top1_weight_max" in b for b in breaches)


def test_compute_metrics_fail_top3_over_70_pct():
    """Top-3 sum of 0.75 (with no single name over 0.40) must still fail
    on the top-3 ceiling alone."""
    weights = pd.DataFrame(
        [
            [0.30, 0.25, 0.20, 0.10, 0.10],   # top1 = 0.30, top3 = 0.75
        ],
        columns=list("ABCDE"),
    )
    result = compute_concentration_metrics(weights)
    assert result["m12_top1_weight_max"] == pytest.approx(0.30)
    assert result["m12_top3_weight_max"] == pytest.approx(0.75)

    passed, breaches = validate_concentration(
        top1_observed=result["m12_top1_weight_max"],
        top3_observed=result["m12_top3_weight_max"],
    )
    assert passed is False
    assert all("top1_weight_max" not in b for b in breaches), (
        "top-1 ceiling should NOT have been breached at 0.30"
    )
    assert any("top3_weight_max" in b for b in breaches)


def test_compute_metrics_uses_absolute_weights():
    """Long-short matrix: a -0.50 short must trip top-1 by absolute size,
    not be hidden by sign."""
    weights = pd.DataFrame(
        [
            [-0.50, 0.20, 0.20, 0.10, 0.0],   # |top1| = 0.50
        ],
        columns=list("ABCDE"),
    )
    result = compute_concentration_metrics(weights)
    assert result["m12_top1_weight_max"] == pytest.approx(0.50)

    passed, breaches = validate_concentration(
        top1_observed=result["m12_top1_weight_max"],
        top3_observed=result["m12_top3_weight_max"],
    )
    assert passed is False
    assert any("top1_weight_max=0.5000" in b for b in breaches)


def test_compute_metrics_zero_or_empty_weights_deterministic():
    """Empty / all-zero weight matrices return deterministic metric
    dict — caller should not need to special-case None / empty."""
    # None
    r_none = compute_concentration_metrics(None)
    assert r_none["m12_top1_weight_max"] == 0.0
    assert r_none["m12_top3_weight_max"] == 0.0
    assert r_none["m12_n_dates_with_weights"] == 0

    # 0 rows
    r_zero_rows = compute_concentration_metrics(pd.DataFrame(columns=list("ABCDE")))
    assert r_zero_rows == {
        "m12_top1_weight_max": 0.0,
        "m12_top3_weight_max": 0.0,
        "m12_n_dates_with_weights": 0,
    }

    # 0 cols
    r_zero_cols = compute_concentration_metrics(
        pd.DataFrame(index=pd.date_range("2024-01-01", periods=3))
    )
    assert r_zero_cols == {
        "m12_top1_weight_max": 0.0,
        "m12_top3_weight_max": 0.0,
        "m12_n_dates_with_weights": 0,
    }

    # All-zero: dates exist, but no weight → metrics are 0 yet n_dates>0
    weights = pd.DataFrame(np.zeros((3, 5)), columns=list("ABCDE"))
    r_all_zero = compute_concentration_metrics(weights)
    assert r_all_zero["m12_top1_weight_max"] == 0.0
    assert r_all_zero["m12_top3_weight_max"] == 0.0
    assert r_all_zero["m12_n_dates_with_weights"] == 3

    passed, breaches = validate_concentration(
        top1_observed=r_all_zero["m12_top1_weight_max"],
        top3_observed=r_all_zero["m12_top3_weight_max"],
    )
    assert passed is True
    assert breaches == []


# ── validate_concentration policy edges ────────────────────────────────


def test_validate_at_ceiling_exactly_passes():
    """Top-1 = 0.40 exactly is at-ceiling; passes (strict > breach)."""
    passed, breaches = validate_concentration(top1_observed=0.40, top3_observed=0.70)
    assert passed is True
    assert breaches == []


def test_validate_above_ceiling_by_epsilon_fails():
    """Top-1 = 0.4001 fails by an epsilon — strict > comparison."""
    passed, _ = validate_concentration(top1_observed=0.4001, top3_observed=0.50)
    assert passed is False


def test_validate_custom_ceilings_respected():
    """Caller can tighten ceilings (e.g. for a stricter sub-policy)."""
    passed, breaches = validate_concentration(
        top1_observed=0.30, top3_observed=0.65,
        top1_ceiling=0.25, top3_ceiling=0.60,
    )
    assert passed is False
    assert any("ceiling=0.25" in b for b in breaches)
    assert any("ceiling=0.60" in b for b in breaches)


def test_validate_does_not_mutate_or_clamp():
    """validate_concentration must be pure: same inputs → same outputs;
    the returned breaches list never references mutated thresholds."""
    p1, b1 = validate_concentration(top1_observed=0.50, top3_observed=0.40)
    p2, b2 = validate_concentration(top1_observed=0.50, top3_observed=0.40)
    assert p1 is p2
    assert b1 == b2


def test_default_ceilings_match_research_concentration_warning_band():
    """Sanity: defaults agree with core.research.concentration.report.WARNING_TOP1/TOP3,
    so the two subsystems share the same threshold even if they apply
    different policies."""
    from core.research.concentration.report import WARNING_TOP1, WARNING_TOP3
    assert DEFAULT_TOP1_CEILING == WARNING_TOP1
    assert DEFAULT_TOP3_CEILING == WARNING_TOP3
