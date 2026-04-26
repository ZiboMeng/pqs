"""Daily-store source boundary contract.

Pre-2026-04-26 the daily store at ``data/daily/<sym>.parquet`` had
two writers:

  1. ``core.data.daily_aggregator`` (round-3 step-3b polygon 1m → daily;
     raw bars + read-time splits via ``data/ref/splits.parquet``;
     dividends NOT applied)
  2. ``scripts/fetch_data.py`` via ``MarketDataStore.append`` (yfinance
     ``auto_adjust=True``; splits AND dividends both baked into bar
     values)

These two have different adjustment semantics. Mixing them silently
inside one parquet contaminates forward returns when an observation
window crosses the boundary (a dividend ex-date between the two
sources gets either preserved or removed depending on which side of
the boundary the bar is on).

This module provides a per-symbol boundary sidecar so consumers
(forward runner, master report, drift report) can detect when an
observation window crosses a source boundary and either flag the
artifact or refuse to mix.

Per user direction (2026-04-26 audit): physically separating the two
sources into different directories is NOT required. What IS required
is making the source layer explicit.

Sidecar location: ``data/ref/daily_source_boundaries.parquet``

Schema:
  symbol                str   — ticker
  canonical_end_date    date  — last polygon-canonical day; null if
                                 no canonical history
  frontier_start_date   date  — first non-canonical day stored; null
                                 if no frontier yet
  frontier_source       str   — e.g. 'yfinance_auto_adjust'; null if
                                 no frontier
  frontier_semantics    str   — short tag, e.g. 'auto_adjust_True_split_div'
  last_updated_at       datetime
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd


DEFAULT_BOUNDARIES_PATH = Path("data/ref/daily_source_boundaries.parquet")
DEFAULT_DAILY_DIR = Path("data/daily")

# Round-3 step-3b's polygon canonical horizon. Anything in
# data/daily/<sym>.parquet whose date is > this AT BACKFILL TIME is
# assumed to be yfinance-frontier from a prior fetch_data run.
# (Heuristic: precise per-symbol horizons aren't recoverable without
# row-level provenance; this is the conservative cutoff observed in
# the round-3 close memo.)
ROUND3_POLYGON_CANONICAL_HORIZON = date(2026, 4, 17)

# Source / semantics labels — keep consistent across writers.
SOURCE_POLYGON_AGGREGATOR = "polygon_aggregator"
SOURCE_YFINANCE_AUTO_ADJUST = "yfinance_auto_adjust"

SEMANTICS_RAW_SPLIT_AT_READ = "raw_bars_splits_at_read_no_dividends"
SEMANTICS_AUTO_ADJUST = "auto_adjust_True_split_and_dividends_baked"

_COLUMNS = [
    "symbol",
    "canonical_end_date",
    "frontier_start_date",
    "frontier_source",
    "frontier_semantics",
    "last_updated_at",
]


def _resolve_path(path: Optional[Path]) -> Path:
    """Resolve sidecar path with lazy module-global default.

    Default args are bound at function-definition time; this helper
    reads the module global at call time so test monkey-patches of
    ``DEFAULT_BOUNDARIES_PATH`` actually take effect.
    """
    return Path(path) if path else DEFAULT_BOUNDARIES_PATH


def load_boundaries(path: Optional[Path] = None) -> pd.DataFrame:
    """Load the boundary sidecar; return empty DataFrame with the right
    columns if the file doesn't exist yet."""
    p = _resolve_path(path)
    if not p.exists():
        return pd.DataFrame(columns=_COLUMNS).set_index("symbol")
    df = pd.read_parquet(p)
    if "symbol" in df.columns:
        df = df.set_index("symbol")
    return df


def save_boundaries(
    df: pd.DataFrame, path: Optional[Path] = None,
) -> Path:
    """Atomically write the boundary sidecar."""
    p = _resolve_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy().reset_index() if df.index.name == "symbol" else df.copy()
    tmp = p.with_suffix(p.suffix + ".tmp")
    out.to_parquet(tmp)
    tmp.replace(p)
    return p


def get_boundary(
    symbol: str, path: Optional[Path] = None,
) -> Optional[dict]:
    """Per-symbol boundary lookup. Returns None if the symbol has no
    sidecar entry (caller should treat as "all canonical / no
    frontier" — the safe default).
    """
    df = load_boundaries(path)
    if symbol not in df.index:
        return None
    row = df.loc[symbol]
    return {
        "symbol": symbol,
        "canonical_end_date": _to_date(row.get("canonical_end_date")),
        "frontier_start_date": _to_date(row.get("frontier_start_date")),
        "frontier_source": _str_or_none(row.get("frontier_source")),
        "frontier_semantics": _str_or_none(row.get("frontier_semantics")),
        "last_updated_at": row.get("last_updated_at"),
    }


