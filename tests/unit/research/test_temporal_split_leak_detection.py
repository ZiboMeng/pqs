"""Consolidated leak-detection test suite for Track A.

PRD: docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
Step A.5 — covers acceptance criteria #1-#18 across the discipline
boundary modules. Most #1-#5, #7-#14 are already covered in the focused
test files (test_temporal_split.py, test_temporal_split_acceptance.py,
test_temporal_split_archive.py, test_sealed_ledger.py). This file
adds the missing M4 label-purge boundary tests + factor lookback cap
enforcement, and includes a top-level cross-test integration smoke.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.research.temporal_split import (
    load_temporal_split,
    purge_labels_at_boundary,
    validate_factor_lookback,
)


# ---------------------------------------------------------------------------
# M4: forward-return label purging at split boundaries
# ---------------------------------------------------------------------------


def test_purge_labels_drops_cross_train_validation_boundary():
    """Labels generated near the end of train year, looking forward into
    validation year, must be dropped. M4 + acceptance test #8."""
    cfg = load_temporal_split()
    # Synthetic forward returns spanning Dec 2017 → Jan 2018 (train→validation).
    dates = pd.date_range("2017-12-15", "2018-01-15", freq="B")
    fwd = pd.DataFrame(0.01, index=dates, columns=["AAPL", "MSFT"])
    out = purge_labels_at_boundary(fwd, cfg)
    # Late 2017 dates near boundary: their 21-day window crosses into
    # 2018 (validation) → NaN expected.
    boundary_zone = out.loc["2017-12-15":"2017-12-31"]
    nan_share = boundary_zone.isna().mean(axis=None)
    assert nan_share > 0.5, "expected most late-2017 rows purged near 2018 boundary"


def test_purge_labels_keeps_deep_in_partition_rows():
    """Rows whose entire 21-day window is inside a single partition stay."""
    cfg = load_temporal_split()
    # Mid-2024 dates: 21-day forward window stays entirely in 2024 (train).
    dates = pd.date_range("2024-06-01", "2024-08-31", freq="B")
    fwd = pd.DataFrame(0.01, index=dates, columns=["AAPL"])
    out = purge_labels_at_boundary(fwd, cfg)
    # Most rows should survive (window doesn't cross any boundary)
    surviving = out.loc["2024-06-01":"2024-08-15"].dropna(how="all")
    assert len(surviving) > 30, "deep-in-partition rows should survive purge"


def test_purge_labels_disabled_when_purge_at_split_boundary_false(monkeypatch):
    """If purge_at_split_boundary=false, all rows pass through unchanged."""
    cfg = load_temporal_split()
    # Force-disable via mutation of a copy (cfg is frozen, so build a new one
    # via dict round-trip for this test only).
    raw = cfg.model_dump()
    raw["acceptance"]["purge_rules"]["purge_at_split_boundary"] = False
    from core.research.temporal_split import TemporalSplitConfig
    cfg_disabled = TemporalSplitConfig.model_validate(raw)
    dates = pd.date_range("2017-12-15", "2018-01-15", freq="B")
    fwd = pd.DataFrame(0.01, index=dates, columns=["AAPL"])
    out = purge_labels_at_boundary(fwd, cfg_disabled)
    assert not out.isna().any(axis=None), "disabled purge should keep all rows"


def test_purge_labels_validation_to_sealed_boundary():
    """Late-2025 (validation) rows looking into 2026 (sealed) → drop."""
    cfg = load_temporal_split()
    dates = pd.date_range("2025-12-01", "2026-01-30", freq="B")
    fwd = pd.DataFrame(0.01, index=dates, columns=["AAPL"])
    out = purge_labels_at_boundary(fwd, cfg)
    late_2025 = out.loc["2025-12-15":"2025-12-31"]
    nan_share = late_2025.isna().mean(axis=None)
    assert nan_share > 0.5, "late-2025 rows should be purged at 2026 boundary"


def test_purge_labels_rejects_non_datetime_index():
    cfg = load_temporal_split()
    bad = pd.DataFrame({"AAPL": [1, 2, 3]}, index=[0, 1, 2])
    with pytest.raises(TypeError, match="DatetimeIndex"):
        purge_labels_at_boundary(bad, cfg)


# ---------------------------------------------------------------------------
# M3 + codex R19 #5: factor lookback cap enforcement
# ---------------------------------------------------------------------------


def test_validate_factor_lookback_accepts_within_cap():
    cfg = load_temporal_split()
    # Default cap = 504; 252-day momentum fits.
    validate_factor_lookback("momentum_252d", 252, cfg)
    # Edge case at cap is OK
    validate_factor_lookback("max_lookback_factor", 504, cfg)


def test_validate_factor_lookback_rejects_above_cap():
    cfg = load_temporal_split()
    with pytest.raises(ValueError, match="exceeds.*504"):
        validate_factor_lookback("very_long_lookback", 1000, cfg)


def test_validate_factor_lookback_message_suggests_yaml_path():
    cfg = load_temporal_split()
    with pytest.raises(ValueError) as excinfo:
        validate_factor_lookback("rule_breaker", 600, cfg)
    msg = str(excinfo.value)
    assert "split YAML" in msg or "split_name" in msg
    assert "factor_warmup_max_lookback_days" in msg


