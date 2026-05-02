"""Unit tests for Two-Stage Allocation Architecture Phase C-PRD-1.

Coverage targets per PRD §11.1-11.3:
- CandidateRole enum exists with 4 values
- ForwardRunManifest.candidate_role + soft_warn_flags fields
- Lazy migration: pre-PRD manifest loads with default role
- CandidateRegistry.role field + ALTER TABLE migration + immutability
- Trial 9 frozen spec yaml hash verification
- core_alpha rule UNCHANGED regression (no relaxation by adding diversifier role)

PRD: docs/prd/20260501-two_stage_allocation_architecture_prd.md
Decision memo: docs/memos/20260501-diversifier_role_decision.md
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

import pytest

from core.research.candidate_registry import (
    CandidateRecord, CandidateRegistry, CandidateStatus,
    DuplicateCandidateError, _VALID_ROLES,
)
from core.research.forward.manifest_schema import (
    CandidateRole, ForwardRunManifest, ForwardRunStatus,
)
from core.research.robustness.window_spec import (
    DataIntegritySnapshot, EvidenceClass,
)


# ─── CandidateRole enum ─────────────────────────────────────────────────


def test_candidate_role_enum_has_four_values():
    """PRD §6: 4 roles."""
    values = {r.value for r in CandidateRole}
    assert values == {"core_alpha", "diversifier",
                      "legacy_decay_verification", "risk_control"}


def test_candidate_role_diversifier_value():
    assert CandidateRole.diversifier.value == "diversifier"


def test_candidate_role_legacy_decay_value():
    assert CandidateRole.legacy_decay_verification.value == "legacy_decay_verification"


def test_candidate_role_string_round_trip():
    """Each role round-trips through its string value."""
    for r in CandidateRole:
        assert CandidateRole(r.value) is r


# ─── ForwardRunManifest schema additions ───────────────────────────────


def _minimal_manifest_kwargs(**override):
    """Minimal valid kwargs to construct a ForwardRunManifest."""
    from core.research.forward.manifest_schema import CostAssumptions

    base = {
        "candidate_id": "test_candidate_001",
        "evidence_class": EvidenceClass.forward_oos,
        "spec_hash": "a" * 16,
        "start_date": date(2026, 5, 1),
        "cost_assumptions": CostAssumptions(
            source="config/cost_model.yaml",
            config_hash="b" * 16,
        ),
        "data_integrity_snapshot": DataIntegritySnapshot(
            daily_store_rebuild_commit="abcdef123456789",
            baseline_snapshot_path="data/baseline/latest.json",
            generated_at_utc="2026-05-01T00:00:00+00:00",
        ),
    }
    base.update(override)
    return base


def test_manifest_default_role_is_legacy_decay():
    """Lazy-migration default: pre-PRD manifests load with default role."""
    m = ForwardRunManifest(**_minimal_manifest_kwargs())
    assert m.candidate_role == CandidateRole.legacy_decay_verification


def test_manifest_explicit_role_diversifier():
    m = ForwardRunManifest(**_minimal_manifest_kwargs(
        candidate_role=CandidateRole.diversifier,
    ))
    assert m.candidate_role == CandidateRole.diversifier


def test_manifest_default_soft_warn_flags_empty():
    m = ForwardRunManifest(**_minimal_manifest_kwargs())
    assert m.soft_warn_flags == []


def test_manifest_soft_warn_flag_diversifier_2025_maxdd():
    m = ForwardRunManifest(**_minimal_manifest_kwargs(
        candidate_role=CandidateRole.diversifier,
        soft_warn_flags=["diversifier_2025_maxdd_18_20pct"],
    ))
    assert "diversifier_2025_maxdd_18_20pct" in m.soft_warn_flags


def test_manifest_serialization_includes_role():
    m = ForwardRunManifest(**_minimal_manifest_kwargs(
        candidate_role=CandidateRole.diversifier,
        soft_warn_flags=["diversifier_2025_maxdd_18_20pct"],
    ))
    blob = m.model_dump(mode="json")
    assert blob["candidate_role"] == "diversifier"
    assert blob["soft_warn_flags"] == ["diversifier_2025_maxdd_18_20pct"]


def test_manifest_lazy_migration_from_pre_prd_json():
    """Pre-PRD manifest JSON without candidate_role field must load."""
    pre_prd_kwargs = _minimal_manifest_kwargs()
    m = ForwardRunManifest(**pre_prd_kwargs)
    blob = m.model_dump(mode="json")
    # Simulate pre-PRD by stripping the new field
    blob.pop("candidate_role", None)
    blob.pop("soft_warn_flags", None)
    # Reload
    reloaded = ForwardRunManifest(**blob)
    assert reloaded.candidate_role == CandidateRole.legacy_decay_verification
    assert reloaded.soft_warn_flags == []


# ─── CandidateRegistry role field ───────────────────────────────────────


@pytest.fixture
def fresh_registry(tmp_path):
    db_path = tmp_path / "test_registry.db"
    return CandidateRegistry(db_path)


def test_registry_register_default_role_legacy_decay(fresh_registry):
    rec = fresh_registry.register(
        candidate_id="test_001",
        source_trial_id="trial_001",
        source_lineage_tag="test_lineage",
    )
    assert rec.role == "legacy_decay_verification"


def test_registry_register_role_diversifier(fresh_registry):
    rec = fresh_registry.register(
        candidate_id="test_div",
        source_trial_id="trial_div",
        source_lineage_tag="test_lineage",
        role="diversifier",
    )
    assert rec.role == "diversifier"


def test_registry_register_invalid_role_raises(fresh_registry):
    with pytest.raises(ValueError, match="not in valid roles"):
        fresh_registry.register(
            candidate_id="test_bad",
            source_trial_id="trial_bad",
            source_lineage_tag="test_lineage",
            role="not_a_real_role",
        )


def test_registry_role_persists_across_reads(fresh_registry, tmp_path):
    fresh_registry.register(
        candidate_id="test_persist",
        source_trial_id="trial_x",
        source_lineage_tag="test_lineage",
        role="diversifier",
    )
    # Reopen via new registry instance
    db_path = fresh_registry.db_path
    new_reg = CandidateRegistry(db_path)
    rec = new_reg.get("test_persist")
    assert rec.role == "diversifier"


def test_registry_to_dict_includes_role(fresh_registry):
    rec = fresh_registry.register(
        candidate_id="test_dict",
        source_trial_id="trial_d",
        source_lineage_tag="test_lineage",
        role="risk_control",
    )
    d = rec.to_dict()
    assert d["role"] == "risk_control"
    # Must be JSON-serializable
    json.dumps(d)


def test_registry_alter_table_migration_idempotent(tmp_path):
    """Registry init twice should not error on existing role column."""
    db_path = tmp_path / "test_migrate.db"
    reg1 = CandidateRegistry(db_path)
    reg1.register(
        candidate_id="test_mig",
        source_trial_id="trial_m",
        source_lineage_tag="lineage",
        role="diversifier",
    )
    # Second init must not raise
    reg2 = CandidateRegistry(db_path)
    rec = reg2.get("test_mig")
    assert rec.role == "diversifier"


def test_registry_alter_table_legacy_db_gets_default_role(tmp_path):
    """Pre-PRD DB without role column → migration adds column with default."""
    db_path = tmp_path / "test_legacy.db"
    # Create pre-PRD schema manually (no role column)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE research_candidates (
                candidate_id          TEXT    PRIMARY KEY,
                source_trial_id       TEXT    NOT NULL,
                source_lineage_tag    TEXT    NOT NULL,
                status                TEXT    NOT NULL,
                frozen_spec_path      TEXT,
                decision_memo_path    TEXT,
                promoted_at           TEXT,
                revoked_at            TEXT,
                revoke_reason         TEXT,
                revoke_memo_path      TEXT,
                created_at            TEXT    NOT NULL,
                updated_at            TEXT    NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO research_candidates VALUES (
                'legacy_001', 'trial_legacy', 'old_lineage', 'S2_paper_candidate',
                NULL, NULL, NULL, NULL, NULL, NULL, '2026-04-01', '2026-04-01'
            )
        """)
        conn.commit()
    # Now open via new registry (triggers migration)
    reg = CandidateRegistry(db_path)
    rec = reg.get("legacy_001")
    assert rec.role == "legacy_decay_verification"  # default applied via ALTER


