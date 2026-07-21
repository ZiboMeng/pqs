#!/usr/bin/env python
"""Build the frozen current-company pool for future mining/forward work."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.data.yfinance_provider import YFinanceProvider  # noqa: E402
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


def _snapshot_candidate_tickers(
    records: list[dict[str, object]],
    config: CompanyPoolConfig,
    excluded_symbols: set[str],
) -> list[str]:
    """Return a safe superset of symbols the authoritative selector can admit."""

    allowed_exchanges = set(config.exchanges)
    patterns = [re.compile(pattern) for pattern in config.excluded_name_patterns]
    tickers = {
        str(record["ticker"]).upper()
        for record in records
        if str(record["exchange"]) in allowed_exchanges
        and str(record["ticker"]).upper() not in excluded_symbols
        and not any(pattern.search(str(record["name"])) for pattern in patterns)
    }
    return sorted(tickers)


def _fetch_market_snapshot(
    tickers: list[str],
    *,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    batch_size: int,
    pause_seconds: float,
) -> tuple[pd.DataFrame, list[str]]:
    """Fetch split-adjusted, dividend-unadjusted Yahoo bars into a long frame."""

    provider = YFinanceProvider(auto_adjust=False, progress=False)
    frames: list[pd.DataFrame] = []
    failed: list[str] = []
    batches = (len(tickers) + batch_size - 1) // batch_size
    for offset in range(0, len(tickers), batch_size):
        batch = tickers[offset:offset + batch_size]
        batch_number = offset // batch_size + 1
        yahoo_to_sec = {ticker.replace(".", "-"): ticker for ticker in batch}
        yahoo_symbols = list(yahoo_to_sec)
        print(
            f"market snapshot batch {batch_number}/{batches}: "
            f"{len(batch)} symbols",
            flush=True,
        )
        try:
            downloaded = provider.fetch_daily(
                yahoo_symbols,
                start=start,
                end=end_exclusive,
            )
        except RuntimeError as exc:
            print(f"  batch failed: {exc}", flush=True)
            failed.extend(batch)
            continue
        for yahoo_symbol, sec_symbol in yahoo_to_sec.items():
            wrapped = downloaded.get(yahoo_symbol)
            if wrapped is None or wrapped.df.empty:
                failed.append(sec_symbol)
                continue
            frame = wrapped.df[["close", "volume"]].copy()
            frame = frame.loc[frame.index <= end_exclusive - pd.Timedelta(days=1)]
            frame.insert(0, "date", frame.index)
            frame.insert(0, "ticker", sec_symbol)
            frames.append(frame.reset_index(drop=True))
        if offset + batch_size < len(tickers) and pause_seconds:
            time.sleep(pause_seconds)
    if not frames:
        raise RuntimeError("Yahoo market snapshot returned no usable symbols")
    snapshot = pd.concat(frames, ignore_index=True)
    snapshot["date"] = pd.to_datetime(snapshot["date"]).dt.tz_localize(None)
    snapshot = snapshot.sort_values(["ticker", "date"]).reset_index(drop=True)
    return snapshot, sorted(set(failed))


def _read_snapshot(path: Path) -> pd.DataFrame:
    snapshot = pd.read_parquet(path)
    required = {"ticker", "date", "close", "volume"}
    missing = required - set(snapshot)
    if missing:
        raise ValueError(f"market snapshot lacks columns: {sorted(missing)}")
    snapshot = snapshot[list(sorted(required))].copy()
    snapshot["ticker"] = snapshot["ticker"].astype(str).str.upper()
    snapshot["date"] = pd.to_datetime(snapshot["date"]).dt.tz_localize(None)
    return snapshot.sort_values(["ticker", "date"]).reset_index(drop=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    parser.add_argument(
        "--market-snapshot-input",
        default=None,
        help="Reuse a previously frozen Yahoo snapshot instead of fetching",
    )
    parser.add_argument(
        "--market-snapshot-output",
        default="research/mining_v4/source_snapshots/company_pool_market.parquet",
        help="Path under data-root for the fetched evidence snapshot",
    )
    parser.add_argument("--snapshot-lookback-calendar-days", type=int, default=180)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--batch-pause-seconds", type=float, default=0.5)
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
    excluded_set = {str(symbol).upper() for symbol in excluded}

    response = requests.get(
        SEC_COMPANY_TICKERS_EXCHANGE_URL,
        headers={"User-Agent": args.user_agent},
        timeout=30,
    )
    response.raise_for_status()
    records = parse_sec_company_tickers(response.json())
    data_root = Path(args.data_root).resolve()
    cutoff = pd.Timestamp(price_as_of).tz_localize(None).normalize()
    snapshot_start = cutoff - pd.Timedelta(
        days=args.snapshot_lookback_calendar_days)
    snapshot_end_exclusive = cutoff + pd.Timedelta(days=1)
    snapshot_failed: list[str] = []
    if args.market_snapshot_input:
        snapshot_path = Path(args.market_snapshot_input).resolve()
        snapshot = _read_snapshot(snapshot_path)
        snapshot_mode = "reused"
    else:
        snapshot_tickers = _snapshot_candidate_tickers(
            records, pool_cfg, excluded_set)
        snapshot, snapshot_failed = _fetch_market_snapshot(
            snapshot_tickers,
            start=snapshot_start,
            end_exclusive=snapshot_end_exclusive,
            batch_size=args.batch_size,
            pause_seconds=args.batch_pause_seconds,
        )
        snapshot_path = data_root / args.market_snapshot_output
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot.to_parquet(snapshot_path, index=False)
        snapshot_mode = "fetched"
    snapshot_by_ticker = {
        ticker: frame.set_index("date")[["close", "volume"]]
        for ticker, frame in snapshot.groupby("ticker", sort=False)
    }
    try:
        snapshot_location = str(snapshot_path.relative_to(data_root))
    except ValueError:
        snapshot_location = snapshot_path.name

    def load_combined_bars(ticker: str) -> pd.DataFrame | None:
        local = _load_local_bars(data_root, ticker)
        recent = snapshot_by_ticker.get(ticker)
        if local is None:
            return None
        if recent is None or recent.empty:
            return local
        return pd.concat([local, recent]).sort_index()

    result = select_company_pool(
        records,
        load_combined_bars,
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
        "market_snapshot": {
            "provider": "yfinance",
            "price_basis": "split_adjusted_dividend_unadjusted",
            "mode": snapshot_mode,
            "data_root_relative_path": snapshot_location,
            "file_sha256": _sha256_file(snapshot_path),
            "start": str(snapshot_start.date()),
            "end_exclusive": str(snapshot_end_exclusive.date()),
            "n_rows": int(len(snapshot)),
            "n_symbols": int(snapshot["ticker"].nunique()),
            "failed_symbols": snapshot_failed,
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
