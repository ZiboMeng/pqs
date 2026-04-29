"""Tracks pre/post-close fetch state per (symbol, freq, date).

Used by ``scripts/fetch_data.py`` to detect when a previously-fetched row
was captured **before** that day's NYSE close (partial / intraday data
mistakenly written as final close) and force a refresh on the next
post-close run.

Storage: a tiny JSON at ``data/ref/fetch_session_log.json``. Schema:

::

    {
      "AAPL/1d/2026-04-29": {
         "fetched_at_utc": "2026-04-29T18:30:15+00:00",
         "session_close_utc": "2026-04-29T20:00:00+00:00",
         "is_pre_close": true,
         "post_close_buffer_min": 15
      },
      ...
    }

Atomic write via tempfile + replace. Single-writer (the fetch script);
no concurrent-access locking.

Public API
----------
- ``record_fetch(symbol, freq, target_date, *, fetched_at_utc, session_close_utc, ...)``
- ``was_fetched_pre_close(symbol, freq, target_date)``
- ``read_log()`` — entire JSON for inspection / tests.
"""
from __future__ import annotations

import json
from datetime import date as _date
from pathlib import Path
from typing import Dict, Optional

import pandas as pd


_DEFAULT_LOG_PATH = Path("data/ref/fetch_session_log.json")


def _key(symbol: str, freq: str, target_date) -> str:
    if isinstance(target_date, pd.Timestamp):
        d = target_date.strftime("%Y-%m-%d")
    elif isinstance(target_date, _date):
        d = target_date.strftime("%Y-%m-%d")
    else:
        d = str(target_date)[:10]
    return f"{symbol}/{freq}/{d}"


def _load(log_path: Path) -> Dict[str, dict]:
    if not log_path.exists():
        return {}
    try:
        with log_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def _save_atomic(log_path: Path, data: Dict[str, dict]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = log_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp.replace(log_path)


def record_fetch(
    symbol: str,
    freq: str,
    target_date,
    *,
    fetched_at_utc: pd.Timestamp,
    session_close_utc: Optional[pd.Timestamp],
    post_close_buffer_min: int,
    log_path: Optional[Path] = None,
) -> None:
    """Record a fetch event.

    ``session_close_utc`` may be None (target_date was a non-trading day);
    in that case ``is_pre_close`` is always False.
    """
    if session_close_utc is not None:
        is_pre_close = bool(
            fetched_at_utc < session_close_utc + pd.Timedelta(minutes=post_close_buffer_min)
        )
        sc_iso: Optional[str] = pd.Timestamp(session_close_utc).isoformat()
    else:
        is_pre_close = False
        sc_iso = None

    log_path = log_path or _DEFAULT_LOG_PATH
    data = _load(log_path)
    data[_key(symbol, freq, target_date)] = {
        "fetched_at_utc": pd.Timestamp(fetched_at_utc).isoformat(),
        "session_close_utc": sc_iso,
        "is_pre_close": is_pre_close,
        "post_close_buffer_min": int(post_close_buffer_min),
    }
    _save_atomic(log_path, data)


def was_fetched_pre_close(
    symbol: str,
    freq: str,
    target_date,
    log_path: Optional[Path] = None,
) -> bool:
    """Return True iff an earlier fetch for (symbol, freq, target_date) was
    captured pre-close. Caller uses this to decide whether to force-refresh.

    Returns False if no record exists (no prior fetch known).
    """
    log_path = log_path or _DEFAULT_LOG_PATH
    data = _load(log_path)
    rec = data.get(_key(symbol, freq, target_date))
    if rec is None:
        return False
    return bool(rec.get("is_pre_close", False))


def read_log(log_path: Optional[Path] = None) -> Dict[str, dict]:
    """Return the entire log dict (for inspection / tests)."""
    return _load(log_path or _DEFAULT_LOG_PATH)


def clear_log(log_path: Optional[Path] = None) -> None:
    """Delete the log file (for tests)."""
    p = log_path or _DEFAULT_LOG_PATH
    if p.exists():
        p.unlink()