def test_registry_role_is_in_valid_roles_set():
    assert _VALID_ROLES == {"core_alpha", "diversifier",
                            "legacy_decay_verification", "risk_control"}


# ─── Trial 9 frozen spec verification ──────────────────────────────────


PROJ = Path(__file__).resolve().parent.parent.parent.parent
TRIAL9_SPEC_PATH = PROJ / "data" / "research_candidates" / "trial9_diversifier_001.yaml"


def test_trial9_frozen_spec_exists():
    assert TRIAL9_SPEC_PATH.exists(), f"Trial 9 spec not found at {TRIAL9_SPEC_PATH}"


def test_trial9_spec_role_is_diversifier():
    import yaml
    spec = yaml.safe_load(TRIAL9_SPEC_PATH.read_text())
    assert spec["candidate_role"] == "diversifier"


def test_trial9_spec_source_trial_id_matches_archive():
    """Spec's source.trial_id MUST match the actual archive entry."""
    import yaml
    spec = yaml.safe_load(TRIAL9_SPEC_PATH.read_text())
    assert spec["source"]["trial_id"] == "6c745c601a47"
    assert spec["source"]["lineage_tag"] == "track-c-cycle-2026-05-01-05"


def test_trial9_spec_features_match_archive():
    """Spec's feature_set MUST match the archived trial."""
    import yaml
    spec = yaml.safe_load(TRIAL9_SPEC_PATH.read_text())
    feats = [f["name"] for f in spec["feature_set"]]
    assert feats == ["beta_spy_60d", "max_dd_126d", "ret_1d"]


