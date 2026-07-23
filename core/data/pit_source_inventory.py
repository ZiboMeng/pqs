"""Compact, non-directional inventory for V6 PIT source readiness."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from core.data.pit_contract import PitDataContract

ACCESS_ENV_PREFIXES = (
    "WRDS",
    "CRSP",
    "COMPUSTAT",
    "NORGATE",
    "DATABENTO",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_summary(path: Path, pattern: str = "*") -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "files": 0, "bytes": 0}
    files = [candidate for candidate in path.glob(pattern) if candidate.is_file()]
    return {
        "exists": True,
        "files": len(files),
        "bytes": sum(candidate.stat().st_size for candidate in files),
    }


def parquet_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:  # inventory must surface corrupt/unreadable inputs
        return {
            "exists": True,
            "readable": False,
            "error_type": type(exc).__name__,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return {
        "exists": True,
        "readable": True,
        "rows": len(frame),
        "columns": sorted(str(column) for column in frame.columns),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def json_manifest_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "exists": True,
            "readable": False,
            "error_type": type(exc).__name__,
            "sha256": sha256_file(path),
        }
    selected_keys = (
        "schema_version",
        "corpus_id",
        "created_at_utc",
        "source",
        "raw_responses",
        "main_responses",
        "historical_shard_responses",
        "selected_filings",
        "documents",
        "unique_document_hashes",
        "first_acceptance_utc",
        "last_acceptance_utc",
        "evidence_scope",
    )
    return {
        "exists": True,
        "readable": True,
        "sha256": sha256_file(path),
        "fields": {key: payload[key] for key in selected_keys if key in payload},
    }


def _access_markers(
    environment: Mapping[str, str],
    known_paths: list[Path] | None = None,
) -> dict[str, Any]:
    env_names = sorted(
        name
        for name in environment
        if any(name.upper().startswith(prefix) for prefix in ACCESS_ENV_PREFIXES)
    )
    paths = known_paths or []
    return {
        "environment_variable_names": env_names,
        "known_access_files": [str(path) for path in paths if path.exists()],
        "values_recorded": False,
    }


def build_source_inventory(
    source_project_root: str | Path,
    *,
    contract: PitDataContract,
    environment: Mapping[str, str] | None = None,
    known_access_paths: list[Path] | None = None,
) -> dict[str, Any]:
    """Inspect source availability without calculating directional metrics."""

    contract.assert_operation_allowed("source_inventory")
    root = Path(source_project_root).resolve()
    data = root / "data"
    mining_v4 = data / "research" / "mining_v4"
    env = os.environ if environment is None else environment
    access = _access_markers(env, known_access_paths)
    historical_cfg = contract.raw.get("historical_sources", {})
    approved_sources = list(historical_cfg.get("approved_source_ids", []))

    inventory = {
        "schema_version": 1,
        "inventory_id": "pqs-pit-source-inventory-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_id": contract.contract_id,
        "evidence_scope": contract.evidence_scope,
        "source_root": str(root),
        "local_market_data": {
            "daily_parquet": directory_summary(data / "daily", "*.parquet"),
            "reference_tables": {
                name: parquet_summary(data / "ref" / name)
                for name in (
                    "bar_provenance.parquet",
                    "split_coverage.parquet",
                    "distribution_coverage.parquet",
                    "splits.parquet",
                    "distributions.parquet",
                )
            },
        },
        "sec_data": {
            "companyfacts_cache": directory_summary(
                data / "fundamentals" / "edgar_cache", "*.json"
            ),
            "submissions_complete": json_manifest_summary(
                mining_v4 / "sec_submissions_complete_v2" / "manifest.json"
            ),
            "submissions_metadata": parquet_summary(
                mining_v4
                / "sec_submissions_complete_v2"
                / "filing_metadata.parquet"
            ),
            "primary_documents_8k": json_manifest_summary(
                mining_v4 / "sec_8k_primary_docs_2015_2024_v1" / "manifest.json"
            ),
        },
        "historical_security_master_access": access,
        "historical_source_assessment": {
            "approved_source_ids": approved_sources,
            "formal_lane_unlocked": bool(
                historical_cfg.get("formal_lane_unlocked", False)
            ),
            "required_capabilities": list(
                historical_cfg.get("required_capabilities", [])
            ),
            "status": (
                "READY_FOR_ADAPTER_VALIDATION"
                if approved_sources
                and historical_cfg.get("formal_lane_unlocked", False)
                else "BLOCKED_NO_APPROVED_HISTORICAL_SECURITY_MASTER"
            ),
        },
        "directional_compute_performed": False,
    }
    contract.assert_artifact_non_directional(inventory)
    return inventory


__all__ = [
    "ACCESS_ENV_PREFIXES",
    "build_source_inventory",
    "directory_summary",
    "json_manifest_summary",
    "parquet_summary",
    "sha256_file",
]
