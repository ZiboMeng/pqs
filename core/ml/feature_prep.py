"""R0 — literature-grade data preparation / cleaning layer.

Per supplementary PRD `docs/prd/20260516-ml_methodology_supplementary_prd.md`
§3 (literature review §1.A [S5][S9][S12]). Every factor panel goes
through this BEFORE any model — the layer Phase 3 naive attempts skipped.

All transforms are **cross-sectional per rebalance date** (one panel row
= one date × all symbols) and therefore **causal by construction**: row
``t`` never reads any row > t. ``fractional_difference`` is the only
time-axis transform and is opt-in (default off); its numpy ADF keeps the
dependency surface flat (statsmodels is NOT installed in this env).

Config-sourced (`config/ml_feature_prep.yaml`); no hardcoded thresholds
(PRD §9.5 / G7).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd


# ── cross-sectional transforms (causal: per-row, no future) ────────────
def cross_sectional_rank_norm(df: pd.DataFrame) -> pd.DataFrame:
    """Per date (row), rank symbols → [0,1] percentile. [S12]

    Causal by construction — each row is ranked independently across
    columns; no temporal information crosses rows. NaNs stay NaN.
    """
    return df.rank(axis=1, pct=True, na_option="keep")


def winsorize(df: pd.DataFrame, p_low: float, p_high: float) -> pd.DataFrame:
    """Per date, hard-cap to the [p_low, p_high] cross-sectional quantiles. [S12]"""
    if not (0.0 <= p_low < p_high <= 1.0):
        raise ValueError(f"bad winsor quantiles {p_low},{p_high}")
    lo = df.quantile(p_low, axis=1)
    hi = df.quantile(p_high, axis=1)
    return df.clip(lower=lo, upper=hi, axis=0)


def sector_neutralize(
    df: pd.DataFrame,
    sector_of,  # callable(symbol, as_of: date) -> Optional[str]
) -> pd.DataFrame:
    """Per date, subtract the PIT-GICS-sector cross-sectional mean. [S12]

    ``sector_of`` resolves point-in-time sector (no future reclass
    leakage). Symbols with unknown sector form their own residual group
    (demeaned among themselves). Result: within-sector mean ≈ 0 per date.
    """
    out = df.copy()
    cols = list(df.columns)
    for dt in df.index:
        as_of = dt.date() if hasattr(dt, "date") else dt
        sec = np.array([sector_of(c, as_of) or "__UNK__" for c in cols])
        row = df.loc[dt]
        for s in np.unique(sec):
            m = sec == s
            grp = row.values[m]
            finite = np.isfinite(grp)
            if finite.sum() >= 1:
                grp_mean = np.nanmean(grp) if finite.any() else 0.0
                vals = grp.copy()
                vals[finite] = grp[finite] - grp_mean
                out.loc[dt, np.array(cols)[m]] = vals
    return out


def vol_scale(
    df: pd.DataFrame, returns_df: pd.DataFrame, lookback: int
) -> pd.DataFrame:
    """Divide each (date, symbol) factor by trailing realized vol. [S12]

    ``returns_df`` is the (date × symbol) return panel; vol uses only
    ``[t-lookback, t-1]`` (shifted, causal). Zero/NaN vol → factor NaN
    (excluded downstream rather than exploded).
    """
    vol = returns_df.rolling(lookback, min_periods=max(2, lookback // 2)).std()
    vol = vol.shift(1).reindex(index=df.index, columns=df.columns)
    scaled = df / vol.replace(0.0, np.nan)
    return scaled


# ── fractional differentiation (opt-in; numpy ADF, no statsmodels) ─────
def _ffd_weights(d: float, thres: float = 1e-4, max_k: int = 10_000) -> np.ndarray:
    """Fixed-width fractional-diff weights (Lopez de Prado AFML ch.5 [S9])."""
    w = [1.0]
    k = 1
    while k < max_k:
        w_ = -w[-1] * (d - k + 1) / k
        if abs(w_) < thres:
            break
        w.append(w_)
        k += 1
    return np.array(w[::-1])


def frac_diff_ffd(series: pd.Series, d: float, thres: float = 1e-4) -> pd.Series:
    """Fixed-width fractional difference of a single series. [S9]"""
    w = _ffd_weights(d, thres)
    width = len(w) - 1
    vals = series.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    for i in range(width, len(vals)):
        win = vals[i - width: i + 1]
        if np.isfinite(win).all():
            out[i] = float(w @ win)
    return pd.Series(out, index=series.index)


def _adf_tstat(y: np.ndarray, n_lags: int = 1) -> float:
    """Augmented Dickey-Fuller t-stat on the y_{t-1} coefficient, numpy
    OLS only (statsmodels absent). More negative = more stationary."""
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if len(y) < n_lags + 10:
        return 0.0
    dy = np.diff(y)
    n = len(dy) - n_lags
    if n < 10:
        return 0.0
    Y = dy[n_lags:]
    X_cols = [np.ones(n), y[n_lags:-1]]
    for L in range(1, n_lags + 1):
        X_cols.append(dy[n_lags - L: -L])
    X = np.column_stack(X_cols)
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ beta
    dof = n - X.shape[1]
    if dof <= 0:
        return 0.0
    s2 = (resid @ resid) / dof
    xtx_inv = np.linalg.pinv(X.T @ X)
    se_gamma = np.sqrt(s2 * xtx_inv[1, 1])
    return float(beta[1] / se_gamma) if se_gamma > 0 else 0.0


def min_ffd(
    series: pd.Series,
    d_grid: Optional[list] = None,
    adf_crit: float = -2.86,
    thres: float = 1e-4,
) -> tuple[float, pd.Series]:
    """Smallest d on ``d_grid`` whose FFD series is ADF-stationary
    (t-stat < ``adf_crit``, default ≈ 5% critical value). Returns
    ``(d, ffd_series)``. Preserves max memory subject to stationarity. [S9]
    """
    if d_grid is None:
        d_grid = [round(x, 2) for x in np.arange(0.0, 1.01, 0.1)]
    last = (1.0, frac_diff_ffd(series, 1.0, thres))
    for d in d_grid:
        ffd = frac_diff_ffd(series, d, thres)
        if _adf_tstat(ffd.to_numpy()) < adf_crit:
            return d, ffd
        last = (d, ffd)
    return last


# ── orchestrator ───────────────────────────────────────────────────────
def prepare_factor_panel(
    panel: dict[str, pd.DataFrame],
    cfg: dict,
    sector_of=None,
    returns_df: Optional[pd.DataFrame] = None,
) -> dict[str, pd.DataFrame]:
    """Apply the configured R0 steps to every factor frame.

    ``cfg`` = parsed `config/ml_feature_prep.yaml`. Steps run in the
    literature order: winsorize → sector-neutral → vol-scale →
    rank-norm. frac-diff is opt-in and applies per-symbol BEFORE the
    cross-sectional steps (it is the only time-axis transform).
    Default config (all cross-sectional on, frac-diff off) is the
    literature baseline; nothing here is hardcoded.
    """
    out: dict[str, pd.DataFrame] = {}
    fd = cfg.get("frac_diff", {})
    for name, df in panel.items():
        x = df
        if fd.get("enabled", False):
            cols = {}
            for c in x.columns:
                _, s = min_ffd(
                    x[c], d_grid=fd.get("d_grid"),
                    adf_crit=fd.get("adf_crit", -2.86),
                    thres=fd.get("thres", 1e-4))
                cols[c] = s
            x = pd.DataFrame(cols, index=x.index)
        if cfg.get("winsorize", {}).get("enabled", True):
            w = cfg["winsorize"]
            x = winsorize(x, w.get("p_low", 0.01), w.get("p_high", 0.99))
        if cfg.get("sector_neutralize", {}).get("enabled", True) and sector_of:
            x = sector_neutralize(x, sector_of)
        if cfg.get("vol_scale", {}).get("enabled", True) and returns_df is not None:
            x = vol_scale(x, returns_df,
                          cfg["vol_scale"].get("lookback", 63))
        if cfg.get("rank_norm", {}).get("enabled", True):
            x = cross_sectional_rank_norm(x)
        out[name] = x
    return out
