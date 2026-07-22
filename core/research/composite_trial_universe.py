"""Cross-campaign independent-trial accounting without a rename reset."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from core.research.qualification_v2 import canonical_sha256, sha256_file
from core.research.trial_ledger import AppendOnlyTrialLedger


class CompositeTrialUniverseError(RuntimeError):
    """Raised when any bound ledger is missing, mutable, or unverifiable."""


def composite_trial_snapshot(
    *,
    repo_root: str | Path,
    current_ledger_path: str | Path,
    historical_ledger_refs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    current = Path(current_ledger_path).resolve()
    try:
        current.relative_to(root)
    except ValueError as exc:
        raise CompositeTrialUniverseError("current ledger must be inside repo") from exc
    entries: list[tuple[Path, str, str]] = []
    for reference in historical_ledger_refs:
        path = (root / str(reference.get("path", ""))).resolve()
        try:
            relative = str(path.relative_to(root))
        except ValueError as exc:
            raise CompositeTrialUniverseError(
                "historical ledger must be inside repo"
            ) from exc
        expected_sha = reference.get("sha256")
        if not path.is_file() or not isinstance(expected_sha, str):
            raise CompositeTrialUniverseError("historical ledger is missing")
        if sha256_file(path) != expected_sha:
            raise CompositeTrialUniverseError("historical ledger hash mismatch")
        entries.append((path, relative, "historical"))
    current_relative = str(current.relative_to(root))
    if any(path == current for path, _, _ in entries):
        raise CompositeTrialUniverseError("current ledger duplicated as historical")
    entries.append((current, current_relative, "current"))

    content_hashes: set[str] = set()
    ledgers: list[dict[str, Any]] = []
    incomplete: list[str] = []
    for path, relative, role in entries:
        ledger = AppendOnlyTrialLedger(path)
        snapshot = ledger.snapshot()
        events = ledger.verified_events()
        content_hashes.update(
            str(event["content_hash"])
            for event in events
            if event["event_type"] in {"INTENT", "REPLAY_INTENT"}
        )
        incomplete.extend(
            f"{relative}:{trial_id}"
            for trial_id in snapshot["incomplete_trial_ids"]
        )
        ledgers.append({
            "role": role,
            "path": relative,
            "sha256": sha256_file(path),
            "head_event_hash": snapshot["head_event_hash"],
            "event_count": snapshot["event_count"],
            "raw_independent_n_local": snapshot["raw_independent_n"],
        })
    ordered = sorted(content_hashes)
    return {
        "schema_version": 1,
        "ledgers": ledgers,
        "raw_independent_n": len(ordered),
        "independent_content_hashes_sha256": canonical_sha256(ordered),
        "incomplete_trial_ids": incomplete,
    }


def validate_trial_matrix_ids(
    *,
    repo_root: str | Path,
    current_ledger_path: str | Path,
    historical_ledger_refs: Sequence[Mapping[str, Any]],
    trial_ids: Sequence[str],
) -> None:
    """Require each performance-matrix column to name a terminal bound trial."""

    if not trial_ids or len(trial_ids) != len(set(trial_ids)):
        raise CompositeTrialUniverseError("trial matrix IDs must be unique")
    root = Path(repo_root).resolve()
    paths: list[Path] = []
    for reference in historical_ledger_refs:
        path = (root / str(reference.get("path", ""))).resolve()
        if not path.is_file() or sha256_file(path) != reference.get("sha256"):
            raise CompositeTrialUniverseError("historical ledger hash mismatch")
        paths.append(path)
    paths.append(Path(current_ledger_path).resolve())
    terminal_ids: set[str] = set()
    intended_ids: set[str] = set()
    for path in paths:
        for event in AppendOnlyTrialLedger(path).verified_events():
            if event["event_type"] in {"INTENT", "REPLAY_INTENT"}:
                intended_ids.add(str(event["trial_id"]))
            if event["event_type"] in {"OUTCOME", "FAILED", "ABORTED"}:
                terminal_ids.add(str(event["trial_id"]))
    missing = sorted(set(trial_ids) - intended_ids)
    incomplete = sorted(set(trial_ids) - terminal_ids)
    if missing:
        raise CompositeTrialUniverseError(
            f"trial matrix contains unregistered IDs: {missing}"
        )
    if incomplete:
        raise CompositeTrialUniverseError(
            f"trial matrix contains non-terminal IDs: {incomplete}"
        )


__all__ = [
    "CompositeTrialUniverseError",
    "composite_trial_snapshot",
    "validate_trial_matrix_ids",
]
