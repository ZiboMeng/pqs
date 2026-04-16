"""
Research-side diagnostics: factor decay, cost drift, strategy alpha, paper-backtest divergence.

Each detector returns a DiagnosticResult with triggered/value/threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class DiagnosticResult:
    detector:    str
    triggered:   bool
    value:       float
    threshold:   float
    description: str
    severity:    str = "warn"

    def __str__(self) -> str:
        tag = "TRIGGERED" if self.triggered else "OK"
        return f"[{tag}] {self.detector}: {self.description}"


class FactorDecayDetector:
    """
    Detect factor IC decay: rolling 60d IC vs long-term IC drops > threshold.

    Parameters
    ----------
    rolling_window : bars for rolling IC
    decay_threshold : fraction drop that triggers (e.g. 0.50 = 50% decline)
    """

    def __init__(self, rolling_window: int = 60, decay_threshold: float = 0.50):
        self._window = rolling_window
        self._threshold = decay_threshold

    def check(
        self,
        ic_series: pd.Series,
    ) -> DiagnosticResult:
        if len(ic_series) < self._window * 2:
            return DiagnosticResult(
                detector="factor_decay", triggered=False,
                value=0.0, threshold=self._threshold,
                description="Insufficient IC history",
            )

        long_term_ic = float(ic_series.mean())
        recent_ic = float(ic_series.tail(self._window).mean())

        if abs(long_term_ic) < 1e-6:
            decay = 0.0
        else:
            decay = 1.0 - (recent_ic / long_term_ic)

        triggered = decay > self._threshold
        return DiagnosticResult(
            detector="factor_decay",
            triggered=triggered,
            value=decay,
            threshold=self._threshold,
            description=f"IC decay {decay:.1%} (long={long_term_ic:.4f}, recent={recent_ic:.4f})",
            severity="warn",
        )


class CostDriftDetector:
    """
    Detect when actual execution costs diverge from model assumptions.

    Parameters
    ----------
    drift_threshold : multiplier (e.g. 2.0 = actual costs > 2x model)
    """

    def __init__(self, drift_threshold: float = 2.0):
        self._threshold = drift_threshold

    def check(
        self,
        model_costs_bps: pd.Series,
        actual_costs_bps: pd.Series,
    ) -> DiagnosticResult:
        common = model_costs_bps.index.intersection(actual_costs_bps.index)
        if len(common) < 10:
            return DiagnosticResult(
                detector="cost_drift", triggered=False,
                value=0.0, threshold=self._threshold,
                description="Insufficient cost data for comparison",
            )

        model = model_costs_bps.loc[common].replace(0, np.nan).dropna()
        actual = actual_costs_bps.loc[common].reindex(model.index)
        ratio = (actual / model).dropna()

        if ratio.empty:
            return DiagnosticResult(
                detector="cost_drift", triggered=False,
                value=0.0, threshold=self._threshold,
                description="No valid cost comparisons",
            )

        mean_ratio = float(ratio.mean())
        triggered = mean_ratio > self._threshold
        return DiagnosticResult(
            detector="cost_drift",
            triggered=triggered,
            value=mean_ratio,
            threshold=self._threshold,
            description=f"Cost ratio actual/model = {mean_ratio:.2f}x (threshold {self._threshold:.1f}x)",
            severity="warn" if mean_ratio < self._threshold * 1.5 else "critical",
        )


class StrategyAlphaDetector:
    """
    Detect strategy alpha decay: rolling 60d alpha vs SPY turns negative.

    Parameters
    ----------
    rolling_window : trading days for rolling alpha
    alpha_threshold : minimum cumulative alpha (e.g. -0.05 = -5%)
    """

    def __init__(self, rolling_window: int = 60, alpha_threshold: float = -0.05):
        self._window = rolling_window
        self._threshold = alpha_threshold

    def check(
        self,
        strategy_equity: pd.Series,
        benchmark_equity: pd.Series,
    ) -> DiagnosticResult:
        common = strategy_equity.index.intersection(benchmark_equity.index)
        if len(common) < self._window:
            return DiagnosticResult(
                detector="strategy_alpha", triggered=False,
                value=0.0, threshold=self._threshold,
                description="Insufficient data",
            )

        s_ret = strategy_equity.loc[common].pct_change().dropna()
        b_ret = benchmark_equity.loc[common].pct_change().dropna()
        common2 = s_ret.index.intersection(b_ret.index)

        recent_s = s_ret.loc[common2].tail(self._window)
        recent_b = b_ret.loc[common2].tail(self._window)
        cum_alpha = float((1 + recent_s).prod() - (1 + recent_b).prod())

        triggered = cum_alpha < self._threshold
        return DiagnosticResult(
            detector="strategy_alpha",
            triggered=triggered,
            value=cum_alpha,
            threshold=self._threshold,
            description=f"Rolling {self._window}d alpha vs SPY = {cum_alpha:.2%}",
            severity="warn",
        )


class PaperBacktestDivergenceDetector:
    """
    Detect divergence between paper trading and backtest simulation.

    Parameters
    ----------
    rolling_window : days to check
    divergence_threshold_bps : mean daily divergence in bps
    """

    def __init__(self, rolling_window: int = 20, divergence_threshold_bps: float = 150.0):
        self._window = rolling_window
        self._threshold = divergence_threshold_bps

    def check(
        self,
        backtest_equity: pd.Series,
        paper_equity: pd.Series,
    ) -> DiagnosticResult:
        common = backtest_equity.index.intersection(paper_equity.index)
        if len(common) < self._window:
            return DiagnosticResult(
                detector="paper_bt_divergence", triggered=False,
                value=0.0, threshold=self._threshold,
                description="Insufficient overlapping data",
            )

        bt_ret = backtest_equity.loc[common].pct_change().dropna()
        pp_ret = paper_equity.loc[common].pct_change().dropna()
        common2 = bt_ret.index.intersection(pp_ret.index)
        recent_bt = bt_ret.loc[common2].tail(self._window)
        recent_pp = pp_ret.loc[common2].tail(self._window)

        diff_bps = (recent_bt - recent_pp).abs() * 10000
        mean_div = float(diff_bps.mean())

        triggered = mean_div > self._threshold
        return DiagnosticResult(
            detector="paper_bt_divergence",
            triggered=triggered,
            value=mean_div,
            threshold=self._threshold,
            description=f"Mean {self._window}d divergence = {mean_div:.1f} bps",
            severity="warn" if mean_div < self._threshold * 2 else "critical",
        )


class DiagnosticSuite:
    """Run all diagnostics and aggregate results."""

    def __init__(self) -> None:
        self.factor_decay = FactorDecayDetector()
        self.cost_drift = CostDriftDetector()
        self.strategy_alpha = StrategyAlphaDetector()
        self.paper_bt_div = PaperBacktestDivergenceDetector()

    def run_all(
        self,
        strategy_equity:  Optional[pd.Series] = None,
        benchmark_equity: Optional[pd.Series] = None,
        paper_equity:     Optional[pd.Series] = None,
        ic_series:        Optional[pd.Series] = None,
        model_costs_bps:  Optional[pd.Series] = None,
        actual_costs_bps: Optional[pd.Series] = None,
    ) -> List[DiagnosticResult]:
        results: List[DiagnosticResult] = []

        if ic_series is not None:
            results.append(self.factor_decay.check(ic_series))

        if model_costs_bps is not None and actual_costs_bps is not None:
            results.append(self.cost_drift.check(model_costs_bps, actual_costs_bps))

        if strategy_equity is not None and benchmark_equity is not None:
            results.append(self.strategy_alpha.check(strategy_equity, benchmark_equity))

        if strategy_equity is not None and paper_equity is not None:
            results.append(self.paper_bt_div.check(strategy_equity, paper_equity))

        for r in results:
            if r.triggered:
                logger.warning("Diagnostic %s", r)
            else:
                logger.debug("Diagnostic %s", r)

        return results

    def any_triggered(self, results: List[DiagnosticResult]) -> bool:
        return any(r.triggered for r in results)

    def critical_triggered(self, results: List[DiagnosticResult]) -> bool:
        return any(r.triggered and r.severity == "critical" for r in results)
