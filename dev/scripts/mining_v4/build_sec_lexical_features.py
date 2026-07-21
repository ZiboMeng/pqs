#!/usr/bin/env python3
"""Parse an immutable SEC document corpus into lexical feature rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.research.sec_lexical_features import (  # noqa: E402
    compute_lexical_features,
    extract_visible_text,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJ, text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-corpus-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    document_root = Path(args.document_corpus_root).resolve()
    output_root = Path(args.output_root).resolve()
    if output_root.exists():
        raise FileExistsError(f"lexical artifact is immutable: {output_root}")
    document_manifest_path = document_root / "manifest.json"
    document_manifest = json.loads(document_manifest_path.read_text())
    provenance_path = document_root / "document_provenance.parquet"
    if _sha256_file(provenance_path) != document_manifest.get(
        "document_provenance_sha256"
    ):
        raise RuntimeError("document provenance hash differs from manifest")
    provenance = pd.read_parquet(provenance_path)
    rows = []
    for position, row in enumerate(provenance.itertuples(index=False), start=1):
        path = document_root / "documents" / row.storage_name
        actual_hash = _sha256_file(path)
        if actual_hash != row.document_sha256:
            raise RuntimeError(f"document hash mismatch: {row.storage_name}")
        payload = path.read_bytes()
        base = {
            "key": row.key,
            "ticker": row.ticker,
            "cik": int(row.cik),
            "accession_number": row.accession_number,
            "form": row.form,
            "acceptance_datetime_utc": row.acceptance_datetime_utc,
            "primary_document": row.primary_document,
            "document_sha256": actual_hash,
        }
        try:
            text = extract_visible_text(payload, row.content_type)
            base.update(compute_lexical_features(text))
            base["parse_status"] = "PASS"
            base["parse_error"] = None
        except (UnicodeError, ValueError) as exc:
            base["parse_status"] = "MISSING"
            base["parse_error"] = f"{type(exc).__name__}: {exc}"
        rows.append(base)
        if position % 500 == 0 or position == len(provenance):
            print(f"parsed {position}/{len(provenance)}", flush=True)

    frame = pd.DataFrame(rows)
    pass_fraction = float(frame["parse_status"].eq("PASS").mean())
    if pass_fraction < 0.90:
        raise RuntimeError(f"lexical parse coverage below 90%: {pass_fraction:.3f}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    building = Path(tempfile.mkdtemp(
        prefix=f".{output_root.name}.building.", dir=output_root.parent))
    try:
        features_path = building / "lexical_features.parquet"
        frame.to_parquet(features_path, index=False, compression="snappy")
        manifest = {
            "schema_version": 1,
            "artifact_id": output_root.name,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "builder_commit": _git_commit(),
            "builder_script_sha256": _sha256_file(Path(__file__).resolve()),
            "parser_module_sha256": _sha256_file(
                PROJ / "core" / "research" / "sec_lexical_features.py"),
            "document_corpus_id": document_manifest.get("corpus_id"),
            "document_manifest_sha256": _sha256_file(document_manifest_path),
            "documents": len(frame),
            "parse_pass": int(frame["parse_status"].eq("PASS").sum()),
            "parse_missing": int(frame["parse_status"].ne("PASS").sum()),
            "parse_pass_fraction": pass_fraction,
            "features_sha256": _sha256_file(features_path),
            "feature_names": sorted(
                set(frame) - {
                    "key", "ticker", "cik", "accession_number", "form",
                    "acceptance_datetime_utc", "primary_document",
                    "document_sha256", "parse_status", "parse_error",
                }),
            "evidence_scope": "DEVELOPMENT_LEXICAL_FEATURES",
            "automatic_promotion_eligible": False,
        }
        _atomic_json(manifest, building / "manifest.json")
        os.replace(building, output_root)
    except Exception:
        shutil.rmtree(building, ignore_errors=True)
        raise
    print(f"lexical_artifact={output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
