"""PRD-3 RB1/RB2 — B1 intraday engineered features + shallow XGB.

Honest scope (R4/R6/R7): intraday-REVERSAL is already canonically
implemented (``core.factors.intraday_factor_bundle.
build_intraday_reversal_factor_bundle``, locked PRD 20260512);
VWAP is in ``core.intraday.sr_volume_profile``; shallow XGBoost
with sample_weight is ``core.ml.xgb_alpha.XGBAlphaModel`` (RA2
additive passthrough). DELEGATED, NOT reimplemented. The
genuinely-new RB2 surface is (a) the cross-name differentiated
primitives the PRD-3 §2-B archetype list calls out (open-range
breakout, VWAP deviation, realized-vol regime, intraday volume z)
as **scalar per-(date,symbol) summaries** of a day's intraday bars
+ (b) the thin ``train_b1`` pipeline that ROUTES through the RB1
gate (``component_b_gate.assert_archetype_differentiated`` —
naive-archetype refuser) and the RA2 shallow XGB.

Each primitive takes a single day's intraday OHLCV bars
``(T, 5)`` and returns ONE scalar (the day's summary); causal by
construction (a function of that day's bars only). RB2 is a build
round — RB3 is the acceptance experiment (leakage-correct + 3x
cost + A/B de-confound + not-worse-than-60m-only).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from core.ml.xgb_alpha import XGBAlphaModel
from core.research.component_b_gate import (
    DIFFERENTIATED_ARCHETYPES,
    assert_archetype_differentiated,
    assert_component_b_prerequisites,
)
from core.research.engineered_features import engineered_sample_weights

__all__ = [
    "open_range_breakout",
    "vwap_deviation",
    "realized_vol_regime",
    "intraday_volume_z",
    "compute_b1_day_features",
    "B1Config",
    "train_b1",
]


# ── per-day intraday primitives (window=one trading day's bars) ──────
def open_range_breakout(bars: np.ndarray, k: int = 1) -> float:
    """(close − open_range_high) / open_range_high using the first
    ``k`` bars as the open range. Positive = closed above OR top.
    """
    b = np.asarray(bars, dtype=float)
    if b.ndim != 2 or b.shape[0] < k + 1 or b.shape[1] < 4:
        return float("nan")
    or_high = float(np.nanmax(b[:k, 1]))  # high col
    c = float(b[-1, 3])
    if not np.isfinite(or_high) or or_high == 0:
        return float("nan")
    return (c - or_high) / or_high


def vwap_deviation(bars: np.ndarray) -> float:
    """(close − vwap) / vwap. VWAP = Σ(close·vol)/Σ(vol)."""
    b = np.asarray(bars, dtype=float)
    if b.ndim != 2 or b.shape[0] == 0 or b.shape[1] < 5:
        return float("nan")
    c = b[:, 3]; v = b[:, 4]
    tv = float(np.nansum(v))
    if tv <= 0:
        return float("nan")
    vwap = float(np.nansum(c * v) / tv)
    last = float(c[-1])
    return (last - vwap) / vwap if vwap != 0 else float("nan")


def realized_vol_regime(bars: np.ndarray) -> float:
    """Sqrt sum-of-squared intrabar log-returns = realized vol of
    the day (stationary, scale-free across names)."""
    b = np.asarray(bars, dtype=float)
    if b.ndim != 2 or b.shape[0] < 2 or b.shape[1] < 4:
        return float("nan")
    c = b[:, 3]
    r = np.diff(np.log(c[c > 0])) if (c > 0).all() else np.array([])
    if r.size == 0:
        return float("nan")
    return float(np.sqrt(np.nansum(r * r)))


def intraday_volume_z(bars: np.ndarray) -> float:
    """Mean intraday volume z within the day (against the day's own
    mean/std — captures volume-distribution shape, NOT level)."""
    b = np.asarray(bars, dtype=float)
    if b.ndim != 2 or b.shape[0] < 3 or b.shape[1] < 5:
        return float("nan")
    v = b[:, 4]
    m, s = float(np.nanmean(v)), float(np.nanstd(v, ddof=1))
    if not np.isfinite(s) or s <= 0:
        return float("nan")
    return float(np.nanmean((v - m) / s))


def compute_b1_day_features(bars: np.ndarray) -> dict:
    """Assemble the 4 scalar features for one (date, symbol)'s day
    of intraday OHLCV bars ``(T, 5)``."""
    return {
        "open_range_breakout": open_range_breakout(bars),
        "vwap_deviation": vwap_deviation(bars),
        "realized_vol_regime": realized_vol_regime(bars),
        "intraday_volume_z": intraday_volume_z(bars),
    }


# ── B1 training pipeline (RB1-gated + RA2 XGB delegate) ──────────────
@dataclass
class B1Config:
    """Intraday B1 model config. ``archetype`` MUST be one of
    ``DIFFERENTIATED_ARCHETYPES`` — naive bar-voting is refused at
    the RB1 gate BEFORE any training begins (the documented
    losing-path 老路子防呆)."""
    archetype: str = "intraday_reversal"
    max_depth: int = 3
    n_estimators: int = 200
    random_state: int = 42


@dataclass
class B1FitResult:
    model: XGBAlphaModel
    sample_weight: np.ndarray
    feature_cols: List[str]
    archetype: str


def train_b1(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    start_pos: np.ndarray,
    horizon: int,
    groups: Optional[np.ndarray] = None,
    X_val: Optional[pd.DataFrame] = None,
    y_val: Optional[pd.Series] = None,
    cfg: B1Config = B1Config(),
) -> B1FitResult:
    """Fit the B1 intraday shallow-XGB on engineered features.

    Gate FIRST (RB1):
      * ``assert_component_b_prerequisites`` — refuse if any prereq
        (PRD-1 / P2.3 / R11 / RA7 R6) is unmet.
      * ``assert_archetype_differentiated`` — refuse naive
        bar-direction-voting / naive-15m-momentum configs upstream.
    Then delegate to RA2's leakage-correct shallow-XGB recipe
    (engineered_sample_weights → label_leakage; XGBAlphaModel).
    """
    assert_component_b_prerequisites()
    assert_archetype_differentiated(cfg.archetype)
    if not (2 <= cfg.max_depth <= 4):
        raise ValueError(
            f"max_depth={cfg.max_depth} — B1 is shallow by design "
            f"(2-4 only; low variance at low intraday SNR)")

    w = engineered_sample_weights(
        np.asarray(start_pos), horizon, groups=groups)
    feat_cols = list(X.columns)
    model = XGBAlphaModel(
        max_depth=cfg.max_depth, n_estimators=cfg.n_estimators,
        random_state=cfg.random_state)
    model.fit(X, y, X_val, y_val, feature_cols=feat_cols,
              sample_weight=w)
    return B1FitResult(model=model, sample_weight=w,
                       feature_cols=feat_cols,
                       archetype=cfg.archetype)
