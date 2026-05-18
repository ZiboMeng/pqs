"""P0-A F1 — single adjusted-price access point for the price-CONSUMER
tier (factor / IC / return / NAV computation).

PRD docs/prd/20260518-p0a_loader_barstore_fix_prd.md §2 F1.

Root cause it fixes: mining SEARCH / paper / factor-screen used
`MarketDataStore.read()` which returns RAW unadjusted parquet (no
split cascade), bypassing the documented `BarStore.load(adjusted=
True)` contract → split-corrupted returns in the selection tier.

This module is the ONE place the price-consumer tier loads daily
bars. It delegates to BarStore (split cascade + NaN-vol-safe). It
does NOT replace MarketDataStore — that remains the legitimate RAW
store accessor for ingest / storage / provenance. ONLY price-consumer
callers switch here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

from core.data.bar_store import BarStore


def load_adjusted(
    symbol: str,
    root: str | Path,
    freq: str = "1d",
    *,
    adjusted_total_return: bool = False,
    fallback: str = "local",
    _store: Optional[BarStore] = None,
) -> Optional[pd.DataFrame]:
    """One symbol, split-adjusted OHLCV+volume via BarStore. Returns
    None on missing/empty/load-failure (caller skips), never raises
    for a single bad symbol."""
    store = _store or BarStore(root=Path(root))
    try:
        df = store.load(symbol, freq=freq, adjusted=True,
                        adjusted_total_return=adjusted_total_return,
                        fallback=fallback)
    except Exception:
        return None
    if df is None or df.empty or "close" not in df.columns:
        return None
    return df


def load_adjusted_panel(
    symbols: Sequence[str],
    root: str | Path,
    freq: str = "1d",
    *,
    adjusted_total_return: bool = False,
    fallback: str = "local",
) -> dict[str, pd.DataFrame]:
    """{close,open,high,low,volume} DataFrames (index=date,
    cols=symbol), split-adjusted. Drop-in shape for the legacy
    `_load_price_volume` frame layout. Symbols that fail to load are
    silently skipped (same contract as the pre-fix loop)."""
    store = BarStore(root=Path(root))
    frames: dict[str, dict] = {k: {} for k in
                               ("close", "open", "high", "low", "volume")}
    for sym in symbols:
        df = load_adjusted(sym, root, freq,
                           adjusted_total_return=adjusted_total_return,
                           fallback=fallback, _store=store)
        if df is None:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    out: dict[str, pd.DataFrame] = {}
    out["close"] = pd.DataFrame(frames["close"]).sort_index()
    for col in ("open", "high", "low", "volume"):
        out[col] = (pd.DataFrame(frames[col]).reindex(out["close"].index)
                    if frames[col] else None)
    return out
