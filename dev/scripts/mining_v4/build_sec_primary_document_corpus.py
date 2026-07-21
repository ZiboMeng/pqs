#!/usr/bin/env python3
"""Fetch a resumable, immutable SEC primary-document corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
from core.research.sec_document_corpus import (  # noqa: E402
    select_primary_document_requests,
)


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


def _atomic_bytes(payload: bytes, path: Path) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    _atomic_bytes(
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        path,
    )


def _fetch(
    session: requests.Session,
    *,
    url: str,
    user_agent: str,
    last_request_at: float,
    interval: float,
) -> tuple[requests.Response, float]:
    wait = interval - (time.monotonic() - last_request_at)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(5):
        requested_at = time.monotonic()
        response = session.get(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=60,
        )
        if response.status_code not in {403, 429, 500, 502, 503, 504}:
            response.raise_for_status()
            return response, requested_at
        if attempt == 4:
            response.raise_for_status()
        time.sleep(min(30, 2 ** attempt))
    raise AssertionError("unreachable SEC document retry state")


def _read_journal(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            key = str(row["key"])
            if key in rows:
                raise RuntimeError(
                    f"duplicate document journal key at line {line_number}: {key}")
            rows[key] = row
    return rows


def _append_journal(path: Path, row: dict[str, Any]) -> None:
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filing-corpus-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--forms", nargs="+", default=["8-K"])
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--requests-per-second", type=float, default=8.0)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    args = parser.parse_args()
    if not 0 < args.requests_per_second <= 10:
        raise ValueError("SEC requests-per-second must be in (0, 10]")

    filing_root = Path(args.filing_corpus_root).resolve()
    output_root = Path(args.output_root).resolve()
    if output_root.exists():
        raise FileExistsError(f"document corpus is immutable: {output_root}")
    filing_manifest_path = filing_root / "manifest.json"
    filing_manifest_sha = _sha256_file(filing_manifest_path)
    metadata = pd.read_parquet(filing_root / "filing_metadata.parquet")
    requests_to_make = select_primary_document_requests(
        metadata,
        forms=args.forms,
        start_year=args.start_year,
        end_year=args.end_year,
    )
    partial = output_root.with_name(f".{output_root.name}.partial")
    partial.mkdir(parents=True, exist_ok=True)
    documents_dir = partial / "documents"
    documents_dir.mkdir(exist_ok=True)
    intent_path = partial / "build_intent.json"
    intent = {
        "filing_manifest_sha256": filing_manifest_sha,
        "forms": sorted({form.upper() for form in args.forms}),
        "start_year": args.start_year,
        "end_year": args.end_year,
        "requests": len(requests_to_make),
        "builder_commit": _git_commit(),
        "builder_script_sha256": _sha256_file(Path(__file__).resolve()),
    }
    if intent_path.exists():
        if json.loads(intent_path.read_text()) != intent:
            raise RuntimeError(
                f"partial corpus intent differs; inspect before removal: {partial}")
    else:
        _atomic_json(intent, intent_path)

    journal_path = partial / "fetch_journal.jsonl"
    journal = _read_journal(journal_path)
    session = requests.Session()
    last_request_at = float("-inf")
    interval = 1.0 / args.requests_per_second
    for position, request in enumerate(requests_to_make, start=1):
        if request.key in journal:
            row = journal[request.key]
            path = documents_dir / row["storage_name"]
            if path.exists() and _sha256_file(path) == row["document_sha256"]:
                continue
            raise RuntimeError(
                f"journal/file mismatch for {request.key}; refuse silent refetch")
        response, last_request_at = _fetch(
            session,
            url=request.url,
            user_agent=args.user_agent,
            last_request_at=last_request_at,
            interval=interval,
        )
        content = response.content
        if not content:
            raise RuntimeError(f"empty SEC primary document: {request.url}")
        destination = documents_dir / request.storage_name
        _atomic_bytes(content, destination)
        row = {
            "key": request.key,
            "ticker": request.ticker,
            "cik": request.cik,
            "accession_number": request.accession_number,
            "form": request.form,
            "acceptance_datetime_utc": request.acceptance_datetime_utc,
            "primary_document": request.primary_document,
            "url": request.url,
            "storage_name": request.storage_name,
            "http_status": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "response_bytes": len(content),
            "document_sha256": _sha256_bytes(content),
        }
        _append_journal(journal_path, row)
        journal[request.key] = row
        if position % 250 == 0 or position == len(requests_to_make):
            print(
                f"documents {position}/{len(requests_to_make)} "
                f"downloaded={len(journal)}",
                flush=True,
            )

    if set(journal) != {request.key for request in requests_to_make}:
        raise RuntimeError("document journal key set differs from request set")
    provenance = pd.DataFrame(list(journal.values())).sort_values(
        ["acceptance_datetime_utc", "cik", "accession_number"])
    provenance_path = partial / "document_provenance.parquet"
    provenance.to_parquet(provenance_path, index=False, compression="snappy")
    manifest = {
        "schema_version": 1,
        "corpus_id": output_root.name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        **intent,
        "source": "SEC Archives primaryDocument",
        "source_filing_corpus": filing_root.name,
        "requests_per_second_cap": args.requests_per_second,
        "documents": len(provenance),
        "total_response_bytes": int(provenance["response_bytes"].sum()),
        "unique_document_hashes": int(provenance["document_sha256"].nunique()),
        "document_provenance_sha256": _sha256_file(provenance_path),
        "evidence_scope": "DEVELOPMENT_TEXT_CORPUS_NO_MODEL_CLAIM",
        "automatic_promotion_eligible": False,
    }
    _atomic_json(manifest, partial / "manifest.json")
    os.replace(partial, output_root)
    print(f"document_corpus={output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
