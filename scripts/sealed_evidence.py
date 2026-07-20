#!/usr/bin/env python3
"""Operate the Phase 3 sealed evidence store and fixed evaluator."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.research.sealed_evidence import (  # noqa: E402
    HypothesisRegistration,
    SealedBatchInput,
    SealedBudgetPolicy,
    SealedEvaluator,
    SealedEvidenceStore,
    SealedGovernance,
    SealedSubmission,
    load_hypothesis_registry,
)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate request JSON key: {key}")
        payload[key] = value
    return payload


def _mapping(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"request/config must be a regular non-symlink file: {path}")
    if path.suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicates,
        )
    if not isinstance(payload, dict):
        raise ValueError(f"request/config must be a mapping: {path}")
    return payload


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _components():
    config = _mapping(ROOT / "config/sealed_evaluator.yaml")
    if (
        config.get("schema_version") != 1
        or config.get("mode") != "PAPER"
        or config.get("live_enabled") is not False
    ):
        raise ValueError("sealed evaluator configuration violates PAPER boundary")
    store_config = config["store"]
    store = SealedEvidenceStore(
        _path(store_config["directory"]),
        maximum_batch_bytes=int(store_config["maximum_batch_bytes"]),
        maximum_rows=int(store_config["maximum_rows"]),
    )
    governance_config = config["governance"]
    governance = SealedGovernance(
        _path(governance_config["database"]),
        SealedBudgetPolicy.from_mapping(config["budget_policy"]),
    )
    for registration, registered_at in load_hypothesis_registry(
        _path(governance_config["hypothesis_registry"])
    ):
        governance.preregister(registration, now=registered_at)
    evaluator_config = config["evaluator"]
    evaluator = SealedEvaluator(
        repo_root=ROOT,
        store=store,
        governance=governance,
        results_directory=_path(governance_config["results_directory"]),
        worker_path=_path(evaluator_config["worker"]),
        metric_policies=evaluator_config["metric_policies"],
        allowed_benchmark_policies=evaluator_config[
            "allowed_benchmark_policies"
        ],
        allowed_cost_policies=evaluator_config["allowed_cost_policies"],
        timeout_seconds=int(evaluator_config["timeout_seconds"]),
        maximum_output_bytes=int(evaluator_config["maximum_output_bytes"]),
    )
    return store, governance, evaluator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("status", "append", "preregister", "submit", "evaluate"),
    )
    parser.add_argument("--request")
    parser.add_argument("--submission-id")
    args = parser.parse_args()
    try:
        store, governance, evaluator = _components()
        if args.command == "status":
            chain = store.verify_chain()
            result = {
                "schema_version": 1,
                "mode": "PAPER",
                "live_enabled": False,
                "sealed_batches": len(chain),
                "latest_record_sha256": (
                    None if not chain else chain[-1].record_sha256
                ),
                "evaluator_policy_sha256": evaluator.evaluator_policy_sha256,
                "governance": governance.status(),
                "raw_rows_returned": False,
            }
        elif args.command == "evaluate":
            if not args.submission_id:
                raise ValueError("evaluate requires --submission-id")
            result = evaluator.evaluate(args.submission_id)
        else:
            if not args.request:
                raise ValueError(f"{args.command} requires --request")
            payload = _mapping(Path(args.request))
            if args.command == "append":
                batch = SealedBatchInput(
                    batch_id=str(payload["batch_id"]),
                    source=str(payload["source"]),
                    event_time=datetime.fromisoformat(str(payload["event_time"])),
                    available_time=datetime.fromisoformat(
                        str(payload["available_time"])
                    ),
                    received_time=datetime.fromisoformat(str(payload["received_time"])),
                    data_schema=str(payload["data_schema"]),
                    rows=payload["rows"],
                    quality_flags=tuple(payload.get("quality_flags", [])),
                    revision_of=payload.get("revision_of"),
                )
                result = asdict(store.append(batch))
            elif args.command == "preregister":
                registration = HypothesisRegistration(
                    hypothesis_id=str(payload["hypothesis_id"]),
                    family_id=str(payload["family_id"]),
                    lineage_id=str(payload["lineage_id"]),
                    title=str(payload["title"]),
                    economic_rationale=str(payload["economic_rationale"]),
                    eligible_data_start=date.fromisoformat(
                        str(payload["eligible_data_start"])
                    ),
                    evidence_origin=str(payload["evidence_origin"]),
                )
                result = {
                    "hypothesis_id": registration.hypothesis_id,
                    "reused": governance.preregister(registration),
                }
            else:
                submission = SealedSubmission(
                    submission_id=str(payload["submission_id"]),
                    hypothesis_id=str(payload["hypothesis_id"]),
                    artifact_path=str(payload["artifact_path"]),
                    artifact_id=str(payload["artifact_id"]),
                    artifact_version=str(payload["artifact_version"]),
                    artifact_root_sha256=str(payload["artifact_root_sha256"]),
                    sealed_batch_id=str(payload["sealed_batch_id"]),
                    metric_policy_id=str(payload["metric_policy_id"]),
                    benchmark_policy_id=str(payload["benchmark_policy_id"]),
                    cost_policy_id=str(payload["cost_policy_id"]),
                )
                result = {
                    "submission_id": submission.submission_id,
                    "reused": governance.register_submission(submission),
                }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
