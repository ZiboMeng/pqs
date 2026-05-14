"""SUE (Standardized Unexpected Earnings) calculator — Path 1 PEAD signal.

Definition (Foster-Olsen-Shevlin 1984 / Bernard-Thomas 1989):

    expected_EPS(Q)  = EPS(Q-4)                              # naive same-quarter-LY
    residual(Q)      = actual_EPS(Q) - expected_EPS(Q)
    sigma(Q)         = std(residual_{Q-1 .. Q-8})            # 8-q rolling std
    SUE(Q)           = residual(Q) / sigma(Q)

Operationally:
  - Requires ≥ 8 prior quarters of residuals to compute sigma.
  - 10-Q and 10-K both feed the sequence (FY is one of the 4 quarters).
  - Returns NaN for early quarters lacking 9+ historical points.

Input: DataFrame from `extract_earnings_dates(ticker)` with columns
  ticker, period_end, first_filed_date, fy, fp, eps_value, ...

Output: same shape + new column `sue` (float, may be NaN for early quarters).

Note: this is the "naive" SUE, which captures earnings momentum / trend
break vs the analyst-consensus version. Expect 30-50% lower magnitude
of detected surprise vs IBES SUE (per Livnat-Mendenhall 2006).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


_MIN_QUARTERS_FOR_SIGMA = 8
_DEFAULT_LAG = 4  # quarters to look back for naive forecast


def compute_sue(
    earnings_df: pd.DataFrame,
    lag_quarters: int = _DEFAULT_LAG,
    sigma_window: int = _MIN_QUARTERS_FOR_SIGMA,
    drop_fy_rows: bool = True,
) -> pd.DataFrame:
    """Compute SUE for one ticker's earnings sequence.

    Args:
        earnings_df: output of `extract_earnings_dates(ticker)`.
            Must contain ['period_end', 'eps_value'] columns,
            sorted by period_end ascending.
        lag_quarters: Q-N for naive forecast (default 4 = same quarter LY).
        sigma_window: rolling window for residual std (default 8 quarters).
        drop_fy_rows: if True, drop fp == 'FY' rows (10-K full-year EPS)
            before computing SUE. This prevents the lag-4 from mis-matching
            a full-year EPS against a standalone-Q EPS 4 rows back.
            For MVP we accept losing Q4 events; document in PRD §7.4.

    Returns:
        same DataFrame + columns:
            expected_eps   float  (NaN for first `lag_quarters` rows)
            residual       float  (NaN for first `lag_quarters` rows)
            sigma_residual float  (NaN until 8 residuals accumulated)
            sue            float  (NaN where residual or sigma is NaN)
    """
    if earnings_df.empty:
        return earnings_df.assign(
            expected_eps=pd.Series(dtype=float),
            residual=pd.Series(dtype=float),
            sigma_residual=pd.Series(dtype=float),
            sue=pd.Series(dtype=float),
        )

    df = earnings_df.sort_values("period_end").reset_index(drop=True).copy()
    if drop_fy_rows and "fp" in df.columns:
        df = df[df["fp"] != "FY"].reset_index(drop=True)
        if df.empty:
            return df.assign(
                expected_eps=pd.Series(dtype=float),
                residual=pd.Series(dtype=float),
                sigma_residual=pd.Series(dtype=float),
                sue=pd.Series(dtype=float),
            )

    df["expected_eps"] = df["eps_value"].shift(lag_quarters)
    df["residual"] = df["eps_value"] - df["expected_eps"]

    # Rolling std of residual over the prior `sigma_window` quarters
    # NOT including current quarter (`closed='left'` semantics via shift).
    # Use min_periods = sigma_window so early quarters return NaN.
    df["sigma_residual"] = (
        df["residual"]
        .shift(1)
        .rolling(window=sigma_window, min_periods=sigma_window)
        .std()
    )

    # SUE = residual / sigma_residual. Handle sigma=0 → SUE = NaN.
    with np.errstate(divide="ignore", invalid="ignore"):
        sue = df["residual"] / df["sigma_residual"].replace(0.0, np.nan)
    df["sue"] = sue

    return df


def compute_sue_panel(
    earnings_panel: pd.DataFrame,
    lag_quarters: int = _DEFAULT_LAG,
    sigma_window: int = _MIN_QUARTERS_FOR_SIGMA,
    drop_fy_rows: bool = True,
) -> pd.DataFrame:
    """Apply `compute_sue` per ticker, return concatenated panel.

    Args:
        earnings_panel: output of `extract_earnings_dates_panel(tickers)`.
            Must contain 'ticker' column.
        drop_fy_rows: see `compute_sue`.

    Returns:
        Same shape as input + 4 new columns (FY rows excluded if drop_fy_rows).
    """
    if earnings_panel.empty:
        return earnings_panel.assign(
            expected_eps=pd.Series(dtype=float),
            residual=pd.Series(dtype=float),
            sigma_residual=pd.Series(dtype=float),
            sue=pd.Series(dtype=float),
        )

    frames = []
    for ticker, sub in earnings_panel.groupby("ticker", sort=False):
        df_ticker = compute_sue(sub, lag_quarters=lag_quarters,
                                sigma_window=sigma_window,
                                drop_fy_rows=drop_fy_rows)
        if not df_ticker.empty:
            frames.append(df_ticker)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["first_filed_date", "ticker"]).reset_index(drop=True)


def build_sue_signal_panel(
    earnings_panel_with_sue: pd.DataFrame,
    sue_threshold: float,
    price_index: pd.DatetimeIndex,
    universe: list,
) -> pd.DataFrame:
    """Build entry_signals DataFrame for K1 SignalDrivenBacktest.

    For each (ticker, first_filed_date) row with SUE > sue_threshold,
    set entry_signals[first_filed_date, ticker] = True.

    Args:
        earnings_panel_with_sue: output of `compute_sue_panel`.
        sue_threshold: trigger threshold (e.g., 1.5 σ).
        price_index: pd.DatetimeIndex of trading days (from price panel).
        universe: list of ticker symbols (columns).

    Returns:
        DataFrame indexed by price_index, columns=universe, bool values.
        True where (first_filed_date, ticker) had SUE >= threshold AND
        the filed_date is in price_index AND ticker is in universe.
        Off-trading-day filed_dates are rolled forward to next trading day.
    """
    entry = pd.DataFrame(False, index=price_index, columns=universe)
    if earnings_panel_with_sue.empty:
        return entry

    triggers = earnings_panel_with_sue[
        earnings_panel_with_sue["sue"].notna()
        & (earnings_panel_with_sue["sue"] >= sue_threshold)
    ]
    for _, row in triggers.iterrows():
        sym = row["ticker"]
        if sym not in universe:
            continue
        filed = pd.Timestamp(row["first_filed_date"])
        # Roll filed date forward to next trading day if not in price_index
        if filed not in price_index:
            after = price_index[price_index >= filed]
            if len(after) == 0:
                continue
            filed = after[0]
        entry.loc[filed, sym] = True
    return entry
