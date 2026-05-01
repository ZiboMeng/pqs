"""Unit tests for core.research.anti_sibling_policy.

Coverage targets per cycle #05 yaml pre-registration:
- All tier outcomes: 1 / 1-conditional / 2 / 5
- All sibling pathways: factor-overlap hard-reject, factor-overlap=2 with
  active_core, factor-overlap=2 with non-active + conditional pass / fail
  (each of 4 conditions individually), NAV raw, NAV residual
- POLICY_VERSION gating
"""
from __future__ import annotations

import math

import pytest

from core.research.anti_sibling_policy import (
    ACTIVE_CORE_ANCHORS,
    ACTIVE_LEGACY_DECAY_ANCHORS,
    HISTORICAL_FAILED_ANCHORS,
    POLICY_VERSION,
    R41Result,
    assert_policy_version_matches,
    classify,
    get_anchor_status,
)


# ─── Fixtures ────────────────────────────────────────────────────────────


ANCHORS_DEFAULT = {
    "rcm_v1": ["beta_spy_60d", "drawup_from_252d_low", "days_since_52w_high",
               "amihud_20d"],
    "cand_2": ["ret_5d", "rs_vs_spy_126d", "hl_range"],
    "cycle_03_top": ["rs_vs_spy_126d", "drawup_from_252d_low", "market_vol_ratio"],
}


def _nav(rcm_raw=0.50, rcm_resid_spy=0.30, rcm_resid_qqq=0.30,
         cand_raw=0.50, cand_resid_spy=0.30, cand_resid_qqq=0.30,
         c3_raw=0.50, c3_resid_spy=0.30, c3_resid_qqq=0.30):
    """Build a complete NAV-correlation dict (low values = no sibling-by-NAV)."""
    return {
        "rcm_v1_pooled_pearson_raw": rcm_raw,
        "rcm_v1_pooled_pearson_residual_vs_spy": rcm_resid_spy,
        "rcm_v1_pooled_pearson_residual_vs_qqq": rcm_resid_qqq,
        "rcm_v1_n_overlap_days": 1000,
        "cand_2_pooled_pearson_raw": cand_raw,
        "cand_2_pooled_pearson_residual_vs_spy": cand_resid_spy,
        "cand_2_pooled_pearson_residual_vs_qqq": cand_resid_qqq,
        "cand_2_n_overlap_days": 1000,
        "cycle_03_top_pooled_pearson_raw": c3_raw,
        "cycle_03_top_pooled_pearson_residual_vs_spy": c3_resid_spy,
        "cycle_03_top_pooled_pearson_residual_vs_qqq": c3_resid_qqq,
        "cycle_03_top_n_overlap_days": 1000,
    }


METRICS_FP_HEALTHY = {"cum_ret": 1.50, "max_dd": -0.18, "sharpe": 1.20, "vs_qqq": 0.05}
METRICS_2025_HEALTHY = {"vs_qqq": 0.105, "vs_spy": 0.04, "max_dd": -0.19}

ANCHOR_DD_LOOKUP = {"rcm_v1": -0.25, "cand_2": -0.27, "cycle_03_top": -0.27}


# ─── Anchor status registry ─────────────────────────────────────────────


def test_active_core_empty_as_of_2026_05_01():
    """ACTIVE_CORE_ANCHORS is empty until Track A acceptance promotes one.
    Sentinel for CLAUDE.md inventory consistency."""
    assert ACTIVE_CORE_ANCHORS == ()


def test_legacy_decay_anchors_are_rcm_and_cand2():
    assert "rcm_v1" in ACTIVE_LEGACY_DECAY_ANCHORS
    assert "cand_2" in ACTIVE_LEGACY_DECAY_ANCHORS


def test_historical_failed_anchors_include_cycles_01_02_03():
    assert "cycle_01_top" in HISTORICAL_FAILED_ANCHORS
    assert "cycle_02_top" in HISTORICAL_FAILED_ANCHORS
    assert "cycle_03_top" in HISTORICAL_FAILED_ANCHORS


def test_get_anchor_status_dispatches_correctly():
    assert get_anchor_status("rcm_v1") == "active_legacy_decay"
    assert get_anchor_status("cand_2") == "active_legacy_decay"
    assert get_anchor_status("cycle_03_top") == "historical_failed"
    assert get_anchor_status("unknown_anchor") == "unknown"