def _to_date(v) -> Optional[date]:
    if v is None or pd.isna(v):
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, pd.Timestamp):
        return v.date()
    return pd.Timestamp(v).date()


def _str_or_none(v) -> Optional[str]:
    if v is None or pd.isna(v):
        return None
    s = str(v)
    return s if s else None


def record_yfinance_append(
    symbol: str,
    appended_dates: list,
    *,
    prev_max_date: Optional[date] = None,
    path: Optional[Path] = None,
) -> None:
    """Mark new yfinance-frontier rows for ``symbol``.

    Called by ``MarketDataStore.append`` (or fetch_data) AFTER any
    successful append of yfinance bars. Records:
      - frontier_start_date = first appended date if no frontier
        existed yet, else unchanged
      - canonical_end_date = ``prev_max_date`` if no canonical
        recorded yet (the symbol's polygon end-of-canonical date)
      - frontier_source / frontier_semantics = yfinance markers
      - last_updated_at = now (UTC)
    """
    if not appended_dates:
        return
    appended = [_to_date(d) for d in appended_dates if _to_date(d) is not None]
    if not appended:
        return
    appended_sorted = sorted(appended)

    df = load_boundaries(path)
    now = datetime.now(timezone.utc)

    if symbol in df.index:
        row = df.loc[symbol]
        existing_canonical = _to_date(row.get("canonical_end_date"))
        existing_frontier = _to_date(row.get("frontier_start_date"))
    else:
        existing_canonical = None
        existing_frontier = None

    new_canonical = existing_canonical
    new_frontier = existing_frontier

    if new_frontier is None:
        new_frontier = appended_sorted[0]
        if new_canonical is None and prev_max_date is not None:
            new_canonical = _to_date(prev_max_date)
    else:
        # Frontier already exists — nothing to update except timestamp.
        # New appends extend the frontier but the start_date is fixed.
        pass

    df.loc[symbol] = {
        "canonical_end_date": new_canonical,
        "frontier_start_date": new_frontier,
        "frontier_source": SOURCE_YFINANCE_AUTO_ADJUST,
        "frontier_semantics": SEMANTICS_AUTO_ADJUST,
        "last_updated_at": now,
    }
    save_boundaries(df, path)


def backfill_from_daily_store(
    *,
    daily_dir: Path = DEFAULT_DAILY_DIR,
    canonical_horizon: date = ROUND3_POLYGON_CANONICAL_HORIZON,
    path: Optional[Path] = None,
) -> pd.DataFrame:
    """One-time backfill of the sidecar from the current daily store.

    Heuristic (no row-level provenance available):
      - For each symbol in ``daily_dir``:
          * canonical_end_date = min(parquet_max_date, canonical_horizon)
          * frontier_start_date = first date > canonical_end_date in
            parquet, or None if no such date exists
          * frontier_source/semantics = yfinance markers if frontier
            exists, else None
      - canonical_horizon defaults to round-3 step-3b's
        polygon coverage end (2026-04-17). Symbols whose polygon
        history ended earlier will have their canonical_end_date
        capped by their actual parquet max — the heuristic accepts
        this slack.

    Overwrites any existing sidecar entries. Idempotent.
    """
    daily_dir = Path(daily_dir)
    rows = []
    now = datetime.now(timezone.utc)
    for parquet in sorted(daily_dir.glob("*.parquet")):
        symbol = parquet.stem
        try:
            df = pd.read_parquet(parquet)
        except Exception:
            continue
        if df.empty or not isinstance(df.index, pd.DatetimeIndex):
            continue
        max_date = df.index.max().date()
        canonical_end = min(max_date, canonical_horizon)
        post_canonical = df.index[df.index.date > canonical_end]
        frontier_start = (
            post_canonical[0].date() if len(post_canonical) > 0 else None
        )
        rows.append({
            "symbol": symbol,
            "canonical_end_date": canonical_end,
            "frontier_start_date": frontier_start,
            "frontier_source": (
                SOURCE_YFINANCE_AUTO_ADJUST if frontier_start else None
            ),
            "frontier_semantics": (
                SEMANTICS_AUTO_ADJUST if frontier_start else None
            ),
            "last_updated_at": now,
        })
    out_df = pd.DataFrame(rows).set_index("symbol")
    save_boundaries(out_df, path)
    return out_df


def window_crosses_boundary(
    symbols: list,
    start_date: date,
    end_date: date,
    *,
    path: Optional[Path] = None,
) -> bool:
    """Return True if any of the given symbols has a frontier_start_date
    that falls inside ``[start_date, end_date]`` — meaning an
    observation over that window crosses a source boundary for at
    least one held name.
    """
    df = load_boundaries(path)
    if df.empty:
        return False
    for sym in symbols:
        if sym not in df.index:
            continue
        fs = _to_date(df.loc[sym, "frontier_start_date"])
        if fs is None:
            continue
        if start_date <= fs <= end_date:
            return True
    return False
