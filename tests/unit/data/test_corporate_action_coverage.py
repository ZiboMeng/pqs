from __future__ import annotations

import pandas as pd

from core.data.corporate_action_coverage import (
    compare_split_events,
    normalize_canonical_splits,
    normalize_vendor_splits,
)
from dev.scripts.data_integrity import build_split_coverage


def test_split_comparison_matches_forward_and_reverse_events():
    canonical_raw = pd.DataFrame({
        "symbol": ["AAA", "AAA", "AAA"],
        "date": pd.to_datetime(["2020-01-02", "2021-01-04", "2022-01-03"]),
        "from": [1, 5, 1],
        "to": [2, 1, 1],
    })
    vendor_raw = pd.Series(
        [2.0, 0.2],
        index=pd.to_datetime(["2020-01-02", "2021-01-04"]),
    )
    canonical = normalize_canonical_splits(
        canonical_raw, "AAA", start="2019-01-01", end="2026-07-17")
    vendor = normalize_vendor_splits(
        vendor_raw, start="2019-01-01", end="2026-07-17")
    result = compare_split_events(canonical, vendor)
    assert result.status == "OK"
    assert result.matched_event_count == 2
    assert result.canonical_event_count == 2


def test_split_comparison_surfaces_missing_and_ratio_mismatch():
    canonical = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-02", "2021-01-04"]),
        "canonical_ratio": [2.0, 5.0],
    })
    vendor = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-02", "2022-01-03"]),
        "vendor_ratio": [3.0, 4.0],
    })
    result = compare_split_events(canonical, vendor)
    assert result.status == "MISMATCH"
    assert result.ratio_mismatch_count == 1
    assert result.canonical_only_count == 1
    assert result.vendor_only_count == 1
    assert set(result.details["comparison"]) == {
        "RATIO_MISMATCH", "CANONICAL_ONLY", "VENDOR_ONLY",
    }


def test_timezone_vendor_event_normalizes_to_new_york_date():
    vendor = pd.Series(
        [2.0],
        index=pd.DatetimeIndex(["2020-01-02T14:30:00Z"]),
    )
    normalized = normalize_vendor_splits(
        vendor, start="2020-01-01", end="2020-01-03")
    assert normalized.loc[0, "date"] == pd.Timestamp("2020-01-02")


def test_non_append_query_error_preserves_existing_coverage(tmp_path, monkeypatch):
    ref = tmp_path / "ref"
    ref.mkdir()
    pd.DataFrame({
        "symbol": ["AAA"],
        "date": pd.to_datetime(["2020-01-02"]),
        "from": [1],
        "to": [2],
    }).to_parquet(ref / "splits.parquet", index=False)
    coverage_path = ref / "split_coverage.parquet"
    events_path = ref / "split_verification_events.parquet"
    pd.DataFrame({"symbol": ["KEEP"], "status": ["OK"]}).to_parquet(
        coverage_path, index=False)
    pd.DataFrame({"symbol": ["KEEP"], "comparison": ["MATCH"]}).to_parquet(
        events_path, index=False)
    before_coverage = coverage_path.read_bytes()
    before_events = events_path.read_bytes()

    def fail(symbol):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(build_split_coverage, "_fetch_vendor_splits", fail)
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_split_coverage.py",
            "--symbols", "AAA",
            "--start", "2007-01-01",
            "--end", "2026-07-17",
            "--data-root", str(tmp_path),
            "--pause-seconds", "0",
        ],
    )
    assert build_split_coverage.main() == 2
    assert coverage_path.read_bytes() == before_coverage
    assert events_path.read_bytes() == before_events
    assert len(list((tmp_path / "audit").glob("split_coverage_errors_*.parquet"))) == 1
