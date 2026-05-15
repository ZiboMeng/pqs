"""
FactorGenerator: auto-construct candidate factors from OHLCV + macro data.

Role: RESEARCH pipeline. Outputs are never consumed by the execution
strategy directly — `MultiFactorStrategy` computes its own inline factors
from `core/factors/factor_registry.PRODUCTION_FACTORS` for performance.

Promotion path (see `core/factors/factor_registry.py` for the contract):
  research candidate (here) → IC screen → OOS walk-forward → regime
  robustness → manual code addition to MultiFactorStrategy.generate() +
  registry update → execution.

Every research factor's relationship to production is declared in
`factor_registry.RESEARCH_TO_PRODUCTION_MAP`. Unmapped factors are
"research-only" and cannot drive execution until explicitly promoted.

Factor families (35):
  - Momentum (multi-period return, risk-adjusted, 12-1 month)
  - Mean reversion (short-term reversal, SMA deviation)
  - Volatility (realized vol, vol regime, drawdown)
  - Volume (volume surge, price-volume divergence)
  - Quality (Sharpe-based, drawdown-based)
  - Relative strength (vs SPY, cross-sectional rank, acceleration)
  - Sector rotation (rank momentum change, return-per-risk)
  - Macro regime (SPY trend, market vol ratio, market drawdown)
  - Overnight (gap momentum, overnight vs intraday split)
  - Breadth (cross-section dispersion, advance ratio)
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)


def generate_all_factors(
    price_df: pd.DataFrame,
    volume_df: pd.DataFrame | None = None,
    benchmark_col: str = "SPY",
    open_df: pd.DataFrame | None = None,
    high_df: pd.DataFrame | None = None,
    low_df: pd.DataFrame | None = None,
    backfill_tickers: set[str] | None = None,
    volume_sensitive_factors: list[str] | None = None,
    intraday_bars_60m: Dict[str, pd.DataFrame] | None = None,
    benchmark_map: Dict[str, pd.Series] | None = None,
) -> Dict[str, pd.DataFrame]:
    """
    Generate all candidate factors from price (and optionally volume) data.

    Parameters
    ----------
    price_df      : close prices, index=date, columns=symbols
    volume_df     : daily volume, same shape as price_df (optional)
    benchmark_col : column name for benchmark (used in relative strength).
                    Backward-compat: if `benchmark_map` is None, the
                    benchmark is sourced from `price_df[benchmark_col]`.
    benchmark_map : PRD 20260424 P1. Optional dict mapping benchmark name
                    (e.g. "SPY", "QQQ") → close-price Series. When supplied,
                    each benchmark is injected into a copy of `price_df`
                    under its name column, so downstream factor families
                    can reference any benchmark by name. Enables features
                    like `rel_qqq_*`, `beta_spy_*`, `residual_mom_*` that
                    need benchmarks beyond the single `benchmark_col`.
                    The original `price_df` is not mutated.
    backfill_tickers : set of tickers whose bars come from trades_backfill
                       pipeline; their volume semantics differ from
                       stocks-only CSV source. If supplied, the output
                       values for these tickers in `volume_sensitive_factors`
                       are set to NaN (prevents volume-sensitive factors
                       from making decisions on data with unverified volume
                       semantics).
    volume_sensitive_factors : list of factor names to mask. Defaults to
                       `UniverseConfig.data_sensitivity.volume_sensitive_factors`
                       if None and config is loadable.

    Returns
    -------
    Dict[factor_name → DataFrame] with same index/columns as price_df
    (benchmark-injected columns are NOT returned as factors).
    """
    factors: Dict[str, pd.DataFrame] = {}

    # PRD 20260424 P1: if a benchmark_map is supplied, inject each
    # named benchmark as a column in a COPY of price_df so factor
    # families that lookup `price_df[name]` work uniformly regardless
    # of whether the caller passed benchmarks as explicit columns or
    # via the map. Original caller's price_df is not mutated.
    effective_price_df = _resolve_benchmark_map(
        price_df, benchmark_col, benchmark_map,
    )

    factors.update(_baseline_return_factors(effective_price_df, open_df))
    factors.update(_baseline_range_factors(effective_price_df, high_df, low_df, volume_df))
    factors.update(_baseline_relative_factors(effective_price_df, benchmark_col))
    factors.update(_family_a_benchmark_relative(effective_price_df))
    factors.update(_family_b_position_breakout(effective_price_df))
    factors.update(_family_c_liquidity_risk(effective_price_df, volume_df))
    factors.update(_family_d_trend_quality(effective_price_df))
    factors.update(_momentum_factors(effective_price_df))
    factors.update(_mean_reversion_factors(effective_price_df))
    factors.update(_volatility_factors(effective_price_df))
    if volume_df is not None:
        factors.update(_volume_factors(effective_price_df, volume_df, high_df, low_df))
    factors.update(_family_g_consolidation(effective_price_df, high_df, low_df, volume_df))
    factors.update(_family_h_higher_moments(effective_price_df, benchmark_col))
    factors.update(_family_i_anchor_bab(effective_price_df, volume_df, benchmark_col))
    factors.update(_family_j_calendar(effective_price_df))
    factors.update(_family_r_chart_patterns(effective_price_df, high_df, low_df))
    factors.update(_family_s_regime_ml(effective_price_df, benchmark_col))
    factors.update(_quality_factors(effective_price_df))
    factors.update(_sr_swing_factors(effective_price_df, high_df, low_df))
    factors.update(_relative_strength_factors(effective_price_df, benchmark_col))
    factors.update(_sector_rotation_factors(effective_price_df))
    factors.update(_macro_regime_factors(effective_price_df, benchmark_col))
    factors.update(_regime_gated_factors(effective_price_df, benchmark_col))
    factors.update(_weak_market_factors(effective_price_df, benchmark_col))
    if open_df is not None:
        factors.update(_overnight_factors(effective_price_df, open_df))
    factors.update(_breadth_factors(effective_price_df))
    if intraday_bars_60m is not None:
        factors.update(_intraday_factors(effective_price_df, intraday_bars_60m))

    # Factor outputs must be aligned to caller's original price_df
    # columns — injected benchmarks should not leak into output panels
    # if they weren't in the caller's symbol set.
    factors = _trim_factors_to_caller_symbols(factors, price_df.columns)

    # PRD §D3 / §3.1.C alias layer: expose historically-named factors
    # as thin references to existing ones. Same DataFrame shared — no
    # recomputation. Research-only convenience so downstream LLM /
    # mining can query by either name. Aliases added LAST so they
    # reflect any earlier mutations.
    _apply_research_aliases(factors)

    if backfill_tickers:
        factors = apply_data_sensitivity_mask(
            factors, backfill_tickers,
            volume_sensitive_factors=volume_sensitive_factors,
        )

    logger.info("FactorGenerator: produced %d candidate factors", len(factors))
    return factors


# PRD 20260424 P1 (Research Composite Miner v1) multi-benchmark helpers.


def _resolve_benchmark_map(
    price_df: pd.DataFrame,
    benchmark_col: str,
    benchmark_map: Dict[str, pd.Series] | None,
) -> pd.DataFrame:
    """Return a price_df variant whose columns include every named
    benchmark in `benchmark_map` (and the original caller columns).

    Backward-compat: when `benchmark_map` is None, returns `price_df`
    unchanged (no copy). When supplied, returns a COPY of `price_df`
    with each benchmark series injected as a column named by its key.

    Parameters
    ----------
    price_df      : caller's original close panel
    benchmark_col : legacy single-benchmark name (for documentation only
                    — this helper does not consult it). Kept in signature
                    so mistake-proofing: if caller passes an unmapped
                    benchmark_col without benchmark_map, they will get
                    the existing KeyError at subfactor lookup time (same
                    behavior as pre-P1).
    benchmark_map : {name: close_series} dict

    Returns
    -------
    DataFrame — same as price_df if benchmark_map is None, else a copy
    with all benchmarks injected as columns named by key.
    """
    if not benchmark_map:
        return price_df
    merged = price_df.copy()
    for name, series in benchmark_map.items():
        merged[name] = series.reindex(merged.index)
    return merged


def _trim_factors_to_caller_symbols(
    factors: Dict[str, pd.DataFrame],
    caller_columns: pd.Index,
) -> Dict[str, pd.DataFrame]:
    """Return a new factor dict where every factor DataFrame's columns
    are restricted to `caller_columns`. This prevents benchmark-injected
    columns (e.g. an extra "QQQ" from benchmark_map) from leaking into
    factor outputs if QQQ wasn't part of the caller's universe."""
    trimmed: Dict[str, pd.DataFrame] = {}
    caller_set = set(caller_columns)
    for name, df in factors.items():
        if isinstance(df, pd.DataFrame):
            cols_to_keep = [c for c in df.columns if c in caller_set]
            if len(cols_to_keep) == len(df.columns):
                trimmed[name] = df  # no change
            else:
                trimmed[name] = df[cols_to_keep]
        else:
            trimmed[name] = df
    return trimmed


# PRD §D3 / §3.1.C alias map: alias_name → canonical_name already in
# the generator output. Windows are near-equivalent (21 vs 20) — the
# decision is not to re-implement, just resolve names.
_RESEARCH_ALIASES = {
    "vol_20d": "vol_21d",
    "volume_ratio_20d": "volume_surge_20d",
}


def _apply_research_aliases(factors: Dict[str, pd.DataFrame]) -> None:
    """Add alias entries to the factor dict in-place. Same DataFrame
    reference — no copy. No-op if the canonical factor is absent."""
    for alias, canonical in _RESEARCH_ALIASES.items():
        if canonical in factors and alias not in factors:
            factors[alias] = factors[canonical]


def _default_volume_sensitive_factors() -> list[str]:
    """Load the default volume-sensitive factor list from config.
    Falls back to a hard-coded list if config not loadable (tests etc.)."""
    try:
        from core.config.loader import load_config
        cfg = load_config()
        return list(cfg.universe.data_sensitivity.volume_sensitive_factors)
    except Exception:
        return ["volume_surge_20d", "price_volume_div"]


def apply_data_sensitivity_mask(
    factors: Dict[str, pd.DataFrame],
    backfill_tickers: set[str] | list[str],
    volume_sensitive_factors: list[str] | None = None,
) -> Dict[str, pd.DataFrame]:
    """Mask volume-sensitive factor values to NaN for `backfill_tickers`.

    Returns a new dict; original factor DataFrames are unchanged.
    See DataSensitivityConfig for rationale.
    """
    if not backfill_tickers:
        return factors
    if volume_sensitive_factors is None:
        volume_sensitive_factors = _default_volume_sensitive_factors()
    sensitive = set(volume_sensitive_factors)
    backfill = set(backfill_tickers)
    out: Dict[str, pd.DataFrame] = {}
    for name, df in factors.items():
        if name in sensitive:
            cols_to_mask = [c for c in df.columns if c in backfill]
            if cols_to_mask:
                df = df.copy()
                df[cols_to_mask] = np.nan
                logger.info("FactorGenerator: masked %d backfill tickers in '%s'",
                            len(cols_to_mask), name)
        out[name] = df
    return out


def _baseline_return_factors(
    price_df: pd.DataFrame,
    open_df: pd.DataFrame | None = None,
) -> Dict[str, pd.DataFrame]:
    """Short-horizon raw return factors (PRD 20260423 Step 1, Returns family).

    Emits:
      - ret_1d, ret_2d  (close-to-close raw returns, unsigned siblings
        of the existing reversal_5d / reversal_10d / reversal_21d family)
      - overnight_ret_1d  (raw 1-bar overnight gap, sibling of rolling
        overnight_gap_5d / overnight_gap_21d) — only when open_df provided
      - intraday_ret_1d  (raw 1-bar intraday return) — only when open_df
        provided

    All values are raw (sign = direction of return). Callers that want
    mean-reversion direction must negate explicitly.
    """
    from core.factors.base_returns import (
        simple_return, overnight_return_raw, intraday_return_raw,
    )
    factors: Dict[str, pd.DataFrame] = {}
    factors["ret_1d"] = simple_return(price_df, 1)
    factors["ret_2d"] = simple_return(price_df, 2)
    if open_df is not None:
        factors["overnight_ret_1d"] = overnight_return_raw(open_df, price_df)
        factors["intraday_ret_1d"] = intraday_return_raw(open_df, price_df)
    return factors


def _baseline_range_factors(
    price_df: pd.DataFrame,
    high_df: pd.DataFrame | None = None,
    low_df: pd.DataFrame | None = None,
    volume_df: pd.DataFrame | None = None,
) -> Dict[str, pd.DataFrame]:
    """Short-horizon range / liquidity factors (PRD 20260423 Step 1,
    Volatility-Range family).

    Emits:
      - hl_range  : (high - low) / prev_close, raw 1-bar ATR-lite
        (only when both high_df and low_df provided)
      - dollar_vol_20d : rolling 20d mean of close * volume
        (only when volume_df provided; dual-role per PRD §D2 —
        also basis for future tradability masks)
    """
    from core.factors.base_volatility import hl_range as _hl_range_fn
    from core.factors.base_volatility import dollar_volume_ma
    factors: Dict[str, pd.DataFrame] = {}
    if high_df is not None and low_df is not None:
        factors["hl_range"] = _hl_range_fn(
            high_df, low_df, price_df, normalize=True,
        )
    if volume_df is not None:
        factors["dollar_vol_20d"] = dollar_volume_ma(
            price_df, volume_df, window=20,
        )
    return factors


def _family_a_benchmark_relative(
    price_df: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """PRD 20260424 Family A — benchmark-relative / residual / risk exposure.

    Produces (conditional on benchmark presence in price_df):
      - rel_spy_20d   : 20d stock return - 20d SPY return (short sibling
                        of rs_vs_spy_21d which uses 21d lookback — distinct
                        by a bar, both kept)
      - rel_qqq_20d   : same vs QQQ (primary benchmark per PRD invariant;
                        net-new coverage — no rs_vs_qqq_* existed before)
      - beta_spy_60d  : rolling 60d OLS beta of daily returns vs SPY
      - residual_mom_spy_20d : sum of 20d daily residual returns after
                               removing rolling-60d SPY beta exposure

    All 4 rely on P1 multi-benchmark plumbing: the caller must either
    include SPY/QQQ columns in price_df OR pass them via benchmark_map.
    Missing benchmark → feature silently omitted from output (not NaN'd).
    """
    from core.factors.base_relative import (
        relative_return, rolling_beta, residualize_returns,
    )
    factors: Dict[str, pd.DataFrame] = {}
    daily_ret = price_df.pct_change()

    # rel_spy_20d
    if "SPY" in price_df.columns:
        factors["rel_spy_20d"] = relative_return(price_df, "SPY", 20)
        # beta_spy_60d
        spy_ret = daily_ret["SPY"]
        factors["beta_spy_60d"] = rolling_beta(
            daily_ret, spy_ret, lookback=60,
        )
        # residual_mom_spy_20d: rolling sum of 20d daily residuals
        residuals = residualize_returns(daily_ret, spy_ret, lookback=60)
        factors["residual_mom_spy_20d"] = residuals.rolling(
            20, min_periods=10,
        ).sum()

    # rel_qqq_20d — separate branch so SPY-missing case doesn't block QQQ
    if "QQQ" in price_df.columns:
        factors["rel_qqq_20d"] = relative_return(price_df, "QQQ", 20)

    return factors


def _family_b_position_breakout(
    price_df: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """PRD 20260424 Family B — position / breakout / path-shape.

    Produces 4 features (all T1 — adjusted-close only):
      - range_pos_252d : (close - min_252d) / (max_252d - min_252d), ∈ [0,1]
                         Complement to dist_52w_high (which is close / max - 1
                         ∈ [-∞, 0]); range_pos normalizes by range span.
      - days_since_52w_high : number of trading days since the 252d rolling
                              max was most recently set (0 = today is new high)
      - breakout_20d_strength : close / max(prior 20d close) - 1
                                Positive = today closed above prior 20d high
                                (breakout magnitude); negative = still within
                                range. Uses shift(1) on rolling max so today's
                                close is compared to yesterday's 20d high.
      - dist_from_new_high_252 : close / max(prior 252d close) - 1
                                 Same logic at 252d horizon. Distinct from
                                 `dist_52w_high` (which uses same-bar max,
                                 always ≤ 0): this version uses shifted max
                                 so breakout bars get positive values.
    """
    factors: Dict[str, pd.DataFrame] = {}

    # range_pos_252d
    min_252 = price_df.rolling(252, min_periods=60).min()
    max_252 = price_df.rolling(252, min_periods=60).max()
    range_span = (max_252 - min_252).replace(0, np.nan)
    factors["range_pos_252d"] = (price_df - min_252) / range_span

    # days_since_52w_high — rolling argmax, offset to "days since"
    # apply with np.argmax is O(N*window) but acceptable on research panels.
    def _days_since_max(arr: np.ndarray) -> float:
        # arr has length == window (within min_periods). argmax returns
        # position of the first max; convert to "days since" where today
        # is window-1 (0 = new high today).
        last_idx = len(arr) - 1
        return float(last_idx - int(np.argmax(arr)))

    factors["days_since_52w_high"] = price_df.rolling(
        252, min_periods=60,
    ).apply(_days_since_max, raw=True)

    # breakout_20d_strength — compare today's close to yesterday's 20d max
    # (shift(1) on rolling max excludes today so breakout bars get positive)
    prior_20d_max = price_df.rolling(20, min_periods=10).max().shift(1)
    factors["breakout_20d_strength"] = (
        price_df / prior_20d_max.replace(0, np.nan) - 1.0
    )

    # dist_from_new_high_252 — same formulation at 252d horizon
    prior_252d_max = price_df.rolling(252, min_periods=60).max().shift(1)
    factors["dist_from_new_high_252"] = (
        price_df / prior_252d_max.replace(0, np.nan) - 1.0
    )

    return factors


def _family_c_liquidity_risk(
    price_df: pd.DataFrame,
    volume_df: pd.DataFrame | None = None,
) -> Dict[str, pd.DataFrame]:
    """PRD 20260424 Family C — liquidity / cost proxy / risk state.

    Produces:
      - amihud_20d       : rolling 20d mean of |ret_1d| / dollar_volume.
                           Classic Amihud illiquidity; higher = less liquid.
                           Requires volume_df — silently omitted if None.
      - downside_vol_20d : rolling 20d std of daily returns restricted to
                           negative returns only (downside risk asymmetry).
      - vol_ratio_5_20   : 5d rolling vol / 20d rolling vol. Values < 1
                           mean recent volatility compressed below 20d
                           average — classic "quiet before the storm"
                           or "compression before breakout" signal.
                           Values > 1 mean recent heightened volatility.
    """
    factors: Dict[str, pd.DataFrame] = {}
    daily_ret = price_df.pct_change()

    # amihud_20d — requires volume
    if volume_df is not None:
        aligned_vol = volume_df.reindex_like(price_df)
        dollar_vol = price_df * aligned_vol
        # Daily illiquidity contribution: |ret| / dollar_vol
        daily_illiq = daily_ret.abs() / dollar_vol.replace(0, np.nan)
        # Rolling mean over 20d
        factors["amihud_20d"] = daily_illiq.rolling(
            20, min_periods=10,
        ).mean()

    # downside_vol_20d — std of negative-only daily returns
    downside_only = daily_ret.where(daily_ret < 0)
    factors["downside_vol_20d"] = downside_only.rolling(
        20, min_periods=5,
    ).std()

    # vol_ratio_5_20 — short/long vol term structure
    vol_5 = daily_ret.rolling(5, min_periods=3).std()
    vol_20 = daily_ret.rolling(20, min_periods=10).std()
    factors["vol_ratio_5_20"] = vol_5 / vol_20.replace(0, np.nan)

    return factors


def _family_d_trend_quality(
    price_df: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """PRD 20260424 Family D — trend quality.

    Produces:
      - trend_tstat_20d : OLS slope t-statistic of rolling 20d regression
                          of log(close) on time index [0..19]. Higher |t|
                          = stronger trend (up or down); values near 0 =
                          no trend (random walk). More informative than
                          raw slope because it's normalized by regression
                          residual variance.

    Implementation uses rolling.apply(raw=True) with a pure-numpy inner
    function; O(N × 20 × S) but fast enough on research panels.
    """
    factors: Dict[str, pd.DataFrame] = {}
    log_close = np.log(price_df.replace(0, np.nan))

    def _tstat_20d(y: np.ndarray) -> float:
        """OLS slope t-stat of y vs [0..n-1]. Returns 0 for degenerate cases."""
        n = len(y)
        if n < 3 or np.isnan(y).any():
            return np.nan
        x = np.arange(n, dtype=float)
        x_mean = x.mean()
        y_mean = y.mean()
        x_dev = x - x_mean
        y_dev = y - y_mean
        x_var = (x_dev ** 2).sum()
        if x_var <= 0:
            return np.nan
        slope = (x_dev * y_dev).sum() / x_var
        intercept = y_mean - slope * x_mean
        y_pred = intercept + slope * x
        residuals = y - y_pred
        rss = (residuals ** 2).sum()
        # SE(slope) = sqrt( (rss / (n - 2)) / x_var )
        if n <= 2:
            return np.nan
        se_slope_sq = (rss / (n - 2)) / x_var
        if se_slope_sq <= 0:
            return np.nan
        return float(slope / np.sqrt(se_slope_sq))

    factors["trend_tstat_20d"] = log_close.rolling(
        20, min_periods=15,
    ).apply(_tstat_20d, raw=True)

    return factors


def _baseline_relative_factors(
    price_df: pd.DataFrame,
    benchmark_col: str = "SPY",
) -> Dict[str, pd.DataFrame]:
    """Relative / position factors (PRD 20260423 Step 1, Relative family).

    Emits:
      - ret_5d          : raw 5d close-to-close return (unsigned sibling
                          of existing reversal_5d, per PRD §3.1.B)
      - dist_52w_high   : close / rolling_max(close, 252) - 1 (PRD §D4)
      - rel_spy_5d      : 5d return of symbol minus 5d return of SPY
                          (per PRD §3.1.A, missing shorter-horizon sibling
                          of rs_vs_spy_21d / 63d / 126d)
    """
    from core.factors.base_returns import simple_return
    from core.factors.base_relative import (
        dist_from_rolling_max, relative_return,
    )
    factors: Dict[str, pd.DataFrame] = {}
    factors["ret_5d"] = simple_return(price_df, 5)
    factors["dist_52w_high"] = dist_from_rolling_max(price_df, window=252)
    if benchmark_col in price_df.columns:
        factors["rel_spy_5d"] = relative_return(
            price_df, benchmark_col, lookback=5,
        )
    return factors


def _momentum_factors(price_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    factors = {}
    for lookback in [21, 63, 126, 252]:
        ret = price_df.pct_change(lookback)
        factors[f"mom_{lookback}d"] = ret

    mom_252 = price_df.pct_change(252)
    mom_21 = price_df.pct_change(21)
    factors["mom_12_1"] = mom_252 - mom_21

    vol_63 = price_df.pct_change().rolling(63).std()
    mom_63 = price_df.pct_change(63)
    factors["risk_adj_mom_63d"] = mom_63 / vol_63.replace(0, np.nan)

    return factors


def _mean_reversion_factors(price_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    factors = {}
    for lookback in [5, 10, 21]:
        ret = price_df.pct_change(lookback)
        factors[f"reversal_{lookback}d"] = -ret

    for window in [20, 50]:
        sma = price_df.rolling(window).mean()
        factors[f"mean_rev_sma{window}"] = -(price_df - sma) / sma.replace(0, np.nan)

    return factors


def _volatility_factors(price_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Volatility factor family.

    `vol_21d` / `vol_63d` go through the shared `low_vol_factor`
    helper (Round 6 Topic E merge, 2026-04-20) so this path and
    MultiFactorStrategy's `low_vol` factor share ONE implementation.
    The shared helper does not annualize; cross-sectional z-score
    removes the scale difference downstream.
    """
    from core.factors.base_factors import low_vol_factor
    factors = {}
    daily_ret = price_df.pct_change()

    for window in [21, 63]:
        factors[f"vol_{window}d"] = low_vol_factor(
            price_df, lookback=window, min_periods=20,
        )

    vol_short = daily_ret.rolling(21).std()
    vol_long = daily_ret.rolling(126).std()
    factors["vol_regime"] = -(vol_short / vol_long.replace(0, np.nan))

    cummax = price_df.cummax()
    dd = (price_df - cummax) / cummax
    factors["drawdown_current"] = dd

    return factors


def _volume_factors(
    price_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    high_df: Optional[pd.DataFrame] = None,
    low_df: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """Volume + volume-microstructure factor family.

    Bucket A T1 batch 1 (PRD-driven 2026-05-12):
      - obv_norm_20d            : OBV 20-day momentum slope, normalized
      - chaikin_money_flow_20d  : classic CMF (needs H+L)
      - accum_dist_line_zscore_60d : A/D line z-score (needs H+L)
      - vol_price_corr_20d      : rolling corr(ΔVolume, daily return)
      - volume_surge_when_flat  : volume z-score gated by flat-price regime
      - klinger_oscillator      : simplified Klinger VF EMA(34) - EMA(55) (needs H+L)

    CONDITIONAL on high_df + low_df: CMF / AD / Klinger return NaN-only
    DataFrames when either missing (mirrors `_sr_swing_factors` pattern).
    """
    factors = {}
    vol_ma20 = volume_df.rolling(20).mean()
    factors["volume_surge_20d"] = volume_df / vol_ma20.replace(0, np.nan)

    daily_ret = price_df.pct_change()
    vol_chg = volume_df.pct_change()
    factors["price_volume_div"] = daily_ret.rolling(20).mean() - vol_chg.rolling(20).mean()

    # ── Bucket A T1 batch 1 (close + volume only; H/L not required) ──

    # obv_norm_20d: OBV slope over 20d, normalized by daily-OBV-change std.
    # OBV = cum sum of sign(daily_ret) × volume. Captures "smart-money
    # accumulation" via volume-weighted directional bias. Norm by ΔOBV
    # 20d std so cross-sectional rank is comparable across stocks with
    # different absolute volume.
    sign_ret = np.sign(daily_ret.fillna(0.0))
    obv = (sign_ret * volume_df.fillna(0.0)).cumsum()
    obv_chg = obv.diff()
    obv_chg_std = obv_chg.rolling(20).std().replace(0, np.nan)
    factors["obv_norm_20d"] = obv.diff(20) / obv_chg_std

    # vol_price_corr_20d: rolling 20d Pearson corr(ΔVolume, daily ret).
    # High = healthy trend (volume rises with price). Low / negative =
    # divergence (volume drying up on advance OR rising on decline).
    # Element-wise rolling correlation via cov / (std_a × std_b) formula
    # (avoids pandas DataFrame.rolling().corr() shape ambiguity).
    ret_mean_20 = daily_ret.rolling(20).mean()
    volchg_mean_20 = vol_chg.rolling(20).mean()
    ret_std_20 = daily_ret.rolling(20).std()
    volchg_std_20 = vol_chg.rolling(20).std()
    cov_20 = (daily_ret * vol_chg).rolling(20).mean() - ret_mean_20 * volchg_mean_20
    factors["vol_price_corr_20d"] = cov_20 / (ret_std_20 * volchg_std_20).replace(0, np.nan)

    # volume_surge_when_flat: volume z-score × flat-price flag. Captures
    # "stealth accumulation" — volume spikes while 20d return is small.
    # Threshold = 5%; binary flag (not soft) per resident-quant choice.
    vol_zscore_20 = (volume_df - volume_df.rolling(20).mean()) / volume_df.rolling(20).std().replace(0, np.nan)
    ret_20 = price_df.pct_change(20)
    is_flat = (ret_20.abs() < 0.05).astype(float)
    factors["volume_surge_when_flat"] = vol_zscore_20 * is_flat

    # ── Bucket A T1 batch 2 (4-quadrant volume) — PRD-driven 2026-05-12 ──
    # up_vol_ratio_20d / down_vol_ratio_20d / vol_weighted_ret_20d
    is_up = (daily_ret > 0).astype(float)
    is_down = (daily_ret < 0).astype(float)
    vol_total_20 = volume_df.rolling(20).sum().replace(0, np.nan)
    factors["up_vol_ratio_20d"] = (volume_df * is_up).rolling(20).sum() / vol_total_20
    factors["down_vol_ratio_20d"] = (volume_df * is_down).rolling(20).sum() / vol_total_20
    factors["vol_weighted_ret_20d"] = (
        (daily_ret * volume_df).rolling(20).sum() / vol_total_20
    )

    # ── Bucket A T1 batch 1 (need H+L; CONDITIONAL) ──

    if high_df is not None and low_df is not None:
        hl_range = (high_df - low_df).replace(0, np.nan)

        # chaikin_money_flow_20d: classic CMF formula.
        # MFM = ((C - L) - (H - C)) / (H - L), set 0 when H == L.
        # MFV = MFM × volume. CMF_20 = Σ MFV / Σ volume over 20d.
        mfm = ((price_df - low_df) - (high_df - price_df)) / hl_range
        mfv = mfm * volume_df
        factors["chaikin_money_flow_20d"] = (
            mfv.rolling(20).sum() / volume_df.rolling(20).sum().replace(0, np.nan)
        )

        # accum_dist_line_zscore_60d: A/D line = cumsum of MFV; z-score
        # over 60d window. Captures long-window divergence from local
        # mean — useful as "distribution / accumulation" regime tag.
        ad_line = mfv.cumsum()
        ad_mean_60 = ad_line.rolling(60).mean()
        ad_std_60 = ad_line.rolling(60).std().replace(0, np.nan)
        factors["accum_dist_line_zscore_60d"] = (ad_line - ad_mean_60) / ad_std_60

        # klinger_oscillator: simplified Klinger volume-force formulation.
        # The canonical Klinger (1997) uses a trend-reset cumulative
        # measure (CM) that's path-dependent and prone to numerical
        # accumulation drift; PQS uses a sign-of-trend × volume EMA
        # difference variant which preserves the directional signal
        # without the path-dependency. Documented as "simplified Klinger"
        # in factor_registry comments.
        trend_proxy = (high_df + low_df + price_df) / 3.0
        trend_sign = np.sign(trend_proxy.diff()).fillna(0.0)
        vf = volume_df * trend_sign
        kvo_short = vf.ewm(span=34, adjust=False, min_periods=34).mean()
        kvo_long = vf.ewm(span=55, adjust=False, min_periods=55).mean()
        factors["klinger_oscillator"] = kvo_short - kvo_long

    return factors


def _family_h_higher_moments(
    price_df: pd.DataFrame,
    benchmark_col: str = "SPY",
    window: int = 60,
) -> Dict[str, pd.DataFrame]:
    """Higher-moment factors — coskew / cokurt vs benchmark + idio skew.

    Bucket A T1 batch 3 (PRD 2026-05-12; Harvey-Siddique 2000 +
    Bressan 2024 RFE).

    Formulas (rolling `window` daily bars):
      coskew_60d_spy  = E[(r_i - μ_i)² × (r_m - μ_m)] / (σ_i² × σ_m)
      cokurt_60d_spy  = E[(r_i - μ_i)³ × (r_m - μ_m)] / (σ_i³ × σ_m)
      idiosyncratic_skew_60d = rolling skewness of stock daily returns

    CONDITIONAL on benchmark_col present in price_df columns.
    """
    factors: Dict[str, pd.DataFrame] = {}
    if benchmark_col not in price_df.columns:
        return factors

    daily_ret = price_df.pct_change()
    bench_ret = daily_ret[benchmark_col]

    # Rolling moments
    ri_mean = daily_ret.rolling(window).mean()
    rm_mean = bench_ret.rolling(window).mean()
    ri_dev = daily_ret.sub(ri_mean)
    rm_dev = bench_ret.sub(rm_mean)
    ri_var = daily_ret.rolling(window).var()
    rm_var = bench_ret.rolling(window).var()
    ri_std = np.sqrt(ri_var)
    rm_std = np.sqrt(rm_var)

    # coskew_60d_spy
    coskew_num = (ri_dev.pow(2)).mul(rm_dev, axis=0).rolling(window).mean()
    coskew_den = (ri_var * rm_std.values[:, None]) if False else None
    # Easier: compute element-wise
    coskew = coskew_num.div((ri_var.mul(rm_std, axis=0)).replace(0, np.nan))
    factors[f"coskew_{window}d_spy"] = coskew

    # cokurt_60d_spy
    cokurt_num = (ri_dev.pow(3)).mul(rm_dev, axis=0).rolling(window).mean()
    cokurt = cokurt_num.div((ri_std.pow(3).mul(rm_std, axis=0)).replace(0, np.nan))
    factors[f"cokurt_{window}d_spy"] = cokurt

    # idiosyncratic skew (no benchmark; just per-symbol)
    factors[f"idiosyncratic_skew_{window}d"] = daily_ret.rolling(window).skew()

    return factors


def _family_i_anchor_bab(
    price_df: pd.DataFrame,
    volume_df: Optional[pd.DataFrame] = None,
    benchmark_col: str = "SPY",
) -> Dict[str, pd.DataFrame]:
    """Anchor (52w high) + short-term reversal + simplified BAB.

    Bucket A T1 batch 3 (PRD 2026-05-12):
      - nearness_to_52w_high : close / 252d_max ∈ [0, 1]
                               (complements existing dist_52w_high which
                                is fraction-below)
      - weekly_reversal_signal_5d : -ret_5d × volume_zscore_5d
                                    (Lehmann 1990: high-turnover winners
                                     reverse next week)
      - bab_score_60d        : -beta_spy_60d / downside_vol_20d
                               (simplified BAB; Frazzini-Pedersen 2014;
                                divides by downside vol as risk normalizer)

    CONDITIONAL on benchmark_col (BAB needs SPY) and volume_df
    (weekly_reversal needs turnover).
    """
    factors: Dict[str, pd.DataFrame] = {}

    # nearness_to_52w_high — no benchmark / no volume needed
    max_252 = price_df.rolling(252, min_periods=63).max()
    factors["nearness_to_52w_high"] = price_df / max_252.replace(0, np.nan)

    # weekly_reversal_signal_5d — needs volume
    if volume_df is not None:
        ret_5d = price_df.pct_change(5)
        vol_mean_5 = volume_df.rolling(5).mean()
        vol_std_60 = volume_df.rolling(60).std().replace(0, np.nan)
        vol_z_5d = (vol_mean_5 - volume_df.rolling(60).mean()) / vol_std_60
        factors["weekly_reversal_signal_5d"] = -ret_5d * vol_z_5d

    # bab_score_60d — needs benchmark
    if benchmark_col in price_df.columns:
        daily_ret = price_df.pct_change()
        bench_ret = daily_ret[benchmark_col]
        # Rolling 60d OLS beta vs SPY
        cov_60 = daily_ret.rolling(60).cov(bench_ret)
        var_60 = bench_ret.rolling(60).var()
        beta_60 = cov_60.div(var_60.replace(0, np.nan), axis=0)
        # downside vol 20d
        neg_ret = daily_ret.where(daily_ret < 0, 0.0)
        downside_vol_20 = neg_ret.rolling(20).std().replace(0, np.nan)
        factors["bab_score_60d"] = -beta_60 / downside_vol_20

    return factors


def _family_j_calendar(
    price_df: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """Calendar / seasonal timing factors.

    Bucket A T1 batch 3 (PRD 2026-05-12):
      - turn_of_month_flag        : ±2 trading days from month-end → 1
                                    (10bps premium per 2024 calendar
                                     anomaly review)
      - sell_in_may_seasonal      : Nov-Apr → +1, May-Oct → -1
      - month_end_quarter_end     : Mar/Jun/Sep/Dec last trading day → 1
                                    (institutional rebalance)

    No data dependencies beyond price_df's DatetimeIndex (for shape).
    All flags are broadcast across columns identically (time-only signals).
    """
    factors: Dict[str, pd.DataFrame] = {}
    idx = price_df.index
    if not isinstance(idx, pd.DatetimeIndex):
        return factors

    # turn_of_month_flag: identify each month's last K + first K trading days
    # Easier: rank trading days within each month from start AND end; flag
    # if rank ≤ 2 from either side.
    month_period = idx.to_period("M")
    df_idx = pd.DataFrame({"d": idx, "m": month_period}, index=idx)
    df_idx["rank_from_start"] = df_idx.groupby("m").cumcount() + 1
    df_idx["rank_from_end"] = df_idx.groupby("m").cumcount(ascending=False) + 1
    tom_flag = ((df_idx["rank_from_start"] <= 2) | (df_idx["rank_from_end"] <= 2)).astype(float)
    factors["turn_of_month_flag"] = pd.DataFrame(
        np.tile(tom_flag.values[:, None], (1, len(price_df.columns))),
        index=idx, columns=price_df.columns,
    )

    # sell_in_may_seasonal: Nov-Apr +1, May-Oct -1
    month = idx.month
    seasonal = np.where((month >= 11) | (month <= 4), 1.0, -1.0)
    factors["sell_in_may_seasonal"] = pd.DataFrame(
        np.tile(seasonal[:, None], (1, len(price_df.columns))),
        index=idx, columns=price_df.columns,
    )

    # month_end_quarter_end: last trading day of Mar/Jun/Sep/Dec
    df_idx["is_qend_month"] = month_period.month.isin([3, 6, 9, 12])
    df_idx["is_qend_day"] = df_idx["is_qend_month"] & (df_idx["rank_from_end"] == 1)
    factors["month_end_quarter_end"] = pd.DataFrame(
        np.tile(df_idx["is_qend_day"].astype(float).values[:, None], (1, len(price_df.columns))),
        index=idx, columns=price_df.columns,
    )

    return factors


def _family_g_consolidation(
    price_df: pd.DataFrame,
    high_df: Optional[pd.DataFrame] = None,
    low_df: Optional[pd.DataFrame] = None,
    volume_df: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """Consolidation / box-pattern / breakout precursor family.

    Bucket A T1 batch 2 (PRD-driven 2026-05-12):
      - bb_squeeze_20d            : (BB_upper - BB_lower)/SMA20 → 20d pct rank
      - atr_compression_20d       : ATR20 / ATR60 (needs H+L)
      - range_position_pct_60d    : (close-60d_min)/(60d_max-60d_min)
      - consolidation_days_count  : 连续 N 天 close 在 ±5% SMA20 范围
      - adx_low_trend_flag        : ADX14 < 20 持续天数 (needs H+L)
      - pre_breakout_volume_decay : 整理期内 volume 20d slope < 0 标记
                                    (needs volume_df)
    """
    factors: Dict[str, pd.DataFrame] = {}

    # bb_squeeze_20d: Bollinger band width as fraction of SMA, then 20d pct rank.
    sma_20 = price_df.rolling(20).mean()
    std_20 = price_df.rolling(20).std()
    bb_width_ratio = (4.0 * std_20) / sma_20.replace(0, np.nan)
    factors["bb_squeeze_20d"] = bb_width_ratio.rolling(20).rank(pct=True)

    # range_position_pct_60d: where in 60d high-low range is close?
    # 0 = at 60d low, 1 = at 60d high
    min_60 = price_df.rolling(60).min()
    max_60 = price_df.rolling(60).max()
    rng_60 = (max_60 - min_60).replace(0, np.nan)
    factors["range_position_pct_60d"] = (price_df - min_60) / rng_60

    # consolidation_days_count: run length of consecutive days where
    # |close - sma20| / sma20 < 5%. Reset to 0 when out of range.
    within_band = ((price_df - sma_20).abs() / sma_20.replace(0, np.nan) < 0.05).astype(float)
    # Cumulative run-length: group resets at every 0 in `within_band`
    # Trick: cumsum of within_band, minus cumsum at last 0 → run length
    cum_w = within_band.cumsum()
    reset = cum_w.where(within_band == 0).ffill().fillna(0)
    factors["consolidation_days_count"] = (cum_w - reset) * within_band

    # CONDITIONAL on H+L
    if high_df is not None and low_df is not None:
        prev_close = price_df.shift(1)
        tr = pd.concat([
            (high_df - low_df),
            (high_df - prev_close).abs(),
            (low_df - prev_close).abs(),
        ]).groupby(level=0).max()
        atr_20 = tr.rolling(20).mean()
        atr_60 = tr.rolling(60).mean()
        factors["atr_compression_20d"] = atr_20 / atr_60.replace(0, np.nan)

        # adx_low_trend_flag: ADX(14) < 20 → no trend; count run-length.
        # Wilder ADX classic: smooth +DM / -DM / TR with EMA(14), DI+/DI-,
        # DX = |DI+ - DI-| / (DI+ + DI-), ADX = EMA(DX, 14).
        up_move = high_df.diff()
        down_move = -low_df.diff()
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        atr_14 = tr.ewm(span=14, adjust=False, min_periods=14).mean()
        plus_di = 100.0 * plus_dm.ewm(span=14, adjust=False, min_periods=14).mean() / atr_14.replace(0, np.nan)
        minus_di = 100.0 * minus_dm.ewm(span=14, adjust=False, min_periods=14).mean() / atr_14.replace(0, np.nan)
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx_14 = dx.ewm(span=14, adjust=False, min_periods=14).mean()
        low_trend = (adx_14 < 20).astype(float)
        cum_lt = low_trend.cumsum()
        reset_lt = cum_lt.where(low_trend == 0).ffill().fillna(0)
        factors["adx_low_trend_flag"] = (cum_lt - reset_lt) * low_trend

    # CONDITIONAL on volume_df
    if volume_df is not None:
        # pre_breakout_volume_decay: volume slope down × in-consolidation regime.
        # Slope proxy: (vol_t - vol_{t-20}) / mean(vol over 20d).
        vol_slope_20 = (volume_df - volume_df.shift(20)) / volume_df.rolling(20).mean().replace(0, np.nan)
        in_consol = (within_band > 0).astype(float)
        # Negative slope inside consolidation → factor < 0 (breakout precursor)
        factors["pre_breakout_volume_decay"] = vol_slope_20 * in_consol

    return factors


def _family_r_chart_patterns(
    price_df: pd.DataFrame,
    high_df: Optional[pd.DataFrame] = None,
    low_df: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """Family R — chart-pattern factor library (Priority 1, 2026-05-14).

    10 chart-pattern technical factors. Distinct from family G (consolidation/
    breakout-precursor) and family I (nearness_to_52w_high). Focus:
    Donchian breakouts (3) + MA-cross/alignment (3) + streak (2) + ATR
    breakout (1) + inside bar (1).

    All factors compute on (close, high, low) panels.
    """
    factors: Dict[str, pd.DataFrame] = {}

    # --- Donchian breakouts (3) — close > rolling max of PRIOR N days ---
    # Excludes today's close (uses shift(1)) to prevent lookahead.
    for n in (20, 55, 252):
        prior_max = price_df.shift(1).rolling(n, min_periods=n).max()
        # 1.0 = new N-day high today; 0.0 otherwise. Float for grad/IC.
        factors[f"donchian_break_{n}d"] = (
            (price_df > prior_max).astype(float).where(prior_max.notna())
        )

    # --- MA-cross / alignment ---
    sma_20  = price_df.rolling(20).mean()
    sma_50  = price_df.rolling(50).mean()
    sma_100 = price_df.rolling(100).mean()
    sma_200 = price_df.rolling(200).mean()

    # golden_cross_score: (sma_50 - sma_200) / close — magnitude of cross
    # Positive when sma_50 > sma_200 (golden cross regime).
    factors["golden_cross_score"] = (
        (sma_50 - sma_200) / price_df.replace(0, np.nan)
    )

    # ma_pullback_20d: close / sma_20 - 1
    # Negative when price pulled back below sma_20; positive when above.
    factors["ma_pullback_20d"] = (
        price_df / sma_20.replace(0, np.nan) - 1.0
    )

    # price_above_4ma_count: how many of {sma_20, 50, 100, 200} are below
    # close. Range 0-4. Higher = stronger trend alignment.
    above_count = (
        (price_df > sma_20).astype(float)
        + (price_df > sma_50).astype(float)
        + (price_df > sma_100).astype(float)
        + (price_df > sma_200).astype(float)
    )
    factors["price_above_4ma_count"] = above_count.where(sma_200.notna())

    # --- Streaks / consecutive patterns ---
    up_day = (price_df > price_df.shift(1)).astype(float)

    # consecutive_up_streak: run-length of consecutive up days, today inclusive.
    # Reset to 0 when up_day = 0.
    cum_up = up_day.cumsum()
    reset_up = cum_up.where(up_day == 0).ffill().fillna(0)
    factors["consecutive_up_streak"] = (cum_up - reset_up) * up_day

    # higher_highs_5d: count of higher-than-previous closes in last 5 bars.
    factors["higher_highs_5d"] = up_day.rolling(5).sum()

    # --- ATR breakout (CONDITIONAL on H+L) ---
    if high_df is not None and low_df is not None:
        prev_close = price_df.shift(1)
        tr = pd.concat([
            (high_df - low_df),
            (high_df - prev_close).abs(),
            (low_df - prev_close).abs(),
        ]).groupby(level=0).max()
        atr_14 = tr.rolling(14).mean()

        # atr_breakout_5d: (close - max(close, 5).shift(1)) / atr_14
        # Magnitude of breakout above 5-day high, scaled by ATR.
        prior_5d_high = price_df.shift(1).rolling(5, min_periods=5).max()
        factors["atr_breakout_5d"] = (
            (price_df - prior_5d_high) / atr_14.replace(0, np.nan)
        )

        # inside_bar_pct_20d: fraction of last 20 bars that are "inside bars"
        # (today high < yesterday high AND today low > yesterday low).
        prev_high = high_df.shift(1)
        prev_low = low_df.shift(1)
        inside = ((high_df < prev_high) & (low_df > prev_low)).astype(float)
        factors["inside_bar_pct_20d"] = inside.rolling(20).mean()

    return factors


def _family_s_regime_ml(
    price_df: pd.DataFrame,
    benchmark_col: str = "SPY",
) -> Dict[str, pd.DataFrame]:
    """Family S — regime-aware ML-style continuous factors (Priority 2, 2026-05-14).

    3 regime factors aggregating multi-signal evidence into continuous scores
    (NOT hand-coded thresholds). Each output is broadcast to all symbols (the
    regime classification is market-level, applied uniformly per date).

    regime_score_combined:
      Logistic-style aggregation of bull/bear evidence. ∈ approx [0, 1].
      0 = bear regime (defensive); 1 = bull regime (risk-on).
      Inputs: SPY position vs 200d MA, 60d realized vol, 21d momentum sign.

    regime_transition_risk:
      Proxy for regime-change probability. High when signals disagree
      (mixed evidence) or recent vol has expanded. ∈ approx [0, 1].

    regime_persistence_score:
      Run-length of regime stability (consecutive days same regime). Higher
      = more entrenched regime. Useful for "trend exhaustion" gating.

    All factors broadcast to all symbols (column-wise constant per date).
    """
    factors: Dict[str, pd.DataFrame] = {}

    if benchmark_col not in price_df.columns:
        return factors

    spy = price_df[benchmark_col]
    spy_returns = spy.pct_change()

    # Signal 1: SPY position vs 200d MA (linear bull evidence)
    sma_200 = spy.rolling(200).mean()
    spy_ma_pct = (spy / sma_200.replace(0, np.nan) - 1.0)
    # logistic-style squashing: -10% → ~0.27, 0% → 0.5, +10% → ~0.73
    spy_ma_score = 1.0 / (1.0 + np.exp(-spy_ma_pct * 10.0))

    # Signal 2: 60d realized vol inverted (low vol = bull-friendly)
    vol_60 = spy_returns.rolling(60).std() * np.sqrt(252)
    vol_zscore = (vol_60 - vol_60.rolling(252).mean()) / vol_60.rolling(252).std().replace(0, np.nan)
    vol_score = 1.0 / (1.0 + np.exp(vol_zscore))  # high vol → low score

    # Signal 3: 21d momentum sign (positive = bull)
    mom_21 = spy.pct_change(21)
    mom_score = 1.0 / (1.0 + np.exp(-mom_21 * 20.0))

    # Aggregate: simple average. Range ≈ [0, 1].
    combined = (spy_ma_score + vol_score + mom_score) / 3.0

    # Broadcast to all symbols (per-date market regime)
    combined_panel = pd.DataFrame(
        np.tile(combined.values[:, None], (1, len(price_df.columns))),
        index=price_df.index, columns=price_df.columns,
    )
    factors["regime_score_combined"] = combined_panel

    # Transition risk: signal disagreement + vol expansion
    # Disagreement: stddev across the 3 signal values per date
    sig_stack = pd.concat(
        [spy_ma_score, vol_score, mom_score], axis=1
    ).std(axis=1)  # 0 = perfect agreement; large = mixed
    # Vol expansion: vol_60 / vol_60.shift(60)
    vol_expansion = vol_60 / vol_60.shift(60).replace(0, np.nan) - 1.0
    transition_risk = (sig_stack + vol_expansion.clip(lower=0)) / 2.0
    factors["regime_transition_risk"] = pd.DataFrame(
        np.tile(transition_risk.values[:, None], (1, len(price_df.columns))),
        index=price_df.index, columns=price_df.columns,
    )

    # Persistence: run-length of regime > 0.5 (bull) or <= 0.5 (bear).
    is_bull = (combined > 0.5).astype(int)
    # Run-length: cumcount of same-state streak
    # Simple impl: count diff-detection then cumsum within group
    state_change = (is_bull != is_bull.shift(1)).astype(int)
    state_group = state_change.cumsum()
    persist = is_bull.groupby(state_group).cumcount() + 1
    factors["regime_persistence_score"] = pd.DataFrame(
        np.tile(persist.values[:, None], (1, len(price_df.columns))),
        index=price_df.index, columns=price_df.columns,
    )

    return factors


def _sr_swing_factors(
    price_df: pd.DataFrame,
    high_df: Optional[pd.DataFrame],
    low_df: Optional[pd.DataFrame],
    n: int = 5,
    lookback: int = 20,
) -> Dict[str, pd.DataFrame]:
    """Daily-resolution swing-extrema-based S/R factors.

    Per-symbol Python loop wraps `core.intraday.sr_swing.distance_to_sr`.
    Computes nearest support / resistance from local swing highs / lows
    in the past ``lookback`` daily bars (after a confirmation lag of
    ``n`` bars).

    Returns 3 factors, each a fraction (NOT percent) for convention
    with `dist_52w_high`, `breakout_20d_strength`, etc.:

      - ``dist_to_swing_high_20d``: (R - close) / close, non-negative
        when defined, NaN when no qualifying swing high above close in
        last ``lookback`` bars. Small = close to resistance.
      - ``dist_to_swing_low_20d``: (close - S) / close, non-negative
        when defined, NaN when no qualifying swing low below close.
        Small = close to support.
      - ``sr_range_compression_20d``: (R - S) / close, non-negative
        when both defined, NaN if either missing. Small = price wedged
        between near S and near R; often precedes range expansion.

    Sign convention: factor magnitudes are always non-negative when
    defined; mining discovers the directional IC from history.

    CONDITIONAL: requires both ``high_df`` and ``low_df``. Returns empty
    dict if either is None (mirrors `_volume_factors` pattern).

    PRD path: docs/prd/20260505-* (Step 2 of S/R alpha-first plan).
    """
    if high_df is None or low_df is None:
        return {}

    from core.intraday.sr_swing import distance_to_sr

    cols = price_df.columns
    idx = price_df.index
    dist_R = pd.DataFrame(np.nan, index=idx, columns=cols, dtype=float)
    dist_S = pd.DataFrame(np.nan, index=idx, columns=cols, dtype=float)
    range_compression = pd.DataFrame(np.nan, index=idx, columns=cols, dtype=float)

    for col in cols:
        if col not in high_df.columns or col not in low_df.columns:
            continue
        sym_bars = pd.DataFrame({
            "high": high_df[col],
            "low": low_df[col],
            "close": price_df[col],
        }).dropna()
        if len(sym_bars) < 2 * n + 1:
            continue
        out = distance_to_sr(sym_bars, n=n, lookback=lookback)
        # Convert pct → fraction (factor convention; / 100)
        dist_R.loc[out.index, col] = out["dist_to_resistance_pct"].values / 100.0
        dist_S.loc[out.index, col] = out["dist_to_support_pct"].values / 100.0
        range_compression.loc[out.index, col] = out["sr_range_pct"].values / 100.0

    return {
        "dist_to_swing_high_20d": dist_R,
        "dist_to_swing_low_20d": dist_S,
        "sr_range_compression_20d": range_compression,
    }


def _quality_factors(price_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    factors = {}
    daily_ret = price_df.pct_change()

    ret_126 = daily_ret.rolling(126).mean() * 252
    vol_126 = daily_ret.rolling(126).std() * np.sqrt(252)
    factors["rolling_sharpe_126d"] = ret_126 / vol_126.replace(0, np.nan)

    cummax = price_df.rolling(252, min_periods=63).max()
    dd = (price_df - cummax) / cummax
    max_dd_126 = dd.rolling(126, min_periods=21).min()
    factors["max_dd_126d"] = -max_dd_126

    # LLM-Round 10 promotion (2026-04-21, user-authorized):
    # drawup_from_252d_low = symmetric counterpart of max_dd_126d.
    # Ranked #1 in Ridge permutation importance + #7 in XGBoost across
    # 43-feature panel (Round 6), passed §5.4 reverse review (Round 3).
    # Research-only — NOT in PRODUCTION_FACTORS. Promoted here so
    # `run_mining.py` + `run_xgb_importance.py` can use it directly.
    rolling_min = price_df.rolling(252, min_periods=126).min()
    drawup = (price_df - rolling_min) / rolling_min.replace(0, np.nan)
    factors["drawup_from_252d_low"] = drawup

    return factors


def _relative_strength_factors(
    price_df: pd.DataFrame,
    benchmark_col: str = "SPY",
) -> Dict[str, pd.DataFrame]:
    """Relative strength vs benchmark — outperformers tend to keep outperforming.

    All three horizons (`rs_vs_spy_21d/63d/126d`) now go through
    `rel_strength_factor` helper (Round 6 Topic E merge, 2026-04-20)
    so the 63-day variant shares implementation with MultiFactorStrategy's
    inline `rel_strength`.
    """
    from core.factors.base_factors import rel_strength_factor
    factors = {}
    if benchmark_col not in price_df.columns:
        return factors

    for lookback in [21, 63, 126]:
        factors[f"rs_vs_spy_{lookback}d"] = rel_strength_factor(
            price_df, benchmark_col=benchmark_col, lookback=lookback,
        )
    # Acceleration computed from the same helper outputs
    rs_63 = factors["rs_vs_spy_63d"]
    rs_21 = factors["rs_vs_spy_21d"]
    factors["rs_acceleration"] = rs_63 - rs_21

    return factors


def _sector_rotation_factors(price_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Cross-sectional rank-based factors for sector/asset rotation."""
    factors = {}
    daily_ret = price_df.pct_change()

    for lookback in [21, 63]:
        rolling_ret = price_df.pct_change(lookback)
        rank = rolling_ret.rank(axis=1, pct=True)
        factors[f"xsection_rank_{lookback}d"] = rank

    ret_63 = price_df.pct_change(63)
    ret_21 = price_df.pct_change(21)
    rank_63 = ret_63.rank(axis=1, pct=True)
    rank_21 = ret_21.rank(axis=1, pct=True)
    factors["rank_momentum_change"] = rank_63 - rank_21

    vol_21 = daily_ret.rolling(21).std()
    ret_21_raw = price_df.pct_change(21)
    factors["return_per_risk_21d"] = ret_21_raw / vol_21.replace(0, np.nan)

    return factors


def _overnight_factors(
    price_df: pd.DataFrame,
    open_df: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """Overnight return factors — isolate pre-market information flow."""
    factors = {}
    overnight_ret = open_df / price_df.shift(1) - 1

    for window in [5, 21]:
        factors[f"overnight_gap_{window}d"] = overnight_ret.rolling(window).mean()

    intraday_ret = price_df / open_df - 1
    factors["overnight_vs_intraday"] = (
        overnight_ret.rolling(21).mean() - intraday_ret.rolling(21).mean()
    )

    return factors


def _intraday_factors(
    price_df: pd.DataFrame,
    intraday_bars_60m: Dict[str, pd.DataFrame],
) -> Dict[str, pd.DataFrame]:
    """First intraday factor family (Round 5 Topic F, 2026-04-20).

    Computes daily-indexed factor values from within-day 60m bar
    granularity — information that CAN'T be captured from daily OHLC.

    Current factors (RESEARCH-only, not in PRODUCTION_FACTORS):

    - `realized_vol_60m_21d` — 21d rolling annualized realized vol
      computed from 60m bar returns. More precise than daily
      close-to-close vol in capturing within-day variance.

    - `intraday_vol_ratio_21d` — ratio of intraday realized vol to
      daily close-to-close vol. > 1 = intraday noise dominates
      (mean-reversion regime proxy); < 1 = overnight drift dominates
      (trending regime proxy).

    - `intraday_autocorr_21d` — 21-day mean of lag-1 autocorrelation
      of within-day 60m bar returns. Negative = intraday mean-
      reversion; positive = intraday momentum continuation.

    RTH-only: bars outside (09:30, 16:00] ET are filtered out so
    the signals reflect session-time price action only.
    """
    factors: Dict[str, pd.DataFrame] = {}
    index = price_df.index
    symbols = list(price_df.columns)

    # Results: symbol → Series indexed by business date
    rv_series: Dict[str, pd.Series] = {}
    ratio_series: Dict[str, pd.Series] = {}
    ac_series: Dict[str, pd.Series] = {}

    # Daily close-to-close vol (for ratio denominator), reuse price_df
    daily_ret = price_df.pct_change()
    daily_vol_21 = daily_ret.rolling(21, min_periods=10).std() * np.sqrt(252)

    for sym, bars in intraday_bars_60m.items():
        if sym not in symbols or bars is None or bars.empty:
            continue
        # RTH-filter: bars closing in (09:30, 16:00] ET
        mins = bars.index.hour * 60 + bars.index.minute
        rth = bars.loc[(mins > 9 * 60 + 30) & (mins <= 16 * 60)]
        if len(rth) < 20:
            continue

        # 60m bar log returns — close-to-close within the session
        close = rth["close"].astype(float)
        bar_ret = close.pct_change()

        # Group by trading date: within-day realized vol + autocorr
        date_idx = rth.index.normalize()
        by_day = pd.DataFrame({
            "ret": bar_ret.values,
            "sq":  (bar_ret ** 2).values,
            "day": date_idx,
        })
        # Daily RV = sqrt(sum bar_ret^2) * annualization
        # With ~7 60m RTH bars/day, annualization = sqrt(252)
        daily_sq_sum = by_day.groupby("day")["sq"].sum()
        daily_rv_raw = np.sqrt(daily_sq_sum.clip(lower=0)) * np.sqrt(252)

        # Daily lag-1 autocorrelation of bar_ret within the day
        def _day_ac(group):
            r = group["ret"].dropna().values
            if len(r) < 3:
                return np.nan
            r1 = r[:-1]
            r2 = r[1:]
            if r1.std() < 1e-10 or r2.std() < 1e-10:
                return np.nan
            return float(np.corrcoef(r1, r2)[0, 1])

        daily_ac_raw = by_day.groupby("day").apply(_day_ac, include_groups=False)

        # Align to business-date index used by price_df
        daily_rv = daily_rv_raw.reindex(index)
        daily_ac = daily_ac_raw.reindex(index)

        # Rolling 21d smoothing
        rv_series[sym] = daily_rv.rolling(21, min_periods=10).mean()
        ac_series[sym] = daily_ac.rolling(21, min_periods=10).mean()

        if sym in daily_vol_21.columns:
            denom = daily_vol_21[sym].replace(0, np.nan)
            ratio_series[sym] = rv_series[sym] / denom

    if rv_series:
        factors["realized_vol_60m_21d"] = pd.DataFrame(rv_series).reindex(
            index=index, columns=symbols,
        )
    if ratio_series:
        factors["intraday_vol_ratio_21d"] = pd.DataFrame(ratio_series).reindex(
            index=index, columns=symbols,
        )
    if ac_series:
        factors["intraday_autocorr_21d"] = pd.DataFrame(ac_series).reindex(
            index=index, columns=symbols,
        )

    return factors


def _breadth_factors(price_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Cross-sectional breadth and dispersion factors."""
    factors = {}
    daily_ret = price_df.pct_change()

    cs_std_21 = daily_ret.rolling(21).std().mean(axis=1)
    factors["cross_section_dispersion_21d"] = pd.DataFrame(
        {s: cs_std_21 for s in price_df.columns}, index=price_df.index
    )

    advancing = (daily_ret > 0).sum(axis=1)
    total = daily_ret.notna().sum(axis=1).replace(0, 1)
    adv_ratio = (advancing / total).rolling(10).mean()
    factors["advance_ratio_10d"] = pd.DataFrame(
        {s: adv_ratio for s in price_df.columns}, index=price_df.index
    )

    return factors


def _macro_regime_factors(
    price_df: pd.DataFrame,
    benchmark_col: str = "SPY",
) -> Dict[str, pd.DataFrame]:
    """Market-wide regime signals applied cross-sectionally as factors."""
    factors = {}
    if benchmark_col not in price_df.columns:
        return factors

    bench = price_df[benchmark_col]
    bench_ret = bench.pct_change()

    bench_ma200 = bench.rolling(200).mean()
    above_ma200 = (bench / bench_ma200 - 1).clip(-0.3, 0.3)
    factors["spy_trend_200d"] = pd.DataFrame(
        {s: above_ma200 for s in price_df.columns}, index=price_df.index
    )

    bench_vol_21 = bench_ret.rolling(21).std() * np.sqrt(252)
    bench_vol_63 = bench_ret.rolling(63).std() * np.sqrt(252)
    vol_ratio = (bench_vol_21 / bench_vol_63.replace(0, np.nan)).clip(0.3, 3.0)
    factors["market_vol_ratio"] = pd.DataFrame(
        {s: -vol_ratio for s in price_df.columns}, index=price_df.index
    )

    bench_dd = bench / bench.cummax() - 1
    factors["market_drawdown"] = pd.DataFrame(
        {s: bench_dd for s in price_df.columns}, index=price_df.index
    )

    return factors


def _regime_gated_factors(
    price_df: pd.DataFrame, benchmark_col: str = "SPY",
) -> Dict[str, pd.DataFrame]:
    """Regime-gated momentum and RS factors (R7 2026-04-22 deep mining).

    Gated by SPY>SMA200 binary indicator. Predictor in uptrend only;
    zeroed in downtrend. R5 interaction mine: incremental IC +0.0458
    vs independent parents. R7 deep_check: OOS walk-forward IR +0.332.
    """
    factors: Dict[str, pd.DataFrame] = {}
    if benchmark_col not in price_df.columns:
        return factors

    bench = price_df[benchmark_col]
    bench_ma200 = bench.rolling(200, min_periods=100).mean()
    gate = (bench > bench_ma200).astype(float)

    # spy_trend_gated_mom_63d: momentum × regime gate
    mom_63d = price_df.pct_change(63)
    gated_mom = mom_63d.mul(gate, axis=0)
    factors["spy_trend_gated_mom_63d"] = gated_mom.shift(1)

    return factors


def _weak_market_factors(
    price_df: pd.DataFrame, benchmark_col: str = "SPY",
) -> Dict[str, pd.DataFrame]:
    """Weak-market conditional factors (R10 2026-04-22, Codex-seeded).

    Measures stock behavior on SPY-weak vs SPY-strong days.
    weak_market_relative_strength_63d = mean(stock_ret | SPY_weak) - mean(stock_ret | SPY_strong)
    Stocks that hold up on weak days but don't outperform on strong days
    are defensive names; those that outperform both ways are all-weather.

    R10 deep_check: OOS walk-forward mean IR -0.402 (ABS passes 0.30 gate,
    but NEGATIVE direction — factor predicts LOW forward returns for the
    defensive behavior; use with flipped sign in MFS composite).
    Regime 6/6 correct sign, quartile stable.
    """
    factors: Dict[str, pd.DataFrame] = {}
    if benchmark_col not in price_df.columns:
        return factors
    ret = price_df.pct_change()
    spy_ret = ret[benchmark_col]
    # Define "weak" and "strong" SPY days by rolling median
    spy_median_63 = spy_ret.rolling(63, min_periods=20).median()
    weak_mask = spy_ret.lt(spy_median_63).astype(float)
    strong_mask = spy_ret.gt(spy_median_63).astype(float)

    # Masked rolling mean: sum(ret * mask) / sum(mask) over 63d window
    weak_sum = ret.mul(weak_mask, axis=0).rolling(63, min_periods=15).sum()
    weak_cnt = weak_mask.rolling(63, min_periods=15).sum().replace(0, np.nan)
    weak_mean = weak_sum.div(weak_cnt, axis=0)

    strong_sum = ret.mul(strong_mask, axis=0).rolling(63, min_periods=15).sum()
    strong_cnt = strong_mask.rolling(63, min_periods=15).sum().replace(0, np.nan)
    strong_mean = strong_sum.div(strong_cnt, axis=0)

    factors["weak_market_relative_strength_63d"] = (weak_mean - strong_mean).shift(1)
    return factors


def compute_forward_returns(
    price_df: pd.DataFrame,
    horizons: List[int] = None,
    mode: str = "cc",
    open_df: pd.DataFrame | None = None,
) -> Dict[int, pd.DataFrame]:
    """Compute forward returns for IC calculation.

    Modes (PRD 20260423 §6.3):
      - "cc" (close-to-close, default, backward-compatible):
          close[t+h] / close[t] - 1
        No open_df needed. Matches original semantics.
      - "oc" (close-to-next-period-open-to-close):
          close[t+h] / open[t+h] - 1
        Captures "buy at t+h open, sell at t+h close" label. Requires
        open_df.
      - "oo" (open-to-open, forward):
          open[t+h] / open[t] - 1
        Captures "buy at t open, sell at t+h open" label. Requires
        open_df.

    All modes return the result aligned to `price_df.index` and
    shifted so that `result[h].loc[t]` is the forward return that
    would be realized if the bar at `t` is the decision bar.

    Parameters
    ----------
    price_df : close prices, index=date, columns=symbols
    horizons : list of horizons in trading days; default [5, 10, 21]
    mode     : one of {"cc", "oc", "oo"}
    open_df  : open prices, required when mode in {"oc", "oo"}

    Returns
    -------
    Dict[int, pd.DataFrame]: horizon → forward-return panel
    """
    if mode not in {"cc", "oc", "oo"}:
        raise ValueError(f"mode must be one of cc/oc/oo, got {mode!r}")
    if mode in {"oc", "oo"} and open_df is None:
        raise ValueError(f"mode={mode!r} requires open_df")
    horizons = horizons or [5, 10, 21]
    result: Dict[int, pd.DataFrame] = {}
    for h in horizons:
        if h < 1:
            raise ValueError(f"horizons must be >= 1, got {h}")
        if mode == "cc":
            # close[t+h] / close[t] - 1, aligned back to t
            result[h] = price_df.pct_change(h).shift(-h)
        elif mode == "oc":
            # close[t+h] / open[t+h] - 1, aligned back to t
            oc = price_df / open_df.reindex_like(price_df) - 1.0
            result[h] = oc.shift(-h)
        else:  # mode == "oo"
            # open[t+h] / open[t] - 1, aligned back to t
            oo = open_df.pct_change(h)
            result[h] = oo.reindex_like(price_df).shift(-h)
    return result
