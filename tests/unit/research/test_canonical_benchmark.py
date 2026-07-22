from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from core.research.canonical_benchmark import build_canonical_spy_payload


def test_canonical_benchmark_reinvests_cash_and_rejects_cash_held_control(
    tmp_path: Path,
) -> None:
    sessions = pd.bdate_range("2020-01-02", periods=6)
    close = pd.Series([100.0, 101.0, 99.0, 100.0, 102.0, 103.0], index=sessions)
    cash = pd.Series([0.0, 0.0, 2.0, 0.0, 0.0, 0.0], index=sessions)
    gross = close.add(cash).div(close.shift(1))
    gross.iloc[0] = 1.0
    frame = pd.DataFrame({
        "close": close,
        "cash_distribution": cash,
        "total_return_close": close.iloc[0] * gross.cumprod(),
    })
    source = tmp_path / "SPY.parquet"
    frame.to_parquet(source)
    payload = build_canonical_spy_payload(
        source,
        evaluation_start=date(2020, 1, 3),
        evaluation_end=sessions[-1].date(),
    )
    assert payload["parity"]["passed"] is True
    assert payload["parity"]["distribution_events"] == 1
    assert payload["parity"]["dividend_cash_negative_control_passed"] is True
    assert payload["returns_sha256"]
