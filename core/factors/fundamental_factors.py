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


def compute_beneish_factors(
    daily_idx: pd.DatetimeIndex,
    tickers: List[str],
    store: FundamentalsStore,
) -> Dict[str, pd.DataFrame]:
    """Beneish M-score and 8 sub-ratios — earnings manipulation detection.

    M-score = -4.84
            + 0.92×DSRI + 0.528×GMI + 0.404×AQI + 0.892×SGI
            + 0.115×DEPI - 0.172×SGAI + 4.679×TATA - 0.327×LVGI
    Threshold: M > -2.22 → likely manipulator.

    Reference: Beneish 1999. Validated again in 2025 G7 study
    (Tandfonline Cogent 2025.2502542) and 2025 Borsa Istanbul ML
    study (Sage 2025.21582440251386174).
    """
    factors: Dict[str, pd.DataFrame] = {}

    # Load all required panels
    ar = store.load_panel(tickers, "accounts_receivable", daily_idx)
    sales_ttm = store.load_panel(tickers, "revenues", daily_idx, ttm=True)
    gross_ttm = store.load_panel(tickers, "gross_profit", daily_idx, ttm=True)
    assets = store.load_panel(tickers, "total_assets", daily_idx)
    current_assets = store.load_panel(tickers, "current_assets", daily_idx)
    ppe = store.load_panel(tickers, "ppe_net", daily_idx)
    dep_ttm = store.load_panel(tickers, "depreciation", daily_idx, ttm=True)
    sga_ttm = store.load_panel(tickers, "sga_expense", daily_idx, ttm=True)
    ni_ttm = store.load_panel(tickers, "net_income", daily_idx, ttm=True)
    cfo_ttm = store.load_panel(tickers, "cfo", daily_idx, ttm=True)
    total_liab = store.load_panel(tickers, "total_liabilities", daily_idx)

    L = 252  # YoY lag in business days

    # DSRI = (AR/Sales)_t / (AR/Sales)_{t-L}
    ar_to_sales = _safe_div(ar, sales_ttm)
    factors["beneish_dsri"] = _safe_div(ar_to_sales, ar_to_sales.shift(L))

    # GMI = GM_{t-L} / GM_t (note inversion: rising COGS share → GMI > 1)
    gross_margin = _safe_div(gross_ttm, sales_ttm)
    factors["beneish_gmi"] = _safe_div(gross_margin.shift(L), gross_margin)

    # AQI = (1 - (CA + PPE) / Assets)_t / same_{t-L}
    quality_ratio = 1.0 - _safe_div(current_assets + ppe, assets)
    factors["beneish_aqi"] = _safe_div(quality_ratio, quality_ratio.shift(L))

    # SGI = Sales_t / Sales_{t-L}
    factors["beneish_sgi"] = _safe_div(sales_ttm, sales_ttm.shift(L))

    # DEPI = (DepRate_{t-L}) / (DepRate_t)
    dep_rate = _safe_div(dep_ttm, dep_ttm + ppe.replace(0, np.nan))
    factors["beneish_depi"] = _safe_div(dep_rate.shift(L), dep_rate)

    # SGAI = (SGA/Sales)_t / (SGA/Sales)_{t-L}
    sga_to_sales = _safe_div(sga_ttm, sales_ttm)
    factors["beneish_sgai"] = _safe_div(sga_to_sales, sga_to_sales.shift(L))

    # TATA = (NI - CFO) / Assets (total accruals to total assets)
    factors["beneish_tata"] = _safe_div(ni_ttm - cfo_ttm, assets)

    # LVGI = (Liab/Assets)_t / (Liab/Assets)_{t-L}
    leverage_ratio = _safe_div(total_liab, assets)
    factors["beneish_lvgi"] = _safe_div(leverage_ratio, leverage_ratio.shift(L))

    # M-score composite
    factors["beneish_m_score"] = (
        -4.84
        + 0.92 * factors["beneish_dsri"]
        + 0.528 * factors["beneish_gmi"]
        + 0.404 * factors["beneish_aqi"]
        + 0.892 * factors["beneish_sgi"]
        + 0.115 * factors["beneish_depi"]
        - 0.172 * factors["beneish_sgai"]
        + 4.679 * factors["beneish_tata"]
        - 0.327 * factors["beneish_lvgi"]
    )

    return factors


