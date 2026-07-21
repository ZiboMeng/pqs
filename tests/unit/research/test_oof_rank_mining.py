from __future__ import annotations

import numpy as np
import pandas as pd

from core.research.ml.pipeline import WalkForwardConfig
from core.research.oof_rank_mining import RuleRankModel, run_oof_rank_mining


def test_rule_rank_model_respects_feature_orientation():
    index = pd.DatetimeIndex(["2024-01-31"])
    columns = ["A", "B", "C"]
    features = {
        "momentum": pd.DataFrame([[1.0, 2.0, 3.0]], index=index, columns=columns),
        "volatility": pd.DataFrame([[3.0, 2.0, 1.0]], index=index, columns=columns),
    }
    model = RuleRankModel({"momentum": 1.0, "volatility": -1.0})
    model.fit(features, pd.DataFrame(index=index, columns=columns))
    prediction = model.predict_rank(features)
    assert prediction.loc[index[0], "C"] == 1.0
    assert prediction.loc[index[0], "A"] < prediction.loc[index[0], "C"]


def test_oof_predictions_exist_only_in_validation_windows():
    daily_index = pd.bdate_range("2010-01-01", "2017-12-31")
    monthly = pd.DatetimeIndex(
        pd.Series(daily_index, index=daily_index)
        .groupby([daily_index.year, daily_index.month]).last().to_numpy()
    )
    columns = [f"S{i}" for i in range(6)]
    rng = np.random.default_rng(3)
    feature = pd.DataFrame(
        rng.normal(size=(len(monthly), len(columns))),
        index=monthly,
        columns=columns,
    )
    labels = feature + pd.DataFrame(
        rng.normal(scale=0.1, size=feature.shape),
        index=monthly,
        columns=columns,
    )
    eligibility = pd.DataFrame(True, index=monthly, columns=columns)
    config = WalkForwardConfig(
        start_year=2010,
        end_year=2017,
        train_window_years=5,
        val_window_years=1,
        step_years=1,
        embargo_days=21,
    )
    result = run_oof_rank_mining(
        lambda: RuleRankModel({"signal": 1.0}),
        config,
        {"signal": feature},
        labels,
        eligibility,
        daily_trading_index=daily_index,
        cluster_features=False,
        sealed_years=(),
    )
    assert result.successful_folds == 3
    assert result.predictions.loc[result.predictions.index.year < 2015].isna().all().all()
    assert result.predictions.loc[result.predictions.index.year >= 2015].notna().all().all()
    assert all(fold.rank_ic > 0.8 for fold in result.folds)


def test_empty_validation_cross_section_is_a_failed_fold_not_zero_ic_success():
    daily_index = pd.bdate_range("2010-01-01", "2015-12-31")
    monthly = pd.DatetimeIndex(
        pd.Series(daily_index, index=daily_index)
        .groupby([daily_index.year, daily_index.month]).last().to_numpy()
    )
    columns = ["A", "B", "C"]
    feature = pd.DataFrame(1.0, index=monthly, columns=columns)
    labels = feature.copy()
    labels.loc[labels.index.year == 2015] = np.nan
    eligibility = pd.DataFrame(True, index=monthly, columns=columns)
    result = run_oof_rank_mining(
        lambda: RuleRankModel({"signal": 1.0}),
        WalkForwardConfig(
            start_year=2010,
            end_year=2015,
            train_window_years=5,
            val_window_years=1,
            step_years=1,
        ),
        {"signal": feature},
        labels,
        eligibility,
        daily_trading_index=daily_index,
        cluster_features=False,
        sealed_years=(),
    )
    assert result.successful_folds == 0
    assert result.folds[0].validation_observations == 0
    assert "no cross-section" in str(result.folds[0].error)
