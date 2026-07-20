from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.runtime.strategy_artifact import (
    REQUIRED_COMPONENT_ROLES,
    StrategyArtifactError,
    build_strategy_artifact,
    verify_strategy_artifact,
    write_strategy_artifact,
)


def _files(root: Path) -> tuple[dict[str, list[str]], list[str]]:
    components: dict[str, list[str]] = {}
    for role in sorted(REQUIRED_COMPONENT_ROLES):
        path = root / f"{role}.txt"
        path.write_text(f"{role}\n", encoding="utf-8")
        components[role] = [path.name]
    evidence = root / "evidence.json"
    evidence.write_text('{"passed":true}\n', encoding="utf-8")
    return components, [evidence.name]


def _artifact(root: Path, **overrides):
    components, evidence = _files(root)
    values = {
        "repo_root": root,
        "strategy_id": "approved_v1",
        "strategy_version": "v1",
        "promotion_status": "PAPER_APPROVED",
        "allowed_runtime_modes": ["PAPER"],
        "live_enabled": False,
        "component_paths": components,
        "strategy_parameters": {"window": 42},
        "universe": ["SPY", "BIL"],
        "schedule": {"signal": "close", "execution": "next_open"},
        "data_schema_version": "test-v1",
        "promotion_evidence_paths": evidence,
        "code_commit": "a" * 40,
        "created_at_utc": "2026-07-20T00:00:00Z",
        "environment": {"pytest": "test"},
    }
    values.update(overrides)
    return build_strategy_artifact(**values)


def test_artifact_is_deterministic_and_verifies_every_component(tmp_path) -> None:
    first = _artifact(tmp_path)
    second = _artifact(tmp_path)
    assert first == second
    verified = verify_strategy_artifact(
        first,
        repo_root=tmp_path,
        expected_strategy_id="approved_v1",
        expected_strategy_version="v1",
        expected_promotion_status="PAPER_APPROVED",
        verify_environment=False,
    )
    assert verified["artifact_root_sha256"] == first["artifact_root_sha256"]


def test_component_drift_fails_closed(tmp_path) -> None:
    artifact = _artifact(tmp_path)
    (tmp_path / "risk.txt").write_text("changed\n", encoding="utf-8")
    with pytest.raises(StrategyArtifactError, match="component drift"):
        verify_strategy_artifact(artifact, repo_root=tmp_path, verify_environment=False)


def test_manifest_tamper_fails_even_when_components_are_unchanged(tmp_path) -> None:
    artifact = _artifact(tmp_path)
    artifact["strategy_parameters"]["window"] = 99
    with pytest.raises(StrategyArtifactError, match="root hash mismatch"):
        verify_strategy_artifact(artifact, repo_root=tmp_path, verify_environment=False)


def test_live_or_extra_runtime_mode_cannot_inherit_paper_approval(tmp_path) -> None:
    with pytest.raises(StrategyArtifactError, match="PAPER only"):
        _artifact(tmp_path, live_enabled=True)
    with pytest.raises(StrategyArtifactError, match="PAPER only"):
        _artifact(tmp_path, allowed_runtime_modes=["PAPER", "LIVE"])


def test_symlink_and_parent_escape_are_rejected(tmp_path) -> None:
    components, evidence = _files(tmp_path)
    outside = tmp_path.parent / "outside-artifact.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (tmp_path / "risk.txt").unlink()
    (tmp_path / "risk.txt").symlink_to(outside)
    with pytest.raises(StrategyArtifactError, match="symlink"):
        _artifact(
            tmp_path,
            component_paths=components,
            promotion_evidence_paths=evidence,
        )

    components["risk"] = ["../outside-artifact.txt"]
    with pytest.raises(StrategyArtifactError, match="repository-relative"):
        _artifact(
            tmp_path,
            component_paths=components,
            promotion_evidence_paths=evidence,
        )


def test_atomic_writer_reuses_identical_and_rejects_conflict(tmp_path) -> None:
    target = tmp_path / "registry" / "artifact.json"
    artifact = _artifact(tmp_path)
    path, reused = write_strategy_artifact(target, artifact)
    assert path == target
    assert reused is False
    assert target.stat().st_mode & 0o222 == 0

    _, reused = write_strategy_artifact(target, artifact)
    assert reused is True
    conflict = dict(artifact)
    conflict["artifact_root_sha256"] = "0" * 64
    with pytest.raises(StrategyArtifactError, match="immutable.*conflict"):
        write_strategy_artifact(target, conflict)


def test_loader_rejects_duplicate_json_keys(tmp_path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"strategy_id":"one","strategy_id":"two"}', encoding="utf-8")
    with pytest.raises(StrategyArtifactError, match="duplicate JSON key"):
        verify_strategy_artifact(path, repo_root=tmp_path, verify_environment=False)


def test_file_round_trip_uses_canonical_payload(tmp_path) -> None:
    target = tmp_path / "artifact.json"
    artifact = _artifact(tmp_path)
    write_strategy_artifact(target, artifact)
    assert json.loads(target.read_text(encoding="utf-8")) == artifact
