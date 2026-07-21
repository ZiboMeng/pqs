from pathlib import Path

import pandas as pd
import pytest

from core.research.mining_v4_daily_snapshot import (
    repair_known_plus_one_day_shift,
    resolve_raw_daily_source,
    validate_raw_daily,
)


def _frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({
        "open": [10.0] * len(index),
        "high": [11.0] * len(index),
        "low": [9.0] * len(index),
        "close": [10.5] * len(index),
        "volume": [100.0] * len(index),
    }, index=index)


def test_known_plus_one_shift_requires_and_removes_weekend_signature():
    sessions = pd.DatetimeIndex(["2024-01-05", "2024-01-08"])
    shifted = _frame(pd.DatetimeIndex(["2024-01-06", "2024-01-09"]))
    repaired = repair_known_plus_one_day_shift(
        shifted, symbol="ABC", benchmark_sessions=sessions)
    assert repaired.index.equals(sessions)


def test_shift_refuses_clean_source():
    sessions = pd.DatetimeIndex(["2024-01-05", "2024-01-08"])
    with pytest.raises(ValueError, match="no weekend signature"):
        repair_known_plus_one_day_shift(
            _frame(sessions), symbol="ABC", benchmark_sessions=sessions)


def test_validation_rejects_non_benchmark_weekday():
    sessions = pd.DatetimeIndex(["2024-01-05", "2024-01-08"])
    with pytest.raises(ValueError, match="outside benchmark"):
        validate_raw_daily(
            _frame(pd.DatetimeIndex(["2024-01-04"])),
            symbol="ABC",
            benchmark_sessions=sessions,
        )


def test_phase4_source_must_use_retained_raw_sidecar(tmp_path: Path):
    (tmp_path / "ABC.parquet").touch()
    backup = tmp_path / "ABC.parquet.preP4Expand_20260516_000000Z"
    backup.touch()
    resolved = resolve_raw_daily_source(
        tmp_path, "ABC", phase4_preadjusted=True)
    assert resolved.path == backup
    assert resolved.transform.startswith("KNOWN_PLUS_ONE")
