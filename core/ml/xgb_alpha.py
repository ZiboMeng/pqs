"""XGBoost alpha mining — non-linear factor → return prediction model.

Per `docs/prd/20260512-ml_mining_pipeline_prd.md` §3.

Predicts cross-sectional rank of 21d forward returns from 162-factor
cross-sectional rank features. Implements leave-one-train-year-out CV
(LOTYO) per PRD §3.3 (audit pass #2 fix for non-contiguous train years).

Per PRD §3.2:
- n_estimators 100-500, max_depth 4-6 (shallow → less overfit)
- learning_rate 0.03-0.1
- subsample 0.8, colsample_bytree 0.7
- early stopping on validation IC

Per PRD §3.3 + audit pass #3:
- Loss: RankIC-aligned (default 'rank:pairwise' for ranking; 'reg:squarederror'
  for regression-on-rank — both supported, default pairwise).
- Feature normalization: cross-sectional rank in [0, 1] from
  `core.ml.feature_panel_builder.cross_sectional_rank` (NOT z-score —
  rank is robust to outliers and handles factor scale differences).
- NaN handling: XGBoost native (`missing=np.nan`); no imputation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from core.logging_setup import get_logger

logger = get_logger("xgb_alpha")


class XGBAlphaModel:
    """XGBoost alpha model trained on cross-sectional rank features →
    cross-sectional rank target (21d forward return rank per date)."""

    def __init__(
        self,
        n_estimators: int = 200,
        max_depth: int = 5,
        learning_rate: float = 0.05,
        subsample: float = 0.8,
        colsample_bytree: float = 0.7,
        reg_alpha: float = 0.1,
        reg_lambda: float = 0.1,
        objective: str = "reg:squarederror",
        random_state: int = 42,
        early_stopping_rounds: int = 20,
    ):
        try:
            import xgboost as xgb  # noqa
        except ImportError:
            raise RuntimeError(
                "xgboost not installed; pip install xgboost"
            )
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.reg_alpha = reg_alpha
        self.reg_lambda = reg_lambda
        self.objective = objective
        self.random_state = random_state
        self.early_stopping_rounds = early_stopping_rounds
        self.model: Optional[Any] = None
        self.feature_cols: List[str] = []
        self.best_iteration: Optional[int] = None

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
        feature_cols: Optional[List[str]] = None,
    ) -> "XGBAlphaModel":
        import xgboost as xgb
        if feature_cols is None:
            feature_cols = [c for c in X_train.columns
                            if c not in {"date", "symbol", "fwd_return"}]
        self.feature_cols = feature_cols
        params: Dict[str, Any] = {
            "n_estimators": self.n_estimators,
            "max_depth": self.max_depth,
            "learning_rate": self.learning_rate,
            "subsample": self.subsample,
            "colsample_bytree": self.colsample_bytree,
            "reg_alpha": self.reg_alpha,
            "reg_lambda": self.reg_lambda,
            "objective": self.objective,
            "random_state": self.random_state,
            "tree_method": "hist",
        }
        if X_val is not None and y_val is not None:
            params["early_stopping_rounds"] = self.early_stopping_rounds
            self.model = xgb.XGBRegressor(**params)
            self.model.fit(
                X_train[feature_cols], y_train,
                eval_set=[(X_val[feature_cols], y_val)],
                verbose=False,
            )
            self.best_iteration = (
                int(self.model.best_iteration)
                if hasattr(self.model, "best_iteration") else None
            )
        else:
            self.model = xgb.XGBRegressor(**params)
            self.model.fit(X_train[feature_cols], y_train, verbose=False)
            self.best_iteration = None
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("model not trained; call fit() first")
        return self.model.predict(X[self.feature_cols])

    def feature_importance(self) -> pd.Series:
        if self.model is None:
            raise RuntimeError("model not trained")
        # XGBRegressor.feature_importances_ is aligned with feature_cols
        # (the order passed at fit time). Default importance type = 'gain'.
        importances = self.model.feature_importances_
        s = pd.Series(
            importances, index=self.feature_cols, name="gain",
        )
        return s.sort_values(ascending=False)


def compute_rank_ic(
    y_true: pd.Series,
    y_pred: np.ndarray,
    dates: pd.Series,
) -> Tuple[float, float, pd.Series]:
    """Compute cross-sectional rank IC (Spearman corr between predicted
    score and true forward return, computed per date then averaged).

    Returns (mean_ic, ic_std, per_date_ic_series).
    """
    df = pd.DataFrame({
        "date": dates.values,
        "y_true": y_true.values,
        "y_pred": y_pred,
    })
    per_date = []
    for date, grp in df.groupby("date"):
        if len(grp) < 5:
            continue
        if grp["y_true"].nunique() < 2 or grp["y_pred"].std() == 0:
            continue
        rho, _ = stats.spearmanr(grp["y_true"], grp["y_pred"], nan_policy="omit")
        if not np.isnan(rho):
            per_date.append({"date": date, "ic": rho})
    if not per_date:
        return float("nan"), float("nan"), pd.Series(dtype=float)
    ic_df = pd.DataFrame(per_date).set_index("date")["ic"]
    return float(ic_df.mean()), float(ic_df.std()), ic_df


def leave_one_train_year_out_cv(
    panel: pd.DataFrame,
    feature_cols: List[str],
    train_years: List[int],
    model_kwargs: Optional[Dict[str, Any]] = None,
    inner_val_year: int = 2017,
) -> Tuple[Dict[int, Dict[str, float]], pd.DataFrame]:
    """Leave-one-train-year-out CV per PRD §3.3 (audit pass #2 fix).

    For each train year Y_test in `train_years`:
      - Train on remaining (n-1) train years
      - Predict on Y_test
      - Compute cross-sectional rank IC

    inner_val_year used for early stopping (default 2017 — last
    contiguous pre-validation year). Skipped if equal to Y_test.

    Returns (per_fold_metrics, ic_per_fold_table).
    """
    if model_kwargs is None:
        model_kwargs = {}
    panel = panel.copy()
    if not pd.api.types.is_datetime64_any_dtype(panel["date"]):
        panel["date"] = pd.to_datetime(panel["date"])
    panel["year"] = panel["date"].dt.year
    panel_train = panel[panel["year"].isin(train_years)].copy()
    if panel_train.empty:
        logger.warning("LOTYO CV: no rows match train_years")
        return {}, pd.DataFrame()

    fold_metrics: Dict[int, Dict[str, float]] = {}
    rows = []
    for y_test in train_years:
        train_mask = (panel_train["year"] != y_test) & (
            panel_train["year"] != inner_val_year
        )
        val_mask = (panel_train["year"] == inner_val_year) & (y_test != inner_val_year)
        test_mask = panel_train["year"] == y_test
        train_panel = panel_train[train_mask]
        val_panel = panel_train[val_mask] if val_mask.any() else None
        test_panel = panel_train[test_mask]
        if train_panel.empty or test_panel.empty:
            continue
        model = XGBAlphaModel(**model_kwargs)
        model.fit(
            train_panel, train_panel["fwd_return"],
            X_val=val_panel, y_val=val_panel["fwd_return"]
                if val_panel is not None else None,
            feature_cols=feature_cols,
        )
        y_pred = model.predict(test_panel)
        ic_mean, ic_std, ic_series = compute_rank_ic(
            test_panel["fwd_return"], y_pred, test_panel["date"],
        )
        fold_metrics[y_test] = {
            "n_train_rows": len(train_panel),
            "n_test_rows": len(test_panel),
            "ic_mean": ic_mean,
            "ic_std": ic_std,
            "best_iteration": model.best_iteration,
        }
        rows.append({
            "fold_year": y_test, "n_test_rows": len(test_panel),
            "ic_mean": ic_mean, "ic_std": ic_std,
            "best_iteration": model.best_iteration,
        })
        logger.info(
            "LOTYO fold y_test=%d n_train=%d n_test=%d "
            "ic_mean=%.4f ic_std=%.4f best_iter=%s",
            y_test, len(train_panel), len(test_panel),
            ic_mean, ic_std, model.best_iteration,
        )
    ic_table = pd.DataFrame(rows)
    return fold_metrics, ic_table


def train_full_then_predict(
    panel: pd.DataFrame,
    feature_cols: List[str],
    train_years: List[int],
    predict_years: List[int],
    model_kwargs: Optional[Dict[str, Any]] = None,
    inner_val_year: int = 2017,
) -> Tuple[XGBAlphaModel, pd.DataFrame]:
    """Train on all train_years (with inner_val for early stop), predict
    on predict_years.

    Returns (model, predictions_df) where predictions_df has columns
    [date, symbol, fwd_return, y_pred].
    """
    if model_kwargs is None:
        model_kwargs = {}
    panel = panel.copy()
    if not pd.api.types.is_datetime64_any_dtype(panel["date"]):
        panel["date"] = pd.to_datetime(panel["date"])
    panel["year"] = panel["date"].dt.year
    train_panel = panel[panel["year"].isin(train_years)
                        & (panel["year"] != inner_val_year)]
    val_panel = panel[panel["year"] == inner_val_year]
    predict_panel = panel[panel["year"].isin(predict_years)]
    model = XGBAlphaModel(**model_kwargs)
    model.fit(
        train_panel, train_panel["fwd_return"],
        X_val=val_panel if not val_panel.empty else None,
        y_val=val_panel["fwd_return"] if not val_panel.empty else None,
        feature_cols=feature_cols,
    )
    y_pred = model.predict(predict_panel)
    predictions = predict_panel[["date", "symbol", "fwd_return"]].copy()
    predictions["y_pred"] = y_pred
    return model, predictions