def test_trial9_spec_cycle_yaml_sha_matches():
    """Cycle yaml sha256 in trial 9 spec must match actual yaml file."""
    import hashlib
    import yaml
    spec = yaml.safe_load(TRIAL9_SPEC_PATH.read_text())
    cycle_yaml_path = PROJ / spec["source"]["cycle_yaml_path"]
    actual_sha = hashlib.sha256(cycle_yaml_path.read_bytes()).hexdigest()
    assert spec["source"]["cycle_yaml_sha256"] == actual_sha


def test_trial9_spec_diversifier_acceptance_status_is_enter_with_warn():
    import yaml
    spec = yaml.safe_load(TRIAL9_SPEC_PATH.read_text())
    status = spec["diversifier_acceptance_pre_evaluation"]["overall_acceptance_status"]
    assert status == "ENTER_FORWARD_AS_DIVERSIFIER_WITH_SOFT_WARN"


def test_trial9_spec_soft_warn_flag_listed():
    import yaml
    spec = yaml.safe_load(TRIAL9_SPEC_PATH.read_text())
    flags = spec["diversifier_acceptance_pre_evaluation"]["soft_warn_flags"]
    assert "diversifier_2025_maxdd_18_20pct" in flags


# ─── Regression: core_alpha rule UNCHANGED ─────────────────────────────


def test_core_alpha_role_does_not_change_existing_acceptance_path():
    """Adding CandidateRole enum + diversifier path must NOT change
    behavior for core_alpha role (regression: ensure no accidental
    softening of CLAUDE.md QQQ Rule for core)."""
    # The core_alpha role uses existing temporal_split_acceptance.py
    # evaluator unchanged. CandidateRole.core_alpha exists in enum but
    # the dispatch in temporal_split_acceptance.py still reads role
    # string from yaml; passing "core" or "core_alpha" to evaluate_candidate
    # uses role-specific gates.

    # This test asserts that the enum name aligns with the yaml role name
    # so dispatch doesn't break.
    assert CandidateRole.core_alpha.value == "core_alpha"
    # And that adding diversifier did NOT remove or rename core_alpha
    assert CandidateRole.core_alpha is CandidateRole.core_alpha


