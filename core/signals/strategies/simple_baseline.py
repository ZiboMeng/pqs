"""
SimpleBaselineStrategy: literature-grounded retail baseline with
VIX + 200SMA dual circuit-breaker on the leveraged sleeve.

Allocation (rebalanced monthly):
  - 70% MTUM  (iShares Edge MSCI USA Momentum Factor ETF, hold)
  - 30% TQQQ  IFF "risk-on" regime
              ELSE 30% in cash_symbol (default BIL).

Risk-on / Risk-off state machine (asymmetric hysteresis, prevents whipsaw):
  - Enter risk-off when:  VIX_close > 30  OR  QQQ_close < 200-day-SMA
  - Enter risk-on  when:  VIX_close < 20  AND QQQ_close > 200-day-SMA
  - Between 20-30 VIX with mixed SMA: maintain previous state (ffill)

Design provenance (train-only, ≤2024 data + theory papers):
  - MTUM hold: Antonacci (2012) "Risk Premia Harvesting Through Dual
    Momentum" + AQR style premia long-leg literature.
  - 200d SMA filter: Faber (2007) "A Quantitative Approach to Tactical
    Asset Allocation" (SSRN 962461) — caps SPY MaxDD around -14%.
  - VIX 30/20 thresholds: Whaley (2009) "Understanding the VIX" (J. Portfolio
    Management 35:98-105) — canonical 30 = elevated fear, 20 = normal regime.
  - Asymmetric hysteresis: Macrosynergy / Cipollini-Manzini convention; same-
    level re-entry (30→30) whipsaws around VIX mean-reversion clustering.
  - TQQQ-specific: VIX-fast trigger + SMA-slow confirmation is the standard
    pairing because 3x leveraged ETF daily-reset decay penalizes slow exits;
    documented across QuantifiedStrategies + retail-quant practitioner blogs.

Constraints:
  - long-only, no-margin, no-short (CLAUDE.md invariant)
  - TQQQ allowed under PQS "TQQQ/SOXL require stricter risk thresholds" —
    here capped at 30% of capital + DUAL filter (VIX + SMA).

NOT included intentionally (per sealed-window leak rollback 2026-05-13):
  - No XLE / sector tilt
  - No FOMC overlay (separate optional add-on)
  - No 60d return drawdown trigger (would require fitting; stick to literature
    canonical thresholds only).
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)


class SimpleBaselineStrategy:
    """
    70% MTUM + 30% TQQQ-or-cash, monthly rebalance, dual circuit-breaker.

    Risk-on/risk-off state machine determines whether the leveraged sleeve
    holds TQQQ or rotates to cash. State transitions:
      - Risk-on entry:   VIX < vix_reentry  AND  QQQ > 200d-SMA
      - Risk-off entry:  VIX > vix_exit     OR   QQQ < 200d-SMA

    Asymmetric hysteresis (default 30 exit / 20 re-entry) prevents whipsaw
    around VIX mean-reversion clustering.

    Parameters
    ----------
    mtum_symbol         : momentum-factor sleeve (default 'MTUM')
    leveraged_symbol    : leveraged equity sleeve (default 'TQQQ')
    cash_symbol         : held when filter rejects leveraged sleeve (default 'BIL')
    trend_signal_symbol : ticker for SMA filter computation (default 'QQQ')
    vix_symbol          : ticker for VIX series (default 'VIX'); set to None
                          to disable VIX filter (200SMA-only mode for testing)
    mtum_weight         : target weight for MTUM sleeve (default 0.70)
    leveraged_weight    : target weight for TQQQ/cash leg (default 0.30)
    sma_window          : SMA window in trading days (default 200; Faber 2007)
    vix_exit            : VIX close > vix_exit → enter risk-off (default 30; Whaley 2009)
    vix_reentry         : VIX close < vix_reentry → eligible for risk-on (default 20)
    rebalance_monthly   : if True, only rebalance on month-end (default True)
    """

    def __init__(
        self,
        mtum_symbol:         str   = "MTUM",
        leveraged_symbol:    str   = "TQQQ",
        cash_symbol:         str   = "BIL",
        trend_signal_symbol: str   = "QQQ",
        vix_symbol:          Optional[str] = "VIX",
        mtum_weight:         float = 0.70,
        leveraged_weight:    float = 0.30,
        mtum_risk_off_weight: float = 0.0,  # Faber GTAA default: full defense
        sma_window:          int   = 200,
        vix_exit:            float = 30.0,
        vix_reentry:         float = 20.0,
        rebalance_monthly:   bool  = True,
    ):
        if mtum_weight < 0 or leveraged_weight < 0:
            raise ValueError("weights must be non-negative")
        if mtum_risk_off_weight < 0 or mtum_risk_off_weight > mtum_weight:
            raise ValueError(
                f"mtum_risk_off_weight must be in [0, mtum_weight={mtum_weight}], "
                f"got {mtum_risk_off_weight}"
            )
        if abs((mtum_weight + leveraged_weight) - 1.0) > 1e-6:
            raise ValueError(
                f"mtum_weight + leveraged_weight must sum to 1.0, "
                f"got {mtum_weight + leveraged_weight}"
            )
        if sma_window < 2:
            raise ValueError("sma_window must be >= 2")
        if vix_symbol is not None:
            if vix_exit <= vix_reentry:
                raise ValueError(
                    f"vix_exit ({vix_exit}) must be > vix_reentry ({vix_reentry}) "
                    f"for asymmetric hysteresis"
                )

        self._mtum = mtum_symbol
        self._lev = leveraged_symbol
        self._cash = cash_symbol
        self._signal_sym = trend_signal_symbol
        self._vix_sym = vix_symbol
        self._w_mtum = mtum_weight
        self._w_lev = leveraged_weight
        self._w_mtum_risk_off = mtum_risk_off_weight
        self._sma_window = sma_window
        self._vix_exit = vix_exit
        self._vix_reentry = vix_reentry
        self._monthly = rebalance_monthly

    @property
    def required_symbols(self) -> List[str]:
        required = [self._mtum, self._lev, self._cash, self._signal_sym]
        if self._vix_sym is not None:
            required.append(self._vix_sym)
        return required

    def _risk_on_state(self, price_df: pd.DataFrame) -> pd.Series:
        """Compute risk-on (1) / risk-off (0) state per bar with hysteresis.

        Returns a Series indexed like price_df. State is forward-filled
        between explicit signals; ambiguous days (VIX in [20,30] with
        no SMA cross) inherit previous state.
        """
        signal_close = price_df[self._signal_sym]
        sma = signal_close.rolling(self._sma_window, min_periods=self._sma_window).mean()
        above_sma = signal_close > sma

        if self._vix_sym is None:
            # SMA-only mode: explicit state from SMA
            return above_sma.astype(float).fillna(0.0)

        vix = price_df[self._vix_sym]

        # Explicit transitions
        # risk_on entry:  VIX < reentry AND above SMA
        # risk_off entry: VIX > exit OR below SMA
        risk_on_signal = (vix < self._vix_reentry) & above_sma
        risk_off_signal = (vix > self._vix_exit) | (~above_sma)

        # Build state: 1 at risk_on signal, 0 at risk_off signal, NaN elsewhere
        state = pd.Series(np.nan, index=price_df.index)
        state[risk_on_signal] = 1.0
        state[risk_off_signal] = 0.0

        # Conflict resolution: if both fire (impossible here since
        # ~above_sma blocks risk_on, and below SMA forces risk_off),
        # risk_off wins because it's the safer state.
        state[risk_off_signal] = 0.0

        # Forward fill state; initial NaN (no prior signal) defaults to
        # risk-off (conservative — leveraged stays out until trigger).
        state = state.ffill().fillna(0.0)
        return state

    def _compute_raw_signals(self, price_df: pd.DataFrame) -> pd.DataFrame:
        """Per-bar target weights (no monthly mask, no shift).

        Faber GTAA pattern: filter applies at ASSET-CLASS level. When risk-off,
        BOTH MTUM and leveraged sleeves go to cash. mtum_risk_off_weight allows
        partial-defense override (Newfound-style "Protect & Participate") but
        defaults to 0 (full defense per Faber 1973-2012 backtest).
        """
        required = self.required_symbols
        missing = [s for s in required if s not in price_df.columns]
        if missing:
            raise ValueError(
                f"SimpleBaselineStrategy: missing required symbols {missing} "
                f"in price_df.columns. Required: {required}"
            )

        signals = pd.DataFrame(
            0.0, index=price_df.index, columns=price_df.columns
        )

        risk_on = self._risk_on_state(price_df)

        mtum_has_data = price_df[self._mtum].notna().astype(float)
        lev_has_data = price_df[self._lev].notna().astype(float)
        cash_has_data = price_df[self._cash].notna().astype(float)

        # MTUM: full weight in risk-on, mtum_risk_off_weight in risk-off
        mtum_w = (
            risk_on * self._w_mtum
            + (1.0 - risk_on) * self._w_mtum_risk_off
        )
        signals[self._mtum] = mtum_w * mtum_has_data

        # Leveraged sleeve: full weight in risk-on only; 0 in risk-off
        signals[self._lev] = self._w_lev * risk_on * lev_has_data

        # Cash leg: absorbs whatever isn't in MTUM or leveraged
        # In risk-on:  cash = 1 - w_mtum - w_lev = 0 (if weights sum to 1)
        # In risk-off: cash = 1 - w_mtum_risk_off - 0 = 1 - mtum_risk_off
        cash_w = 1.0 - mtum_w - signals[self._lev]
        signals[self._cash] = cash_w * cash_has_data

        return signals

    def generate(
        self,
        price_df:      pd.DataFrame,
        regime_series: Optional[pd.Series] = None,  # unused; interface parity
        volume_df:     Optional[pd.DataFrame] = None,  # unused; interface parity
    ) -> pd.DataFrame:
        """
        Produce per-bar target weight DataFrame.

        Returns
        -------
        weights : DataFrame indexed like price_df, columns = price_df.columns.
                  Most columns are 0; only mtum_symbol / leveraged_symbol /
                  cash_symbol carry non-zero weight.
        """
        raw = self._compute_raw_signals(price_df)

        if not self._monthly:
            return raw

        # Monthly rebalance: take the LAST signal of each month, propagate
        # forward until the next month-end. This matches MultiFactorStrategy's
        # convention.
        month_ends = raw.index.to_series().groupby(
            [raw.index.year, raw.index.month]
        ).max()
        monthly = raw.reindex(month_ends).fillna(0.0)
        # Reindex to the full daily index, forward-filling each month's
        # target weight until the next rebalance date.
        signals = monthly.reindex(raw.index, method="ffill").fillna(0.0)
        return signals
