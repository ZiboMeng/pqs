#!/usr/bin/env python3
"""Fetch official current listings into the free prospective PIT hash chain."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from core.data.edgar_provider import DEFAULT_USER_AGENT  # noqa: E402
from core.data.pit_contract import PitDataContract  # noqa: E402
from core.data.prospective_pit import collect_prospective_snapshot  # noqa: E402


def _atomic_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default="config/pit_data_v1.yaml")
    parser.add_argument("--output-root", default="data/pit/prospective")
    parser.add_argument(
        "--compact-output",
        default="research/data_readiness/pit_v1/prospective_latest.json",
    )
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    args = parser.parse_args()

    contract = PitDataContract.load(args.contract)
    sources = contract.raw["prospective_sources"]
    payloads = {}
    session = requests.Session()
    for source_id in (
        "sec_company_tickers_exchange",
        "nasdaq_listed",
        "other_listed",
    ):
        url = sources[source_id]["url"]
        response = session.get(
            url,
            headers={
                "User-Agent": args.user_agent,
                "Accept": "application/json,text/plain,*/*",
            },
            timeout=60,
        )
        response.raise_for_status()
        payloads[source_id] = {
            "url": url,
            "content": response.content,
            "content_type": response.headers.get("Content-Type", ""),
            "etag": response.headers.get("ETag", ""),
            "last_modified": response.headers.get("Last-Modified", ""),
        }

    captured_at = datetime.now(timezone.utc)
    result = collect_prospective_snapshot(
        payloads,
        output_root=args.output_root,
        captured_at=captured_at,
        contract=contract,
    )
    compact = {
        "schema_version": 1,
        "batch_id": result["batch_id"],
        "captured_at_utc": result["captured_at_utc"],
        "contract_id": result["contract_id"],
        "evidence_scope": result["evidence_scope"],
        "raw_sources": result["raw_sources"],
        "normalized_records": result["normalized_records"],
        "normalized_sha256": result["normalized_sha256"],
        "diff_counts": result["diff_counts"],
        "ledger": result["ledger"],
        "directional_compute_performed": False,
    }
    contract.assert_artifact_non_directional(compact)
    _atomic_json(compact, Path(args.compact_output))
    print(f"prospective_batch={result['batch_id']}")
    print(f"normalized_records={result['normalized_records']}")
    print(f"ledger_events={result['ledger']['events']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
