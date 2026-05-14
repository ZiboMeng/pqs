#!/usr/bin/env python3
"""Initialize SimpleBaselineStrategy paper-trading manifest.

Idempotent — refuses to overwrite an existing manifest unless --force.
Mirrors data/options/paper_runs/spy_8otm_bull_put_v1/ pattern.

Workflow:
  1. Read frozen spec yaml
  2. Compute spec_hash (sha256 of canonical YAML bytes)
  3. Determine start_date (next NYSE trading day after today)
  4. Write initial manifest.json + empty daily_nav.csv

Usage:
  python dev/scripts/baseline/init_simple_baseline.py
  python dev/scripts/baseline/init_simple_baseline.py --force  # overwrite
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd
import yaml

CANDIDATE_DIR = Path("data/baseline_simple/paper_runs/simple_baseline_v1")
SPEC_PATH = CANDIDATE_DIR / "spec.yaml"
MANIFEST_PATH = CANDIDATE_DIR / "manifest.json"
NAV_CSV_PATH = CANDIDATE_DIR / "daily_nav.csv"


def _spec_hash(spec_text: str) -> str:
    """SHA256 of canonical YAML round-trip (key-sorted)."""
    data = yaml.safe_load(spec_text)
    canon = yaml.safe_dump(data, sort_keys=True, default_flow_style=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _next_nyse_trading_day(today: date) -> date:
    """Approximate next NYSE trading day (skip weekends; ignores holidays)."""
    d = pd.Timestamp(today) + pd.Timedelta(days=1)
    while d.dayofweek >= 5:  # 5=Sat, 6=Sun
        d = d + pd.Timedelta(days=1)
    return d.date()


def main() -> None:
    parser = argparse.ArgumentParser(description="Init simple_baseline_v1 paper manifest")
    parser.add_argument("--force", action="store_true", help="overwrite existing manifest")
    args = parser.parse_args()

    if not SPEC_PATH.exists():
        sys.exit(f"[FAIL] spec not found: {SPEC_PATH}")

    spec_text = SPEC_PATH.read_text()
    spec = yaml.safe_load(spec_text)
    spec_sha = _spec_hash(spec_text)

    if MANIFEST_PATH.exists() and not args.force:
        existing = json.loads(MANIFEST_PATH.read_text())
        if existing.get("spec_hash") == spec_sha:
            print(f"[OK] manifest already initialized at {MANIFEST_PATH}")
            print(f"     spec_hash={spec_sha[:16]}…  (match — no action)")
            return
        sys.exit(
            f"[FAIL] manifest exists with DIFFERENT spec_hash:\n"
            f"  on-disk: {existing.get('spec_hash', '')[:16]}…\n"
            f"  current: {spec_sha[:16]}…\n"
            f"  rerun with --force to overwrite OR bump candidate_id."
        )

    today_d = pd.Timestamp.today().date()
    start_d = _next_nyse_trading_day(today_d)
    init_nav = float(spec["paper_config"]["initial_nav_usd"])

    manifest = {
        "candidate_id": spec["candidate_id"],
        "strategy_type": spec["strategy_type"],
        "spec_hash": spec_sha,
        "spec_path": str(SPEC_PATH),
        "created_at": spec["created_at"],
        "initialized_at_utc": datetime.now(timezone.utc).isoformat(),
        "start_date": str(start_d),
        "current_status": "initialized_awaiting_first_observe",

        # NAV tracking
        "initial_nav_usd": init_nav,
        "current_nav_usd": init_nav,
        "high_water_nav_usd": init_nav,
        "current_cash_usd": init_nav,
        "n_observe_days": 0,
        "last_observe_date": None,

        # Positions / target weights (populated on first observe)
        "target_weights": {},
        "current_positions": {},

        # Regime state (populated on first observe)
        "regime": None,
        "vix_close": None,
        "qqq_close": None,
        "qqq_above_sma200": None,

        # Forward observations
        "forward_runs": [],
    }

    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    # Empty NAV CSV header
    pd.DataFrame(columns=[
        "date", "td_number", "nav_usd", "cash_usd",
        "mtum_value", "tqqq_value", "bil_value",
        "regime", "vix_close", "qqq_close", "qqq_above_sma200",
    ]).to_csv(NAV_CSV_PATH, index=False)

    print(f"[OK] Initialized {spec['candidate_id']}")
    print(f"     spec_hash={spec_sha}")
    print(f"     start_date={start_d}")
    print(f"     initial_nav={init_nav:.2f} USD")
    print(f"     manifest: {MANIFEST_PATH}")
    print(f"     nav csv:  {NAV_CSV_PATH}")
    print(f"\n  Next: run observe script after NYSE close on {start_d}")


if __name__ == "__main__":
    main()
