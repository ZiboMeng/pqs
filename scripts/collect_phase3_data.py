#!/usr/bin/env python3
"""Run or inspect the Phase 3 collect-only market-data boundary."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.data.collection import (  # noqa: E402
    CollectionIngestor,
    CollectionProvider,
    CollectionRequest,
    CollectionStore,
    FeedKind,
    FileCollectionProvider,
    MockCollectionProvider,
    load_envelope_file,
)


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate YAML configuration key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _config() -> dict[str, Any]:
    path = ROOT / "config/data_collection.yaml"
    if path.is_symlink() or not path.is_file():
        raise ValueError("data collection config must be a regular non-symlink file")
    payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    if not isinstance(payload, dict):
        raise ValueError("data collection config must be a mapping")
    if (
        payload.get("schema_version") != 1
        or payload.get("mode") != "COLLECT_ONLY"
        or payload.get("strategy_consumption_enabled") is not False
        or payload.get("live_enabled") is not False
    ):
        raise ValueError("data collection config violates the collect-only boundary")
    if payload.get("providers", {}).get("allowed_adapter_types") != ["file", "mock"]:
        raise ValueError("only file and mock data adapters are approved")
    return payload


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _store(config: dict[str, Any]) -> CollectionStore:
    settings = config["store"]
    return CollectionStore(
        _path(str(settings["directory"])),
        maximum_batch_bytes=int(settings["maximum_batch_bytes"]),
        maximum_rows=int(settings["maximum_rows"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "ingest-file", "ingest-mock"))
    parser.add_argument("--feed", choices=tuple(feed.value for feed in FeedKind))
    parser.add_argument("--source")
    parser.add_argument("--input")
    parser.add_argument("--provider-root")
    parser.add_argument("--store-root")
    parser.add_argument("--cursor")
    parser.add_argument("--requested-at")
    args = parser.parse_args()
    try:
        config = _config()
        store = (
            CollectionStore(
                _path(args.store_root),
                maximum_batch_bytes=int(config["store"]["maximum_batch_bytes"]),
                maximum_rows=int(config["store"]["maximum_rows"]),
            )
            if args.store_root
            else _store(config)
        )
        if args.command == "status":
            result = {
                **store.status_manifest(),
                "configured_schedules": config["schedules"],
                "real_provider_configured": False,
            }
        else:
            if not args.feed or not args.source or not args.input:
                raise ValueError(f"{args.command} requires --feed, --source, and --input")
            feed = FeedKind(args.feed)
            cursor = (
                args.cursor if args.cursor is not None else store.resume_cursor(feed, args.source)
            )
            requested_at = (
                datetime.now(UTC)
                if args.requested_at is None
                else datetime.fromisoformat(args.requested_at)
            )
            request = CollectionRequest(
                feed=feed,
                requested_at=requested_at,
                cursor=cursor,
                resource=args.input if args.command == "ingest-file" else None,
            )
            maximum_bytes = int(config["providers"]["maximum_input_bytes"])
            provider: CollectionProvider
            if args.command == "ingest-file":
                if not args.provider_root:
                    raise ValueError("ingest-file requires --provider-root")
                provider = FileCollectionProvider(
                    _path(args.provider_root),
                    args.source,
                    maximum_bytes=maximum_bytes,
                )
            else:
                envelope = load_envelope_file(_path(args.input), maximum_bytes=maximum_bytes)
                provider = MockCollectionProvider(args.source, [envelope])
            metadata = CollectionIngestor(store, provider).ingest(request)
            result = {
                **asdict(metadata),
                "feed": metadata.feed.value,
                "status": metadata.status.value,
                "mode": "COLLECT_ONLY",
                "strategy_consumption_enabled": False,
            }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
