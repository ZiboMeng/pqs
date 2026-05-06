"""PRD-E v1.1 §4.4 TAA backtest harness.

Wraps ``core.backtest.backtest_engine.BacktestEngine`` with regime-driven
target_wts construction. The harness:

  1. Builds monthly-cadence regime labels (caller supplies daily labels
     + cadence; harness resamples).
  2. Constructs target_wts_panel via ``asset_class_builder``.
  3. Forward-fills target_wts to daily index (so non-rebalance days
     hold prior weights; engine's rebalance_threshold gate fires only
     when label changes).
  4. Runs BacktestEngine T+1 open execution.
  5. Computes per-regime NAV slice + per-year metrics + vs-SPY
     comparison (Calmar / Sharpe / MaxDD).

Result schema is ``TaaBacktestResult`` (similar to harness
``EvaluatedComposite`` but TAA-specific fields).

PRD references:
  * §4.4 monthly cadence design (I16); daily variant via cadence='D'
  * §4.6 OOS discipline: panel + regime labels are caller's
    responsibility (caller filters via partition_for_role)
  * §5.2 Phase 2 deliverables: per-regime NAV slice, vs-SPY Calmar/
    Sharpe, V1 vs V0_MINIMAL Occam comparison (caller drives by
    instantiating two harness runs)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestEngine, BacktestResult
from core.regime.regime_detector import RegimeState
from core.research.taa.asset_class_builder import build_target_wts_panel
from core.research.taa.regime_label_generator import monthly_regime_labels
from core.research.taa.regime_rules import RegimeAllocation


@dataclass
class TaaBacktestResult:
    """Result of a TAA backtest run.

    Mirrors ``core.research.harness.composite_evaluator.EvaluatedComposite``
    schema where it overlaps; adds TAA-specific fields (per-regime
    NAV slice, vs-SPY comparison, rule-set + cadence echoes).
    """
    nav: pd.Series
    weights: pd.DataFrame
    daily_returns: pd.Series
    metrics_full_period: Dict[str, float] = field(default_factory=dict)
    metrics_per_validation_year: Dict[int, Dict[str, float]] = field(default_factory=dict)
    metrics_per_stress_slice: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # TAA-specific: NAV slice per RegimeState (string value → metrics dict)
    metrics_per_regime: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # TAA-specific: vs buy-hold SPY comparison (cum_ret / cagr / sharpe /
    # max_dd / calmar) for both spec and SPY, side-by-side
    vs_spy_comparison: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # Echoes
    rule_set_name: str = ""
    cadence: str = ""
    rebalance_dates: Optional[pd.DatetimeIndex] = None
    n_observed_days: int = 0


def _annualized_sharpe(daily_returns: pd.Series, periods_per_year: int = 252) -> float:
    if len(daily_returns) < 2:
        return 0.0
    sd = float(daily_returns.std())
    if not np.isfinite(sd) or sd < 1e-12:
        return 0.0
    return float(daily_returns.mean() / sd * np.sqrt(periods_per_year))


def _max_drawdown(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    peak = nav.cummax()
    dd = (nav - peak) / peak
    return float(dd.min())


def _cagr(nav: pd.Series) -> float:
    if len(nav) < 2 or nav.iloc[0] <= 0:
        return 0.0
    n_years = (nav.index[-1] - nav.index[0]).days / 365.25
    if n_years < 1e-9:
        return 0.0
    total_return = float(nav.iloc[-1] / nav.iloc[0])
    if total_return <= 0:
        return -1.0
    return float(total_return ** (1 / n_years) - 1)


def _calmar(nav: pd.Series) -> float:
    """Calmar ratio = CAGR / |MaxDD|. PRD-E §5.2 Phase 2 primary
    risk-adjusted metric (per I15)."""
    cagr = _cagr(nav)
    mdd = abs(_max_drawdown(nav))
    if mdd < 1e-9:
        return float("inf") if cagr > 0 else 0.0
    return cagr / mdd


def _full_period_metrics(nav: pd.Series, daily_ret: pd.Series) -> Dict[str, float]:
    if len(nav) < 2:
        return {}
    return {
        "cum_ret": float(nav.iloc[-1] / nav.iloc[0] - 1),
        "cagr": _cagr(nav),
        "sharpe": _annualized_sharpe(daily_ret),
        "max_dd": _max_drawdown(nav),
        "calmar": _calmar(nav),
    }


def run_taa_backtest(
    panel: Mapping[str, pd.DataFrame],
    daily_regime_labels: pd.Series,
    rule_set: Mapping[RegimeState, RegimeAllocation],
    universe: Sequence[str],
    *,
    cadence: str = "MS",
    cost_model: Any = None,
    initial_capital: float = 10_000.0,
    rebalance_threshold: float = 0.02,
    integer_shares: bool = False,
    spy_series: Optional[pd.Series] = None,
    rule_set_name: str = "v1",
    validation_years: Optional[Sequence[int]] = None,
    stress_slices: Optional[Mapping[str, tuple]] = None,
    asset_class_lookup=None,
) -> TaaBacktestResult:
    """Run the regime-driven TAA backtest end-to-end.

    Sequence:
      1. Resample daily regime labels to ``cadence`` (default monthly
         start). Each cadence boundary = a rebalance date.
      2. Build target_wts at each rebalance date via the rule_set →
         asset_class_builder (equal-weight within asset class).
      3. Forward-fill target_wts to all trading days (engine sees
         non-rebalance days as "no change" and skips orders unless the
         rebalance_threshold trips for drift).
      4. Run BacktestEngine T+1 open execution + cost_model.
      5. Compute per-regime / per-year / per-stress NAV slice metrics +
         vs-SPY Calmar/Sharpe/MaxDD comparison.

    Parameters
    ----------
    panel : Mapping[str, pd.DataFrame]
        Standard {"close", "open", "high", "low", "volume"} dict; the
        harness consumes close + open. Caller is responsible for
        filtering this panel via ``partition_for_role`` per PRD §4.6
        OOS discipline (mining role for Phase 2 train-only;
        selector role for Phase 3 acceptance).
    daily_regime_labels : pd.Series
        Daily regime labels (output of ``daily_regime_labels``); index
        = trading days, dtype=str, values = RegimeState string values.
    rule_set : Mapping[RegimeState, RegimeAllocation]
        DEFAULT_TAA_RULES_V1 / V0_MINIMAL / custom; validated at the
        builder layer.
    universe : Sequence[str]
        Tradable symbols (MUST include all symbols required by the
        rule_set's non-zero asset classes).
    cadence : str
        Pandas resample freq for rebalance dates. "MS" (default) =
        month-start; "D" = daily; "W-MON" = weekly.
    cost_model : optional
        BacktestEngine cost_model. None → loads default from
        config/cost_model.yaml at engine layer.
    initial_capital : float
        Starting NAV (default $10K matching CLAUDE.md initial capital
        guidance).
    rebalance_threshold : float
        BacktestEngine drift threshold for forcing rebalance between
        target_wts changes. Default 0.02 (2%).
    integer_shares : bool
        BacktestEngine integer-shares mode (default False).
    spy_series : Optional[pd.Series]
        SPY benchmark for vs-SPY comparison (CAGR / Sharpe / MaxDD /
        Calmar).
    rule_set_name : str
        For result echo + closeout memo audit trail.
    validation_years : Optional[Sequence[int]]
        Years for per-year metrics breakdown; same convention as
        composite_evaluator.evaluate_composite_spec.
    stress_slices : Optional[Mapping[str, tuple]]
        Named (start, end) date ranges for per-stress-slice metrics.
    asset_class_lookup : callable, optional
        Symbol → asset class mapper (passed through to
        ``build_target_wts_panel``).

    Returns
    -------
    TaaBacktestResult
    """
    if cost_model is None:
        from core.config.loader import load_config
        from core.execution.cost_model import CostModel
        cfg = load_config()
        cost_model = CostModel(cfg.cost_model)

    # 1) Resample daily labels → rebalance cadence
    rebalance_labels = monthly_regime_labels(
        daily_regime_labels, cadence=cadence,
    )
    if rebalance_labels.empty:
        raise ValueError(
            f"daily_regime_labels resampled at cadence={cadence!r} produced "
            f"empty index; check input series"
        )

    # 2) Build target_wts at rebalance dates
    target_wts_at_rebalance = build_target_wts_panel(
        rebalance_labels, rule_set, universe,
        asset_class_lookup=asset_class_lookup,
    )

    # 3) Forward-fill to all trading days (engine consumes daily-aligned
    # signals_df; non-rebalance days carry forward prior weights)
    daily_index = panel["close"].index
    target_wts_daily = target_wts_at_rebalance.reindex(daily_index, method="ffill")
    # Drop any leading NaN rows (pre-first-rebalance) — engine handles
    # NaN signals as "no position" but cleaner to start at first
    # rebalance day.
    first_valid = target_wts_daily.dropna(how="all").index[0]
    target_wts_daily = target_wts_daily.loc[first_valid:].fillna(0.0)

    # 4) Run BacktestEngine
    engine = BacktestEngine(
        cost_model=cost_model,
        initial_capital=initial_capital,
        rebalance_threshold=rebalance_threshold,
        integer_shares=integer_shares,
    )
    common_syms = [s for s in target_wts_daily.columns if s in panel["close"].columns]
    if not common_syms:
        raise ValueError(
            "no overlap between target_wts columns and panel close columns"
        )
    sig = target_wts_daily[common_syms]
    px = panel["close"][common_syms].reindex(sig.index)
    op = (
        panel["open"][common_syms].reindex(sig.index)
        if panel.get("open") is not None else None
    )
    bt: BacktestResult = engine.run(
        signals_df=sig, price_df=px, open_df=op,
        benchmark_series=spy_series,
    )

    nav = bt.equity_curve.copy()
    nav.name = "nav"
    daily_ret = nav.pct_change().fillna(0.0)
    daily_ret.name = "daily_ret"

    # 5) Metrics: full-period + per-year + per-stress + per-regime
    full = _full_period_metrics(nav, daily_ret)

    per_year: Dict[int, Dict[str, float]] = {}
    if validation_years:
        for y in validation_years:
            year_mask = (nav.index.year == y)
            slc_nav = nav.loc[year_mask]
            if len(slc_nav) < 2:
                continue
            slc_ret = slc_nav.pct_change().fillna(0.0)
            year_metrics = _full_period_metrics(slc_nav, slc_ret)
            if spy_series is not None:
                # ffill bridges intra-year gaps but doesn't back-fill into
                # prior years (so 2019-01-01 holiday → NaN); ALSO doesn't
                # forward-fill past series end (2023-12-30 weekend after
                # 2023-12-29 last trade → NaN). Drop NaN BEFORE computing
                # iloc[0]/iloc[-1] so per-year vs_spy is robust to year-
                # boundary holidays/weekends in the TAA nav index.
                spy_in_year = (
                    spy_series.reindex(slc_nav.index, method="ffill").dropna()
                )
                if len(spy_in_year) >= 2:
                    spy_cum = float(spy_in_year.iloc[-1] / spy_in_year.iloc[0] - 1)
                    year_metrics["vs_spy"] = year_metrics["cum_ret"] - spy_cum
            per_year[int(y)] = year_metrics

    per_slice: Dict[str, Dict[str, float]] = {}
    if stress_slices:
        for sname, (s_start, s_end) in stress_slices.items():
            sw = pd.Timestamp(s_start)
            ew = pd.Timestamp(s_end)
            mask = (nav.index >= sw) & (nav.index <= ew)
            slc_nav = nav.loc[mask]
            if len(slc_nav) < 2:
                continue
            slc_ret = slc_nav.pct_change().fillna(0.0)
            per_slice[sname] = _full_period_metrics(slc_nav, slc_ret)

    # Per-regime NAV slice: filter daily returns by regime label
    per_regime: Dict[str, Dict[str, float]] = {}
    daily_labels_aligned = daily_regime_labels.reindex(nav.index, method="ffill")
    for state in RegimeState:
        mask = (daily_labels_aligned == state.value)
        if mask.sum() < 5:
            continue
        # Sub-NAV: cumulative product of in-regime returns only
        in_regime_returns = daily_ret.loc[mask]
        sub_nav = (1.0 + in_regime_returns).cumprod()
        per_regime[state.value] = {
            "n_days": int(mask.sum()),
            "cum_ret": float(sub_nav.iloc[-1] - 1),
            "sharpe": _annualized_sharpe(in_regime_returns),
            "max_dd": _max_drawdown(sub_nav),
        }

    # vs-SPY comparison (full period)
    vs_spy: Dict[str, Dict[str, float]] = {}
    if spy_series is not None:
        spy_aligned = spy_series.reindex(nav.index, method="ffill").dropna()
        if len(spy_aligned) >= 2:
            spy_ret = spy_aligned.pct_change().fillna(0.0)
            spy_metrics = _full_period_metrics(spy_aligned, spy_ret)
            vs_spy = {
                "taa": full,
                "spy_buy_hold": spy_metrics,
                "delta_calmar": full.get("calmar", 0) - spy_metrics.get("calmar", 0),
                "delta_max_dd": full.get("max_dd", 0) - spy_metrics.get("max_dd", 0),
                "delta_sharpe": full.get("sharpe", 0) - spy_metrics.get("sharpe", 0),
            }

    return TaaBacktestResult(
        nav=nav,
        weights=bt.weights,
        daily_returns=daily_ret,
        metrics_full_period=full,
        metrics_per_validation_year=per_year,
        metrics_per_stress_slice=per_slice,
        metrics_per_regime=per_regime,
        vs_spy_comparison=vs_spy,
        rule_set_name=rule_set_name,
        cadence=cadence,
        rebalance_dates=rebalance_labels.index,
        n_observed_days=int(len(nav)),
    )
