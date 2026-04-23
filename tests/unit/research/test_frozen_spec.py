"""Tests for core/research/frozen_spec.py (Phase E-1 R4)."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.research.frozen_spec import (
    FeatureEntry,
    FrozenSpecError,
    FrozenStrategySpec,
)


# ── Minimal fixture for construction ─────────────────────────────────────────


def _minimal_kwargs(**overrides):
    base = dict(
        candidate_id="c1",
        strategy_version="test-v1",
        source_trial_id="abc123",
        feature_set=[FeatureEntry(name="feature_a", weight=1.0)],
        benchmark_relative_summary={"note": "direct", "ic": 0.03},
        oos_holdout_summary={"folds": 4},
        robustness_summary={"range": [0.3, 0.5]},
        decision_memo="/tmp/memo.md",
    )
    base.update(overrides)
    return base


# ── Mandatory field validation ───────────────────────────────────────────────


def test_all_mandatory_fields_present_succeeds():
    spec = FrozenStrategySpec(**_minimal_kwargs())
    assert spec.candidate_id == "c1"


def test_missing_candidate_id_rejected():
    with pytest.raises(FrozenSpecError, match="candidate_id"):
        FrozenStrategySpec(**_minimal_kwargs(candidate_id=""))


def test_invalid_strategy_version_rejected():
    """Version must match name-pattern."""
    with pytest.raises(FrozenSpecError, match="strategy_version"):
        FrozenStrategySpec(**_minimal_kwargs(strategy_version=""))
    with pytest.raises(FrozenSpecError, match="strategy_version"):
        FrozenStrategySpec(**_minimal_kwargs(strategy_version="x"))
    with pytest.raises(FrozenSpecError, match="strategy_version"):
        FrozenStrategySpec(**_minimal_kwargs(strategy_version="1234"))
    # Valid forms
    ok_vers = ["rcm-v1-2026-04-24", "strat_v2", "alpha.3", "mfs-2026"]
    for v in ok_vers:
        spec = FrozenStrategySpec(**_minimal_kwargs(strategy_version=v))
        assert spec.strategy_version == v


def test_empty_feature_set_rejected():
    with pytest.raises(FrozenSpecError, match="feature_set"):
        FrozenStrategySpec(**_minimal_kwargs(feature_set=[]))


def test_feature_set_must_contain_feature_entries():
    with pytest.raises(FrozenSpecError, match="feature_set"):
        FrozenStrategySpec(**_minimal_kwargs(
            feature_set=[{"name": "raw_dict"}]  # dict, not FeatureEntry
        ))


def test_source_trial_id_required():
    with pytest.raises(FrozenSpecError, match="source_trial_id"):
        FrozenStrategySpec(**_minimal_kwargs(source_trial_id=""))


def test_decision_memo_required():
    with pytest.raises(FrozenSpecError, match="decision_memo"):
        FrozenStrategySpec(**_minimal_kwargs(decision_memo=""))


def test_empty_summary_rejected():
    """Summaries must be non-empty (dict or non-empty string)."""
    for name in ("benchmark_relative_summary", "oos_holdout_summary",
                 "robustness_summary"):
        with pytest.raises(FrozenSpecError, match=name):
            FrozenStrategySpec(**_minimal_kwargs(**{name: {}}))
        with pytest.raises(FrozenSpecError, match=name):
            FrozenStrategySpec(**_minimal_kwargs(**{name: ""}))


def test_summary_accepts_str():
    """Summary fields accept markdown string (not only dict)."""
    spec = FrozenStrategySpec(**_minimal_kwargs(
        benchmark_relative_summary="Full paragraph narrative here.",
        oos_holdout_summary="OOS 4/4 folds positive.",
        robustness_summary="IR range 0.38-0.51.",
    ))
    assert isinstance(spec.benchmark_relative_summary, str)


# ── FeatureEntry ─────────────────────────────────────────────────────────────


def test_feature_entry_minimal():
    fe = FeatureEntry(name="x")
    assert fe.name == "x"
    assert fe.weight is None


def test_feature_entry_missing_name_raises():
    with pytest.raises(FrozenSpecError, match="name"):
        FeatureEntry.from_dict({"weight": 0.5})  # no name


def test_feature_entry_extras_preserved():
    """Unknown keys in a feature dict land in `extras` and survive round-trip."""
    fe = FeatureEntry.from_dict({
        "name": "x", "weight": 0.5, "family": "A",
        "custom_flag": True, "comment": "foo",
    })
    assert fe.extras == {"custom_flag": True, "comment": "foo"}
    d = fe.to_dict()
    assert d["custom_flag"] is True
    assert d["comment"] == "foo"


# ── YAML round-trip ──────────────────────────────────────────────────────────


def test_yaml_round_trip_minimal(tmp_path):
    spec = FrozenStrategySpec(**_minimal_kwargs())
    path = spec.to_yaml_file(tmp_path / "spec.yaml")
    assert path.exists()
    spec2 = FrozenStrategySpec.from_yaml_file(path)
    assert spec2.candidate_id == spec.candidate_id
    assert spec2.strategy_version == spec.strategy_version
    assert spec2.source_trial_id == spec.source_trial_id
    assert len(spec2.feature_set) == 1
    assert spec2.feature_set[0].name == "feature_a"


def test_yaml_round_trip_full(tmp_path):
    """Every optional field round-trips."""
    spec = FrozenStrategySpec(
        **_minimal_kwargs(
            strategy_type="composite",
            family="research",
            transforms={"std": "zscore"},
            composite_rule={"method": "weighted_sum"},
            labels={"horizon": 21},
            panel_contract={"n": 79},
            rebalance={"freq": "monthly"},
            weighting_rule="TBD",
            benchmark_definition={"primary": "SPY"},
            risk_overlay={"max": 0.35},
            cost_model_version="v1",
            alternative_weighting_variant={"equal": True},
            source={"trial_id": "abc123", "lineage_tag": "test"},
            research_evidence={"ic_ir": 0.5},
            notes="some note",
        ),
    )
    y = spec.to_yaml()
    spec2 = FrozenStrategySpec.from_yaml(y)
    assert spec2.strategy_type == "composite"
    assert spec2.family == "research"
    assert spec2.transforms == {"std": "zscore"}
    assert spec2.weighting_rule == "TBD"
    assert spec2.risk_overlay == {"max": 0.35}
    assert spec2.notes == "some note"


def test_from_yaml_nested_source_trial_id(tmp_path):
    """Tolerant to RCMv1-style nested `source.trial_id` layout."""
    yaml_text = """