# ─── Tier 1 (non-sibling) ────────────────────────────────────────────────


def test_tier1_factor_overlap_zero_clean_nav():
    """Candidate features fully orthogonal to all anchors + NAV clean → Tier 1."""
    feats = ["intraday_autocorr_21d", "block_trade_rate", "vwap_deviation"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(),
        candidate_metrics_full_period=METRICS_FP_HEALTHY,
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 1
    assert res.factor_overlap_max == 0
    assert res.sibling_by_factor_anchor is None
    assert res.sibling_by_nav_anchor is None
    assert res.policy_version == POLICY_VERSION


def test_tier1_factor_overlap_one_clean_nav():
    """One factor shared with rcm_v1 → still Tier 1 (overlap=1 < threshold)."""
    feats = ["beta_spy_60d", "intraday_vol_ratio_21d", "block_trade_rate"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(),
        candidate_metrics_full_period=METRICS_FP_HEALTHY,
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 1
    assert res.factor_overlap_max == 1


# ─── Tier 2 (sibling) ────────────────────────────────────────────────────


def test_tier2_factor_overlap_three_hard_reject():
    """3-factor identical match with cycle_03_top → hard reject."""
    feats = ["rs_vs_spy_126d", "drawup_from_252d_low", "market_vol_ratio"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(),
        candidate_metrics_full_period=METRICS_FP_HEALTHY,
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 2
    assert res.sibling_by_factor_anchor == "cycle_03_top"
    assert "hard-reject" in res.reason


def test_tier2_factor_overlap_two_with_active_core_hard_reject():
    """factor_overlap=2 with active_core anchor → hard reject (no conditional review)."""
    # Inject a synthetic active_core anchor
    anchors = dict(ANCHORS_DEFAULT)
    anchors["fleet_core_alpha_01"] = ["beta_spy_60d", "amihud_20d", "ret_5d"]

    # Patch active_core list at module level via a guard test fixture
    import core.research.anti_sibling_policy as policy
    original = policy.ACTIVE_CORE_ANCHORS
    policy.ACTIVE_CORE_ANCHORS = ("fleet_core_alpha_01",)
    try:
        feats = ["beta_spy_60d", "amihud_20d", "intraday_autocorr_21d"]
        res = classify(
            candidate_features=feats,
            anchor_features=anchors,
            nav_correlation=_nav(),
            candidate_metrics_full_period=METRICS_FP_HEALTHY,
            candidate_metrics_2025=METRICS_2025_HEALTHY,
            anchor_max_dd_lookup={**ANCHOR_DD_LOOKUP, "fleet_core_alpha_01": -0.15},
        )
        assert res.tier == 2
        assert res.sibling_by_factor_anchor == "fleet_core_alpha_01"
        assert "active_core" in res.reason
    finally:
        policy.ACTIVE_CORE_ANCHORS = original


def test_tier2_nav_raw_above_threshold_bypasses_factor_check():
    """raw_NAV >= 0.85 → Tier 2 even with overlap=0."""
    feats = ["intraday_autocorr_21d", "block_trade_rate", "vwap_deviation"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(rcm_raw=0.92),
        candidate_metrics_full_period=METRICS_FP_HEALTHY,
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 2
    assert res.sibling_by_nav_anchor == "rcm_v1"
    assert "raw_pearson" in res.reason


def test_tier2_nav_residual_above_threshold():
    """residual_NAV >= 0.70 → Tier 2 even with low raw."""
    feats = ["intraday_autocorr_21d", "block_trade_rate", "vwap_deviation"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(cand_resid_spy=0.75),
        candidate_metrics_full_period=METRICS_FP_HEALTHY,
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 2
    assert res.sibling_by_nav_anchor == "cand_2"
    assert "residual_pearson" in res.reason


# ─── Tier 1-conditional (the critical new path) ────────────────────────


def test_tier1_conditional_passes_all_four_checks():
    """Cycle #04 Cluster A trial 8 archetype: overlap=2 with rcm_v1 (drawup +
    amihud) + raw 0.66 + residual ~0.45 + max_dd -0.19 (better than rcm_v1
    -0.25) + 2025 vs_qqq +10.5%."""
    feats = ["drawup_from_252d_low", "amihud_20d", "intraday_autocorr_21d"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(rcm_raw=0.66, rcm_resid_spy=0.42, rcm_resid_qqq=0.45),
        candidate_metrics_full_period={"cum_ret": 1.20, "max_dd": -0.19,
                                        "sharpe": 1.10, "vs_qqq": 0.04},
        candidate_metrics_2025={"vs_qqq": 0.105, "vs_spy": 0.04, "max_dd": -0.19},
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == "1-conditional"
    assert res.sibling_by_factor_anchor == "rcm_v1"
    details = res.conditional_review_details
    assert details is not None
    assert details["all_pass"] is True
    assert details["anchor_status"] == "active_legacy_decay"
    for cname in ("c1_raw_nav", "c2_residual_nav", "c3_max_dd_strictly_better",
                  "c4_2025_qqq_strict_pass"):
        assert details["checks"][cname]["pass"] is True


def test_tier1_conditional_fails_c1_raw_nav():
    """raw_nav = 0.72 (above 0.70 threshold) → c1 fails → Tier 2."""
    feats = ["drawup_from_252d_low", "amihud_20d", "intraday_autocorr_21d"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(rcm_raw=0.72, rcm_resid_spy=0.42),
        candidate_metrics_full_period={"cum_ret": 1.20, "max_dd": -0.19,
                                        "vs_qqq": 0.04},
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 2
    assert res.conditional_review_details["all_pass"] is False
    assert res.conditional_review_details["checks"]["c1_raw_nav"]["pass"] is False
    assert "c1_raw_nav" in res.reason


def test_tier1_conditional_fails_c2_residual():
    """residual = 0.55 (above 0.50 threshold) → c2 fails → Tier 2."""
    feats = ["drawup_from_252d_low", "amihud_20d", "intraday_autocorr_21d"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(rcm_raw=0.66, rcm_resid_spy=0.55, rcm_resid_qqq=0.40),
        candidate_metrics_full_period={"cum_ret": 1.20, "max_dd": -0.19,
                                        "vs_qqq": 0.04},
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 2
    assert res.conditional_review_details["checks"]["c2_residual_nav"]["pass"] is False


def test_tier1_conditional_fails_c3_max_dd_not_strictly_better():
    """candidate max_dd = -0.25 = rcm_v1 max_dd → c3 fails (not strictly better)."""
    feats = ["drawup_from_252d_low", "amihud_20d", "intraday_autocorr_21d"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(rcm_raw=0.66, rcm_resid_spy=0.42),
        candidate_metrics_full_period={"cum_ret": 1.20, "max_dd": -0.25,  # equals
                                        "vs_qqq": 0.04},
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 2
    assert res.conditional_review_details["checks"]["c3_max_dd_strictly_better"]["pass"] is False


def test_tier1_conditional_fails_c4_2025_qqq_zero_or_negative():
    """2025 vs_qqq = 0.0 → c4 fails (strict > 0)."""
    feats = ["drawup_from_252d_low", "amihud_20d", "intraday_autocorr_21d"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(rcm_raw=0.66, rcm_resid_spy=0.42),
        candidate_metrics_full_period={"cum_ret": 1.20, "max_dd": -0.19,
                                        "vs_qqq": 0.04},
        candidate_metrics_2025={"vs_qqq": 0.0, "vs_spy": 0.04, "max_dd": -0.19},
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 2
    assert res.conditional_review_details["checks"]["c4_2025_qqq_strict_pass"]["pass"] is False


def test_tier1_conditional_fails_when_2025_metrics_missing():
    """No 2025 metrics → c4 auto-fails."""
    feats = ["drawup_from_252d_low", "amihud_20d", "intraday_autocorr_21d"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(rcm_raw=0.66, rcm_resid_spy=0.42),
        candidate_metrics_full_period={"cum_ret": 1.20, "max_dd": -0.19,
                                        "vs_qqq": 0.04},
        candidate_metrics_2025=None,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 2
    assert res.conditional_review_details["checks"]["c4_2025_qqq_strict_pass"]["pass"] is False


def test_tier1_conditional_fails_when_anchor_max_dd_missing():
    """No anchor_max_dd_lookup → c3 auto-fails (degenerate strict mode)."""
    feats = ["drawup_from_252d_low", "amihud_20d", "intraday_autocorr_21d"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(rcm_raw=0.66, rcm_resid_spy=0.42),
        candidate_metrics_full_period={"cum_ret": 1.20, "max_dd": -0.19,
                                        "vs_qqq": 0.04},
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=None,
    )
    assert res.tier == 2
    assert res.conditional_review_details["checks"]["c3_max_dd_strictly_better"]["pass"] is False


def test_tier1_conditional_with_historical_anchor():
    """factor_overlap=2 with cycle_03_top (historical_failed) → conditional review path."""
    feats = ["rs_vs_spy_126d", "drawup_from_252d_low", "intraday_autocorr_21d"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(c3_raw=0.66, c3_resid_spy=0.42),
        candidate_metrics_full_period={"cum_ret": 1.20, "max_dd": -0.19,
                                        "vs_qqq": 0.04},
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    # Note: max_overlap may equal 2 with both cycle_03_top (rs_vs_spy + drawup)
    # AND rcm_v1 (drawup only = 1). cycle_03_top wins since overlap=2 > rcm_v1=1.
    assert res.tier == "1-conditional"
    assert res.sibling_by_factor_anchor == "cycle_03_top"
    assert res.conditional_review_details["anchor_status"] == "historical_failed"


# ─── Tier 5 (non-evaluable) ─────────────────────────────────────────────


def test_tier5_cum_ret_nan():
    feats = ["intraday_autocorr_21d", "block_trade_rate", "vwap_deviation"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(),
        candidate_metrics_full_period={"cum_ret": float("nan"), "max_dd": -0.19},
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 5
    assert "non-evaluable" in res.reason


def test_tier5_cum_ret_none():
    feats = ["intraday_autocorr_21d"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(),
        candidate_metrics_full_period={"cum_ret": None},
        candidate_metrics_2025=None,
        anchor_max_dd_lookup=None,
    )
    assert res.tier == 5


# ─── Edge / boundary ─────────────────────────────────────────────────────


def test_residual_uses_max_across_spy_and_qqq():
    """residual_max should take max across vs_spy and vs_qqq separately."""
    feats = ["intraday_autocorr_21d"]
    # vs_spy low, vs_qqq high → should still trigger sibling-by-NAV
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(rcm_resid_spy=0.30, rcm_resid_qqq=0.78),
        candidate_metrics_full_period=METRICS_FP_HEALTHY,
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 2
    assert res.sibling_by_nav_anchor == "rcm_v1"


def test_nan_pearson_treated_as_missing():
    """NaN Pearson values must be filtered, not treated as 0."""
    feats = ["intraday_autocorr_21d"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(rcm_raw=float("nan"), cand_raw=0.50, c3_raw=0.50),
        candidate_metrics_full_period=METRICS_FP_HEALTHY,
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    assert res.tier == 1  # no sibling-by-NAV from NaN
    assert res.raw_pearson_max == 0.50


def test_to_dict_serializable():
    feats = ["intraday_autocorr_21d"]
    res = classify(
        candidate_features=feats,
        anchor_features=ANCHORS_DEFAULT,
        nav_correlation=_nav(),
        candidate_metrics_full_period=METRICS_FP_HEALTHY,
        candidate_metrics_2025=METRICS_2025_HEALTHY,
        anchor_max_dd_lookup=ANCHOR_DD_LOOKUP,
    )
    d = res.to_dict()
    assert d["policy_version"] == POLICY_VERSION
    assert d["tier"] == 1
    import json
    json.dumps(d)  # must be JSON-serializable


# ─── POLICY_VERSION gating ──────────────────────────────────────────────


def test_assert_policy_version_matches_pass():
    assert_policy_version_matches(POLICY_VERSION)


def test_assert_policy_version_matches_raises_on_mismatch():
    with pytest.raises(ValueError, match="POLICY_VERSION"):
        assert_policy_version_matches("v1.0_cycle04_legacy")


def test_policy_version_format():
    """POLICY_VERSION should be a non-empty string with date-like suffix
    so changes are visible in PR diffs."""
    assert isinstance(POLICY_VERSION, str)
    assert len(POLICY_VERSION) > 5
    assert "2026" in POLICY_VERSION or "2027" in POLICY_VERSION  # forward compat
