"""Window-scoped source-layer classification (PRD v2.1 §G3 + §4.5).

The legacy as-of-date single-point classification (``classify(sym,
as_of)``) only certifies today's state. A forward TD's evidence path
spans a window — factor lookback for signal_input, [start_date..as_of]
for execution_nav and benchmark — and the window can cross the
source boundary even when as_of looks clean.

This module provides ``classify_window`` over the boundary sidecar at
``data/ref/daily_source_boundaries.parquet``.

Returns one of:
  - ``canonical_only``: every (sym, date) cell in the window is on the
    candidate's polygon-canonical construction layer.
  - ``frontier_only``: every cell is on the yfinance frontier.
  - ``mixed``: the window straddles the boundary, so some cells are
    on each layer.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable, Literal, Optional

from core.data.source_boundaries import _to_date, load_boundaries

LayerLabel = Literal["canonical_only", "frontier_only", "mixed"]


def classify_window(
    sym: str,
    start: date,
    as_of: date,
    attributes: Iterable[str] = ("close", "open"),
    *,
    boundaries_path: Optional[Path] = None,
) -> LayerLabel:
    """Classify the (sym, [start..as_of], attributes) cells by source
    layer.

    The ``attributes`` argument is preserved in the signature for
    forward compatibility (per PRD §G3) but does not affect the
    current classification because the boundary sidecar tracks
    per-symbol, not per-attribute, source layers. When per-attribute
    provenance lands (e.g. dividend sidecar separating close from
    volume), this function will be extended without changing callers.
    """
    df = load_boundaries(boundaries_path)
    if df.empty or sym not in df.index:
        # No boundary entry recorded — treat as fully canonical (the
        # safe default when no yfinance frontier append happened).
        return "canonical_only"
    row = df.loc[sym]
    canonical_end = _to_date(row.get("canonical_end_date"))
    frontier_start = _to_date(row.get("frontier_start_date"))

    if frontier_start is None:
        # No frontier recorded — pure canonical regardless of window.
        return "canonical_only"

    if canonical_end is None:
        # Frontier exists but no canonical — pure frontier.
        return "frontier_only"

    # Window entirely before frontier starts → canonical
    if frontier_start > as_of:
        return "canonical_only"
    # Window entirely after canonical ends (and on frontier) → frontier
    if canonical_end < start:
        return "frontier_only"
    # Otherwise the window straddles the boundary
    return "mixed"


def aggregate_window_layers(
    classifications: Iterable[LayerLabel],
) -> tuple[int, int, int]:
    """Return (canonical_only_n, frontier_only_n, mixed_n) counts.

    Helper for SourceLayerView aggregation.
    """
    co = fo = mx = 0
    for c in classifications:
        if c == "canonical_only":
            co += 1
        elif c == "frontier_only":
            fo += 1
        else:
            mx += 1
    return co, fo, mx


def classify_as_of(
    sym: str,
    as_of: date,
    *,
    boundaries_path: Optional[Path] = None,
) -> LayerLabel:
    """Single-date as-of classification — used for the
    ``as_of_held_source`` view (PRD §4.5).

    Returns ``canonical_only`` if the boundary either doesn't exist
    or as_of is on-or-before canonical_end; ``frontier_only`` if
    as_of is on-or-after frontier_start; ``mixed`` is impossible at a
    single date by construction (and would only arise for the
    pathological case where canonical_end ≥ frontier_start, which the
    sidecar contract forbids).
    """
    df = load_boundaries(boundaries_path)
    if df.empty or sym not in df.index:
        return "canonical_only"
    row = df.loc[sym]
    canonical_end = _to_date(row.get("canonical_end_date"))
    frontier_start = _to_date(row.get("frontier_start_date"))

    if frontier_start is None:
        return "canonical_only"
    if canonical_end is None:
        return "frontier_only"
    if as_of <= canonical_end:
        return "canonical_only"
    if as_of >= frontier_start:
        return "frontier_only"
    # Gap between canonical_end and frontier_start (rare; treat as
    # frontier since the bar must come from the post-canonical side
    # if we have it at all).
    return "frontier_only"