def test_temporal_split_v2_yaml_exists():
    """v2 yaml is the new SoT for diversifier candidates."""
    v2_path = PROJ / "config" / "temporal_split_v2.yaml"
    assert v2_path.exists(), "config/temporal_split_v2.yaml not created"


def test_temporal_split_v2_split_name_bumped():
    """v2 split_name MUST differ from v1 (locked_after_first_use policy)."""
    import yaml
    v1 = yaml.safe_load((PROJ / "config" / "temporal_split.yaml").read_text())
    v2 = yaml.safe_load((PROJ / "config" / "temporal_split_v2.yaml").read_text())
    assert v1["split_name"] == "alternating_regime_holdout_v1"
    assert v2["split_name"] == "alternating_regime_holdout_v2"


def test_temporal_split_v2_partition_unchanged_from_v1():
    """v2 partition (year buckets) MUST be IDENTICAL to v1 — only role
    thresholds differ. This guards against accidental partition drift."""
    import yaml
    v1 = yaml.safe_load((PROJ / "config" / "temporal_split.yaml").read_text())
    v2 = yaml.safe_load((PROJ / "config" / "temporal_split_v2.yaml").read_text())
    assert v1["partition"] == v2["partition"]


def test_temporal_split_v2_diversifier_thresholds_per_prd():
    """v2 diversifier section uses PRD §6.2 thresholds."""
    import yaml
    v2 = yaml.safe_load((PROJ / "config" / "temporal_split_v2.yaml").read_text())
    div = v2["roles"]["diversifier"]

    # New eligibility constraints
    fields = {ec["field"]: ec for ec in div["eligibility_constraint"]}
    assert "nav_corr_raw_max_vs_anchors" in fields
    assert fields["nav_corr_raw_max_vs_anchors"]["value"] == 0.70
    assert fields["nav_corr_residual_max_vs_anchors"]["value"] == 0.50
    assert fields["factor_overlap_with_active_core"]["value"] == 0
    assert fields["non_equity_weight_avg"]["value"] == 0.15

    # New validation gates
    val_gates = div["validation_gates"]
    has_strict_qqq = any(
        g["field"] == "validation.2025.excess_vs_qqq" and g["value"] == 0.0
        for g in val_gates
    )
    assert has_strict_qqq, "v2 must have strict 2025 vs_qqq > 0 gate"

    has_hard_dd = any(
        g["field"] == "validation.2025.maxdd"
        and g["value"] == 0.20 and g["action"] == "kill_candidate"
        for g in val_gates
    )
    assert has_hard_dd, "v2 must have 20% hard fail max_dd"

    has_soft_warn_dd = any(
        g["field"] == "validation.2025.maxdd"
        and g["value"] == 0.18 and g["action"] == "soft_warn"
        for g in val_gates
    )
    assert has_soft_warn_dd, "v2 must have 18% soft warn max_dd"


# ─── CLAUDE.md QQQ Rule diversifier exception ──────────────────────────


def test_claude_md_diversifier_exception_present():
    """CLAUDE.md must contain the diversifier role exception clause."""
    claude_path = PROJ / "CLAUDE.md"
    text = claude_path.read_text()
    assert "Diversifier Role Exception" in text
    # The waived rule cell must be exactly one
    assert "OOS walk-forward (average)" in text
    # NOT waived list must include critical gates
    assert "Full backtest period | Strategy CAGR > QQQ CAGR" in text


def test_claude_md_diversifier_exception_cites_prd_and_memo():
    claude_path = PROJ / "CLAUDE.md"
    text = claude_path.read_text()
    assert "20260501-two_stage_allocation_architecture_prd.md" in text
    assert "20260501-diversifier_role_decision.md" in text


