"""
DataValidator: data quality checks for OHLCV DataFrames.

Checks performed:
1. min_bars         — enough history to compute features
2. missing_days     — trading days with no data
3. outliers         — extreme single-day price moves (3-sigma on log returns)
4. volume_zeros     — excessive zero-volume bars
5. price_sanity     — negative prices, close outside [low, high]
6. corporate_action — large single-day gaps (possible split/dividend not adjusted)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

from core.data.calendar import get_missing_trading_days
from core.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class ValidationResult:
    symbol:  str
    freq:    str
    passed:  bool
    issues:  List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_issue(self, msg: str) -> None:
        self.issues.append(msg)
        self.passed = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [f"[{status}] {self.symbol}/{self.freq}"]
        for w in self.warnings:
            lines.append(f"  WARN: {w}")
        for e in self.issues:
            lines.append(f"  FAIL: {e}")
        return "\n".join(lines)


class DataValidator:
    """
    Validates OHLCV DataFrames for data quality issues.

    Thresholds are configurable; defaults are conservative for research use.
    """

    def __init__(
        self,
        min_bars:               int   = 252,     # minimum rows required
        max_missing_ratio:      float = 0.02,    # >2% missing trading days → issue
        outlier_sigma:          float = 5.0,     # |log-return| > N-sigma → outlier
        max_outlier_ratio:      float = 0.005,   # >0.5% outlier rows → issue
        max_zero_volume_ratio:  float = 0.05,    # >5% zero-volume bars → issue
        corp_action_threshold:  float = 0.15,    # >15% single-day gap → possible corp action
    ):
        self.min_bars              = min_bars
        self.max_missing_ratio     = max_missing_ratio
        self.outlier_sigma         = outlier_sigma
        self.max_outlier_ratio     = max_outlier_ratio
        self.max_zero_volume_ratio = max_zero_volume_ratio
        self.corp_action_threshold = corp_action_threshold

    def validate(
        self,
        df:     pd.DataFrame,
        symbol: str,
        freq:   str = "1d",
    ) -> ValidationResult:
        """
        Run all checks on an OHLCV DataFrame.

        Args:
            df:     OHLCV DataFrame (columns: open, high, low, close, volume)
            symbol: ticker symbol (for logging)
            freq:   '1d' or intraday ('60m', etc.)

        Returns:
            ValidationResult with passed=True only if all checks pass.
        """
        result = ValidationResult(symbol=symbol, freq=freq, passed=True)

        if df is None or df.empty:
            result.add_issue("DataFrame is empty or None")
            return result

        # 1. Minimum bars
        self._check_min_bars(df, result)

        # 2. Missing trading days (daily only — intraday too noisy)
        if freq == "1d" and len(df) >= 10:
            self._check_missing_days(df, result)

        # 3. Outlier returns
        if "close" in df.columns and len(df) >= 2:
            self._check_outliers(df, result)

        # 4. Zero-volume bars
        if "volume" in df.columns:
            self._check_zero_volume(df, result)

        # 5. Price sanity (close within [low, high], no negatives)
        self._check_price_sanity(df, result)

        # 6. Corporate action detection (daily only)
        if freq == "1d" and "close" in df.columns and len(df) >= 2:
            self._check_corporate_actions(df, result)

        return result

    def validate_multi(
        self,
        frames: dict,
        freq:   str = "1d",
    ) -> dict:
        """Validate multiple symbols. Returns dict[symbol → ValidationResult]."""
        return {sym: self.validate(df, symbol=sym, freq=freq) for sym, df in frames.items()}

    def log_results(self, results: dict) -> None:
        """Log validation results at appropriate log levels."""
        for result in results.values():
            if result.passed:
                if result.warnings:
                    for w in result.warnings:
                        logger.warning("[%s/%s] %s", result.symbol, result.freq, w)
            else:
                for issue in result.issues:
                    logger.error("[%s/%s] VALIDATION FAILED: %s", result.symbol, result.freq, issue)

    # ── Individual checks ─────────────────────────────────────────────────────

    def _check_min_bars(self, df: pd.DataFrame, result: ValidationResult) -> None:
        if len(df) < self.min_bars:
            result.add_warning(
                f"Only {len(df)} bars; expected >= {self.min_bars}. "
                "Features may be unreliable."
            )

    def _check_missing_days(self, df: pd.DataFrame, result: ValidationResult) -> None:
        try:
            start = df.index[0]
            end   = df.index[-1]
            missing = get_missing_trading_days(df.index, start, end)
            ratio = len(missing) / max(len(df), 1)
            if ratio > self.max_missing_ratio:
                result.add_issue(
                    f"{len(missing)} missing trading days ({ratio:.1%} of total). "
                    f"First few: {list(missing[:3])}"
                )
            elif missing.any():
                result.add_warning(f"{len(missing)} missing trading days (within tolerance)")
        except Exception as exc:
            result.add_warning(f"Missing-day check skipped: {exc}")

    def _check_outliers(self, df: pd.DataFrame, result: ValidationResult) -> None:
        log_ret = np.log(df["close"] / df["close"].shift(1)).dropna()
        if log_ret.empty:
            return
        mu, sigma = log_ret.mean(), log_ret.std()
        if sigma == 0:
            return
        z_scores = (log_ret - mu).abs() / sigma
        outlier_mask = z_scores > self.outlier_sigma
        ratio = outlier_mask.mean()
        if ratio > self.max_outlier_ratio:
            worst = log_ret[outlier_mask].abs().nlargest(3)
            result.add_warning(
                f"{outlier_mask.sum()} outlier bars ({ratio:.2%}). "
                f"Largest moves: {worst.round(4).to_dict()}"
            )

    def _check_zero_volume(self, df: pd.DataFrame, result: ValidationResult) -> None:
        zero_vol = (df["volume"] == 0).mean()
        if zero_vol > self.max_zero_volume_ratio:
            result.add_warning(
                f"{zero_vol:.1%} of bars have zero volume (threshold: {self.max_zero_volume_ratio:.1%})"
            )

    def _check_price_sanity(self, df: pd.DataFrame, result: ValidationResult) -> None:
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                neg = (df[col] < 0).sum()
                if neg > 0:
                    result.add_issue(f"{neg} negative values in column '{col}'")

        if {"high", "low", "close"}.issubset(df.columns):
            violations = (
                (df["close"] > df["high"] * 1.001) |
                (df["close"] < df["low"] * 0.999)
            ).sum()
            if violations > 0:
                result.add_warning(
                    f"{violations} bars where close is outside [low, high] (possible data error)"
                )

    def _check_corporate_actions(self, df: pd.DataFrame, result: ValidationResult) -> None:
        """Flag large price gaps that may indicate unadjusted splits or dividends."""
        gaps = df["close"].pct_change().abs()
        large_gaps = gaps[gaps > self.corp_action_threshold]
        if not large_gaps.empty:
            result.add_warning(
                f"{len(large_gaps)} single-day price moves > {self.corp_action_threshold:.0%}. "
                f"Possible unadjusted corporate action on: {list(large_gaps.index[:3])}"
            )
