"""Round 9 Topic H (2026-04-20): smoke tests for model_comparison script.

These are light-weight smoke tests that verify the script's helper
functions return sensible shapes without invoking the full real-data
pipeline (which takes ~1 minute and requires loaded panels).

The real validation IS the `scripts/run_model_comparison.py` output
captured in the round commit; these tests just guard against silent
regressions in the helper contracts.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def _panel():
    """Small synthetic panel: 50 dates × 3 symbols × 4 factors."""
    np.random.seed(42)
    rows = []
    for d in pd.bdate_range("2024-01-02", periods=50):
        for sym in ("AAPL", "MSFT", "NVDA"):
            rows.append({
                "date": d, "symbol": sym,
                "fwd_return": np.random.normal(0.001, 0.02),
                "f1": np.random.normal(0, 1),
                "f2": np.random.normal(0, 1),
                "f3": np.random.normal(0, 1),
                "f4": np.random.normal(0, 1),
            })
    return pd.DataFrame(rows)


def test_train_ridge_returns_model_with_alpha(_panel):
    from scripts.run_model_comparison import _train_ridge
    X = _panel[["f1", "f2", "f3", "f4"]]
    y = _panel["fwd_return"]
    model, alpha = _train_ridge(X, y)
    assert alpha > 0
    # Model can predict
    pred = model.predict(X.values)
    assert pred.shape == (len(X),)


def test_perm_importance_returns_series_with_features(_panel):
    from scripts.run_model_comparison import _train_ridge, _perm_importance
    feat_cols = ["f1", "f2", "f3", "f4"]
    X = _panel[feat_cols]
    y = _panel["fwd_return"]
    split = len(X) // 2
    X_tr, X_te = X.iloc[:split], X.iloc[split:]
    y_tr, y_te = y.iloc[:split], y.iloc[split:]
    model, _ = _train_ridge(X_tr, y_tr)
    imp = _perm_importance(model, X_te, y_te)
    assert set(imp.index) == set(feat_cols)
    assert len(imp) == len(feat_cols)


def test_rank_correlation_perfect_agreement(_panel):
    from scripts.run_model_comparison import _rank_correlation
    a = pd.Series([0.5, 0.3, 0.1, 0.8], index=["A", "B", "C", "D"])
    b = pd.Series([0.4, 0.2, 0.05, 0.7], index=["A", "B", "C", "D"])
    rho = _rank_correlation(a, b)
    assert abs(rho - 1.0) < 1e-6  # same ordering

def test_rank_correlation_reverse_disagreement(_panel):
    from scripts.run_model_comparison import _rank_correlation
    a = pd.Series([1.0, 2.0, 3.0, 4.0], index=["A", "B", "C", "D"])
    b = pd.Series([4.0, 3.0, 2.0, 1.0], index=["A", "B", "C", "D"])
    rho = _rank_correlation(a, b)
    assert abs(rho - (-1.0)) < 1e-6  # opposite ordering
