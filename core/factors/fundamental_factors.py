"""Fundamental factors derived from SEC EDGAR companyfacts cache.

PRD-driven 2026-05-12 per:
- docs/memos/20260512-quant_factor_literature_synthesis_v2.md §2.3 + §7.1
- docs/memos/20260512-bucket_abc_macro_mvp_schedule.md §1 D6+

Inputs: PIT panels from FundamentalsStore (filed_date-indexed,
forward-filled onto daily business-day calendar). Outputs: daily
factor panels aligned to caller's `daily_idx` × `tickers`.

Sign convention (consistent with PQS factor_generator):
  Higher factor value → ML / mining infers IC sign from historical
  forward returns. We use **economic-direction** values where natural
  (e.g. piotroski_f_score positive); do NOT invert.

First batch (R5):
  Piotroski F-score (9 boolean + composite + 2 derived):
    - piotroski_net_income_positive
    - piotroski_cfo_positive
    - piotroski_roa_yoy_improving
    - piotroski_cfo_greater_than_ni
    - piotroski_leverage_yoy_decreasing
    - piotroski_current_ratio_yoy_improving
    - piotroski_no_dilution
    - piotroski_gross_margin_yoy_improving
    - piotroski_asset_turnover_yoy_improving
    - piotroski_f_score              (composite 0-9)
    - piotroski_high_filter           (≥ 7 → 1)
    - piotroski_low_warning           (≤ 3 → 1)
  Magic Formula (3 components + 1 composite):
    - magic_earnings_yield_ttm        (EBIT_ttm / EnterpriseValue)
    - magic_roic_ttm                  (EBIT_ttm × (1-tax) / InvestedCapital)
    - magic_formula_rank_composite    (rank_pct(EY) + rank_pct(ROIC))
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.data.fundamentals_store import FundamentalsStore

logger = logging.getLogger(__name__)


def _yoy_change(panel: pd.DataFrame, lag_days: int = 252) -> pd.DataFrame:
    """Year-over-year change on daily panel (252 business days ≈ 1y)."""
    return panel - panel.shift(lag_days)


def _yoy_pct_change(panel: pd.DataFrame, lag_days: int = 252) -> pd.DataFrame:
    prev = panel.shift(lag_days)
    return (panel - prev) / prev.replace(0, np.nan)


def _safe_div(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    return a / b.replace(0, np.nan)


def compute_piotroski_factors(
    daily_idx: pd.DatetimeIndex,
    tickers: List[str],
    store: FundamentalsStore,
) -> Dict[str, pd.DataFrame]:
    """Piotroski F-Score 9 boolean indicators + composite + 2 derived.

    Reference: Piotroski 2000; Schwartz-Hanauer Dec 2024 NBER (4-formula
    comparison confirming F-score persistent across 1963-2022).
    """
    factors: Dict[str, pd.DataFrame] = {}

    # Load PIT panels
    ni_ttm = store.load_panel(tickers, "net_income", daily_idx, ttm=True)
    cfo_ttm = store.load_panel(tickers, "cfo", daily_idx, ttm=True)
    assets = store.load_panel(tickers, "total_assets", daily_idx)
    revenues_ttm = store.load_panel(tickers, "revenues", daily_idx, ttm=True)
    gross_profit_ttm = store.load_panel(tickers, "gross_profit", daily_idx, ttm=True)
    long_term_debt = store.load_panel(tickers, "long_term_debt", daily_idx)
    current_assets = store.load_panel(tickers, "current_assets", daily_idx)
    current_liab = store.load_panel(tickers, "current_liabilities", daily_idx)
    shares = store.load_panel(tickers, "shares_outstanding", daily_idx)

    def _bool(panel: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
        """Boolean indicator preserving NaN where underlying input is NaN.
        Without this, (NaN > 0).astype(float) silently produces 0.0,
        making missing-data rows look like 'failing' boolean → wrong."""
        return panel.where(~mask.isna())

    # Profitability
    factors["piotroski_net_income_positive"] = _bool((ni_ttm > 0).astype(float), ni_ttm)
    factors["piotroski_cfo_positive"] = _bool((cfo_ttm > 0).astype(float), cfo_ttm)

    # ROA = NI / assets; improvement = YoY
    roa = _safe_div(ni_ttm, assets)
    roa_yoy = _yoy_change(roa)
    factors["piotroski_roa_yoy_improving"] = _bool((roa_yoy > 0).astype(float), roa_yoy)

    # Quality of earnings: CFO > NI (no over-accruing)
    factors["piotroski_cfo_greater_than_ni"] = _bool(
        (cfo_ttm > ni_ttm).astype(float), cfo_ttm + ni_ttm,
    )

    # Leverage: long-term debt / assets — yoy decreasing
    leverage = _safe_div(long_term_debt, assets)
    leverage_yoy = _yoy_change(leverage)
    factors["piotroski_leverage_yoy_decreasing"] = _bool(
        (leverage_yoy <= 0).astype(float), leverage_yoy,
    )

    # Liquidity: current ratio — yoy improving
    current_ratio = _safe_div(current_assets, current_liab)
    cr_yoy = _yoy_change(current_ratio)
    factors["piotroski_current_ratio_yoy_improving"] = _bool(
        (cr_yoy >= 0).astype(float), cr_yoy,
    )

    # No dilution: shares outstanding yoy ≤ 0
    shares_yoy = _yoy_change(shares)
    factors["piotroski_no_dilution"] = _bool((shares_yoy <= 0).astype(float), shares_yoy)

    # Operating efficiency: gross margin yoy improving
    gross_margin = _safe_div(gross_profit_ttm, revenues_ttm)
    gm_yoy = _yoy_change(gross_margin)
    factors["piotroski_gross_margin_yoy_improving"] = _bool(
        (gm_yoy >= 0).astype(float), gm_yoy,
    )

    # Asset turnover yoy improving
    asset_turnover = _safe_div(revenues_ttm, assets)
    at_yoy = _yoy_change(asset_turnover)
    factors["piotroski_asset_turnover_yoy_improving"] = _bool(
        (at_yoy >= 0).astype(float), at_yoy,
    )

    # Composite + filter / warning derived factors
    score_components = [
        factors["piotroski_net_income_positive"],
        factors["piotroski_cfo_positive"],
        factors["piotroski_roa_yoy_improving"],
        factors["piotroski_cfo_greater_than_ni"],
        factors["piotroski_leverage_yoy_decreasing"],
        factors["piotroski_current_ratio_yoy_improving"],
        factors["piotroski_no_dilution"],
        factors["piotroski_gross_margin_yoy_improving"],
        factors["piotroski_asset_turnover_yoy_improving"],
    ]
    # Stack and sum across components — but maintain NaN propagation:
    # a row where any underlying input is NaN should also be NaN.
    composite = sum(score_components)
    # Re-introduce NaN where any underlying data is NaN
    nan_mask = ni_ttm.isna() | cfo_ttm.isna() | assets.isna() | revenues_ttm.isna()
    composite = composite.where(~nan_mask)
    factors["piotroski_f_score"] = composite
    factors["piotroski_high_filter"] = (composite >= 7).astype(float).where(~nan_mask)
    factors["piotroski_low_warning"] = (composite <= 3).astype(float).where(~nan_mask)

    return factors


def compute_magic_formula_factors(
    daily_idx: pd.DatetimeIndex,
    tickers: List[str],
    store: FundamentalsStore,
    price_df: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """Greenblatt Magic Formula: rank by earnings yield × ROIC.

    Definitions used here (closed-form, EDGAR-only where possible):
      earnings_yield_ttm = EBIT_ttm / EnterpriseValue
                          where EV = market_cap + TotalDebt - Cash
      roic_ttm           = EBIT_ttm × (1 - tax_rate) / InvestedCapital
                          where InvestedCapital = TotalAssets - CurrentLiabilities
                          tax_rate proxy = 1 - NetIncome/PretaxIncome (when
                          available); fallback 0.21 (US federal)

    Composite rank: cross-sectional pct_rank of each component, then sum.
    Higher rank composite = more "magic-formula attractive" stock.

    Requires `price_df` (close prices) to compute market cap (close × shares).
    If price_df is None, market_cap is NaN → EY is NaN → composite is NaN.
    """
    factors: Dict[str, pd.DataFrame] = {}

    ebit_ttm = store.load_panel(tickers, "operating_income", daily_idx, ttm=True)
    ni_ttm = store.load_panel(tickers, "net_income", daily_idx, ttm=True)
    assets = store.load_panel(tickers, "total_assets", daily_idx)
    current_liab = store.load_panel(tickers, "current_liabilities", daily_idx)
    long_term_debt = store.load_panel(tickers, "long_term_debt", daily_idx)
    cash = store.load_panel(tickers, "cash", daily_idx)
    shares = store.load_panel(tickers, "shares_outstanding", daily_idx)

    # Market cap = close × shares_outstanding (PIT-forward-filled)
    if price_df is not None:
        # Align price_df to (daily_idx × tickers)
        px = price_df.reindex(index=daily_idx, columns=tickers)
        market_cap = px * shares
    else:
        market_cap = pd.DataFrame(np.nan, index=daily_idx, columns=tickers)

    enterprise_value = market_cap + long_term_debt.fillna(0) - cash.fillna(0)
    factors["magic_earnings_yield_ttm"] = _safe_div(ebit_ttm, enterprise_value)

    # ROIC
    invested_capital = (assets - current_liab).replace(0, np.nan)
    # Tax proxy: avoid divide-by-zero / sign issues with pretax income
    tax_rate = pd.DataFrame(0.21, index=daily_idx, columns=tickers)  # fixed 21% proxy
    nopat = ebit_ttm * (1 - tax_rate)
    factors["magic_roic_ttm"] = _safe_div(nopat, invested_capital)

    # Composite: cross-sectional rank pct of each component, summed
    ey_rank = factors["magic_earnings_yield_ttm"].rank(pct=True, axis=1)
    roic_rank = factors["magic_roic_ttm"].rank(pct=True, axis=1)
    factors["magic_formula_rank_composite"] = ey_rank + roic_rank

    return factors


def compute_fundamental_factors_batch1(
    daily_idx: pd.DatetimeIndex,
    tickers: List[str],
    store: Optional[FundamentalsStore] = None,
    price_df: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """Convenience: produce R5 batch (Piotroski + Magic Formula) as one dict."""
    store = store or FundamentalsStore()
    out = {}
    out.update(compute_piotroski_factors(daily_idx, tickers, store))
    out.update(compute_magic_formula_factors(daily_idx, tickers, store, price_df=price_df))
    return out


FUNDAMENTAL_FACTORS_BATCH1_NAMES = [
    # Piotroski 9 boolean + composite + 2 derived
    "piotroski_net_income_positive",
    "piotroski_cfo_positive",
    "piotroski_roa_yoy_improving",
    "piotroski_cfo_greater_than_ni",
    "piotroski_leverage_yoy_decreasing",
    "piotroski_current_ratio_yoy_improving",
    "piotroski_no_dilution",
    "piotroski_gross_margin_yoy_improving",
    "piotroski_asset_turnover_yoy_improving",
    "piotroski_f_score",
    "piotroski_high_filter",
    "piotroski_low_warning",
    # Magic Formula
    "magic_earnings_yield_ttm",
    "magic_roic_ttm",
    "magic_formula_rank_composite",
]
