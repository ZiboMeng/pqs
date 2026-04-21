"""
MultiFactorStrategy: composite signal from ranked factor scores.

Combines top factors (low-vol, momentum, quality, price-volume, rel-strength,
market-trend) into a single cross-sectional score per day. Selects top_n
symbols by composite rank.

Architecture (formalized 约束 2, 2026-04-20):
  This strategy is the EXECUTION pipeline. It computes factors INLINE for
  performance (avoids the 4× cost of running all 35+ research factors per
  trial). The set of accepted factor names is enumerated in
  `core/factors/factor_registry.py::PRODUCTION_FACTORS` — the authoritative
  single source of truth that ties execution, mining search space, and
  the research→production promotion contract together.

  Passing an unknown factor name via `factor_weights` triggers a warning
  (not an error, so legacy callers keep working while we migrate) but the
  weight is dropped from composite computation. See
  `factor_registry.check_execution_factor_names()`.

  Pipeline relationship (CLAUDE.md → "Factor pipeline contract"):
    Research (factor_generator) → IC/OOS/regime funnel → promotion
      → add inline block here + add to PRODUCTION_FACTORS + add to
         MultiFactorSpace.suggest() → execution

  Research-only factors never enter execution until promoted. This
  strategy deliberately does NOT import factor_generator.

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

from core.factors.factor_registry import (
    PRODUCTION_FACTORS,
    check_execution_factor_names,
    enforce_execution_factor_names,
)
from core.logging_setup import get_logger

logger = get_logger(__name__)


def _cap_and_redistribute(row: pd.Series, cap: float, max_iter: int = 12) -> pd.Series:
    """Iteratively cap each weight at `cap` and redistribute excess mass to
    symbols still below cap, preserving row total. If mass cannot fit within
    the cap (cap * n_nonzero < row.sum), returns best-effort (all at cap).

    Example: row=[0.9, 0.05, 0.05], cap=0.40 → iter 1: [0.40, 0.30, 0.30]
    (excess 0.5 split proportionally to 0.05+0.05=0.10 room) → no further
    violations → total preserved at 1.0.
    """
    target_sum = float(row.sum())
    out = row.copy().astype(float)
    for _ in range(max_iter):
        violators = out > cap
        if not violators.any():
            break
        excess = float((out[violators] - cap).sum())
        out[violators] = cap
        room = (cap - out).clip(lower=0)
        # Only redistribute to currently non-zero (active) symbols; keep zeros at 0
        active = (out > 0) & ~violators
        room_active = room.where(active, 0.0)
        room_total = float(room_active.sum())
        if room_total <= 1e-12:
            break  # no space to redistribute
        out = out + (excess * room_active / room_total)
    return out


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
        apply_extra_shift: bool  = False,
        concentration_warn_threshold: Optional[float] = None,
        soft_cap_max_single: Optional[float] = None,
        strict_registry:   bool  = False,
    ):
        """
        apply_extra_shift : controls signal freshness.
            False (default, 2026-04-20 onward): signal at T uses T-close
            factors; execution at T+1 open = standard 1-bar lag. No
            lookahead — T-close data is observable AT T-close, executable
            at T+1 open. This is the correct production default.

            True (legacy): signals shift(1) after factor compute, so
            signal at T uses T-1 factors, executed at T+1 open = 2-bar
            lag (redundant and stale). Kept as a flag for A/B research
            and reproducibility of historical backtests. Do NOT use in
            live paper trading — signals lag the market by an extra day.

            Bug history: all production paths (run_backtest, run_paper,
            run_mining, run_multi_tf_backtest) previously inherited the
            legacy True default, so live execution used T-2 close data.
            Fixed 2026-04-20 (P0.1 收口闭环).
        concentration_warn_threshold : if set, log a WARNING at end of
            `generate()` whenever any single symbol's weight across any row
            exceeds this threshold (purely diagnostic — does not modify
            signals). Pass e.g. `cfg.risk.max_single_position` to tie to
            portfolio hard cap. None → no warning.
        soft_cap_max_single : if set, clip any single-symbol weight to this
            cap and renormalize to preserve total exposure. This is a
            STRATEGY-level soft cap that runs BEFORE the PortfolioConstructor
            hard cap. None → no strategy-level capping (current default;
            constructor hard cap still applies downstream).
        """
        self._symbols     = symbols or []
        self._top_n       = top_n
        weights = factor_weights or {
            "low_vol":    0.20,
            "momentum":   0.25,
            "quality":    0.20,
            "pv_div":     0.15,
            "rel_strength": 0.20,
        }
        # Registry gate: reject any factor name NOT in PRODUCTION_FACTORS.
        # strict_registry=False (default): WARN + drop (legacy).
        # strict_registry=True: raise UnregisteredFactorError — use in
        # mining / CI / production where silent name drift is a hazard.
        # Round 4 Topic D (2026-04-20): gating now routes through
        # enforce_execution_factor_names so both paths go through one
        # code site that's testable directly.
        weights = enforce_execution_factor_names(
            weights, strict=strict_registry,
        )
        self._strict_registry = strict_registry
        self._weights     = weights
        self._monthly     = rebalance_monthly
        self._score_wt    = score_weighted
        self._vol_lb      = lookback_vol
        self._mom_lb      = lookback_mom
        self._qual_lb     = lookback_quality
        self._regime_scale = regime_scale or self._DEFAULT_REGIME_SCALE
        self._min_hold     = min_holding_days
        self._apply_extra_shift = apply_extra_shift
        self._concentration_warn = concentration_warn_threshold
        self._soft_cap_max_single = soft_cap_max_single

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

        if self._apply_extra_shift:
            # Legacy behaviour: signal at T uses T-1 factors. Combined with
            # BacktestEngine T+1 open execution → 2-bar lag (redundant;
            # T-close factor is knowable by T+1 open).
            composite = composite.shift(1)
        # else: signal at T uses T-close factors (still pre-execution since
        #       BacktestEngine executes at T+1 open → 1-bar lag, no lookahead).

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

        # Strategy-level soft cap (optional, before downstream constructor cap).
        if self._soft_cap_max_single is not None and self._soft_cap_max_single > 0:
            cap = self._soft_cap_max_single
            n_clipped = 0
            for date in signals.index:
                row = signals.loc[date]
                if (row > cap).any():
                    n_clipped += 1
                    signals.loc[date] = _cap_and_redistribute(row, cap)
            if n_clipped > 0:
                from core.logging_setup import get_logger
                get_logger("multi_factor").info(
                    "MultiFactor soft cap applied: %d rows had weights > %.2f",
                    n_clipped, cap,
                )

        # Concentration diagnostic (informational only, never modifies signals).
        if self._concentration_warn is not None and self._concentration_warn > 0:
            thr = self._concentration_warn
            max_per_row = signals.max(axis=1)
            n_violate = int((max_per_row > thr).sum())
            if n_violate > 0:
                from core.logging_setup import get_logger
                get_logger("multi_factor").warning(
                    "MultiFactor concentration: %d dates have max single weight > %.2f "
                    "(worst=%.2f). Consider soft_cap_max_single or lowering score_weighted.",
                    n_violate, thr, float(max_per_row.max()),
                )

        return signals
