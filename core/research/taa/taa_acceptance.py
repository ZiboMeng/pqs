"""PRD-E v1.1 §5.3 TAA validation acceptance evaluator.

Takes a ``TaaBacktestResult`` (from a selector-role run) + reference
SPY metrics and produces a pass/fail verdict against PRD-E §5.2
Phase 3 hard gates (revised per critique I10 + I15 + I17):

  G1. 2018 vs SPY positive (HARD; single BEAR validation year)
  G2. 2025 vs SPY positive (HARD per CLAUDE.md core role gate)
  G3. covid_flash + rate_hike_2022 stress slice MaxDD ≤ 25% (HARD)
  G4. Per-validation-year MaxDD ≤ 20% (HARD; CLAUDE.md core role)
  G5. Beta to SPY in BULL ≤ 0.85 (HARD; should NOT mimic SPY)
  G6. Calmar ≥ SPY Calmar (HARD primary risk-adjusted; I15)
  G7. MaxDD < SPY MaxDD across full period (HARD)

Eligibility (not freeze): all G1-G7 PASS → candidate ELIGIBLE for
forward observation freeze (PRD-E2 separate scope, gated on user
explicit-go).

PRD references:
  * §5.2 Phase 3 hard gate replacement (I10 + I17 fix)
  * §5.3 risk-adjusted gates (I15 fix)
  * §10 reversibility: fail → close PRD-E with rejection memo
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.regime.regime_detector import RegimeState
from core.research.taa.taa_harness import TaaBacktestResult


@dataclass
class TaaGateResult:
    name: str
    passed: bool
    values: Dict[str, Any] = field(default_factory=dict)
    threshold: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass
class TaaAcceptanceResult:
    """Aggregate outcome over PRD-E §5.3 hard gates."""
    overall_passed: bool
    gates: List[TaaGateResult] = field(default_factory=list)
    rule_set_name: str = ""
    cadence: str = ""
    notes: str = ""

    @property
    def n_passed(self) -> int:
        return sum(1 for g in self.gates if g.passed)

    @property
    def n_total(self) -> int:
        return len(self.gates)

    @property
    def failed_gates(self) -> List[str]:
        return [g.name for g in self.gates if not g.passed]


def _safe_get(d: Dict, *path, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
        if cur is None:
            return default
    return cur


def _compute_beta_in_regime(
    daily_returns: pd.Series,
    spy_returns: pd.Series,
    regime_labels: pd.Series,
    regime: RegimeState,
) -> float:
    """OLS beta of taa daily returns vs SPY daily returns, restricted
    to days where the regime label matches ``regime``."""
    common = daily_returns.index.intersection(spy_returns.index).intersection(regime_labels.index)
    if len(common) < 30:
        return float("nan")
    df = pd.DataFrame({
        "y": daily_returns.loc[common],
        "x": spy_returns.loc[common],
        "regime": regime_labels.loc[common],
    }).dropna()
    in_regime = df[df["regime"] == regime.value]
    if len(in_regime) < 30:
        return float("nan")
    var = in_regime["x"].var()
    if not np.isfinite(var) or var < 1e-12:
        return float("nan")
    cov = in_regime[["y", "x"]].cov().loc["y", "x"]
    return float(cov / var)


def evaluate_taa_acceptance(
    result: TaaBacktestResult,
    *,
    spy_metrics_full_period: Dict[str, float],
    spy_daily_returns: Optional[pd.Series] = None,
    daily_regime_labels: Optional[pd.Series] = None,
    maxdd_per_year_max: float = -0.20,
    stress_slice_maxdd_max: float = -0.25,
    bull_beta_to_spy_max: float = 0.85,
) -> TaaAcceptanceResult:
    """Evaluate a TAA backtest result against PRD-E §5.3 hard gates.

    Parameters
    ----------
    result : TaaBacktestResult
        Output of ``run_taa_backtest`` on partition_for_role(role="selector")
        panel (train + validation; sealed excluded).
    spy_metrics_full_period : Dict[str, float]
        Buy-and-hold SPY's full-period metrics (cum_ret / cagr / sharpe /
        max_dd / calmar) over the same window as result.nav.
    spy_daily_returns : Optional[pd.Series]
        SPY daily returns, used for beta computation (G5). If None,
        G5 is skipped (recorded as PASS with note).
    daily_regime_labels : Optional[pd.Series]
        Daily regime label series; used for beta-in-BULL computation
        (G5). If None, G5 is skipped.
    maxdd_per_year_max : float (negative)
        Per-validation-year MaxDD ceiling (CLAUDE.md core role default
        -0.20).
    stress_slice_maxdd_max : float (negative)
        Stress slice MaxDD ceiling (CLAUDE.md 2008-style -0.25).
    bull_beta_to_spy_max : float
        Beta to SPY ceiling in BULL regime (PRD-E §5.3 0.85).

    Returns
    -------
    TaaAcceptanceResult
    """
    gates: List[TaaGateResult] = []

    # G1. 2018 vs SPY positive (HARD; single BEAR validation year)
    vs_2018 = _safe_get(result.metrics_per_validation_year, 2018, "vs_spy")
    g1_pass = (vs_2018 is not None) and (vs_2018 > 0)
    gates.append(TaaGateResult(
        name="g1_2018_vs_spy_positive",
        passed=bool(g1_pass),
        values={"validation_2018_vs_spy": vs_2018},
        threshold={"min": 0.0},
        notes=(
            "Single BEAR validation year (2018 rate_hike_bear); "
            "TAA's primary value should manifest here. Per PRD I17 fix."
        ),
    ))

    # G2. 2025 vs SPY positive (HARD per CLAUDE.md core role)
    vs_2025 = _safe_get(result.metrics_per_validation_year, 2025, "vs_spy")
    g2_pass = (vs_2025 is not None) and (vs_2025 > 0)
    gates.append(TaaGateResult(
        name="g2_2025_vs_spy_positive",
        passed=bool(g2_pass),
        values={"validation_2025_vs_spy": vs_2025},
        threshold={"min": 0.0},
        notes="CLAUDE.md core role hard gate (2025 holdout).",
    ))

    # G3. Stress slice MaxDD ≤ 25%
    stress_results = []
    g3_pass = True
    for sname, sm in (result.metrics_per_stress_slice or {}).items():
        sm_dd = sm.get("max_dd")
        if sm_dd is None:
            continue
        passed_this = sm_dd >= stress_slice_maxdd_max  # both negative; >= is "less deep"
        stress_results.append({
            "name": sname, "max_dd": sm_dd, "passed": passed_this,
        })
        if not passed_this:
            g3_pass = False
    gates.append(TaaGateResult(
        name="g3_stress_slice_maxdd",
        passed=bool(g3_pass and len(stress_results) > 0),
        values={"slices": stress_results},
        threshold={"max_dd_floor": stress_slice_maxdd_max},
        notes="CLAUDE.md 2008-style scenario MaxDD ≤ 25% (HARD).",
    ))

    # G4. Per-validation-year MaxDD ≤ 20%
    year_results = []
    g4_pass = True
    for y, m in (result.metrics_per_validation_year or {}).items():
        ym_dd = m.get("max_dd")
        if ym_dd is None:
            continue
        passed_this = ym_dd >= maxdd_per_year_max
        year_results.append({
            "year": int(y), "max_dd": ym_dd, "passed": passed_this,
        })
        if not passed_this:
            g4_pass = False
    gates.append(TaaGateResult(
        name="g4_per_year_maxdd",
        passed=bool(g4_pass and len(year_results) > 0),
        values={"years": year_results},
        threshold={"max_dd_floor": maxdd_per_year_max},
        notes="CLAUDE.md core role per-validation-year gate.",
    ))

    # G5. Beta to SPY in BULL ≤ 0.85 (skipped if no spy_returns / labels)
    if spy_daily_returns is not None and daily_regime_labels is not None:
        beta_bull = _compute_beta_in_regime(
            result.daily_returns, spy_daily_returns,
            daily_regime_labels, RegimeState.BULL,
        )
        g5_pass = (
            np.isfinite(beta_bull) and beta_bull <= bull_beta_to_spy_max
        ) if np.isfinite(beta_bull) else False
        gates.append(TaaGateResult(
            name="g5_bull_beta_to_spy",
            passed=bool(g5_pass),
            values={"beta_in_bull": float(beta_bull) if np.isfinite(beta_bull) else None},
            threshold={"max": bull_beta_to_spy_max},
            notes="TAA in BULL regime should NOT mimic SPY; beta ≤ 0.85.",
        ))
    else:
        gates.append(TaaGateResult(
            name="g5_bull_beta_to_spy",
            passed=True,
            values={},
            threshold={"max": bull_beta_to_spy_max},
            notes="SKIPPED — no spy_daily_returns/labels provided.",
        ))

    # G6. Calmar ≥ SPY Calmar (HARD primary risk-adjusted)
    taa_calmar = result.metrics_full_period.get("calmar", 0.0)
    spy_calmar = spy_metrics_full_period.get("calmar", 0.0)
    g6_pass = taa_calmar >= spy_calmar
    gates.append(TaaGateResult(
        name="g6_calmar_ge_spy",
        passed=bool(g6_pass),
        values={"taa_calmar": taa_calmar, "spy_calmar": spy_calmar},
        threshold={"min": "spy_calmar"},
        notes="PRD I15 primary risk-adjusted metric.",
    ))

    # G7. MaxDD < SPY MaxDD across full period
    taa_dd = result.metrics_full_period.get("max_dd", 0.0)
    spy_dd = spy_metrics_full_period.get("max_dd", 0.0)
    g7_pass = taa_dd > spy_dd  # both negative; > is less deep
    gates.append(TaaGateResult(
        name="g7_full_period_maxdd_better_than_spy",
        passed=bool(g7_pass),
        values={"taa_max_dd": taa_dd, "spy_max_dd": spy_dd},
        threshold={"min": "spy_max_dd"},
        notes="TAA must improve DD over passive SPY.",
    ))

    overall = all(g.passed for g in gates)
    return TaaAcceptanceResult(
        overall_passed=overall,
        gates=gates,
        rule_set_name=result.rule_set_name,
        cadence=result.cadence,
        notes=(
            "PRD-E v1.1 §5.3 Phase 3 acceptance. ELIGIBLE for forward "
            "observation freeze if all gates pass; freeze itself is "
            "PRD-E2 separate scope (per I11 fix)."
        ),
    )
