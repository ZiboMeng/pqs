"""Source-boundary sidecar tests (post-MVP audit 2026-04-26)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from core.data.source_boundaries import (
    SEMANTICS_AUTO_ADJUST,
    SOURCE_YFINANCE_AUTO_ADJUST,
    backfill_from_daily_store,
    get_boundary,
    load_boundaries,
    record_yfinance_append,
    save_boundaries,
    window_crosses_boundary,
)


def _write_parquet(path: Path, dates: list, value: float = 1.0) -> None:
    idx = pd.DatetimeIndex(dates)
    df = pd.DataFrame({"open": value, "close": value, "volume": 100}, index=idx)
    df.to_parquet(path)


def test_backfill_marks_post_canonical_as_frontier(tmp_path: Path):
    daily = tmp_path / "daily"
    daily.mkdir()
    # SYM_A: polygon-only (max date < canonical horizon)
    _write_parquet(daily / "SYM_A.parquet",
                   ["2026-04-15", "2026-04-16", "2026-04-17"])
    # SYM_B: polygon + yfinance frontier (post-canonical bars present)
    _write_parquet(daily / "SYM_B.parquet",
                   ["2026-04-15", "2026-04-16", "2026-04-17",
                    "2026-04-20", "2026-04-21"])
    sidecar = tmp_path / "boundaries.parquet"
    df = backfill_from_daily_store(
        daily_dir=daily,
        canonical_horizon=date(2026, 4, 17),
        path=sidecar,
    )
    assert "SYM_A" in df.index
    assert "SYM_B" in df.index
    # SYM_A has no frontier
    a = df.loc["SYM_A"]
    assert pd.isna(a["frontier_start_date"])
    assert pd.isna(a["frontier_source"])
    assert a["canonical_end_date"] == date(2026, 4, 17)
    # SYM_B has frontier_start = 2026-04-20
    b = df.loc["SYM_B"]
    assert b["frontier_start_date"] == date(2026, 4, 20)
    assert b["frontier_source"] == SOURCE_YFINANCE_AUTO_ADJUST
    assert b["frontier_semantics"] == SEMANTICS_AUTO_ADJUST


def test_record_yfinance_append_creates_entry(tmp_path: Path):
    sidecar = tmp_path / "boundaries.parquet"
    record_yfinance_append(
        symbol="NEW_SYM",
        appended_dates=[date(2026, 5, 1), date(2026, 5, 2)],
        prev_max_date=date(2026, 4, 17),
        path=sidecar,
    )
    b = get_boundary("NEW_SYM", path=sidecar)
    assert b is not None
    assert b["canonical_end_date"] == date(2026, 4, 17)
    assert b["frontier_start_date"] == date(2026, 5, 1)
    assert b["frontier_source"] == SOURCE_YFINANCE_AUTO_ADJUST


def test_record_yfinance_append_does_not_advance_existing_frontier(tmp_path: Path):
    sidecar = tmp_path / "boundaries.parquet"
    record_yfinance_append(
        symbol="X",
        appended_dates=[date(2026, 5, 1)],
        prev_max_date=date(2026, 4, 17),
        path=sidecar,
    )
    record_yfinance_append(
        symbol="X",
        appended_dates=[date(2026, 5, 2)],  # later append
        path=sidecar,
    )
    b = get_boundary("X", path=sidecar)
    # frontier_start_date stays at the original first frontier date
    assert b["frontier_start_date"] == date(2026, 5, 1)


def test_window_crosses_boundary_true(tmp_path: Path):
    sidecar = tmp_path / "boundaries.parquet"
    record_yfinance_append(
        symbol="A",
        appended_dates=[date(2026, 4, 20)],
        prev_max_date=date(2026, 4, 17),
        path=sidecar,
    )
    assert window_crosses_boundary(
        ["A"], date(2026, 4, 18), date(2026, 4, 25), path=sidecar,
    ) is True


def test_window_crosses_boundary_false(tmp_path: Path):
    sidecar = tmp_path / "boundaries.parquet"
    record_yfinance_append(
        symbol="A",
        appended_dates=[date(2026, 4, 20)],
        prev_max_date=date(2026, 4, 17),
        path=sidecar,
    )
    # Window entirely BEFORE the frontier
    assert window_crosses_boundary(
        ["A"], date(2026, 4, 10), date(2026, 4, 15), path=sidecar,
    ) is False
    # Window entirely AFTER (frontier_start IS in window only if
    # start <= fs <= end; this checks start > fs)
    assert window_crosses_boundary(
        ["A"], date(2026, 5, 1), date(2026, 5, 10), path=sidecar,
    ) is False


def test_load_boundaries_handles_missing_file(tmp_path: Path):
    """Missing sidecar → empty DataFrame with schema columns, not crash."""
    df = load_boundaries(tmp_path / "nope.parquet")
    assert df.empty
    assert "canonical_end_date" in df.columns


def test_get_boundary_returns_none_for_unknown_symbol(tmp_path: Path):
    sidecar = tmp_path / "boundaries.parquet"
    record_yfinance_append(
        symbol="A", appended_dates=[date(2026, 5, 1)],
        prev_max_date=date(2026, 4, 17),
        path=sidecar,
    )
    assert get_boundary("Z", path=sidecar) is None


def test_market_data_store_records_boundary_on_yfinance_append(tmp_path: Path):
    """Integration: MarketDataStore.append for freq=1d records the
    boundary sidecar entry automatically."""
    from core.data.market_data_store import MarketDataStore

    sidecar = tmp_path / "boundaries.parquet"
    # Patch the default sidecar path so the test doesn't touch repo state.
    import core.data.source_boundaries as sb
    orig = sb.DEFAULT_BOUNDARIES_PATH
    sb.DEFAULT_BOUNDARIES_PATH = sidecar
    try:
        data_dir = tmp_path / "data"
        store = MarketDataStore(data_dir=data_dir)
        # First write — establishes canonical history.
        df1 = pd.DataFrame(
            {"open": 100, "close": 101, "volume": 1000},
            index=pd.DatetimeIndex(["2026-04-15", "2026-04-16", "2026-04-17"]),
        )
        store.append("INTGR_T", "1d", df1)
        # No boundary recorded yet (first write — no canonical history
        # to defend).
        assert get_boundary("INTGR_T", path=sidecar) is None
        # Second write — yfinance-style frontier append.
        df2 = pd.DataFrame(
            {"open": 102, "close": 103, "volume": 1200},
            index=pd.DatetimeIndex(["2026-04-20", "2026-04-21"]),
        )
        store.append("INTGR_T", "1d", df2)
        b = get_boundary("INTGR_T", path=sidecar)
        assert b is not None
        assert b["canonical_end_date"] == date(2026, 4, 17)
        assert b["frontier_start_date"] == date(2026, 4, 20)
        assert b["frontier_source"] == SOURCE_YFINANCE_AUTO_ADJUST
    finally:
        sb.DEFAULT_BOUNDARIES_PATH = orig
