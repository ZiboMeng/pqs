#!/usr/bin/env python3
"""Freeze SEC submissions metadata for the governed company pool."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.data.edgar_provider import DEFAULT_USER_AGENT  # noqa: E402
from core.research.sec_filing_corpus import (  # noqa: E402
    parse_recent_submissions,
    records_frame,
)

SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_SUBMISSION_FILE = "https://data.sec.gov/submissions/{name}"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJ, text=True).strip()


def _fetch(
    session: requests.Session,
    *,
    url: str,
    user_agent: str,
    last_request_at: float,
    min_interval_seconds: float,
) -> tuple[requests.Response, float]:
    wait = min_interval_seconds - (time.monotonic() - last_request_at)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(4):
        requested_at = time.monotonic()
        response = session.get(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json",
            },
            timeout=30,
        )
        if response.status_code not in {429, 500, 502, 503, 504}:
            response.raise_for_status()
            return response, requested_at
        if attempt == 3:
            response.raise_for_status()
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable SEC retry state")


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool", default="research/universes/semantic_ml_company_pool_v1.json")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--requests-per-second", type=float, default=7.0)
    parser.add_argument("--history-start", default="2015-01-01")
    parser.add_argument("--history-end", default="2024-12-31")
    args = parser.parse_args()
    if not 0 < args.requests_per_second <= 10:
        raise ValueError("SEC requests-per-second must be in (0, 10]")

    pool_path = (PROJ / args.pool).resolve()
    pool = json.loads(pool_path.read_text())
    output_root = Path(args.output_root).resolve()
    if output_root.exists():
        raise FileExistsError(f"SEC corpus is immutable: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    building = Path(tempfile.mkdtemp(
        prefix=f".{output_root.name}.building.", dir=output_root.parent))
    raw_dir = building / "raw_submissions"
    raw_dir.mkdir()
    shard_dir = raw_dir / "shards"
    shard_dir.mkdir()
    session = requests.Session()
    min_interval = 1.0 / args.requests_per_second
    last_request_at = float("-inf")
    all_records = []
    response_rows = []
    try:
        for position, company in enumerate(pool["selected"], start=1):
            ticker = str(company["ticker"])
            cik = int(company["cik"])
            url = SEC_SUBMISSIONS.format(cik=cik)
            response, last_request_at = _fetch(
                session,
                url=url,
                user_agent=args.user_agent,
                last_request_at=last_request_at,
                min_interval_seconds=min_interval,
            )
            content = response.content
            payload = response.json()
            records = parse_recent_submissions(payload, ticker=ticker, cik=cik)
            raw_path = raw_dir / f"CIK{cik:010d}.json"
            raw_path.write_bytes(content)
            all_records.extend(records)
            response_rows.append({
                "ticker": ticker,
                "cik": cik,
                "url": url,
                "http_status": response.status_code,
                "content_type": response.headers.get("Content-Type"),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "response_bytes": len(content),
                "response_sha256": _sha256_bytes(content),
                "selected_filings": len(records),
                "response_kind": "main_recent",
                "source_name": raw_path.name,
                "raw_relative_path": str(raw_path.relative_to(building)),
            })
            shards = payload.get("filings", {}).get("files", [])
            for shard in shards:
                filing_from = str(shard.get("filingFrom", ""))
                filing_to = str(shard.get("filingTo", ""))
                if (
                    not filing_from
                    or not filing_to
                    or filing_to < args.history_start
                    or filing_from > args.history_end
                ):
                    continue
                shard_name = str(shard.get("name", ""))
                if not shard_name.startswith(f"CIK{cik:010d}-submissions-"):
                    raise ValueError(
                        f"CIK {cik}: unsafe or mismatched shard {shard_name!r}")
                shard_url = SEC_SUBMISSION_FILE.format(name=shard_name)
                shard_response, last_request_at = _fetch(
                    session,
                    url=shard_url,
                    user_agent=args.user_agent,
                    last_request_at=last_request_at,
                    min_interval_seconds=min_interval,
                )
                shard_content = shard_response.content
                shard_payload = shard_response.json()
                shard_records = parse_recent_submissions(
                    shard_payload, ticker=ticker, cik=cik)
                shard_path = shard_dir / shard_name
                shard_path.write_bytes(shard_content)
                all_records.extend(shard_records)
                response_rows.append({
                    "ticker": ticker,
                    "cik": cik,
                    "url": shard_url,
                    "http_status": shard_response.status_code,
                    "content_type": shard_response.headers.get("Content-Type"),
                    "etag": shard_response.headers.get("ETag"),
                    "last_modified": shard_response.headers.get("Last-Modified"),
                    "response_bytes": len(shard_content),
                    "response_sha256": _sha256_bytes(shard_content),
                    "selected_filings": len(shard_records),
                    "response_kind": "historical_shard",
                    "source_name": shard_name,
                    "raw_relative_path": str(shard_path.relative_to(building)),
                })
            if position % 25 == 0 or position == len(pool["selected"]):
                print(
                    f"fetched {position}/{len(pool['selected'])} "
                    f"selected_filings={len(all_records)}",
                    flush=True,
                )

        metadata = records_frame(all_records)
        metadata_path = building / "filing_metadata.parquet"
        metadata.to_parquet(metadata_path, index=False, compression="snappy")
        responses_path = building / "response_provenance.parquet"
        records_frame_rows = pd.DataFrame(response_rows)
        records_frame_rows.to_parquet(
            responses_path, index=False, compression="snappy")
        manifest = {
            "schema_version": 1,
            "corpus_id": output_root.name,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "builder_commit": _git_commit(),
            "builder_script_sha256": _sha256_file(Path(__file__).resolve()),
            "parser_module_sha256": _sha256_file(
                PROJ / "core" / "research" / "sec_filing_corpus.py"),
            "pool_artifact_sha256": pool["artifact_sha256"],
            "source": "SEC submissions main endpoint plus overlapping historical shards",
            "source_base": "https://data.sec.gov/submissions/",
            "historical_shards_included": True,
            "historical_shard_overlap_start": args.history_start,
            "historical_shard_overlap_end": args.history_end,
            "requests_per_second_cap": args.requests_per_second,
            "raw_responses": len(response_rows),
            "main_responses": sum(
                row["response_kind"] == "main_recent" for row in response_rows),
            "historical_shard_responses": sum(
                row["response_kind"] == "historical_shard"
                for row in response_rows),
            "selected_filings": len(metadata),
            "forms": metadata["form"].value_counts().sort_index().to_dict(),
            "first_acceptance_utc": (
                metadata["acceptance_datetime_utc"].min().isoformat()
                if len(metadata) else None),
            "last_acceptance_utc": (
                metadata["acceptance_datetime_utc"].max().isoformat()
                if len(metadata) else None),
            "metadata_sha256": _sha256_file(metadata_path),
            "response_provenance_sha256": _sha256_file(responses_path),
            "evidence_scope": "RAW_CORPUS_INCLUDES_SEALED_DATES_MODEL_MUST_SLICE",
            "automatic_promotion_eligible": False,
        }
        _atomic_json(manifest, building / "manifest.json")
        os.replace(building, output_root)
    except Exception:
        shutil.rmtree(building, ignore_errors=True)
        raise
    print(f"corpus={output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
