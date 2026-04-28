"""Window-scoped source-layer classifier tests (PRD v2.1 §G3 + §4.5)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from core.data.source_boundaries import save_boundaries
from core.research.forward import (
    aggregate_window_layers,
    classify_as_of,
    classify_window,
)


@pytest.fixture
def sidecar(tmp_path: Path) -> Path:
    """Synthetic boundary sidecar: AAPL is mixed (canonical→frontier
    crosses on 2026-04-18); MSFT is fully canonical (no frontier);
    NVDA is fully frontier (no canonical); TSLA absent → default
    canonical."""
    p = tmp_path / "boundaries.parquet"
    df = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "canonical_end_date": date(2026, 4, 17),
                "frontier_start_date": date(2026, 4, 18),
                "frontier_source": "yfinance_auto_adjust",
                "frontier_semantics": "auto_adjust_True_split_div",
                "last_updated_at": datetime.now(timezone.utc),
            },
            {
                "symbol": "MSFT",
                "canonical_end_date": date(2026, 4, 28),
                "frontier_start_date": None,
                "frontier_source": None,
                "frontier_semantics": None,
                "last_updated_at": datetime.now(timezone.utc),
            },
            {
                "symbol": "NVDA",
                "canonical_end_date": None,
                "frontier_start_date": date(2026, 1, 2),
                "frontier_source": "yfinance_auto_adjust",
                "frontier_semantics": "auto_adjust_True_split_div",
                "last_updated_at": datetime.now(timezone.utc),
            },
        ]
    ).set_index("symbol")
    save_boundaries(df, p)
    return p


def test_classify_window_entirely_canonical(sidecar: Path):
    # AAPL canonical_end=4.17; window 4.10–4.16 is fully before frontier.
    assert classify_window(
        "AAPL", date(2026, 4, 10), date(2026, 4, 16),
        boundaries_path=sidecar,
    ) == "canonical_only"


def test_classify_window_entirely_frontier(sidecar: Path):
    # AAPL frontier_start=4.18; window 4.20–4.28 is fully after canonical.
    assert classify_window(
        "AAPL", date(2026, 4, 20), date(2026, 4, 28),
        boundaries_path=sidecar,
    ) == "frontier_only"


def test_classify_window_mixed_straddles_boundary(sidecar: Path):
    # AAPL boundary at 4.17/4.18; window 4.15–4.22 straddles → mixed
    assert classify_window(
        "AAPL", date(2026, 4, 15), date(2026, 4, 22),
        boundaries_path=sidecar,
    ) == "mixed"


def test_classify_window_no_frontier_is_canonical(sidecar: Path):
    # MSFT has no frontier_start_date → always canonical
    assert classify_window(
        "MSFT", date(2026, 4, 1), date(2026, 4, 28),
        boundaries_path=sidecar,
    ) == "canonical_only"


def test_classify_window_no_canonical_is_frontier(sidecar: Path):
    # NVDA has no canonical_end_date → always frontier
    assert classify_window(
        "NVDA", date(2026, 1, 5), date(2026, 4, 28),
        boundaries_path=sidecar,
    ) == "frontier_only"


def test_classify_window_unknown_symbol_defaults_canonical(sidecar: Path):
    # TSLA absent from sidecar → default canonical (per get_boundary
    # safe-default contract)
    assert classify_window(
        "TSLA", date(2026, 4, 1), date(2026, 4, 28),
        boundaries_path=sidecar,
    ) == "canonical_only"


def test_classify_as_of_dates(sidecar: Path):
    # AAPL: 4.17 = canonical (last canonical day); 4.18 = frontier
    assert classify_as_of("AAPL", date(2026, 4, 17),
                          boundaries_path=sidecar) == "canonical_only"
    assert classify_as_of("AAPL", date(2026, 4, 18),
                          boundaries_path=sidecar) == "frontier_only"
    assert classify_as_of("AAPL", date(2026, 4, 28),
                          boundaries_path=sidecar) == "frontier_only"


def test_classify_window_vs_as_of_window_can_be_mixed_when_as_of_clean(sidecar: Path):
    """The point of window-scoped classification (codex Round 7 §5):
    a held set whose as_of lookup says canonical_only can still have
    a window that straddles the boundary."""
    # Window 4.10–4.17 is fully canonical for AAPL
    win = classify_window(
        "AAPL", date(2026, 4, 10), date(2026, 4, 17),
        boundaries_path=sidecar,
    )
    asof = classify_as_of("AAPL", date(2026, 4, 17),
                          boundaries_path=sidecar)
    assert win == "canonical_only"
    assert asof == "canonical_only"

    # Window 4.15–4.22 straddles, but as_of=4.22 itself is frontier
    win2 = classify_window(
        "AAPL", date(2026, 4, 15), date(2026, 4, 22),
        boundaries_path=sidecar,
    )
    asof2 = classify_as_of("AAPL", date(2026, 4, 22),
                           boundaries_path=sidecar)
    assert win2 == "mixed"
    assert asof2 == "frontier_only"  # as_of single-point ≠ window view
    # The whole reason for the new contract: window view reveals what
    # as-of view hides (or vice versa).


def test_aggregate_window_layers_buckets():
    co, fo, mx = aggregate_window_layers([
        "canonical_only", "canonical_only", "frontier_only",
        "mixed", "mixed", "mixed",
    ])
    assert (co, fo, mx) == (2, 1, 3)
