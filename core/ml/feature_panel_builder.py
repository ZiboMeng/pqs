"""Multi-path factor panel builder + cross-sectional rank transformation.

Per `docs/prd/20260512-ml_mining_pipeline_prd.md` §3.2-3.3.

Builds the unified 162-factor panel (OHLCV + EDGAR fundamental + sector +
FRED macro + event-window + signal-confirmation) and converts raw factor
values to per-date cross-sectional rank in [0, 1] suitable for XGBoost
input.

Cross-sectional rank handles:
- Outliers (rank is bounded)
- Scale differences across factors (rank is unit-less)
- Per-date cross-sectional comparison (matches mining harness top-N
  selection semantics)

NaN policy:
- Raw factor NaN → rank NaN preserved (XGBoost native NaN handling)
- NOT zero-imputed (per PRD §7.4b: preserves 4-state distinction
  true-zero / warmup / non-tradable / data-missing)
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from core.data.bar_store import BarStore
from core.factors.base_masks import research_mask_default
from core.factors.factor_generator import generate_all_factors
from core.factors.factor_registry import RESEARCH_FACTORS
from core.logging_setup import get_logger
from core.research.risk_cluster_map import CROSS_ASSET_RISK_CLUSTER_MAP

logger = get_logger("ml_feature_panel")


def build_panel_frames(
    cfg,
    store: Optional[BarStore] = None,
    drop_symbols: Optional[List[str]] = None,
    use_adjusted: bool = True,
) -> Tuple[Dict[str, pd.DataFrame], List[str]]:
    """Load OHLCV frames + tradable list. Uses adjusted prices by default
    (matching cycle07a Track A eval semantics; differs from miner's raw
    `store.read` path)."""
    if store is None:
        store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    drop_set = set(drop_symbols or [])
    syms = [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference and s not in drop_set]
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)
    cross_asset_set = set(CROSS_ASSET_RISK_CLUSTER_MAP.keys())
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        atr = sym in cross_asset_set
        if use_adjusted:
            df = store.load(sym, freq="1d", adjusted=True,
                            adjusted_total_return=atr, fallback="local")
        else:
            df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    out = {"close": pd.DataFrame(frames["close"]).sort_index()}
    for col in ("open", "high", "low", "volume"):
        if frames[col]:
            out[col] = pd.DataFrame(frames[col]).reindex_like(out["close"])
        else:
            out[col] = None
    tradable = [s for s in syms if s in out["close"].columns]
    return out, tradable


def build_multi_path_factors(
    panel: Dict[str, pd.DataFrame],
    restrict_to_research_factors: bool = True,
) -> Dict[str, pd.DataFrame]:
    """Build all factor families: OHLCV (FactorGenerator) + EDGAR fundamental
    + sector + FRED macro + event-window + signal-confirmation.

    Returns dict[factor_name → DataFrame(date × symbol)]. Failed family
    paths log a warning and are skipped (degrades gracefully)."""
    close = panel["close"]
    volume = panel["volume"]
    open_df = panel.get("open")
    high_df = panel.get("high")
    low_df = panel.get("low")
    tickers = list(close.columns)
    daily_idx = close.index

    bench = {b: close[b] for b in ("SPY", "QQQ") if b in close.columns}

    # OHLCV factors (Family A-J)
    ohlcv = generate_all_factors(
        close, volume_df=volume,
        open_df=open_df, high_df=high_df, low_df=low_df,
        benchmark_map=bench,
    )
    if restrict_to_research_factors:
        factors = {n: f for n, f in ohlcv.items() if n in RESEARCH_FACTORS}
    else:
        factors = dict(ohlcv)
    logger.info("OHLCV factors: %d", len(factors))

    # Bucket B EDGAR fundamental (Family K/L/M/N)
    try:
        from core.factors.fundamental_factors import (
            compute_fundamental_factors_full,
        )
        from core.data.fundamentals_store import FundamentalsStore
        fstore = FundamentalsStore()
        fund = compute_fundamental_factors_full(
            daily_idx, tickers, store=fstore, price_df=close,
        )
        added = sum(
            1 for n, fdf in fund.items()
            if (not restrict_to_research_factors or n in RESEARCH_FACTORS)
            and (factors.update({n: fdf}) or True)
        )
        logger.info("Fundamental factors: +%d", added)
    except Exception as e:
        logger.warning("Fundamental compute failed: %s", e)

    # Bucket C sector (Family O)
    try:
        from core.factors.sector_factors import compute_sector_factors
        sec = compute_sector_factors(close)
        for n, sdf in sec.items():
            if not restrict_to_research_factors or n in RESEARCH_FACTORS:
                factors[n] = sdf
        logger.info("Sector factors merged")
    except Exception as e:
        logger.warning("Sector compute failed: %s", e)

    # Bucket Macro FRED (Family P)
    try:
        from core.factors.macro_factors import compute_macro_factors
        macro = compute_macro_factors(daily_idx, tickers)
        for n, mdf in macro.items():
            if not restrict_to_research_factors or n in RESEARCH_FACTORS:
                factors[n] = mdf
        logger.info("Macro factors merged")
    except Exception as e:
        logger.warning("Macro compute failed: %s", e)

    # Round D event window
    try:
        from core.factors.event_window_factors import (
            compute_event_window_factors,
        )
        ev = compute_event_window_factors(daily_idx, tickers)
        for n, edf in ev.items():
            if not restrict_to_research_factors or n in RESEARCH_FACTORS:
                factors[n] = edf
        logger.info("Event-window factors merged")
    except Exception as e:
        logger.warning("Event-window compute failed: %s", e)

    # Round F signal-confirmation
    try:
        from core.factors.signal_confirmation_factors import (
            compute_signal_confirmation_factors,
        )
        sc = compute_signal_confirmation_factors(close, volume)
        for n, sdf in sc.items():
            if not restrict_to_research_factors or n in RESEARCH_FACTORS:
                factors[n] = sdf
        logger.info("Signal-conf factors merged")
    except Exception as e:
        logger.warning("Signal-conf compute failed: %s", e)

    logger.info("Total factors built: %d", len(factors))
    return factors


def cross_sectional_rank(
    factor_df: pd.DataFrame,
    method: str = "average",
) -> pd.DataFrame:
    """Convert per-date factor values to cross-sectional rank in [0, 1].

    NaN values preserved as NaN (not imputed). Rank computed per row
    (per date) using pandas rank with pct=True.

    method: 'average' (default), 'min', 'max', 'dense', 'first' — passed
    through to pandas .rank().
    """
    return factor_df.rank(axis=1, method=method, pct=True, na_option="keep")


def build_ml_panel(
    factors: Dict[str, pd.DataFrame],
    fwd_returns: pd.DataFrame,
    research_mask: Optional[pd.DataFrame] = None,
    apply_rank: bool = True,
) -> Tuple[pd.DataFrame, List[str]]:
    """Combine factors + forward returns into a long-form ML training panel.

    Returns (panel_df, feature_cols) where panel_df has columns:
        date, symbol, <factor_1>, <factor_2>, ..., fwd_return

    If apply_rank=True (default), factors are cross-sectional ranked
    BEFORE the long-form melt (vectorized, not per-date Python loop).
    research_mask (if provided) filters out (date, symbol) pairs that
    fail the tradability mask.
    """
    feature_cols = sorted(factors.keys())
    if not feature_cols:
        return pd.DataFrame(), feature_cols

    # Vectorized cross-sectional rank per factor (much faster than per-date loop)
    if apply_rank:
        ranked_factors = {
            fac: cross_sectional_rank(factors[fac]) for fac in feature_cols
        }
    else:
        ranked_factors = dict(factors)

    # Melt fwd_returns to long form (drop NaN fwd rows), then merge each
    # factor on (date, symbol)
    fwd_long = (
        fwd_returns
        .stack()
        .rename("fwd_return")
        .reset_index()
    )
    fwd_long.columns = ["date", "symbol", "fwd_return"]
    fwd_long = fwd_long.dropna(subset=["fwd_return"])

    if research_mask is not None:
        mask_long = (
            research_mask
            .stack()
            .rename("ok")
            .reset_index()
        )
        mask_long.columns = ["date", "symbol", "ok"]
        fwd_long = fwd_long.merge(mask_long, on=["date", "symbol"], how="left")
        n_before = len(fwd_long)
        fwd_long = fwd_long[fwd_long["ok"].fillna(False)].drop(columns=["ok"])
        n_masked = n_before - len(fwd_long)
    else:
        n_masked = 0

    panel = fwd_long
    for fac in feature_cols:
        fdf = ranked_factors[fac]
        f_long = (
            fdf.stack()
            .rename(fac).reset_index()
        )
        f_long.columns = ["date", "symbol", fac]
        panel = panel.merge(f_long, on=["date", "symbol"], how="left")

    panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)

    logger.info("ML panel: %d rows × %d features (masked out: %d)",
                len(panel), len(feature_cols), n_masked)
    return panel, feature_cols
