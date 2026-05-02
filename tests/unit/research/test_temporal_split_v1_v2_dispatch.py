"""Tests for v1↔v2 temporal_split dispatch logic.

Phase C-PRD-1 follow-up (post-ship gap fix). Per
``docs/memos/20260501-diversifier_role_decision.md``:

- role=diversifier AND freeze_date >= 2026-05-01  → v2 (PRD §6.2 thresholds)
- everything else                                 → v1 (legacy contract)

Why v1 must remain default for non-diversifier roles:
  cycle04+05 archived trials' yaml hashes are pinned to v1; modifying
  default would invalidate those audit trails. RCMv1+Cand-2 legacy
  candidates also operate under v1 contract.

Why role-aware (not just date-aware):
  v2 only modifies diversifier role; routing other roles to v2 would
  pollute audit trail without semantic effect. Conservative dispatch.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from core.research.temporal_split import (
    _DEFAULT_PATH,
    _DEFAULT_PATH_V2,
    _V2_DISPATCH_CUTOFF,
    load_temporal_split,
    resolve_split_path,
)


PROJ = Path(__file__).resolve().parent.parent.parent.parent


# ---------------------------------------------------------------------------
# Cutoff date contract
# ---------------------------------------------------------------------------


def test_cutoff_is_2026_05_01():
    """v2 cutoff is locked to 2026-05-01 per decision memo."""
    assert _V2_DISPATCH_CUTOFF == date(2026, 5, 1)


def test_v1_yaml_exists():
    assert _DEFAULT_PATH.exists(), f"v1 yaml missing at {_DEFAULT_PATH}"


def test_v2_yaml_exists():
    assert _DEFAULT_PATH_V2.exists(), f"v2 yaml missing at {_DEFAULT_PATH_V2}"


# ---------------------------------------------------------------------------
# Dispatch policy: role × freeze_date matrix
# ---------------------------------------------------------------------------


def test_diversifier_post_cutoff_routes_to_v2():
    """role=diversifier + freeze_date >= 2026-05-01 → v2."""
    p = resolve_split_path(role="diversifier", freeze_date=date(2026, 5, 1))
    assert p == _DEFAULT_PATH_V2


def test_diversifier_post_v2_pre_v3_routes_to_v2():
    """role=diversifier + freeze_date in [2026-05-01, 2026-05-02) → v2."""
    # 2026-05-01 is in v2 window (post-v2-cutoff, pre-v3-cutoff).
    # 2026-05-02 onward routes to v3 (test below).
    p = resolve_split_path(role="diversifier", freeze_date=date(2026, 5, 1))
    assert p == _DEFAULT_PATH_V2


def test_diversifier_post_v3_routes_to_v3():
    """role=diversifier + freeze_date >= 2026-05-02 → v3 (QQQ deprecated).

    Per docs/memos/20260502-qqq_benchmark_deprecation.md: v3 dispatch
    cutoff at 2026-05-02; takes precedence over v2 for both core and
    diversifier roles.
    """
    from core.research.temporal_split import _DEFAULT_PATH_V3
    p = resolve_split_path(role="diversifier", freeze_date=date(2027, 1, 1))
    assert p == _DEFAULT_PATH_V3


def test_diversifier_pre_cutoff_routes_to_v1():
    """role=diversifier + freeze_date < 2026-05-01 → v1.

    Why: pre-cutoff diversifier candidates (none exist as of ship date,
    but defensively handled) bound to v1 contract for archive immutability.
    """
    p = resolve_split_path(role="diversifier", freeze_date=date(2026, 4, 30))
    assert p == _DEFAULT_PATH


def test_diversifier_no_freeze_date_routes_to_v1():
    """role=diversifier + freeze_date=None → v1 (conservative default).

    Rationale: missing freeze_date defaults to legacy v1 contract; v2
    requires positive evidence (explicit post-cutoff freeze_date) to opt in.
    """
    p = resolve_split_path(role="diversifier", freeze_date=None)
    assert p == _DEFAULT_PATH


def test_core_post_cutoff_routes_to_v1():
    """role=core + freeze_date >= 2026-05-01 → v1.

    v2 only modifies diversifier role; core gates unchanged. Routing
    core to v2 would change nothing semantically but pollute audit trail.
    """
    p = resolve_split_path(role="core", freeze_date=date(2026, 5, 1))
    assert p == _DEFAULT_PATH


def test_core_pre_cutoff_routes_to_v1():
    """role=core + freeze_date < 2026-05-01 → v1."""
    p = resolve_split_path(role="core", freeze_date=date(2026, 1, 1))
    assert p == _DEFAULT_PATH


def test_legacy_decay_verification_routes_to_v1():
    """role=legacy_decay_verification → always v1 (RCMv1 + Cand-2 contract).

    Even with post-cutoff freeze_date (e.g. backfilled), legacy candidates
    remain on v1 since they predate the v2 evidence base.
    """
    p_pre = resolve_split_path(
        role="legacy_decay_verification",
        freeze_date=date(2026, 4, 24),  # RCMv1 actual freeze
    )
    p_post = resolve_split_path(
        role="legacy_decay_verification",
        freeze_date=date(2026, 5, 15),  # hypothetical backfill
    )
    assert p_pre == _DEFAULT_PATH
    assert p_post == _DEFAULT_PATH


def test_risk_control_routes_to_v1():
    """role=risk_control → v1 (v2 only updated diversifier)."""
    p = resolve_split_path(
        role="risk_control",
        freeze_date=date(2026, 6, 1),
    )
    assert p == _DEFAULT_PATH


# ---------------------------------------------------------------------------
# Path injection (for testing / hermetic eval)
# ---------------------------------------------------------------------------


def test_v1_path_override_used_when_provided(tmp_path: Path):
    """Caller-provided v1_path overrides the default."""
    fake_v1 = tmp_path / "fake_v1.yaml"
    fake_v1.write_text("dummy: 1\n")
    p = resolve_split_path(
        role="core",
        freeze_date=date(2026, 1, 1),
        v1_path=fake_v1,
    )
    assert p == fake_v1


def test_v2_path_override_used_when_provided(tmp_path: Path):
    """Caller-provided v2_path overrides the default."""
    fake_v2 = tmp_path / "fake_v2.yaml"
    fake_v2.write_text("dummy: 2\n")
    p = resolve_split_path(
        role="diversifier",
        freeze_date=date(2026, 5, 1),
        v2_path=fake_v2,
    )
    assert p == fake_v2


# ---------------------------------------------------------------------------
# Fail-closed when target yaml missing
# ---------------------------------------------------------------------------


def test_v2_dispatch_fails_when_v2_missing(tmp_path: Path):
    """Diversifier in v2 window (pre-v3-cutoff) with missing v2 raises FileNotFoundError."""
    missing_v2 = tmp_path / "nonexistent_v2.yaml"
    # Use date in [2026-05-01, 2026-05-02) — v2 window, before v3 cutoff
    with pytest.raises(FileNotFoundError, match="v2 dispatch requested"):
        resolve_split_path(
            role="diversifier",
            freeze_date=date(2026, 5, 1),
            v2_path=missing_v2,
        )


def test_v3_dispatch_fails_when_v3_missing(tmp_path: Path):
    """Core/diversifier post-v3-cutoff with missing v3 raises FileNotFoundError."""
    missing_v3 = tmp_path / "nonexistent_v3.yaml"
    with pytest.raises(FileNotFoundError, match="v3 dispatch requested"):
        resolve_split_path(
            role="core",
            freeze_date=date(2026, 6, 1),
            v3_path=missing_v3,
        )


def test_v1_dispatch_fails_when_v1_missing(tmp_path: Path):
    """Non-diversifier dispatch with missing v1 yaml raises FileNotFoundError."""
    missing_v1 = tmp_path / "nonexistent_v1.yaml"
    with pytest.raises(FileNotFoundError, match="v1 dispatch requested"):
        resolve_split_path(
            role="core",
            freeze_date=date(2026, 1, 1),
            v1_path=missing_v1,
        )


# ---------------------------------------------------------------------------
# End-to-end: dispatch + load yields role-correct config
# ---------------------------------------------------------------------------


def test_diversifier_v2_dispatch_loads_v2_thresholds():
    """End-to-end: dispatch + load gives v2 split_name + diversifier thresholds.

    v2 window = [2026-05-01, 2026-05-02). Trial 9 (freeze_date 2026-05-04)
    is now post-v3-cutoff so this test uses the v2 window edge date.

    v2 yaml must have:
      - split_name == "alternating_regime_holdout_v2"
      - diversifier role with PRD §6.2 thresholds (NAV-level corrs, 0/1
        factor overlap, non-equity ≥15%)
    """
    p = resolve_split_path(role="diversifier", freeze_date=date(2026, 5, 1))
    cfg = load_temporal_split(p)
    assert cfg.split_name == "alternating_regime_holdout_v2"
    assert "diversifier" in cfg.roles
    div_role = cfg.roles["diversifier"]
    field_names = {c.field for c in div_role.eligibility_constraint}
    # v2-specific eligibility fields (NAV-level, PRD §6.2)
    assert "nav_corr_raw_max_vs_anchors" in field_names
    assert "nav_corr_residual_max_vs_anchors" in field_names
    assert "factor_overlap_with_active_core" in field_names
    assert "non_equity_weight_avg" in field_names


def test_diversifier_v3_dispatch_loads_v3_with_qqq_diagnostic():
    """End-to-end: post-v3-cutoff diversifier loads v3 with QQQ deprecated.

    v3 yaml must have:
      - split_name == "alternating_regime_holdout_v3"
      - validation_year_pass.excess_vs_qqq_diagnostic_only == True
      - core role validation_gates: at least one diagnostic_only action
      - core role validation_gates: at least one vs_spy kill_candidate
    """
    p = resolve_split_path(role="diversifier", freeze_date=date(2026, 5, 4))
    cfg = load_temporal_split(p)
    assert cfg.split_name == "alternating_regime_holdout_v3"
    assert cfg.acceptance.validation_year_pass.excess_vs_qqq_diagnostic_only is True
    # v3 core role: vs_qqq diagnostic_only, vs_spy kill_candidate (NEW)
    core_role = cfg.roles["core"]
    actions = {(g.field, g.action) for g in core_role.validation_gates}
    assert ("validation.2025.excess_vs_qqq", "diagnostic_only") in actions
    assert ("validation.2025.excess_vs_spy", "kill_candidate") in actions
    # v3 diversifier: vs_qqq diagnostic, vs_spy kill_candidate
    div_role = cfg.roles["diversifier"]
    div_actions = {(g.field, g.action) for g in div_role.validation_gates}
    assert ("validation.2025.excess_vs_qqq", "diagnostic_only") in div_actions
    assert ("validation.2025.excess_vs_spy", "kill_candidate") in div_actions
    assert ("full_period.excess_vs_qqq", "diagnostic_only") in div_actions
    assert ("full_period.excess_vs_spy", "kill_candidate") in div_actions


def test_legacy_decay_verification_post_v3_cutoff_still_v1():
    """legacy_decay_verification stays on v1 even post-v3-cutoff.

    v3 dispatch is gated on role IN {core, diversifier}; legacy and
    risk_control are excluded by design (they predate the new framework
    and do not re-evaluate against new gates).
    """
    p = resolve_split_path(
        role="legacy_decay_verification",
        freeze_date=date(2027, 1, 1),  # well past v3 cutoff
    )
    assert p == _DEFAULT_PATH


def test_risk_control_post_v3_cutoff_still_v1():
    """risk_control stays on v1 even post-v3-cutoff (rule-based, not mined)."""
    p = resolve_split_path(
        role="risk_control",
        freeze_date=date(2027, 1, 1),
    )
    assert p == _DEFAULT_PATH


def test_core_v1_dispatch_loads_v1_split_name():
    """End-to-end: core role loads v1 (split_name v1)."""
    p = resolve_split_path(role="core", freeze_date=date(2026, 5, 1))
    cfg = load_temporal_split(p)
    assert cfg.split_name == "alternating_regime_holdout_v1"


def test_legacy_decay_verification_loads_v1():
    """End-to-end: legacy_decay_verification → v1 (RCMv1+Cand-2 contract)."""
    p = resolve_split_path(
        role="legacy_decay_verification",
        freeze_date=date(2026, 4, 24),
    )
    cfg = load_temporal_split(p)
    assert cfg.split_name == "alternating_regime_holdout_v1"


# ---------------------------------------------------------------------------
# Boundary: cutoff day exactly
# ---------------------------------------------------------------------------


def test_diversifier_exactly_on_cutoff_routes_to_v2():
    """Inclusive boundary: freeze_date == 2026-05-01 → v2 (>= comparison)."""
    p = resolve_split_path(role="diversifier", freeze_date=date(2026, 5, 1))
    assert p == _DEFAULT_PATH_V2


def test_diversifier_one_day_before_cutoff_routes_to_v1():
    """Exclusive lower bound: 2026-04-30 → v1."""
    p = resolve_split_path(role="diversifier", freeze_date=date(2026, 4, 30))
    assert p == _DEFAULT_PATH
