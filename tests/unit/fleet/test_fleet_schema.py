"""Track B Step 1 — fleet schema validation tests.

Pins the contract between config/fleet.yaml and FleetConfig: typos and
out-of-range values must fail closed at load time.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.fleet import (
    FleetAllocator,
    FleetCandidate,
    FleetConfig,
    FleetManifest,
    FleetRebalance,
    load_fleet_config,
    load_fleet_manifest,
    save_fleet_manifest,
)
from core.fleet.manifest_schema import ConcentrationSnapshot, FleetEvent


# ---------------------------------------------------------------------------
# FleetConfig — happy path + adversarial
# ---------------------------------------------------------------------------


def test_load_default_fleet_yaml_validates():
    """The shipped config/fleet.yaml must validate against FleetConfig."""
    cfg = load_fleet_config("config/fleet.yaml")
    assert cfg.split_policy == "equal_weight"
    assert len(cfg.candidates) >= 1
    assert cfg.max_pairwise_corr_warn < cfg.max_pairwise_corr_reject


def test_extra_key_in_yaml_fails_closed(tmp_path):
    """Codex round-13 extra='forbid' pattern: typo'd keys must be rejected.

    A real-world pre-fix bug class: ``max_pairwise_corr_warning`` (typo)
    silently disappears into the model and the operator's intent is lost.
    """
    bad = {
        "candidates": [{"candidate_id": "c1", "role": "core", "base_weight": 1.0}],
        "max_pairwise_corr_warning": 0.7,  # typo — should be _warn
    }
    p = tmp_path / "fleet.yaml"
    p.write_text(yaml.safe_dump(bad))
    with pytest.raises(ValidationError, match="extra"):
        load_fleet_config(p)


def test_dd_threshold_ordering_enforced():
    """warning < defensive < halt is structurally required."""
    with pytest.raises(ValidationError, match="strictly ordered"):
        FleetConfig(
            candidates=[FleetCandidate(candidate_id="c1", role="core", base_weight=1.0)],
            dd_throttle={"warning_pct": 0.20, "defensive_pct": 0.15, "halt_pct": 0.10,
                         "recovery_consecutive_days": 5, "rolling_window_days": 60},
        )


def test_corr_warn_must_be_below_reject():
    with pytest.raises(ValidationError, match="must be <"):
        FleetConfig(
            candidates=[FleetCandidate(candidate_id="c1", role="core", base_weight=1.0)],
            max_pairwise_corr_warn=0.85,
            max_pairwise_corr_reject=0.70,
        )


def test_duplicate_candidate_ids_fail_closed():
    with pytest.raises(ValidationError, match="duplicate candidate_id"):
        FleetConfig(
            candidates=[
                FleetCandidate(candidate_id="c1", role="core", base_weight=0.5),
                FleetCandidate(candidate_id="c1", role="satellite", base_weight=0.5),
            ],
        )


def test_base_weight_out_of_range_rejected():
    with pytest.raises(ValidationError):
        FleetCandidate(candidate_id="c1", role="core", base_weight=1.5)
    with pytest.raises(ValidationError):
        FleetCandidate(candidate_id="c1", role="core", base_weight=-0.1)


def test_unknown_role_rejected():
    with pytest.raises(ValidationError):
        FleetCandidate(candidate_id="c1", role="hedge", base_weight=0.5)


def test_unknown_split_policy_rejected():
    with pytest.raises(ValidationError):
        FleetConfig(
            candidates=[FleetCandidate(candidate_id="c1", role="core", base_weight=1.0)],
            split_policy="custom_voodoo",
        )


def test_core_min_zero_with_no_core_candidates_rejected():
    """If config sets core_min_capital_pct > 0 but only satellites exist, fail."""
    with pytest.raises(ValidationError, match="no core candidates"):
        FleetConfig(
            candidates=[FleetCandidate(candidate_id="s1", role="satellite", base_weight=1.0)],
            core_min_capital_pct=0.6,
        )


def test_load_missing_yaml_raises():
    with pytest.raises(FileNotFoundError):
        load_fleet_config("/nonexistent/fleet.yaml")


# ---------------------------------------------------------------------------
# FleetManifest schema
# ---------------------------------------------------------------------------


def test_manifest_schema_round_trip(tmp_path):
    manifest = FleetManifest(
        fleet_id="fleet_test_v1",
        candidates=[FleetCandidate(candidate_id="c1", role="core", base_weight=1.0)],
        rebalances=[
            FleetRebalance(
                rebalance_date=date(2026, 4, 29),
                candidate_weights={"c1": 1.0},
                fleet_weight_matrix_hash="a" * 16,
                throttle_factor=1.0,
                concentration_metrics=ConcentrationSnapshot(
                    m12_top1_weight_max=0.18, m12_top3_weight_max=0.42,
                ),
            )
        ],
        created_at_utc=datetime(2026, 4, 29, tzinfo=timezone.utc),
    )
    p = tmp_path / "manifest.json"
    save_fleet_manifest(manifest, p)
    assert p.exists()
    loaded = load_fleet_manifest(p)
    assert loaded.fleet_id == "fleet_test_v1"
    assert loaded.rebalances[0].rebalance_date == date(2026, 4, 29)
    assert loaded.rebalances[0].candidate_weights == {"c1": 1.0}


def test_load_manifest_missing_returns_none(tmp_path):
    p = tmp_path / "nonexistent.json"
    assert load_fleet_manifest(p) is None


def test_manifest_extra_key_rejected(tmp_path):
    """Same forbid-extra discipline applies to the manifest schema."""
    p = tmp_path / "manifest.json"
    bad = {
        "fleet_id": "f1",
        "schema_version": "1.0",
        "candidates": [{"candidate_id": "c1", "role": "core", "base_weight": 1.0}],
        "rebalances": [],
        "created_at_utc": "2026-04-29T00:00:00+00:00",
        "extra_field_typo": "should_reject",
    }
    import json
    p.write_text(json.dumps(bad))
    with pytest.raises(ValidationError):
        load_fleet_manifest(p)


def test_rebalance_weight_out_of_range_rejected():
    with pytest.raises(ValidationError, match="out of"):
        FleetRebalance(
            rebalance_date=date(2026, 4, 29),
            candidate_weights={"c1": 1.5},
            fleet_weight_matrix_hash="a" * 16,
            throttle_factor=1.0,
            concentration_metrics=ConcentrationSnapshot(
                m12_top1_weight_max=0.18, m12_top3_weight_max=0.42,
            ),
        )


def test_rebalance_event_unknown_category_rejected():
    with pytest.raises(ValidationError):
        FleetEvent(category="unknown_event", severity="info")


# ---------------------------------------------------------------------------
# FleetAllocator skeleton — methods raise NotImplementedError until step lands
# ---------------------------------------------------------------------------


def test_allocator_constructed_from_config():
    cfg = load_fleet_config("config/fleet.yaml")
    alloc = FleetAllocator(cfg)
    assert alloc.config is cfg


def test_allocator_rejects_non_config_input():
    with pytest.raises(TypeError, match="FleetConfig"):
        FleetAllocator({"candidates": []})  # raw dict not allowed


def test_step2_method_now_implemented():
    """Step 2 landed: compute_capital_split returns a dict."""
    cfg = load_fleet_config("config/fleet.yaml")
    alloc = FleetAllocator(cfg)
    result = alloc.compute_capital_split()
    assert isinstance(result, dict)
    assert sum(result.values()) == pytest.approx(1.0)


def test_step3_method_now_implemented():
    """Step 3 landed: compose_weight_matrix accepts a non-empty dict and
    returns a DataFrame."""
    import pandas as pd
    cfg = load_fleet_config("config/fleet.yaml")
    alloc = FleetAllocator(cfg)
    cw = {
        "rcm_v1_defensive_composite_01": pd.DataFrame(
            {"AAPL": [1.0]}, index=pd.to_datetime(["2026-01-02"])
        ),
        "candidate_2_orthogonal_01": pd.DataFrame(
            {"AAPL": [1.0]}, index=pd.to_datetime(["2026-01-02"])
        ),
    }
    fleet = alloc.compose_weight_matrix(cw)
    assert isinstance(fleet, pd.DataFrame)


def test_step4_methods_now_implemented():
    """Step 4 landed: compute_concentration_metrics + apply_overlap_throttle."""
    import pandas as pd
    cfg = load_fleet_config("config/fleet.yaml")
    alloc = FleetAllocator(cfg)
    fleet = pd.DataFrame({"AAPL": [0.10]}, index=["2026-01-02"])
    m = alloc.compute_concentration_metrics(fleet)
    assert "m12_top1_weight_max" in m
    trimmed, events = alloc.apply_overlap_throttle(fleet)
    assert isinstance(trimmed, pd.DataFrame)
    assert isinstance(events, list)


def test_steps_5_to_8_explicitly_frozen():
    """Codex R21 boundary: steps 5-9 must remain NotImplementedError until
    explicit-go. Test pins this invariant — accidental partial implementation
    of frozen steps fails this test."""
    cfg = load_fleet_config("config/fleet.yaml")
    alloc = FleetAllocator(cfg)
    with pytest.raises(NotImplementedError, match="frozen"):
        alloc.check_correlation_budget(None)
    with pytest.raises(NotImplementedError, match="frozen"):
        alloc.apply_dd_throttle(None)
    with pytest.raises(NotImplementedError, match="frozen"):
        alloc.observe(date(2026, 4, 29))


# ---------------------------------------------------------------------------
# Audit D7 regression (2026-04-29 R2) — manual_overrides sum at config-load
# ---------------------------------------------------------------------------


def test_manual_overrides_sum_validated_at_config_load():
    """D7: catching sum != 1.0 at config-load (not first compute_capital_split
    call) gives the operator a clear startup error."""
    with pytest.raises(ValidationError, match="sum.*base_weight"):
        FleetConfig(
            candidates=[
                FleetCandidate(candidate_id="c1", role="core", base_weight=0.6),
                FleetCandidate(candidate_id="c2", role="core", base_weight=0.6),  # sum=1.2
            ],
            split_policy="manual_overrides",
        )


def test_equal_weight_does_not_validate_base_weight_sum():
    """For equal_weight, base_weight is ignored; sum != 1.0 must NOT trigger
    the manual_overrides validator."""
    cfg = FleetConfig(
        candidates=[
            FleetCandidate(candidate_id="c1", role="core", base_weight=0.9),
            FleetCandidate(candidate_id="c2", role="core", base_weight=0.9),
        ],
        split_policy="equal_weight",
    )
    assert cfg.split_policy == "equal_weight"


def test_manual_overrides_within_float_tolerance_accepted():
    """1/3 + 1/3 + 1/3 = 0.9999...9 — must accept within 1e-9 tolerance."""
    cfg = FleetConfig(
        candidates=[
            FleetCandidate(candidate_id="c1", role="core", base_weight=1/3),
            FleetCandidate(candidate_id="c2", role="core", base_weight=1/3),
            FleetCandidate(candidate_id="c3", role="core", base_weight=1/3),
        ],
        split_policy="manual_overrides",
    )
    assert len(cfg.candidates) == 3
