from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

from core.runtime.strategy_artifact import canonical_json, sha256_bytes

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from certify_phase3_runtime import (  # noqa: E402
    ROOT,
    RuntimeCertificationError,
    build_payload,
    verify_payload,
)


def test_runtime_certification_covers_every_phase3_role() -> None:
    payload = build_payload(
        validation_evidence_path="tests/fixtures/phase3_validation_pass.json",
        code_commit="a" * 40,
        created_at_utc="2026-07-20T00:00:00+00:00",
    )
    verify_payload(payload)
    assert payload["status"] == "CODE_CERTIFIED_LOCAL_ONLY"
    assert payload["external_state"]["real_forward_sessions"] == 0
    assert payload["external_state"]["cloud_deployed"] is False
    assert {record["role"] for record in payload["components"]} == {
        "runtime",
        "sealed_evidence",
        "collection",
        "operations",
        "deployment",
        "policy",
        "certifier",
    }


def test_runtime_certification_rejects_root_and_component_drift() -> None:
    payload = build_payload(
        validation_evidence_path="tests/fixtures/phase3_validation_pass.json",
        code_commit="b" * 40,
        created_at_utc="2026-07-20T00:00:00+00:00",
    )
    changed = deepcopy(payload)
    changed["live_enabled"] = True
    with pytest.raises(RuntimeCertificationError, match="root hash"):
        verify_payload(changed)

    component = Path(ROOT / payload["components"][0]["path"])
    original = payload["components"][0]["sha256"]
    payload["components"][0]["sha256"] = "0" * 64
    payload.pop("certification_root_sha256")
    payload["certification_root_sha256"] = sha256_bytes(canonical_json(payload))
    assert component.is_file() and original != "0" * 64
    with pytest.raises(RuntimeCertificationError, match="component drift"):
        verify_payload(payload)
