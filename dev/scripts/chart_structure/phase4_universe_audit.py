"""P4·R2 — expanded universe coverage audit + selection.

Per chart-structure ralph-loop execution PRD §8 round P4·R2. Builds the
ADDITIVE candidate set for ``config/universe_expanded_v1.yaml`` from the
existing ``data/daily/*.parquet`` store (no new download — the parquets
already exist; "ingest" = select from what is on disk).

Selection contract (deterministic, reproducible):
  1. ticker pattern ``^[A-Z]{1,5}$`` (drops warrants ``.WS`` / units
     ``.U`` / rights / preferred — non-common-stock instruments).
  2. clean 2015 start: first bar <= 2015-02-01 (matches the polygon-1m
     era that every existing executable-universe stock starts at).
  3. recent coverage: last bar >= 2026-04-01.
  4. row count >= 2500 (>= ~10y of trading days, no large internal gap).
  5. NO weekend rows (bar-level integrity smoke — the SPY off-by-one
     class of bug; see feedback_bar_level_data_integrity_smoke).
  6. liquidity: median(close*volume) over the last 252 bars; ranked
     descending, top-N taken.

Output: prints the ranked list + writes nothing (P4·R2 writes the yaml
in a separate step after review of this audit).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

import pandas as pd

_PROJ = Path(__file__).resolve().parents[3]
_DAILY = _PROJ / "data" / "daily"
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")

_START_MAX = pd.Timestamp("2015-02-01")
_END_MIN = pd.Timestamp("2026-04-01")
_MIN_ROWS = 2500
_LIQ_WINDOW = 252


def _audit_one(path: Path) -> Tuple[str, float, str] | None:
    """Return (ticker, median_dollar_vol, reason) — reason='' if eligible."""
    ticker = path.stem
    if not _TICKER_RE.match(ticker):
        return None
    try:
        df = pd.read_parquet(path, columns=["close", "volume"])
    except Exception:
        return (ticker, 0.0, "unreadable")
    if df.empty:
        return (ticker, 0.0, "empty")
    idx = df.index
    if idx[0] > _START_MAX:
        return (ticker, 0.0, f"late_start:{idx[0].date()}")
    if idx[-1] < _END_MIN:
        return (ticker, 0.0, f"stale_end:{idx[-1].date()}")
    if len(df) < _MIN_ROWS:
        return (ticker, 0.0, f"short:{len(df)}")
    # bar-level integrity smoke: no Sat/Sun labels
    wk = idx.weekday
    if ((wk == 5) | (wk == 6)).any():
        return (ticker, 0.0, "weekend_rows")
    tail = df.iloc[-_LIQ_WINDOW:]
    dv = (tail["close"] * tail["volume"]).median()
    if not pd.notna(dv) or dv <= 0:
        return (ticker, 0.0, "no_dollar_vol")
    return (ticker, float(dv), "")


def run(top_n: int, exclude: List[str]) -> List[str]:
    paths = sorted(
        p for p in _DAILY.glob("*.parquet")
        if ".preDataRepair" not in p.name
    )
    eligible: List[Tuple[str, float]] = []
    rejected = 0
    for p in paths:
        res = _audit_one(p)
        if res is None:
            continue
        ticker, dv, reason = res
        if reason:
            rejected += 1
            continue
        if ticker in exclude:
            continue
        eligible.append((ticker, dv))
    eligible.sort(key=lambda t: -t[1])
    print(f"scanned={len(paths)}  pattern+eligible={len(eligible)}  "
          f"rejected={rejected}", file=sys.stderr)
    picked = [t for t, _ in eligible[:top_n]]
    for i, (t, dv) in enumerate(eligible[:top_n]):
        print(f"{i+1:4d}  {t:6s}  ${dv/1e6:,.1f}M")
    return picked


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-n", type=int, default=400)
    args = ap.parse_args()
    run(args.top_n, exclude=[])