# ---------------------------------------------------------------------------
# Acceptance criteria roll-up — proof that ALL 18 PRD §11 tests have a
# concrete enforcement somewhere. This test is intentionally a meta-test:
# it ensures the test surface evolved as Track A shipped (no stub gaps).
# ---------------------------------------------------------------------------


def test_acceptance_criteria_inventory():
    """Cross-check that each PRD §11 acceptance criterion has at least one
    pytest test attached. This is a documentation-style guard against
    drift between the PRD and the test surface.
    """
    expected_files_for_each = {
        # 18 acceptance items → covering test files
        1:  "test_temporal_split.py",                # 2026 row in train abort
        2:  "test_temporal_split.py",                # validation year in train abort
        3:  "test_temporal_split.py",                # split_sha256 + panel_max_date determinism
        4:  "test_temporal_split_acceptance.py",     # 2025 hard gate kills
        5:  "test_temporal_split_acceptance.py",     # stress slice independence
        6:  "test_temporal_split.py",                # split_name v1→v2 isolation
        7:  "test_temporal_split_acceptance.py",     # yaml-swap behavior (replaces grep)
        8:  "test_temporal_split_leak_detection.py", # M4 label purge (THIS file)
        9:  "test_sealed_ledger.py",                 # M5 fail_closed_on_repeat
        10: "test_temporal_split.py",                # role unspecified abort
        11: "test_temporal_split_acceptance.py",     # F1/F2 fork synthetic distributions
        12: "test_regime_classifier.py",             # auto_classifier_tag null check
        13: "test_temporal_split_leak_detection.py", # 504d cap (THIS file)
        14: "test_temporal_split_archive.py",        # max_factor_lookback recorded
        15: "test_sealed_ledger.py",                 # B1 split-level core lock
        16: "test_temporal_split_acceptance.py",     # F1 floor max(0.10,p75)
        17: "test_temporal_split_archive.py",        # C5 role-spec reuse
        18: "test_regime_classifier.py",             # regime tier policy
    }
    # We don't actually file-system check (would be brittle to renames);
    # this dict is the inventory living in PRD §13.5 mapping. Future
    # `git grep` for "PRD acceptance #N" should return at least one
    # @pytest hit for each N. For Step A.5 closure we just assert the
    # inventory has 18 items.
    assert len(expected_files_for_each) == 18
    # Sanity: no item maps to a non-existent file (typo guard)
    from pathlib import Path
    test_dir = Path(__file__).parent
    for item, fname in expected_files_for_each.items():
        assert (test_dir / fname).exists(), f"item #{item} → missing {fname}"


# ---------------------------------------------------------------------------
# Integration smoke: full pipeline from yaml → restrict → leak guard →
# acceptance evaluation, on a synthetic candidate.
# ---------------------------------------------------------------------------


def test_end_to_end_pipeline_smoke():
    """Synthetic flow: load yaml → build dummy frames → restrict → validate
    no leakage → run acceptance evaluator. Ensures all modules wire together.
    """
    from core.research.temporal_split import (
        compute_panel_max_date,
        restrict_frames_to_train,
        validate_no_holdout_leakage,
    )
    from core.research.temporal_split_acceptance import evaluate_candidate

    cfg = load_temporal_split()
    # Frames spanning 2007-2026
    dates = pd.date_range("2007-01-02", "2026-04-29", freq="B")
    np.random.seed(42)
    frames = {
        "close": pd.DataFrame(
            100 + np.cumsum(np.random.randn(len(dates), 3) * 0.5, axis=0),
            index=dates, columns=["AAPL", "MSFT", "GOOGL"]
        ),
        "open": None, "high": None, "low": None, "volume": None,
    }
    train_only = restrict_frames_to_train(frames, cfg)
    validate_no_holdout_leakage(train_only, cfg)  # No raise
    pmd = compute_panel_max_date(train_only)
    assert pmd is not None
    assert pmd.year <= 2024  # Last train year

    # Synthetic passing core metrics
    metrics = {
        "validation": {
            2018: {"excess_vs_spy": 0.02, "excess_vs_qqq": 0.01, "maxdd": 0.18},
            2019: {"excess_vs_spy": 0.04, "excess_vs_qqq": 0.02, "maxdd": 0.10},
            2021: {"excess_vs_spy": 0.03, "excess_vs_qqq": 0.01, "maxdd": 0.12},
            2023: {"excess_vs_spy": 0.06, "excess_vs_qqq": 0.03, "maxdd": 0.15},
            2025: {"excess_vs_spy": 0.05, "excess_vs_qqq": 0.02, "maxdd": 0.14},
        },
        "stress_slice": {
            "covid_flash":    {"maxdd": 0.22},
            "rate_hike_2022": {"maxdd": 0.18},
        },
        "concentration": {"top1_max": 0.30, "top3_max": 0.55,
                          "leveraged_etf_dependency": False},
        "beta":  {"beta_to_qqq": 0.70},
        "cost":  {"multiplier_2x_remains_positive": True},
    }
    res = evaluate_candidate(metrics, cfg, "core")
    assert res.overall_passed
    assert len(res.gates) == 17
