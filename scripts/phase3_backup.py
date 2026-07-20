#!/usr/bin/env python3
"""Create, verify, or restore a non-overwriting Phase 3 volume snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "phase3_volume_backup_v1"
MANIFEST = "backup_manifest.json"


class BackupError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise BackupError(f"manifest is irregular: {path}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise BackupError(f"duplicate manifest key: {key}")
            result[key] = value
        return result

    payload = json.loads(path.read_bytes(), object_pairs_hook=reject_duplicates)
    if not isinstance(payload, dict):
        raise BackupError("backup manifest must be an object")
    return payload


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or path == Path(MANIFEST):
        raise BackupError(f"unsafe backup relative path: {value!r}")
    return path


def _source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for directory, directories, names in os.walk(root, followlinks=False):
        current = Path(directory)
        for name in [*directories, *names]:
            candidate = current / name
            if candidate.is_symlink():
                raise BackupError(f"backup source contains a symlink: {candidate}")
        for name in names:
            candidate = current / name
            if candidate.name.endswith(("-wal", "-shm")):
                continue
            if not candidate.is_file():
                raise BackupError(f"backup source contains an irregular file: {candidate}")
            files.append(candidate)
    return sorted(files)


def _sqlite_backup(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        result = destination_connection.execute("PRAGMA quick_check").fetchone()
        if result is None or result[0] != "ok":
            raise BackupError(f"SQLite backup quick_check failed: {source}")
    finally:
        destination_connection.close()
        source_connection.close()


def create_backup(source: Path, destination: Path) -> dict[str, Any]:
    if source.is_symlink() or not source.is_dir():
        raise BackupError("backup source must be a regular directory")
    source = source.resolve()
    destination_parent = destination.parent.resolve()
    destination = destination_parent / destination.name
    if destination.exists() or destination.is_symlink():
        raise BackupError("backup destination must not already exist")
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise BackupError("backup source and destination must not contain each other")
    destination_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination_parent))
    records: list[dict[str, Any]] = []
    try:
        for source_path in _source_files(source):
            relative = source_path.relative_to(source)
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source_path.suffix in {".db", ".sqlite", ".sqlite3"}:
                _sqlite_backup(source_path, target)
                kind = "sqlite_backup"
            else:
                shutil.copy2(source_path, target, follow_symlinks=False)
                kind = "file_copy"
            records.append(
                {
                    "path": relative.as_posix(),
                    "kind": kind,
                    "size_bytes": target.stat().st_size,
                    "sha256": _sha256(target),
                }
            )
        manifest = {
            "schema": SCHEMA,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_name": source.name,
            "files": records,
        }
        manifest_path = temporary / MANIFEST
        with manifest_path.open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, destination)
        directory = os.open(destination_parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {
            **manifest,
            "destination": str(destination),
            "manifest_sha256": _sha256(destination / MANIFEST),
        }
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_backup(backup: Path) -> dict[str, Any]:
    if backup.is_symlink() or not backup.is_dir():
        raise BackupError("backup must be a regular directory")
    manifest_path = backup / MANIFEST
    manifest = _strict_json(manifest_path)
    if set(manifest) != {"schema", "created_at_utc", "source_name", "files"}:
        raise BackupError("backup manifest fields are not exact")
    if manifest["schema"] != SCHEMA or not isinstance(manifest["files"], list):
        raise BackupError("unsupported backup manifest schema")
    expected = {MANIFEST}
    for record in manifest["files"]:
        if not isinstance(record, dict) or set(record) != {
            "path",
            "kind",
            "size_bytes",
            "sha256",
        }:
            raise BackupError("backup file record is invalid")
        relative = _safe_relative(str(record["path"]))
        expected.add(relative.as_posix())
        path = backup / relative
        if path.is_symlink() or not path.is_file():
            raise BackupError(f"backup file is absent or irregular: {relative}")
        if path.stat().st_size != record["size_bytes"] or _sha256(path) != record["sha256"]:
            raise BackupError(f"backup file hash or size mismatch: {relative}")
        if record["kind"] == "sqlite_backup":
            with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()
            if result is None or result[0] != "ok":
                raise BackupError(f"backup SQLite quick_check failed: {relative}")
        elif record["kind"] != "file_copy":
            raise BackupError(f"unknown backup file kind: {record['kind']}")
    observed = {
        path.relative_to(backup).as_posix()
        for path in _source_files(backup)
        if not path.name.endswith(("-wal", "-shm"))
    }
    if observed != expected:
        raise BackupError(
            f"backup contains missing/unexpected files: {sorted(observed ^ expected)}"
        )
    return {
        "status": "PASS",
        "backup": str(backup),
        "file_count": len(manifest["files"]),
        "manifest_sha256": _sha256(manifest_path),
    }


def restore_backup(backup: Path, target: Path, confirmation: str) -> dict[str, Any]:
    verification = verify_backup(backup)
    expected = f"RESTORE:{verification['manifest_sha256']}"
    if confirmation != expected:
        raise BackupError(f"restore requires --confirm {expected}")
    target_parent = target.parent.resolve()
    target = target_parent / target.name
    if target.exists() or target.is_symlink():
        raise BackupError("restore target must not already exist")
    if target.is_relative_to(backup.resolve()) or backup.resolve().is_relative_to(target):
        raise BackupError("backup and restore target must not contain each other")
    target_parent.mkdir(parents=True, exist_ok=True)
    manifest = _strict_json(backup / MANIFEST)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target_parent))
    try:
        for record in manifest["files"]:
            relative = _safe_relative(str(record["path"]))
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup / relative, destination, follow_symlinks=False)
        os.rename(temporary, target)
        directory = os.open(target_parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    restored = {
        relative.as_posix(): _sha256(target / relative)
        for relative in (_safe_relative(str(record["path"])) for record in manifest["files"])
    }
    expected_hashes = {str(record["path"]): str(record["sha256"]) for record in manifest["files"]}
    if restored != expected_hashes:
        raise BackupError("restored files do not match the backup manifest")
    return {
        "status": "PASS",
        "target": str(target),
        "file_count": len(restored),
        "manifest_sha256": verification["manifest_sha256"],
        "overwrote_existing_data": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("backup", "verify", "restore"))
    parser.add_argument("--source")
    parser.add_argument("--destination")
    parser.add_argument("--backup")
    parser.add_argument("--target")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        if args.command == "backup":
            if not args.source or not args.destination:
                raise BackupError("backup requires --source and --destination")
            result = create_backup(Path(args.source), Path(args.destination))
        elif args.command == "verify":
            if not args.backup:
                raise BackupError("verify requires --backup")
            result = verify_backup(Path(args.backup))
        else:
            if not args.backup or not args.target:
                raise BackupError("restore requires --backup and --target")
            result = restore_backup(Path(args.backup), Path(args.target), args.confirm)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