candidate_id: c1
strategy_version: test-v1
# NOTE: no top-level source_trial_id
feature_set:
  - name: x
    weight: 1.0
benchmark_relative_summary:
  ic: 0.03
oos_holdout_summary:
  folds: 4
robustness_summary:
  range: [0.3, 0.5]
decision_memo: /tmp/m.md
source:
  trial_id: xyz789          # resolved from nested
  lineage_tag: test-lineage
"""
    spec = FrozenStrategySpec.from_yaml(yaml_text)
    assert spec.source_trial_id == "xyz789"


def test_unknown_top_level_keys_go_to_extras():
    yaml_text = """
candidate_id: c1
strategy_version: test-v1
source_trial_id: abc
feature_set:
  - name: x
benchmark_relative_summary: n/a
oos_holdout_summary: n/a
robustness_summary: n/a
decision_memo: m
future_extension_field: 42
another_unknown:
  nested: true
"""
    spec = FrozenStrategySpec.from_yaml(yaml_text)
    assert spec.extras == {
        "future_extension_field": 42,
        "another_unknown": {"nested": True},
    }


def test_from_yaml_rejects_non_mapping():
    with pytest.raises(FrozenSpecError, match="mapping"):
        FrozenStrategySpec.from_yaml("- a list\n- not a mapping")


def test_from_yaml_file_missing_raises(tmp_path):
    with pytest.raises(FrozenSpecError, match="not found"):
        FrozenStrategySpec.from_yaml_file(tmp_path / "does_not_exist.yaml")


# ── Real RCMv1 YAML ──────────────────────────────────────────────────────────


def test_loads_real_rcmv1_frozen_yaml():
    """The RCMv1 migration YAML must load cleanly and round-trip."""
    path = Path("data/research_candidates/rcm_v1_defensive_composite_01.yaml")
    if not path.exists():
        pytest.skip("RCMv1 frozen YAML not present (expected in repo)")
    spec = FrozenStrategySpec.from_yaml_file(path)
    assert spec.candidate_id == "rcm_v1_defensive_composite_01"
    assert spec.strategy_version == "rcm-v1-2026-04-24"
    assert spec.source_trial_id == "f24aefecc91a"
    assert len(spec.feature_set) == 4
    feat_names = {f.name for f in spec.feature_set}
    assert feat_names == {"beta_spy_60d", "drawup_from_252d_low",
                          "days_since_52w_high", "amihud_20d"}
    # Decision memo
    assert spec.decision_memo.endswith(".md")
    assert "rcm_v1_s1_candidate_memo" in spec.decision_memo
    # Summaries are dicts
    assert isinstance(spec.benchmark_relative_summary, dict)
    assert isinstance(spec.oos_holdout_summary, dict)
    assert isinstance(spec.robustness_summary, dict)
    # Round-trip preserves everything
    y = spec.to_yaml()
    spec2 = FrozenStrategySpec.from_yaml(y)
    assert spec2.candidate_id == spec.candidate_id
    assert len(spec2.feature_set) == len(spec.feature_set)
    assert spec2.source == spec.source
    assert spec2.research_evidence == spec.research_evidence
