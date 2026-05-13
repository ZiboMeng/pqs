"""Unit tests for core.ml.xgb_ranking — Phase 1.6 objectives.

Per `docs/memos/20260513-ml_phase_1_5_closeout.md` §6 hypothesis +
WebSearch 2026-05-13 SOTA literature finding (LambdaRankIC, learning-to-rank
3× Sharpe boost vs MSE baseline).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("xgboost")

from core.ml.xgb_ranking import (
    LambdaRankICModel,
    XGBQuintileModel,
    XGBRankingModel,
    build_qid_groups,
    cross_sectional_quintile_target,
    cross_sectional_rank_target,
)


def _toy_panel(years: list[int], n_stocks: int = 30, n_factors: int = 8, seed: int = 42):
    """Toy ML panel with cross-sectional rank features + target where
    factor_0 strongly predicts forward return."""
    np.random.seed(seed)
    rows = []
    for yr in years:
        dates = pd.date_range(f"{yr}-01-02", periods=24, freq="W-MON")
        syms = [f"S{i}" for i in range(n_stocks)]
        for d in dates:
            # Per-date factor matrix
            factor_vals = np.random.randn(n_stocks, n_factors)
            # Target = linear combo of factor_0 + noise
            fwd_ret = 0.5 * factor_vals[:, 0] + 0.1 * np.random.randn(n_stocks)
            for s_idx, sym in enumerate(syms):
                row = {"date": d, "symbol": sym, "fwd_return": fwd_ret[s_idx]}
                for f_idx in range(n_factors):
                    row[f"factor_{f_idx}"] = factor_vals[s_idx, f_idx]
                rows.append(row)
    return pd.DataFrame(rows)


# ── build_qid_groups ────────────────────────────────────────────────────


def test_build_qid_groups_basic():
    panel = _toy_panel([2020])
    sorted_panel, qid, gsizes = build_qid_groups(panel)
    assert len(qid) == len(panel)
    assert qid[0] == 0
    assert qid[-1] == len(gsizes) - 1
    # All qid sorted non-decreasing
    assert np.all(np.diff(qid) >= 0)
    # Group sizes sum to panel size
    assert gsizes.sum() == len(panel)


def test_build_qid_groups_deterministic_symbol_order():
    panel = _toy_panel([2020])
    sorted_a, _, _ = build_qid_groups(panel)
    sorted_b, _, _ = build_qid_groups(panel.sample(frac=1, random_state=0))
    pd.testing.assert_frame_equal(
        sorted_a.reset_index(drop=True),
        sorted_b.reset_index(drop=True),
    )


# ── cross-sectional targets ─────────────────────────────────────────────


def test_cross_sectional_rank_target_in_unit_interval():
    panel = _toy_panel([2020])
    y_rank = cross_sectional_rank_target(panel)
    assert (y_rank >= 0).all() and (y_rank <= 1).all()
    # Per-date should sum to roughly n*(n+1)/2 / n = (n+1)/2 over n stocks
    # but easier check: each date has rank in [1/n, 1] when no ties
    panel_sorted = panel.sort_values(["date", "symbol"]).reset_index(drop=True)
    panel_sorted["y_rank"] = cross_sectional_rank_target(panel_sorted)
    for date, grp in panel_sorted.groupby("date"):
        n = len(grp)
        assert grp["y_rank"].min() >= 1 / n - 1e-9
        assert grp["y_rank"].max() <= 1 + 1e-9


def test_cross_sectional_quintile_target_5_classes():
    panel = _toy_panel([2020], n_stocks=50)
    labels = cross_sectional_quintile_target(panel, n_quintiles=5)
    assert set(labels[labels >= 0]).issubset({0, 1, 2, 3, 4})
    # Each date should have ~equal distribution across 5 quintiles
    panel_sorted = panel.sort_values(["date", "symbol"]).reset_index(drop=True)
    panel_sorted["label"] = cross_sectional_quintile_target(panel_sorted, n_quintiles=5)
    for date, grp in panel_sorted.groupby("date"):
        counts = grp["label"].value_counts()
        assert len(counts) == 5  # all 5 classes represented
        # Roughly balanced (10 per class for 50 stocks)
        assert counts.max() - counts.min() <= 2


# ── XGBRankingModel ─────────────────────────────────────────────────────


@pytest.mark.parametrize("objective", ["rank:pairwise", "rank:ndcg"])
def test_xgb_ranking_model_fits_and_predicts(objective):
    train = _toy_panel([2020, 2021])
    val = _toy_panel([2022], seed=43)
    feature_cols = [f"factor_{i}" for i in range(8)]
    model = XGBRankingModel(
        objective=objective, n_estimators=20, max_depth=3, learning_rate=0.1,
        early_stopping_rounds=10,
    )
    model.fit(train, train["fwd_return"], val_panel=val, y_val=val["fwd_return"],
              feature_cols=feature_cols)
    pred = model.predict(val)
    assert pred.shape == (len(val),)
    assert np.isfinite(pred).all()


def test_xgb_ranking_model_invalid_objective_raises():
    with pytest.raises(ValueError, match="objective must be"):
        XGBRankingModel(objective="reg:squarederror")


def test_xgb_ranking_recovers_factor_0_signal():
    """With factor_0 driving target, ranking model should learn IC > 0."""
    train = _toy_panel([2020, 2021])
    val = _toy_panel([2022], seed=43)
    feature_cols = [f"factor_{i}" for i in range(8)]
    model = XGBRankingModel(
        objective="rank:pairwise", n_estimators=50, max_depth=3,
        learning_rate=0.1, early_stopping_rounds=10,
    )
    model.fit(train, train["fwd_return"], val_panel=val, y_val=val["fwd_return"],
              feature_cols=feature_cols)
    pred = model.predict(val)
    # Spearman corr between predictions and true fwd_return > 0
    from scipy.stats import spearmanr
    rho, _ = spearmanr(pred, val["fwd_return"].values)
    assert rho > 0.1, f"Expected positive IC (factor_0 dominant), got {rho:.3f}"


# ── XGBQuintileModel ────────────────────────────────────────────────────


def test_quintile_model_fits_and_predicts_top_proba():
    train = _toy_panel([2020, 2021], n_stocks=50)
    val = _toy_panel([2022], n_stocks=50, seed=43)
    feature_cols = [f"factor_{i}" for i in range(8)]
    model = XGBQuintileModel(
        n_estimators=20, max_depth=3, learning_rate=0.1,
        early_stopping_rounds=10, n_quintiles=5,
    )
    model.fit(train, train["fwd_return"], val_panel=val, y_val=val["fwd_return"],
              feature_cols=feature_cols)
    pred = model.predict(val)
    assert pred.shape == (len(val),)
    # Probabilities in [0, 1]
    assert (pred >= 0).all() and (pred <= 1).all()


def test_quintile_model_top_proba_correlates_with_factor_0():
    """Top-quintile probability should correlate with factor_0 driver."""
    train = _toy_panel([2020, 2021], n_stocks=50)
    val = _toy_panel([2022], n_stocks=50, seed=43)
    feature_cols = [f"factor_{i}" for i in range(8)]
    model = XGBQuintileModel(
        n_estimators=50, max_depth=3, learning_rate=0.1,
        early_stopping_rounds=10, n_quintiles=5,
    )
    model.fit(train, train["fwd_return"], val_panel=val, y_val=val["fwd_return"],
              feature_cols=feature_cols)
    pred = model.predict(val)
    from scipy.stats import spearmanr
    rho, _ = spearmanr(pred, val["factor_0"].values)
    assert rho > 0.1, f"Expected pred correlated with factor_0, got {rho:.3f}"


# ── LambdaRankICModel ───────────────────────────────────────────────────


def test_lambda_rank_ic_model_fits_and_predicts():
    train = _toy_panel([2020, 2021], n_stocks=20)
    val = _toy_panel([2022], n_stocks=20, seed=43)
    feature_cols = [f"factor_{i}" for i in range(8)]
    model = LambdaRankICModel(
        n_estimators=10, max_depth=3, learning_rate=0.1,
        early_stopping_rounds=5,
    )
    model.fit(train, train["fwd_return"], val_panel=val, y_val=val["fwd_return"],
              feature_cols=feature_cols)
    pred = model.predict(val)
    assert pred.shape == (len(val),)
    assert np.isfinite(pred).all()


def test_lambda_rank_ic_recovers_signal_when_factor_0_dominant():
    """With factor_0 driving target, LambdaRankIC should learn positive IC.

    Smaller test (~20 stocks × 48 weeks ≈ 960 rows / fold) keeps wall-clock
    < 30s while still being a real-signal test.
    """
    train = _toy_panel([2020, 2021], n_stocks=20)
    val = _toy_panel([2022], n_stocks=20, seed=43)
    feature_cols = [f"factor_{i}" for i in range(8)]
    model = LambdaRankICModel(
        n_estimators=20, max_depth=3, learning_rate=0.2,
        early_stopping_rounds=10,
    )
    model.fit(train, train["fwd_return"], val_panel=val, y_val=val["fwd_return"],
              feature_cols=feature_cols)
    pred = model.predict(val)
    from scipy.stats import spearmanr
    rho, _ = spearmanr(pred, val["fwd_return"].values)
    # Less strict threshold given smaller training data
    assert rho > 0.05, f"Expected positive IC (factor_0 dominant), got {rho:.3f}"


# ── Cross-objective consistency ─────────────────────────────────────────


def test_objectives_all_produce_finite_predictions():
    """All 3 Phase 1.6 objectives + baseline should produce finite preds."""
    train = _toy_panel([2020, 2021])
    val = _toy_panel([2022], seed=43)
    feature_cols = [f"factor_{i}" for i in range(8)]

    models = [
        XGBRankingModel(objective="rank:pairwise", n_estimators=10, max_depth=3,
                        learning_rate=0.1, early_stopping_rounds=5),
        XGBRankingModel(objective="rank:ndcg", n_estimators=10, max_depth=3,
                        learning_rate=0.1, early_stopping_rounds=5),
        XGBQuintileModel(n_estimators=10, max_depth=3, learning_rate=0.1,
                         early_stopping_rounds=5),
    ]
    for m in models:
        m.fit(train, train["fwd_return"], val_panel=val, y_val=val["fwd_return"],
              feature_cols=feature_cols)
        pred = m.predict(val)
        assert pred.shape == (len(val),)
        assert np.isfinite(pred).all(), f"{type(m).__name__} produced non-finite"
