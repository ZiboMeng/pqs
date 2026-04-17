"""
MultiFactorStrategy: composite signal from ranked factor scores.

Combines top factors (low-vol, momentum, quality, price-volume) into a single
cross-sectional score per day. Selects top_n symbols by composite rank.

Key design:
  - Each factor is z-scored cross-sectionally then averaged with weights
  - Top-N symbols get equal weight (or score-weighted)
  - Rebalance frequency configurable (daily / monthly)
  - All signals use shift(1) — no look-ahead
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)


class MultiFactorStrategy:
    """
    Multi-factor composite selection strategy.

    Parameters
    ----------
    symbols       : tradeable symbol list
    top_n         : number of symbols to hold
    factor_weights: {factor_name: weight} — higher = more important
    rebalance_monthly : if True, only rebalance on month-end
    score_weighted    : if True, weight by composite score; else equal weight
    lookback_vol      : window for volatility factor
    lookback_mom      : window for momentum factor
    lookback_quality  : window for quality (rolling sharpe) factor
    """

    _DEFAULT_REGIME_SCALE = {
        "BULL": 1.0, "RISK_ON": 1.0, "NEUTRAL": 0.90,
        "CAUTIOUS": 0.70, "RISK_OFF": 0.50, "CRISIS": 0.20,
    }

    def __init__(
        self,
        symbols:           Optional[List[str]] = None,
        top_n:             int   = 5,
        factor_weights:    Optional[Dict[str, float]] = None,
        rebalance_monthly: bool  = True,
        score_weighted:    bool  = False,
        lookback_vol:      int   = 63,
        lookback_mom:      int   = 252,
        lookback_quality:  int   = 126,
        regime_scale:      Optional[Dict[str, float]] = None,
        min_holding_days:  int   = 5,
    ):
        self._symbols     = symbols or []
        self._top_n       = top_n
        self._weights     = factor_weights or {
            "low_vol":    0.20,
            "momentum":   0.25,
            "quality":    0.20,
            "pv_div":     0.15,
            "rel_strength": 0.20,
        }
        self._monthly     = rebalance_monthly
        self._score_wt    = score_weighted
        self._vol_lb      = lookback_vol
        self._mom_lb      = lookback_mom
        self._qual_lb     = lookback_quality
        self._regime_scale = regime_scale or self._DEFAULT_REGIME_SCALE
        self._min_hold     = min_holding_days

    def generate(
        self,
        price_df:      pd.DataFrame,
        regime_series: pd.Series,
        volume_df:     Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        syms = [s for s in self._symbols if s in price_df.columns]
        if not syms:
            return pd.DataFrame(0.0, index=price_df.index, columns=price_df.columns)

        pdf = price_df[syms]
        daily_ret = pdf.pct_change()

        factors = {}

        vol = daily_ret.rolling(self._vol_lb, min_periods=20).std()
        factors["low_vol"] = -vol

        mom = pdf.pct_change(self._mom_lb)
        mom_short = pdf.pct_change(21)
        factors["momentum"] = mom - mom_short

        ret_roll = daily_ret.rolling(self._qual_lb, min_periods=40).mean() * 252
        vol_roll = daily_ret.rolling(self._qual_lb, min_periods=40).std() * np.sqrt(252)
        factors["quality"] = ret_roll / vol_roll.replace(0, np.nan)

        if volume_df is not None:
            vol_syms = [s for s in syms if s in volume_df.columns]
            if vol_syms:
                vdf = volume_df[vol_syms]
                pv_ret = daily_ret[vol_syms].rolling(20).mean()
                pv_vol = vdf.pct_change().rolling(20).mean()
                pv = pv_ret - pv_vol
                factors["pv_div"] = pv.reindex(columns=syms)

        if "SPY" in price_df.columns:
            spy_ret = price_df["SPY"].pct_change(63)
            sym_ret = pdf.pct_change(63)
            factors["rel_strength"] = sym_ret.sub(spy_ret, axis=0)

            spy = price_df["SPY"]
            spy_ma200 = spy.rolling(200).mean()
            trend = (spy / spy_ma200 - 1).clip(-0.3, 0.3)
            factors["market_trend"] = pd.DataFrame(
                {s: trend for s in syms}, index=pdf.index
            )

        def _zscore(df):
            mu = df.mean(axis=1)
            sd = df.std(axis=1).replace(0, np.nan)
            return df.sub(mu, axis=0).div(sd, axis=0)

        composite = pd.DataFrame(0.0, index=pdf.index, columns=syms)
        total_w = 0.0
        for fname, fdf in factors.items():
            w = self._weights.get(fname, 0.0)
            if w <= 0 or fdf is None:
                continue
            z = _zscore(fdf.reindex(columns=syms))
            composite = composite + z.fillna(0) * w
            total_w += w

        if total_w > 0:
            composite = composite / total_w

        composite = composite.shift(1)

        signals = pd.DataFrame(0.0, index=price_df.index, columns=price_df.columns)

        if self._monthly:
            rebal_mask = pd.Series(False, index=pdf.index)
            months = pdf.index.to_period("M")
            for m in months.unique():
                month_dates = pdf.index[months == m]
                if len(month_dates) > 0:
                    rebal_mask.loc[month_dates[-1]] = True
        else:
            rebal_mask = pd.Series(True, index=pdf.index)

        last_selection = pd.Series(0.0, index=price_df.columns)
        days_since_rebal = self._min_hold

        for date in pdf.index:
            days_since_rebal += 1

            if not rebal_mask.get(date, False) or days_since_rebal < self._min_hold:
                signals.loc[date] = last_selection
                continue

            scores = composite.loc[date].dropna()
            if len(scores) < self._top_n:
                signals.loc[date] = last_selection
                continue

            top = scores.nlargest(self._top_n)
            current_held = set(last_selection[last_selection > 0].index)
            new_held = set(top.index)

            if current_held == new_held:
                signals.loc[date] = last_selection
                continue

            if self._score_wt and (top > 0).any():
                pos_scores = top.clip(lower=0)
                total = pos_scores.sum()
                if total > 0:
                    wts = pos_scores / total
                else:
                    wts = pd.Series(1.0 / self._top_n, index=top.index)
            else:
                wts = pd.Series(1.0 / self._top_n, index=top.index)

            row = pd.Series(0.0, index=price_df.columns)
            for sym in wts.index:
                if sym in row.index:
                    row[sym] = wts[sym]
            signals.loc[date] = row
            last_selection = row
            days_since_rebal = 0

        aligned_regime = regime_series.reindex(signals.index, method="ffill")
        for date in signals.index:
            r = aligned_regime.get(date, "NEUTRAL")
            scale = self._regime_scale.get(str(r), 0.90)
            if scale < 1.0:
                signals.loc[date] = signals.loc[date] * scale

        return signals
