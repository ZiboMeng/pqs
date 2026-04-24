"""
FeaturePipeline: multi-timeframe feature computation for PQS.

Design
------
- Primary timeframe:  1d (interday) or 60m (intraday primary)
- Auxiliary timeframes: 30m / 15m / 5m (confluence scoring)
- Graceful degradation: if aux data is unavailable, pipeline still returns
  primary features rather than failing.
- No look-ahead: daily anchor features use shift(1) before merging.

Usage
-----
    from core.features.feature_pipeline import FeaturePipeline

    pipe = FeaturePipeline()

    # Daily features only
    feat_df = pipe.compute_daily(ohlcv_df)

    # Intraday with aux timeframes
    result = pipe.compute_intraday(
        primary_df=df_60m,
        freq="60m",
        aux_frames={"30m": df_30m, "15m": df_15m},
        daily_df=df_1d,
    )
    # result.primary_features   → DataFrame (60m features incl. daily anchors)
    # result.confluence_score   → Series (0–1 per bar)
    # result.aux_available      → dict of which aux freqs were used
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np
import pandas as pd

from core.features.indicators import (
    compute_daily_features,
    compute_intraday_features,
)
from core.logging_setup import get_logger

logger = get_logger(__name__)


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class IntradayFeatureResult:
    """Output of FeaturePipeline.compute_intraday()."""
    primary_features:  pd.DataFrame
    confluence_score:  pd.Series                        # 0–1, aligned to primary
    aux_available:     Dict[str, bool] = field(default_factory=dict)
    aux_features:      Dict[str, pd.DataFrame] = field(default_factory=dict)

    @property
    def n_bars(self) -> int:
        return len(self.primary_features)

    def __repr__(self) -> str:
        aux_str = ", ".join(
            f"{k}={'yes' if v else 'no'}" for k, v in self.aux_available.items()
        )
        return (
            f"IntradayFeatureResult("
            f"bars={self.n_bars}, "
            f"aux=[{aux_str}], "
            f"mean_confluence={self.confluence_score.mean():.3f})"
        )


# ── Pipeline ──────────────────────────────────────────────────────────────────

class FeaturePipeline:
    """
    Computes technical features for a single symbol across timeframes.

    Parameters
    ----------
    graceful_degradation : bool
        If True (default), missing aux timeframes produce NaN columns rather
        than raising exceptions.  Set False for strict validation in tests.
    confluence_weights : dict
        Relative weights for each aux timeframe in confluence scoring.
        Keys: '30m', '15m', '5m'.
    """

    _DEFAULT_CONFLUENCE_WEIGHTS = {"30m": 0.50, "15m": 0.35, "5m": 0.15}

    def __init__(
        self,
        graceful_degradation: bool = True,
        confluence_weights:   Optional[Dict[str, float]] = None,
        timeframe_optimizer:  Optional["TimeframeOptimizer"] = None,
    ):
        self.graceful_degradation = graceful_degradation
        self._tf_optimizer = timeframe_optimizer
        if confluence_weights is not None:
            self.confluence_weights = confluence_weights
        elif timeframe_optimizer is not None:
            self.confluence_weights = timeframe_optimizer.get_weights()
        else:
            self.confluence_weights = self._DEFAULT_CONFLUENCE_WEIGHTS

    def update_weights_for_regime(self, regime: str) -> None:
        """Update confluence weights from TimeframeOptimizer for the current regime."""
        if self._tf_optimizer is not None:
            self.confluence_weights = self._tf_optimizer.get_weights(regime)

    # ── Public API ────────────────────────────────────────────────────────────

    def compute_daily(
        self,
        df:     pd.DataFrame,
        symbol: str = "",
    ) -> pd.DataFrame:
        """
        Compute full daily feature set for one symbol.

        Args:
            df:     OHLCV DataFrame with lowercase columns (open, high, low, close, volume).
            symbol: ticker label used in log messages only.

        Returns:
            Feature DataFrame aligned to df.index (no OHLCV columns).
        """
        if df is None or df.empty:
            logger.warning("[%s] compute_daily: empty DataFrame", symbol)
            return pd.DataFrame()

        try:
            return compute_daily_features(df)
        except Exception as exc:
            if self.graceful_degradation:
                logger.error("[%s] compute_daily failed: %s — returning empty", symbol, exc)
                return pd.DataFrame()
            raise

    def compute_intraday(
        self,
        primary_df:  pd.DataFrame,
        freq:        str = "60m",
        aux_frames:  Optional[Dict[str, pd.DataFrame]] = None,
        daily_df:    Optional[pd.DataFrame] = None,
        symbol:      str = "",
    ) -> IntradayFeatureResult:
        """
        Compute intraday features for primary + aux timeframes.

        Args:
            primary_df:  Intraday OHLCV DataFrame (e.g. 60m).
            freq:        Frequency string for primary_df ('60m', '30m', etc.).
            aux_frames:  Dict[freq_str → OHLCV DataFrame] for aux timeframes.
            daily_df:    Daily OHLCV DataFrame for cross-TF anchors (optional).
            symbol:      Ticker label for logging.

        Returns:
            IntradayFeatureResult with primary features, confluence scores,
            and per-aux availability flags.
        """
        aux_frames = aux_frames or {}

        # Primary features
        primary_feat = self._safe_intraday(primary_df, freq, daily_df, symbol, is_primary=True)

        # Aux features + confluence scoring
        aux_feat: Dict[str, pd.DataFrame] = {}
        aux_avail: Dict[str, bool] = {}

        for aux_freq, aux_df in aux_frames.items():
            feat = self._safe_intraday(aux_df, aux_freq, daily_df, symbol, is_primary=False)
            if feat is not None and not feat.empty:
                aux_feat[aux_freq] = feat
                aux_avail[aux_freq] = True
            else:
                aux_avail[aux_freq] = False

        confluence = self._compute_confluence(
            primary_df   = primary_df,
            primary_feat = primary_feat,
            aux_feat     = aux_feat,
        )

        return IntradayFeatureResult(
            primary_features = primary_feat,
            confluence_score = confluence,
            aux_available    = aux_avail,
            aux_features     = aux_feat,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _safe_intraday(
        self,
        df:         pd.DataFrame,
        freq:       str,
        daily_df:   Optional[pd.DataFrame],
        symbol:     str,
        is_primary: bool,
    ) -> pd.DataFrame:
        """Compute intraday features with error handling."""
        if df is None or df.empty:
            if not self.graceful_degradation and is_primary:
                raise ValueError(f"[{symbol}] Primary intraday DataFrame is empty")
            return pd.DataFrame()
        try:
            return compute_intraday_features(df, freq=freq, daily_df=daily_df)
        except Exception as exc:
            label = "primary" if is_primary else f"aux/{freq}"
            if self.graceful_degradation:
                logger.warning(
                    "[%s] compute_intraday %s failed: %s — skipping",
                    symbol, label, exc,
                )
                return pd.DataFrame()
            raise

    def _compute_confluence(
        self,
        primary_df:   pd.DataFrame,
        primary_feat: pd.DataFrame,
        aux_feat:     Dict[str, pd.DataFrame],
    ) -> pd.Series:
        """
        Compute a confluence score in [0, 1] aligned to primary_df.index.

        Methodology
        -----------
        For each available aux timeframe, we build a directional signal
        component and aggregate with weights.  The score captures whether
        lower-timeframe structure confirms the primary direction:

          component_i = sigmoid( rsi_deviation_i + trend_alignment_i )

        Where:
          - rsi_deviation:    (RSI - 50) / 50  → bullish lean if > 0
          - trend_alignment:  +1 if close > EMA21 else -1 → normalised

        The primary-timeframe signal is always included (weight = 1.0 -
        sum_aux_weights), so if no aux data is available, the score is
        based purely on the primary.

        The final score is mapped from [-1, 1] → [0, 1] for use as a
        size multiplier (score < 0.6 → no trade; 0.6–0.8 → half; > 0.8 → full).
        """
        if primary_df.empty or primary_feat.empty:
            return pd.Series(0.0, index=primary_df.index, name="confluence_score")

        idx = primary_df.index

        # Primary signal component
        primary_signal = self._directional_signal(primary_df, primary_feat)
        primary_signal = primary_signal.reindex(idx, method="ffill").fillna(0.0)

        # Aux signal components
        total_aux_weight = sum(
            self.confluence_weights.get(f, 0.0)
            for f in aux_feat
            if not aux_feat[f].empty
        )
        primary_weight = max(1.0 - total_aux_weight, 0.2)  # always ≥ 20%

        score = primary_signal * primary_weight

        for aux_freq, feat_df in aux_feat.items():
            if feat_df.empty:
                continue
            aux_df_ohlcv = None  # aux OHLCV not passed here; signal uses feat cols directly
            aux_signal   = self._directional_signal_from_feat(feat_df)
            aux_signal   = _align_aux_to_primary(aux_signal, idx)
            weight       = self.confluence_weights.get(aux_freq, 0.0)
            score        = score + aux_signal * weight

        # Normalise from raw signed signal to [0, 1]
        # raw score ∈ [-1, +1]; map: score = (raw + 1) / 2
        score = (score + 1.0) / 2.0
        score = score.clip(0.0, 1.0)
        score.name = "confluence_score"
        return score

    @staticmethod
    def _directional_signal(
        ohlcv_df: pd.DataFrame,
        feat_df:  pd.DataFrame,
    ) -> pd.Series:
        """
        Build a directional signal ∈ [-1, +1] from primary OHLCV + features.
        """
        signals = []

        # RSI component: (RSI - 50) / 50  ∈ [-1, +1]
        if "rsi14" in feat_df.columns:
            rsi_sig = (feat_df["rsi14"] - 50.0) / 50.0
            signals.append(rsi_sig)

        # Trend component: close > EMA21 → +1 else -1
        if "ema21" in feat_df.columns:
            trend = np.where(ohlcv_df["close"] > feat_df["ema21"], 1.0, -1.0)
            signals.append(pd.Series(trend, index=feat_df.index))
        elif "ema20" in feat_df.columns:
            trend = np.where(ohlcv_df["close"] > feat_df["ema20"], 1.0, -1.0)
            signals.append(pd.Series(trend, index=feat_df.index))

        # MACD component: sign of histogram ∈ {-1, +1}
        if "macd_hist" in feat_df.columns:
            macd_sig = np.sign(feat_df["macd_hist"].fillna(0.0))
            signals.append(macd_sig)

        if not signals:
            return pd.Series(0.0, index=feat_df.index)

        # Average of normalised components
        combined = pd.concat(signals, axis=1).mean(axis=1)
        return combined.clip(-1.0, 1.0)

    @staticmethod
    def _directional_signal_from_feat(feat_df: pd.DataFrame) -> pd.Series:
        """Directional signal when we only have the feature DataFrame (no raw OHLCV)."""
        signals = []

        if "rsi14" in feat_df.columns:
            signals.append((feat_df["rsi14"] - 50.0) / 50.0)

        if "macd_hist" in feat_df.columns:
            signals.append(np.sign(feat_df["macd_hist"].fillna(0.0)))

        # VWAP distance: positive dist = above VWAP → bullish
        if "vwap_dist" in feat_df.columns:
            vd = feat_df["vwap_dist"].clip(-0.05, 0.05) / 0.05  # normalise to [-1, +1]
            signals.append(vd)

        if not signals:
            return pd.Series(0.0, index=feat_df.index)

        return pd.concat(signals, axis=1).mean(axis=1).clip(-1.0, 1.0)


# ── Utility ───────────────────────────────────────────────────────────────────

def _align_aux_to_primary(
    aux_signal: pd.Series,
    primary_idx: pd.DatetimeIndex,
) -> pd.Series:
    """
    Align an aux-timeframe signal to the primary index.

    Strategy: reindex the aux signal to the primary timestamps, then
    forward-fill so each primary bar has the last known aux value.
    """
    combined = aux_signal.reindex(primary_idx.union(aux_signal.index)).sort_index()
    combined = combined.ffill()
    return combined.reindex(primary_idx).fillna(0.0)
