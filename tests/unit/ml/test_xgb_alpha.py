"""Unit tests for core.ml.xgb_alpha.

Per `docs/prd/20260512-ml_mining_pipeline_prd.md` §3.6.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("xgboost")

from core.ml.xgb_alpha import (
    XGBAlphaModel,
    compute_rank_ic,
    leave_one_train_year_out_cv,
    train_full_then_predict,
)


def _toy_ml_panel(years: list[int], n_per_year: int = 80, seed: int = 42):
    """Toy panel with `years` × n_per_year rows × 5 factors. A linear
    factor combination drives the target so XGBoost can find signal."""
    np.random.seed(seed)
    rows = []
    for yr in years:
        dates = pd.date_range(f"{yr}-01-02", periods=n_per_year // 6, freq="W-MON")
        syms = ["A", "B", "C", "D", "E", "F"]
        for d in dates:
            for s in syms:
                f1, f2, f3, f4, f5 = np.random.rand(5)
                # target = f1 - f2 + noise
                y = f1 - f2 + 0.05 * np.random.randn()
                rows.append({
                    "date": d, "symbol": s,
                    "f1": f1, "f2": f2, "f3": f3, "f4": f4, "f5": f5,
                    "fwd_return": y,
                })
    return pd.DataFrame(rows)


def test_xgb_alpha_model_fit_predict():
    """Basic fit/predict produces same-length output."""
    df = _toy_ml_panel([2015, 2016])
    feats = ["f1", "f2", "f3", "f4", "f5"]
    model = XGBAlphaModel(n_estimators=20, max_depth=3)
    model.fit(df, df["fwd_return"], feature_cols=feats)
    yp = model.predict(df)
    assert yp.shape == (len(df),)


def test_xgb_alpha_model_early_stopping():
    """When eval set provided, best_iteration is populated."""
    df_train = _toy_ml_panel([2015, 2016])
    df_val = _toy_ml_panel([2017], seed=99)
    feats = ["f1", "f2", "f3", "f4", "f5"]
    model = XGBAlphaModel(n_estimators=100, max_depth=3, early_stopping_rounds=5)
    model.fit(df_train, df_train["fwd_return"],
              X_val=df_val, y_val=df_val["fwd_return"], feature_cols=feats)
    assert model.best_iteration is not None


def test_xgb_alpha_feature_importance():
    """Feature importance is sortable and contains all features."""
    df = _toy_ml_panel([2015])
    feats = ["f1", "f2", "f3", "f4", "f5"]
    model = XGBAlphaModel(n_estimators=30, max_depth=3)
    model.fit(df, df["fwd_return"], feature_cols=feats)
    imp = model.feature_importance()
    # f1 and f2 should be most important (they drive the target)
    assert imp.index[0] in {"f1", "f2"}


def test_compute_rank_ic_perfect_match():
    """Predicted = true → IC = 1.0 per date."""
    dates = pd.Series(pd.date_range("2020-01-01", periods=10).repeat(5))
    y_true = pd.Series(np.tile(np.arange(5, dtype=float), 10))
    y_pred = y_true.values
    mean_ic, ic_std, ic_series = compute_rank_ic(y_true, y_pred, dates)
    assert mean_ic == pytest.approx(1.0, abs=0.01)


def test_compute_rank_ic_negative():
    """Predicted = -true → IC = -1.0 per date."""
    dates = pd.Series(pd.date_range("2020-01-01", periods=10).repeat(5))
    y_true = pd.Series(np.tile(np.arange(5, dtype=float), 10))
    y_pred = -y_true.values
    mean_ic, _, _ = compute_rank_ic(y_true, y_pred, dates)
    assert mean_ic == pytest.approx(-1.0, abs=0.01)


def test_compute_rank_ic_skips_small_groups():
    """Dates with <5 stocks are excluded."""
    dates = pd.Series([pd.Timestamp("2020-01-01")] * 3 +
                       [pd.Timestamp("2020-01-02")] * 6)
    y_true = pd.Series([1, 2, 3, 1, 2, 3, 4, 5, 6], dtype=float)
    y_pred = np.array([1, 2, 3, 1, 2, 3, 4, 5, 6], dtype=float)
    mean_ic, _, ic_series = compute_rank_ic(y_true, y_pred, dates)
    # First date has only 3 stocks → skipped; only 2020-01-02 contributes
    assert len(ic_series) == 1
    assert ic_series.iloc[0] == pytest.approx(1.0, abs=0.01)


def test_lotyo_cv_basic():
    """LOTYO produces one fold per train year."""
    panel = _toy_ml_panel([2015, 2016, 2017])
    feats = ["f1", "f2", "f3", "f4", "f5"]
    fold_metrics, ic_table = leave_one_train_year_out_cv(
        panel, feats, train_years=[2015, 2016, 2017],
        model_kwargs={"n_estimators": 20, "max_depth": 3},
        inner_val_year=2017,
    )
    # All 3 folds attempted (when y_test=2017, no inner val; when y_test!=2017, val used)
    assert len(fold_metrics) == 3
    assert set(fold_metrics.keys()) == {2015, 2016, 2017}


def test_lotyo_cv_finds_signal():
    """With f1-f2 driving y, LOTYO should produce positive IC."""
    panel = _toy_ml_panel([2015, 2016, 2017], n_per_year=200)
    feats = ["f1", "f2", "f3", "f4", "f5"]
    fold_metrics, ic_table = leave_one_train_year_out_cv(
        panel, feats, train_years=[2015, 2016, 2017],
        model_kwargs={"n_estimators": 50, "max_depth": 3},
    )
    mean_ic = ic_table["ic_mean"].mean()
    # Toy signal-strong panel → IC should be clearly positive
    assert mean_ic > 0.1, f"expected mean_ic > 0.1, got {mean_ic:.3f}"


def test_lotyo_cv_handles_empty_train_years():
    """Empty train_years list returns empty result."""
    panel = _toy_ml_panel([2015])
    fold_metrics, ic_table = leave_one_train_year_out_cv(
        panel, ["f1"], train_years=[2099],
    )
    assert len(fold_metrics) == 0


def test_train_full_then_predict():
    """train_full_then_predict produces predictions for predict_years."""
    panel = _toy_ml_panel([2015, 2016, 2017, 2018])
    feats = ["f1", "f2", "f3", "f4", "f5"]
    model, preds = train_full_then_predict(
        panel, feats,
        train_years=[2015, 2016, 2017], predict_years=[2018],
        model_kwargs={"n_estimators": 20, "max_depth": 3},
        inner_val_year=2017,
    )
    assert "y_pred" in preds.columns
    assert preds["date"].dt.year.unique().tolist() == [2018]


def test_xgb_alpha_handles_nan_features():
    """XGBoost native NaN handling — no imputation required."""
    df = _toy_ml_panel([2015])
    df.loc[df.index[:10], "f3"] = np.nan
    feats = ["f1", "f2", "f3", "f4", "f5"]
    model = XGBAlphaModel(n_estimators=15, max_depth=3)
    # Should not raise
    model.fit(df, df["fwd_return"], feature_cols=feats)
    yp = model.predict(df)
    assert not np.isnan(yp).any()
