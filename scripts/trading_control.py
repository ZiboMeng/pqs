#!/usr/bin/env python3
"""Operator CLI for durable global/strategy/symbol pause controls."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.trading.controls import ControlScope, TradingControlStore


def main() -> int:
    parser = argparse.ArgumentParser(description="PQS trading pause control")
    parser.add_argument("action", choices=["status", "pause", "resume"])
    parser.add_argument("--db-path", default="data/paper_trading/pt.db")
    parser.add_argument("--scope", choices=[scope.value for scope in ControlScope])
    parser.add_argument("--key", default="")
    parser.add_argument("--reason")
    parser.add_argument("--operator")
    args = parser.parse_args()

    store = TradingControlStore(args.db_path)
    if args.action == "status":
        rows = [asdict(control) for control in store.list_current()]
        print(json.dumps(rows, default=str, sort_keys=True))
        return 0

    missing = [
        name
        for name, value in (
            ("--scope", args.scope),
            ("--reason", args.reason),
            ("--operator", args.operator),
        )
        if not value
    ]
    if missing:
        parser.error(f"{args.action} requires {', '.join(missing)}")
    scope = ControlScope(args.scope)
    if scope is not ControlScope.GLOBAL and not args.key.strip():
        parser.error(f"{args.action} with {scope.value} requires --key")

    control = store.set_paused(
        scope,
        args.key,
        paused=args.action == "pause",
        reason=args.reason,
        updated_by=args.operator,
    )
    print(json.dumps(asdict(control), default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