def compute_altman_factors(
    daily_idx: pd.DatetimeIndex,
    tickers: List[str],
    store: FundamentalsStore,
    price_df: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """Altman Z-score (manufacturing 5-variable, 1968) + 5 components.

    Z = 1.2×WC/TA + 1.4×RE/TA + 3.3×EBIT/TA + 0.6×MV_Eq/TL + 1.0×Sales/TA

    Interpretation:
      Z > 2.99 = safe
      Z 1.81-2.99 = grey zone
      Z < 1.81 = distress

    MV_Equity component requires `price_df` (close × shares). If
    price_df is None, that component is NaN → Z composite is NaN.
    """
    factors: Dict[str, pd.DataFrame] = {}

    current_assets = store.load_panel(tickers, "current_assets", daily_idx)
    current_liab = store.load_panel(tickers, "current_liabilities", daily_idx)
    retained_earnings = store.load_panel(tickers, "retained_earnings", daily_idx)
    ebit_ttm = store.load_panel(tickers, "operating_income", daily_idx, ttm=True)
    total_liab = store.load_panel(tickers, "total_liabilities", daily_idx)
    sales_ttm = store.load_panel(tickers, "revenues", daily_idx, ttm=True)
    assets = store.load_panel(tickers, "total_assets", daily_idx)
    shares = store.load_panel(tickers, "shares_outstanding", daily_idx)

    factors["altman_wc_to_assets"] = _safe_div(current_assets - current_liab, assets)
    factors["altman_re_to_assets"] = _safe_div(retained_earnings, assets)
    factors["altman_ebit_to_assets"] = _safe_div(ebit_ttm, assets)
    factors["altman_sales_to_assets"] = _safe_div(sales_ttm, assets)

    if price_df is not None:
        px = price_df.reindex(index=daily_idx, columns=tickers)
        market_cap = px * shares
        factors["altman_mveq_to_liab"] = _safe_div(market_cap, total_liab)
    else:
        factors["altman_mveq_to_liab"] = pd.DataFrame(np.nan, index=daily_idx, columns=tickers)

    factors["altman_z_score"] = (
        1.2 * factors["altman_wc_to_assets"]
        + 1.4 * factors["altman_re_to_assets"]
        + 3.3 * factors["altman_ebit_to_assets"]
        + 0.6 * factors["altman_mveq_to_liab"]
        + 1.0 * factors["altman_sales_to_assets"]
    )

    return factors


def compute_capital_return_factors(
    daily_idx: pd.DatetimeIndex,
    tickers: List[str],
    store: FundamentalsStore,
    price_df: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """Buyback / dividend / shareholder yield + FCF yield + FCF profitability.

    buyback_yield_ttm  = (shares_{t-L} - shares_t) × close / market_cap
                       = pct_decrease in shares × 1 (already a yield)
    dividend_yield_ttm = dividends_paid_ttm / market_cap
    shareholder_yield_ttm = buyback + dividend
    fcf_yield_ttm      = (CFO_ttm - CapEx_ttm) / market_cap
    fcf_to_assets_ttm  = FCF_ttm / total_assets
                       (FCF Profitability per LSEG 2025; Sharpe 0.62 > FCFY 0.50)

    All require `price_df` for market_cap.
    """
    factors: Dict[str, pd.DataFrame] = {}

    shares = store.load_panel(tickers, "shares_outstanding", daily_idx)
    cfo_ttm = store.load_panel(tickers, "cfo", daily_idx, ttm=True)
    capex_ttm = store.load_panel(tickers, "capex", daily_idx, ttm=True)
    dividends_ttm = store.load_panel(tickers, "dividends_cash", daily_idx, ttm=True)
    assets = store.load_panel(tickers, "total_assets", daily_idx)

    fcf_ttm = cfo_ttm - capex_ttm.fillna(0)
    factors["fcf_to_assets_ttm"] = _safe_div(fcf_ttm, assets)

    if price_df is None:
        for n in ["buyback_yield_ttm", "dividend_yield_ttm", "shareholder_yield_ttm", "fcf_yield_ttm"]:
            factors[n] = pd.DataFrame(np.nan, index=daily_idx, columns=tickers)
        return factors

    px = price_df.reindex(index=daily_idx, columns=tickers)
    market_cap = px * shares

    L = 252  # YoY lag
    shares_yoy = shares - shares.shift(L)  # negative = buyback
    # buyback_yield (positive when shares decreased)
    factors["buyback_yield_ttm"] = _safe_div(-shares_yoy * px, market_cap)
    factors["dividend_yield_ttm"] = _safe_div(dividends_ttm, market_cap)
    factors["shareholder_yield_ttm"] = (
        factors["buyback_yield_ttm"].fillna(0) + factors["dividend_yield_ttm"].fillna(0)
    )
    factors["fcf_yield_ttm"] = _safe_div(fcf_ttm, market_cap)
    return factors


def compute_growth_and_leverage_factors(
    daily_idx: pd.DatetimeIndex,
    tickers: List[str],
    store: FundamentalsStore,
) -> Dict[str, pd.DataFrame]:
    """Revenue momentum + asset growth + DOL + R&D intensity."""
    factors: Dict[str, pd.DataFrame] = {}

    sales_ttm = store.load_panel(tickers, "revenues", daily_idx, ttm=True)
    gross_ttm = store.load_panel(tickers, "gross_profit", daily_idx, ttm=True)
    assets = store.load_panel(tickers, "total_assets", daily_idx)
    ebit_ttm = store.load_panel(tickers, "operating_income", daily_idx, ttm=True)
    rd_ttm = store.load_panel(tickers, "rd_expense", daily_idx, ttm=True)

    L = 252
    factors["revenue_growth_yoy"] = _yoy_pct_change(sales_ttm, L)
    factors["gross_profit_growth_yoy"] = _yoy_pct_change(gross_ttm, L)
    factors["sales_acceleration"] = (
        factors["revenue_growth_yoy"] - factors["revenue_growth_yoy"].shift(L)
    )
    factors["asset_growth_yoy"] = _yoy_pct_change(assets, L)

    # DOL proxy: % change in EBIT / % change in Sales (yoy)
    ebit_yoy = _yoy_pct_change(ebit_ttm, L)
    sales_yoy = factors["revenue_growth_yoy"]
    factors["dol_4q_window"] = _safe_div(ebit_yoy, sales_yoy)

    # R&D intensity
    factors["rd_intensity_ttm"] = _safe_div(rd_ttm, sales_ttm)

    return factors


def compute_fundamental_factors_full(
    daily_idx: pd.DatetimeIndex,
    tickers: List[str],
    store: Optional[FundamentalsStore] = None,
    price_df: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """Run all R5-R7 batches (Piotroski + Magic + Beneish + Altman +
    capital return + growth & leverage)."""
    store = store or FundamentalsStore()
    out = {}
    out.update(compute_piotroski_factors(daily_idx, tickers, store))
    out.update(compute_magic_formula_factors(daily_idx, tickers, store, price_df))
    out.update(compute_beneish_factors(daily_idx, tickers, store))
    out.update(compute_altman_factors(daily_idx, tickers, store, price_df))
    out.update(compute_capital_return_factors(daily_idx, tickers, store, price_df))
    out.update(compute_growth_and_leverage_factors(daily_idx, tickers, store))
    return out


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


FUNDAMENTAL_FACTORS_BATCH2_NAMES = [
    # Beneish 8 sub + composite
    "beneish_dsri", "beneish_gmi", "beneish_aqi", "beneish_sgi",
    "beneish_depi", "beneish_sgai", "beneish_tata", "beneish_lvgi",
    "beneish_m_score",
    # Altman 4 ratios + MV variant + composite
    "altman_wc_to_assets", "altman_re_to_assets", "altman_ebit_to_assets",
    "altman_mveq_to_liab", "altman_sales_to_assets",
    "altman_z_score",
    # Capital return + FCF
    "buyback_yield_ttm", "dividend_yield_ttm", "shareholder_yield_ttm",
    "fcf_yield_ttm", "fcf_to_assets_ttm",
    # Growth + leverage
    "revenue_growth_yoy", "gross_profit_growth_yoy", "sales_acceleration",
    "asset_growth_yoy", "dol_4q_window", "rd_intensity_ttm",
]


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
