"""Forward run manifest schema tests (R5).

PRD v3 §B: schema only, NO runner. Acceptance gate:
  - schema validator works
  - NO forward execution code in core/research/forward/
  - pytest no regression
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from core.research.forward import (
    CheckpointCadence,
    CostAssumptions,
    ForwardRun,
    ForwardRunManifest,
    ForwardRunStatus,
)
from core.research.robustness.window_spec import (
    DataIntegritySnapshot,
    EvidenceClass,
)


def _valid_snapshot() -> DataIntegritySnapshot:
    return DataIntegritySnapshot(
        daily_store_rebuild_commit="abcdef012345",
        baseline_snapshot_path="data/baseline/latest.json",
        generated_at_utc=datetime(2026, 4, 25, tzinfo=timezone.utc),
    )


def _valid_costs() -> CostAssumptions:
    return CostAssumptions(
        source="config/cost_model.yaml",
        config_hash="cafebabe1234deadbeef",
    )


def _full_manifest_kwargs(**overrides) -> dict:
    base = dict(
        candidate_id="rcm_v1_defensive_composite_01",
        evidence_class=EvidenceClass.forward_oos,
        spec_hash="abcdef012345",
        start_date=date(2026, 4, 25),
        cost_assumptions=_valid_costs(),
        data_integrity_snapshot=_valid_snapshot(),
    )
    base.update(overrides)
    return base


# ── happy path ─────────────────────────────────────────────────────────


def test_valid_manifest_accepted():
    m = ForwardRunManifest(**_full_manifest_kwargs())
    assert m.schema_version == "1.0"
    assert m.evidence_class is EvidenceClass.forward_oos
    assert m.benchmark == "SPY"
    assert m.secondary_benchmark == "QQQ"
    assert m.current_status is ForwardRunStatus.not_started
    assert m.runs == []
    assert m.checkpoint_cadence.weekly is True
    assert m.checkpoint_cadence.decision_days == [10, 20, 40, 60]


# ── evidence_class hard contract (R6 negative-simulation target) ───────


def test_evidence_class_must_be_forward_oos_pseudo_rejected():
    """R6 negative simulation: setting pseudo_oos_robustness must reject."""
    with pytest.raises(ValidationError) as exc:
        ForwardRunManifest(
            **_full_manifest_kwargs(evidence_class=EvidenceClass.pseudo_oos_robustness)
        )
    assert "forward_oos" in str(exc.value)


def test_evidence_class_must_be_forward_oos_replay_rejected():
    """R6 negative simulation: historical_replay must reject."""
    with pytest.raises(ValidationError) as exc:
        ForwardRunManifest(
            **_full_manifest_kwargs(evidence_class=EvidenceClass.historical_replay)
        )
    assert "forward_oos" in str(exc.value)


def test_missing_evidence_class_rejected():
    kwargs = _full_manifest_kwargs()
    del kwargs["evidence_class"]
    with pytest.raises(ValidationError):
        ForwardRunManifest(**kwargs)


# ── required field rejection ────────────────────────────────────────────


def test_missing_candidate_id_rejected():
    kwargs = _full_manifest_kwargs()
    del kwargs["candidate_id"]
    with pytest.raises(ValidationError):
        ForwardRunManifest(**kwargs)


def test_short_spec_hash_rejected():
    with pytest.raises(ValidationError):
        ForwardRunManifest(**_full_manifest_kwargs(spec_hash="abc"))


def test_short_cost_config_hash_rejected():
    with pytest.raises(ValidationError):
        CostAssumptions(source="config/cost_model.yaml", config_hash="abc")


def test_missing_data_integrity_snapshot_rejected():
    kwargs = _full_manifest_kwargs()
    del kwargs["data_integrity_snapshot"]
    with pytest.raises(ValidationError):
        ForwardRunManifest(**kwargs)


# ── checkpoint cadence ─────────────────────────────────────────────────


def test_decision_days_must_be_positive():
    with pytest.raises(ValidationError):
        CheckpointCadence(decision_days=[10, 0, 40])
    with pytest.raises(ValidationError):
        CheckpointCadence(decision_days=[-5, 10])


def test_decision_days_must_be_ascending():
    with pytest.raises(ValidationError):
        CheckpointCadence(decision_days=[20, 10, 40])


def test_decision_days_must_be_unique():
    with pytest.raises(ValidationError):
        CheckpointCadence(decision_days=[10, 10, 20])


def test_custom_cadence_accepted():
    cadence = CheckpointCadence(weekly=False, decision_days=[5, 15, 30])
    m = ForwardRunManifest(**_full_manifest_kwargs(checkpoint_cadence=cadence))
    assert m.checkpoint_cadence.weekly is False
    assert m.checkpoint_cadence.decision_days == [5, 15, 30]


# ── ForwardRun entry ───────────────────────────────────────────────────


def test_forward_run_entry_accepted():
    run = ForwardRun(
        checkpoint_label="10TD",
        as_of_date=date(2026, 5, 5),
        n_observed_trading_days=10,
        cum_ret=0.012,
        sharpe=0.85,
        max_dd=-0.025,
        vs_spy=0.005,
        vs_qqq=-0.001,
        notes="early",
    )
    assert run.checkpoint_label == "10TD"
    assert run.n_observed_trading_days == 10


def test_forward_run_negative_n_observed_rejected():
    with pytest.raises(ValidationError):
        ForwardRun(
            checkpoint_label="x",
            as_of_date=date(2026, 5, 5),
            n_observed_trading_days=-1,
        )


# ── status enum ────────────────────────────────────────────────────────


def test_status_default_is_not_started():
    m = ForwardRunManifest(**_full_manifest_kwargs())
    assert m.current_status is ForwardRunStatus.not_started


def test_invalid_status_rejected():
    with pytest.raises(ValidationError):
        ForwardRunManifest(**_full_manifest_kwargs(current_status="random_string"))


# ── round-trip: model_dump / model_validate ────────────────────────────


def test_round_trip_via_model_dump():
    m1 = ForwardRunManifest(**_full_manifest_kwargs())
    payload = m1.model_dump(mode="json")
    m2 = ForwardRunManifest.model_validate(payload)
    assert m2.candidate_id == m1.candidate_id
    assert m2.evidence_class is m1.evidence_class


# ── no runner code in the package ──────────────────────────────────────


def test_forward_runner_writes_go_through_schema_validation():
    """Replaces the original "no runner" guard.

    PRD v3 §B's "schema only no runner" constraint applied during the
    OOS MVP (R5). The user has since authorized the forward runner
    (PRD `docs/prd/20260426-forward_oos_runner_prd.md`), so the
    package now legitimately contains runner modules.

    The harder structural invariant we still need to lock in is:
    **every module under core/research/forward that materializes a
    forward manifest from a dict MUST go through
    ``ForwardRunManifest.model_validate``** (or an equivalent path
    that runs the schema's ``_check_evidence_class`` validator).
    Raw ``json.dump(some_dict, ...)`` writes that bypass the schema
    are forbidden because they would let an attacker (or careless
    refactor) silently flip ``evidence_class`` away from
    ``forward_oos``.

    Implementation: scan every .py file in the forward package
    (excluding the schema module itself); any file that imports
    ``json`` AND contains the literal string ``"forward_run_manifest"``
    OR mentions ``runs``/``manifest`` in the function bodies must
    also import ``ForwardRunManifest`` from manifest_schema. A
    grep-based check is sufficient and cheap.
    """
    import core.research.forward as pkg
    from pathlib import Path

    pkg_path = Path(pkg.__path__[0])
    schema_module = "manifest_schema.py"
    for py in pkg_path.iterdir():
        if py.suffix != ".py":
            continue
        if py.name == schema_module or py.name == "__init__.py":
            continue
        src = py.read_text()
        # Heuristic: if the file talks about manifests at all, it
        # MUST also reference the schema model (importing it ensures
        # validation paths are reachable).
        if "manifest" in src.lower() or "ForwardRun" in src:
            assert "ForwardRunManifest" in src, (
                f"{py.name} touches manifests but does not import "
                f"ForwardRunManifest — schema bypass risk. Add an "
                f"explicit import + use model_validate."
            )
