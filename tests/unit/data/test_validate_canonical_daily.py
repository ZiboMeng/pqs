from __future__ import annotations

import pandas as pd

from dev.scripts.data_integrity.validate_canonical_daily import max_return_difference


def test_return_difference_ignores_level_scaling() -> None:
    index = pd.bdate_range("2024-01-02", periods=4)
    left = pd.Series([100.0, 101.0, 99.0, 102.0], index=index)
    right = left * 2.5
    assert max_return_difference(left, right) < 1e-15
