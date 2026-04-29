"""Tests for core.research.temporal_split.

PRD: docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
Step A.1 (loader/validator) — Step A.5 leak-detection tests are wired
to the mining + acceptance pipeline (later commits).

These tests cover schema validation only; pipeline-integration leak
tests are in test_temporal_split_leak_detection.py (Step A.5).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.research.temporal_split import (
    TemporalSplitConfig,
    compute_split_sha256,
    expand_year_ranges,
    load_temporal_split,
)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_YAML = REPO_ROOT / "config" / "temporal_split.yaml"


# ---------------------------------------------------------------------------
# Round-trip validation on the actual repository config
# ---------------------------------------------------------------------------


def test_load_default_config_succeeds():
    """The shipped config/temporal_split.yaml must parse and validate."""
    cfg = load_temporal_split()
    assert isinstance(cfg, TemporalSplitConfig)
    assert cfg.split_name == "alternating_regime_holdout_v1"
    assert cfg.locked_after_first_use is True
    assert "core" in cfg.roles


def test_default_config_has_2025_hard_gate_in_core():
    """M2: core role must hard-gate 2025."""
    cfg = load_temporal_split()
    core = cfg.roles["core"]
    fields = {gate.field for gate in core.validation_gates}
    assert "validation.2025.excess_vs_qqq" in fields
    assert "validation.2025.maxdd" in fields


def test_default_config_diversifier_has_eligibility_constraints():
    """M6 C3: diversifier weak gate must have compensating constraints."""
    cfg = load_temporal_split()
    if "diversifier" not in cfg.roles:
        pytest.skip("diversifier role not in default config")
    div = cfg.roles["diversifier"]
    fields = {ec.field for ec in div.eligibility_constraint}
    assert "vs_existing_core_correlation" in fields
    assert "vs_existing_core_overlap" in fields


def test_default_config_has_purge_rules():
    """M4: purged label boundary must be present."""
    cfg = load_temporal_split()
    assert cfg.acceptance.purge_rules.label_horizon_days_max == 21
    assert cfg.acceptance.purge_rules.purge_at_split_boundary is True


def test_default_config_has_dividend_safety():
    """M8: dividend safety schema must be present (Track D enforces)."""
    cfg = load_temporal_split()
    ds = cfg.acceptance.dividend_safety
    assert ds.enforce_at == "track_d_promotion"
    assert ds.required_excess_margin_5yr == pytest.approx(0.04)


def test_default_config_has_split_level_sealed_lock():
    """Codex R20 B1: sealed ledger must have split-level fail-close."""
    cfg = load_temporal_split()
    ledger = cfg.audit.sealed_eval_ledger
    assert ledger.fail_closed_on_split_failure.role == "core"
    assert "split_name" in ledger.fail_closed_on_split_failure.key


def test_default_config_validation_years_have_manual_tags():
    """M9: every validation year must have manual_regime_tag set."""
    cfg = load_temporal_split()
    for vy in cfg.partition.validation_years:
        assert vy.manual_regime_tag, f"year {vy.year} missing manual_regime_tag"


def test_default_config_validation_years_auto_tags_null_at_draft():
    """M9: auto_classifier_tag is None at PRD draft time (filled by Step A.8)."""
    cfg = load_temporal_split()
    null_count = sum(1 for vy in cfg.partition.validation_years if vy.auto_classifier_tag is None)
    # Step A.8 hasn't run yet; expect all 5 to be None.
    assert null_count == len(cfg.partition.validation_years)


def test_default_config_2025_weight_is_double():
    """M2: 2025 has higher weight (2.0) than other validation years."""
    cfg = load_temporal_split()
    weights = {vy.year: vy.weight for vy in cfg.partition.validation_years}
    assert weights[2025] > max(w for y, w in weights.items() if y != 2025)


def test_default_config_factor_warmup_cap_is_504():
    """M3: 504-day max factor lookback (codex R19 #5)."""
    cfg = load_temporal_split()
    assert cfg.access_rules.factor_warmup_max_lookback_days == 504


def test_default_config_f1_floor_uses_max_formula():
    """Codex R20 Q1: F1 fork must floor at max(0.10, smoke.IR_p75)."""
    cfg = load_temporal_split()
    rules = cfg.acceptance.fork_criteria.rules
    f1_rule = next(r for r in rules if r.get("condition") == "F1_trigger")
    assert "max(0.10" in f1_rule["new_oos_ir_threshold_formula"]


# ---------------------------------------------------------------------------
# Cross-section invariants (disjoint partitions; stress slice sourcing)
# ---------------------------------------------------------------------------


def test_train_validation_sealed_disjoint_in_default():
    cfg = load_temporal_split()
    train = set()
    for entry in cfg.partition.train_years:
        if hasattr(entry, "range"):
            train.update(range(entry.range[0], entry.range[1] + 1))
        else:
            train.add(entry.year)
    validation = {vy.year for vy in cfg.partition.validation_years}
    sealed = {sy.year for sy in cfg.partition.sealed_test_years}
    assert not (train & validation)
    assert not (train & sealed)
    assert not (validation & sealed)


def test_stress_slices_source_from_train_years_in_default():
    cfg = load_temporal_split()
    train = set()
    for entry in cfg.partition.train_years:
        if hasattr(entry, "range"):
            train.update(range(entry.range[0], entry.range[1] + 1))
        else:
            train.add(entry.year)
    for slc in cfg.partition.stress_slices:
        assert slc.source_year in train, f"slice {slc.name} not in train"


# ---------------------------------------------------------------------------
# Schema rejection tests (extra fields / overlap / missing branches)
# ---------------------------------------------------------------------------


def _base_config_dict() -> dict:
    """Minimal valid temporal_split config for mutation tests."""
    return yaml.safe_load(DEFAULT_YAML.read_text())


def test_extra_field_at_top_level_rejected():
    raw = _base_config_dict()
    raw["unknown_field"] = "junk"
    with pytest.raises(ValidationError, match="extra"):
        TemporalSplitConfig.model_validate(raw)


def test_extra_field_in_validation_year_rejected():
    raw = _base_config_dict()
    raw["partition"]["validation_years"][0]["bonus_attribute"] = "x"
    with pytest.raises(ValidationError, match="extra"):
        TemporalSplitConfig.model_validate(raw)


def test_train_validation_overlap_rejected():
    raw = _base_config_dict()
    # 2025 is in validation; duplicate it into train as a {year: 2025} entry.
    raw["partition"]["train_years"].append({"year": 2025})
    with pytest.raises(ValidationError, match="overlap"):
        TemporalSplitConfig.model_validate(raw)


def test_validation_sealed_overlap_rejected():
    raw = _base_config_dict()
    # Add 2026 (sealed) to validation
    raw["partition"]["validation_years"].append(
        {"year": 2026, "manual_regime_tag": "test", "auto_classifier_tag": None, "weight": 1.0}
    )
    with pytest.raises(ValidationError, match="overlap"):
        TemporalSplitConfig.model_validate(raw)


def test_stress_slice_source_year_not_in_train_rejected():
    raw = _base_config_dict()
    raw["partition"]["stress_slices"][0]["source_year"] = 2019  # 2019 is validation
    raw["partition"]["stress_slices"][0]["start"] = "2019-02-15"
    raw["partition"]["stress_slices"][0]["end"] = "2019-04-30"
    with pytest.raises(ValidationError, match="source_year"):
        TemporalSplitConfig.model_validate(raw)


def test_stress_slice_dates_outside_source_year_rejected():
    raw = _base_config_dict()
    # Slice 2020 source but dates in 2019
    raw["partition"]["stress_slices"][0]["start"] = "2019-02-15"
    with pytest.raises(ValidationError, match="must both fall in source_year"):
        TemporalSplitConfig.model_validate(raw)


def test_role_gate_referencing_undeclared_validation_year_rejected():
    raw = _base_config_dict()
    raw["roles"]["core"]["validation_gates"][0]["field"] = "validation.2099.excess_vs_qqq"
    with pytest.raises(ValidationError, match="2099"):
        TemporalSplitConfig.model_validate(raw)


def test_missing_core_role_rejected():
    raw = _base_config_dict()
    del raw["roles"]["core"]
    with pytest.raises(ValidationError, match="must contain at least 'core'"):
        TemporalSplitConfig.model_validate(raw)


def test_fork_criteria_missing_f2_rejected():
    raw = _base_config_dict()
    rules = raw["acceptance"]["fork_criteria"]["rules"]
    # Drop the F2 rule
    raw["acceptance"]["fork_criteria"]["rules"] = [
        r for r in rules if r.get("condition") != "F2_trigger"
    ]
    # Pad with extra escalate to keep min_length=3
    raw["acceptance"]["fork_criteria"]["rules"].append({"condition": "escalate_dup", "if_else": True, "then": "x"})
    with pytest.raises(ValidationError, match="F2_trigger"):
        TemporalSplitConfig.model_validate(raw)


def test_factor_warmup_lookback_above_cap_rejected():
    raw = _base_config_dict()
    raw["access_rules"]["factor_warmup_max_lookback_days"] = 1500
    with pytest.raises(ValidationError):
        TemporalSplitConfig.model_validate(raw)


def test_sealed_test_mode_invalid_value_rejected():
    raw = _base_config_dict()
    raw["partition"]["sealed_test_years"][0]["mode"] = "multi_shot"
    with pytest.raises(ValidationError):
        TemporalSplitConfig.model_validate(raw)


# ---------------------------------------------------------------------------
# split_sha256 determinism + sensitivity
# ---------------------------------------------------------------------------


def test_split_sha256_is_deterministic():
    h1 = compute_split_sha256()
    h2 = compute_split_sha256()
    assert h1 == h2
    assert len(h1) == 64  # full hex SHA-256


def test_split_sha256_changes_with_content(tmp_path):
    """Mutating the YAML body changes the hash."""
    raw = _base_config_dict()
    yaml_path = tmp_path / "split.yaml"
    yaml_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    h1 = compute_split_sha256(yaml_path)

    # Change a meaningful field
    raw["acceptance"]["validation_year_pass"]["maxdd_per_year_max"] = 0.21
    yaml_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    h2 = compute_split_sha256(yaml_path)
    assert h1 != h2


def test_split_sha256_invariant_to_dict_key_reorder(tmp_path):
    """Dict key reorder doesn't change hash (canonicalization sorts keys)."""
    raw = _base_config_dict()
    p1 = tmp_path / "a.yaml"
    p2 = tmp_path / "b.yaml"
    # Write twice with different top-level key orders
    keys = list(raw.keys())
    reordered = {k: raw[k] for k in reversed(keys)}
    p1.write_text(yaml.safe_dump(raw, sort_keys=False))
    p2.write_text(yaml.safe_dump(reordered, sort_keys=False))
    assert compute_split_sha256(p1) == compute_split_sha256(p2)


def test_split_sha256_sensitive_to_list_reorder(tmp_path):
    """List order is preserved in canonicalization (per F PRD convention)."""
    raw = _base_config_dict()
    yaml_path = tmp_path / "split.yaml"
    yaml_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    h1 = compute_split_sha256(yaml_path)

    # Reverse validation_years list (semantically permissible reorder
    # but conservatively flagged — F PRD convention: lists encode order).
    raw["partition"]["validation_years"] = list(reversed(raw["partition"]["validation_years"]))
    yaml_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    h2 = compute_split_sha256(yaml_path)
    assert h1 != h2, "list reorder must change hash (conservative fail-closed)"


# ---------------------------------------------------------------------------
# expand_year_ranges utility
# ---------------------------------------------------------------------------


def test_expand_year_ranges_mixed():
    out = expand_year_ranges([{"range": [2009, 2012]}, {"year": 2020}, {"year": 2022}])
    assert out == [2009, 2010, 2011, 2012, 2020, 2022]


def test_expand_year_ranges_invalid_entry_rejected():
    with pytest.raises(ValueError, match="must have"):
        expand_year_ranges([{"junk": 1}])


def test_load_temporal_split_missing_file_raises(tmp_path):
    nonexistent = tmp_path / "no_such.yaml"
    with pytest.raises(FileNotFoundError):
        load_temporal_split(nonexistent)