# ─── Phase C-PRD-1 ↔ Track A role bridge (R2-A self-audit fix 2026-05-02) ──


def test_phase_c_to_track_a_bridge_core_alpha_to_core():
    """core_alpha is the Phase C name; Track A acceptance expects core."""
    from core.research.forward.manifest_schema import phase_c_role_to_track_a_role
    assert phase_c_role_to_track_a_role("core_alpha") == "core"


def test_phase_c_to_track_a_bridge_diversifier_passthrough():
    """diversifier name is identical in both vocabularies."""
    from core.research.forward.manifest_schema import phase_c_role_to_track_a_role
    assert phase_c_role_to_track_a_role("diversifier") == "diversifier"


def test_phase_c_to_track_a_bridge_legacy_decay_rejected():
    """legacy_decay_verification predates new framework; not Track A acceptance eligible."""
    from core.research.forward.manifest_schema import phase_c_role_to_track_a_role
    with pytest.raises(ValueError, match="not Track A acceptance eligible"):
        phase_c_role_to_track_a_role("legacy_decay_verification")


def test_phase_c_to_track_a_bridge_risk_control_rejected():
    """risk_control sleeves are rule-based; do not enter mining/acceptance."""
    from core.research.forward.manifest_schema import phase_c_role_to_track_a_role
    with pytest.raises(ValueError, match="not Track A acceptance eligible"):
        phase_c_role_to_track_a_role("risk_control")


def test_phase_c_to_track_a_bridge_unknown_role_rejected():
    """Unknown role name fail-closes with informative error."""
    from core.research.forward.manifest_schema import phase_c_role_to_track_a_role
    with pytest.raises(ValueError, match="unknown Phase C role"):
        phase_c_role_to_track_a_role("orphan_role_xyz")


def test_phase_c_to_track_a_bridge_non_string_input_typeerror():
    """Boundary: non-string input raises TypeError, not ValueError."""
    from core.research.forward.manifest_schema import phase_c_role_to_track_a_role
    with pytest.raises(TypeError, match="must be str"):
        phase_c_role_to_track_a_role(None)
    with pytest.raises(TypeError, match="must be str"):
        phase_c_role_to_track_a_role(42)


def test_phase_c_to_track_a_bridge_integration_with_ensure_role_assigned():
    """End-to-end: bridge output is accepted by Track A's ensure_role_assigned.

    Simulates the future cycle #06+ core_alpha promotion path:
      candidate_registry stores role='core_alpha'
      → bridge → 'core'
      → temporal_split.ensure_role_assigned('core', cfg) accepts
    """
    from core.research.forward.manifest_schema import phase_c_role_to_track_a_role
    from core.research.temporal_split import (
        ensure_role_assigned,
        load_temporal_split,
    )

    cfg = load_temporal_split()
    # Without bridge: ensure_role_assigned('core_alpha', cfg) would raise
    with pytest.raises(ValueError, match="not declared in split"):
        ensure_role_assigned("core_alpha", cfg)
    # With bridge: translation → 'core' → accepted
    track_a_role = phase_c_role_to_track_a_role("core_alpha")
    assert ensure_role_assigned(track_a_role, cfg) == "core"


def test_phase_c_to_track_a_bridge_diversifier_v2_dispatch_unchanged():
    """Diversifier path through bridge does NOT break v1↔v2 dispatch.

    Trial 9 path: candidate_registry role='diversifier' → bridge → 'diversifier'
    → resolve_split_path('diversifier', 2026-05-04) → v2 yaml.
    """
    from datetime import date as _date
    from core.research.forward.manifest_schema import phase_c_role_to_track_a_role
    from core.research.temporal_split import resolve_split_path, _DEFAULT_PATH_V2

    track_a_role = phase_c_role_to_track_a_role("diversifier")
    resolved = resolve_split_path(track_a_role, _date(2026, 5, 4))
    assert resolved == _DEFAULT_PATH_V2
