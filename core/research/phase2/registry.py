"""Atomic, append-complete experiment registry.

An experiment must exist as ``PLANNED`` before evaluation starts.  Completion
updates that same immutable specification with results; failed/crashed entries
are retained rather than filtered from the evidence trail.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    strategy_family: str
    strategy_version: str
    hypothesis: str
    parameters: Mapping[str, Any]
    data_range: Mapping[str, str]
    cost_model: str
    benchmark: str
    code_commit: str
    random_seed: int = 20260717

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record.update(
            {
                "status": "PLANNED",
                "registered_at_utc": _utc_now(),
                "started_at_utc": None,
                "completed_at_utc": None,
                "result_path": None,
                "key_metrics": None,
                "pass_fail": None,
                "failure_reason": None,
            }
        )
        return record


class ExperimentRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "experiments": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or not isinstance(payload.get("experiments"), list):
            raise ValueError(f"invalid experiment registry schema: {self.path}")
        return payload

    def _write(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def preregister(self, specs: list[ExperimentSpec]) -> None:
        payload = self._load()
        records = {entry["experiment_id"]: entry for entry in payload["experiments"]}
        for spec in specs:
            if spec.experiment_id in records:
                existing = records[spec.experiment_id]
                immutable = spec.to_record()
                for key in (
                    "strategy_family",
                    "strategy_version",
                    "hypothesis",
                    "parameters",
                    "data_range",
                    "cost_model",
                    "benchmark",
                    "code_commit",
                    "random_seed",
                ):
                    if existing.get(key) != immutable[key]:
                        raise ValueError(f"experiment {spec.experiment_id} specification drift: {key}")
                continue
            record = spec.to_record()
            payload["experiments"].append(record)
            records[spec.experiment_id] = record
        self._write(payload)

    def mark_running(self, experiment_id: str) -> None:
        self._transition(experiment_id, {"PLANNED"}, "RUNNING", started_at_utc=_utc_now())

    def complete(
        self,
        experiment_id: str,
        *,
        result_path: str,
        key_metrics: Mapping[str, Any],
        passed: bool,
        failure_reason: str | None = None,
    ) -> None:
        self._transition(
            experiment_id,
            {"RUNNING"},
            "COMPLETED",
            completed_at_utc=_utc_now(),
            result_path=result_path,
            key_metrics=dict(key_metrics),
            pass_fail="PASS" if passed else "FAIL",
            failure_reason=failure_reason,
        )

    def fail(self, experiment_id: str, reason: str) -> None:
        self._transition(
            experiment_id,
            {"PLANNED", "RUNNING"},
            "FAILED",
            completed_at_utc=_utc_now(),
            pass_fail="FAIL",
            failure_reason=reason,
        )

    def invalidate(self, experiment_id: str, reason: str) -> None:
        """Retain a completed result but exclude it after evidence invalidation."""
        if not reason.strip():
            raise ValueError("invalidation requires a non-empty reason")
        self._transition(
            experiment_id,
            {"COMPLETED"},
            "INVALIDATED",
            invalidated_at_utc=_utc_now(),
            invalidation_reason=reason,
            pass_fail="INVALID",
        )

    def correct_completion_decision(
        self,
        experiment_id: str,
        *,
        passed: bool,
        reason: str,
    ) -> None:
        """Auditably correct a completed result's decision classification."""
        if not reason.strip():
            raise ValueError("decision correction requires a non-empty reason")
        payload = self._load()
        for entry in payload["experiments"]:
            if entry.get("experiment_id") != experiment_id:
                continue
            if entry.get("status") != "COMPLETED":
                raise ValueError(
                    f"experiment {experiment_id} decision correction requires COMPLETED status"
                )
            prior = entry.get("pass_fail")
            corrected = "PASS" if passed else "FAIL"
            entry.setdefault("decision_corrections", []).append(
                {
                    "corrected_at_utc": _utc_now(),
                    "prior_pass_fail": prior,
                    "corrected_pass_fail": corrected,
                    "reason": reason,
                }
            )
            entry["pass_fail"] = corrected
            entry["failure_reason"] = None if passed else reason
            self._write(payload)
            return
        raise KeyError(experiment_id)

    def _transition(
        self,
        experiment_id: str,
        allowed: set[str],
        target: str,
        **updates: Any,
    ) -> None:
        payload = self._load()
        for entry in payload["experiments"]:
            if entry.get("experiment_id") != experiment_id:
                continue
            if entry.get("status") not in allowed:
                raise ValueError(
                    f"experiment {experiment_id} cannot transition "
                    f"{entry.get('status')} -> {target}"
                )
            entry["status"] = target
            entry.update(updates)
            self._write(payload)
            return
        raise KeyError(f"experiment {experiment_id} was not preregistered")

    def get(self, experiment_id: str) -> dict[str, Any]:
        for entry in self._load()["experiments"]:
            if entry.get("experiment_id") == experiment_id:
                return entry
        raise KeyError(experiment_id)
