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

from typing import Dict, List

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
) -> Dict[str, pd.DataFrame]:
    """
    Generate all candidate factors from price (and optionally volume) data.

    Parameters
    ----------
    price_df      : close prices, index=date, columns=symbols
    volume_df     : daily volume, same shape as price_df (optional)
    benchmark_col : column name for benchmark (used in relative strength)
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
    """
    factors: Dict[str, pd.DataFrame] = {}

    factors.update(_baseline_return_factors(price_df, open_df))
    factors.update(_baseline_range_factors(price_df, high_df, low_df, volume_df))
    factors.update(_momentum_factors(price_df))
    factors.update(_mean_reversion_factors(price_df))
    factors.update(_volatility_factors(price_df))
    if volume_df is not None:
        factors.update(_volume_factors(price_df, volume_df))
    factors.update(_quality_factors(price_df))
    factors.update(_relative_strength_factors(price_df, benchmark_col))
    factors.update(_sector_rotation_factors(price_df))
    factors.update(_macro_regime_factors(price_df, benchmark_col))
    factors.update(_regime_gated_factors(price_df, benchmark_col))
    factors.update(_weak_market_factors(price_df, benchmark_col))
    if open_df is not None:
        factors.update(_overnight_factors(price_df, open_df))
    factors.update(_breadth_factors(price_df))
    if intraday_bars_60m is not None:
        factors.update(_intraday_factors(price_df, intraday_bars_60m))

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
) -> Dict[str, pd.DataFrame]:
    factors = {}
    vol_ma20 = volume_df.rolling(20).mean()
    factors["volume_surge_20d"] = volume_df / vol_ma20.replace(0, np.nan)

    daily_ret = price_df.pct_change()
    vol_chg = volume_df.pct_change()
    factors["price_volume_div"] = daily_ret.rolling(20).mean() - vol_chg.rolling(20).mean()

    return factors


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
) -> Dict[int, pd.DataFrame]:
    """Compute forward returns for IC calculation."""
    horizons = horizons or [5, 10, 21]
    result = {}
    for h in horizons:
        result[h] = price_df.pct_change(h).shift(-h)
    return result
