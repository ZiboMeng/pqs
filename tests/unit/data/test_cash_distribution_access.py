from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from core.data.cash_distribution_access import (
    build_total_return_close_panel,
    load_cash_distribution_panel,
)


def _sidecars(root: Path, index: pd.DatetimeIndex) -> None:
    ref = root / "ref"
    ref.mkdir()
    pd.DataFrame({"symbol": [], "date": [], "ratio": []}).to_parquet(
        ref / "splits.parquet"
    )
    split_sha = hashlib.sha256((ref / "splits.parquet").read_bytes()).hexdigest()[:16]
    pd.DataFrame({
        "symbol": ["SPY"],
        "ex_date": [index[1]],
        "cash_amount": [2.0],
        "splits_table_sha": [split_sha],
    }).to_parquet(ref / "distributions.parquet")
    coverage = pd.DataFrame({
        "symbol": ["SPY"],
        "checked_start": [index.min()],
        "checked_end": [index.max()],
        "checked_at": [index.max()],
        "status": ["OK"],
        "splits_table_sha": [split_sha],
    })
    coverage.to_parquet(ref / "distribution_coverage.parquet")
    coverage.to_parquet(ref / "split_coverage.parquet")


def test_exact_cash_panel_and_total_return_recurrence(tmp_path: Path) -> None:
    index = pd.bdate_range("2024-01-02", periods=3)
    _sidecars(tmp_path, index)
    cash = load_cash_distribution_panel(tmp_path, ["SPY"], index)
    close = pd.DataFrame({"SPY": [100.0, 99.0, 100.0]}, index=index)
    total_return = build_total_return_close_panel(close, cash)
    assert cash.loc[index[1], "SPY"] == pytest.approx(2.0)
    assert total_return.loc[index[1], "SPY"] == pytest.approx(101.0)
    assert total_return.loc[index[2], "SPY"] == pytest.approx(101.0 * 100.0 / 99.0)


def test_missing_distribution_coverage_fails_closed(tmp_path: Path) -> None:
    index = pd.bdate_range("2024-01-02", periods=3)
    (tmp_path / "ref").mkdir()
    with pytest.raises(Exception, match="sidecar|coverage"):
        load_cash_distribution_panel(tmp_path, ["SPY"], index)
