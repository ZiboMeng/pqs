#!/usr/bin/env python
"""Build the frozen current-company pool for future mining/forward work."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.research.company_pool import (  # noqa: E402
    SEC_COMPANY_TICKERS_EXCHANGE_URL,
    CompanyPoolConfig,
    canonical_artifact_hash,
    parse_sec_company_tickers,
    sec_payload_sha256,
    select_company_pool,
)


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJ, text=True).strip()


def _load_local_bars(data_root: Path, ticker: str) -> pd.DataFrame | None:
    daily = data_root / "daily"
    variants = [ticker, ticker.replace("-", "."), ticker.replace(".", "_")]
    for symbol in dict.fromkeys(variants):
        path = daily / f"{symbol}.parquet"
        if path.exists():
            return pd.read_parquet(path, columns=["close", "volume"])
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/strategy_mining_v4.yaml")
    parser.add_argument("--universe-config", default="config/universe.yaml")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--price-as-of", default=None)
    parser.add_argument(
        "--output",
        default="research/universes/semantic_ml_company_pool_v1.json",
    )
    parser.add_argument(
        "--user-agent",
        default="PQS Research zibo.meng@innopeaktech.com",
    )
    args = parser.parse_args()

    mining = yaml.safe_load((PROJ / args.config).read_text())
    universe = yaml.safe_load((PROJ / args.universe_config).read_text())
    pool_doc = mining["company_pool"]
    price_as_of = args.price_as_of or mining["observed_through"]
    pool_cfg = CompanyPoolConfig(
        max_symbols=int(pool_doc["max_symbols"]),
        exchanges=tuple(pool_doc["exchanges"]),
        min_history_sessions_at_snapshot=int(
            pool_doc["min_history_sessions_at_snapshot"]),
        freshness_calendar_days=int(pool_doc["freshness_calendar_days"]),
        min_price=float(pool_doc["min_price"]),
        trailing_liquidity_sessions=int(pool_doc["trailing_liquidity_sessions"]),
        min_median_dollar_volume=float(pool_doc["min_median_dollar_volume"]),
        excluded_name_patterns=tuple(pool_doc["excluded_name_patterns"]),
    )
    excluded = list(universe.get("blacklist", []))
    excluded += list(universe.get("high_risk_symbols", {}).get("symbols", []))

    response = requests.get(
        SEC_COMPANY_TICKERS_EXCHANGE_URL,
        headers={"User-Agent": args.user_agent},
        timeout=30,
    )
    response.raise_for_status()
    records = parse_sec_company_tickers(response.json())
    data_root = Path(args.data_root).resolve()
    result = select_company_pool(
        records,
        lambda ticker: _load_local_bars(data_root, ticker),
        price_as_of=price_as_of,
        config=pool_cfg,
        excluded_symbols=excluded,
    )
    frozen_at = datetime.now(timezone.utc)
    artifact = {
        "schema_version": 1,
        "pool_id": "semantic_ml_company_pool_v1",
        "evidence_scope": "DEVELOPMENT_ONLY",
        "automatic_promotion_eligible": False,
        "point_in_time_historical_membership": False,
        "purpose": "current company snapshot frozen for future forward candidates",
        "frozen_at_utc": frozen_at.isoformat(),
        "forward_start_must_be_after": str(frozen_at.date()),
        "price_as_of": str(pd.Timestamp(price_as_of).date()),
        "source": {
            "url": SEC_COMPANY_TICKERS_EXCHANGE_URL,
            "fetched_at_utc": frozen_at.isoformat(),
            "payload_sha256": sec_payload_sha256(response.content),
            "record_count": result.n_records,
        },
        "selection_config": asdict(pool_cfg),
        "project_excluded_symbols": sorted(set(excluded)),
        "code_commit": _git_commit(),
        "n_unique_tickers": result.n_unique_tickers,
        "n_selected": len(result.selected),
        "rejection_counts": result.rejection_counts,
        "selected": list(result.selected),
    }
    artifact["artifact_sha256"] = canonical_artifact_hash(artifact)
    output = PROJ / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")
    print(
        f"company pool: selected={len(result.selected)} / "
        f"SEC records={result.n_records} -> {output}"
    )
    print(f"artifact_sha256={artifact['artifact_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
