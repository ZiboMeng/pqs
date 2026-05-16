"""Unit tests for the Phase 2 attempts log — chart-structure P2B·R4.
Gate P2-A7: phase2_attempts.json schema validation."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from core.ml.phase2_attempts import (
    Phase2Attempt,
    Phase2AttemptsLog,
    load_phase2_attempts,
)

_PROJ = Path(__file__).resolve().parents[3]
_LOG = _PROJ / "data" / "audit" / "chart_structure" / "phase2_attempts.json"

_NEG = dict(
    attempt_id="x", phase="2A", representation="r", status="experimented",
    verdict="no_significant_increment", verdict_scope="config_scoped",
    artifact="a.json", root_cause="redundant with baseline",
)


def test_phase2_attempts_file_schema_valid():
    log = load_phase2_attempts(_LOG)
    assert len(log.attempts) >= 3
    ids = {a.attempt_id for a in log.attempts}
    assert "2A-swing-family-t" in ids


def test_2a_negative_attempt_is_config_scoped_with_root_cause():
    """The real 2A family-T result must be config-scoped + root-caused —
    no blanket 'structure doesn't work' verdict."""
    log = load_phase2_attempts(_LOG)
    a = next(a for a in log.attempts if a.attempt_id == "2A-swing-family-t")
    assert a.verdict == "no_significant_increment"
    assert a.verdict_scope == "config_scoped"
    assert a.root_cause and len(a.root_cause) > 20


def test_negative_verdict_requires_root_cause():
    bad = dict(_NEG)
    bad.pop("root_cause")
    with pytest.raises(ValidationError, match="root_cause"):
        Phase2Attempt.model_validate(bad)


def test_negative_verdict_must_be_config_scoped():
    bad = dict(_NEG, verdict_scope="global")
    with pytest.raises(ValidationError, match="config_scoped"):
        Phase2Attempt.model_validate(bad)


def test_duplicate_attempt_ids_rejected():
    with pytest.raises(ValidationError, match="unique"):
        Phase2AttemptsLog.model_validate({
            "schema_version": "1.0", "updated_at": "2026-05-16",
            "attempts": [_NEG, dict(_NEG)],
        })


def test_extra_keys_forbidden():
    with pytest.raises(ValidationError):
        Phase2Attempt.model_validate(dict(_NEG, sneaky=1))


def test_built_attempt_needs_no_root_cause():
    """A build-round attempt (representation_shipped) is not a negative
    result — it does not require a root_cause."""
    Phase2Attempt.model_validate(dict(
        attempt_id="b", phase="2B", representation="minirocket",
        status="built", verdict="representation_shipped",
        verdict_scope="config_scoped", artifact="m.py"))
