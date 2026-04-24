"""Shared acceptance evaluator helpers (Phase E-1 R7).

Pure functions shared between:
  - scripts/acceptance_research_composite.py (research-level acceptance;
    IC-centric gate for S0 -> S1 promote)
  - future promote/paper acceptance paths

NOT shared with:
  - core/mining/acceptance_pack.py (production-level acceptance; backtest-
    centric gate for config/production_strategy.yaml. Intentionally kept
    separate per PRD 1 §8.1 "three promotes; don't blur layers". A future
    round may optionally refactor acceptance_pack.py to call these helpers
    too; out of Phase E scope.)

Contract:
  - Pure functions: no I/O side effects, no logger side effects, no
    mutable global state. Deterministic given inputs.
  - Returns plain dicts (JSON-serializable) for artifact friendliness.
  - Formatters (_fmt) are UI concerns separated from the numerics.

The IR annualization factor sqrt(252 / horizon) matches R14 rcm-v1 fix.

PRD: docs/20260424-prd_phase_e_execution.md §2 E1-R7
     docs/20260424-prd_research_to_paper_promote_standard.md §7
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


__all__ = [
    "fmt",
    "summarize_ic",
    "walkforward_ic",
    "regime_stratified_ic",
    "turnover_summary",
    "benchmark_relative_ic_summary",
    "ic_stability_decision",
]


# ── Formatters ───────────────────────────────────────────────────────────────


def fmt(x: Any) -> str:
    """Compact float formatter used across acceptance CLIs."""
    if x is None:
        return "nan"
    try:
        x_f = float(x)
    except (TypeError, ValueError):
        return "nan"
    if not np.isfinite(x_f):
        return "nan"
    return f"{x_f:+.4f}"


# ── Core IC summary ─────────────────────────────────────────────────────────


def summarize_ic(ic_series: pd.Series, horizon: int) -> dict:
    """Summarize a per-date IC series.

    Returns dict with:
      n_dates, ic_mean, ic_std, ic_ir (annualized sqrt(252/horizon)),
      positive_rate

    Missing / degenerate inputs produce structured nones rather than raising.
    """
    if horizon <= 0:
        raise ValueError(f"horizon must be > 0, got {horizon}")
    n = len(ic_series)
    if n == 0:
        return {
            "n_dates": 0,
            "ic_mean": None,
            "ic_std": None,
            "ic_ir": None,
            "positive_rate": None,
        }
    mean = float(ic_series.mean())
    std = float(ic_series.std()) if n > 1 else float("nan")
    # Near-zero std (e.g. constant series) yields 1e-17 under floating-
    # point accumulation — enough to slip past a > 0 check but produces
    # runaway IR. Require std above a sensible tolerance.
    _STD_TOL = 1e-12
    if np.isfinite(std) and std > _STD_TOL:
        ir: float | None = mean / std * float(np.sqrt(252.0 / horizon))
    else:
        ir = None
    pos_rate = float((ic_series > 0).mean())
    return {
        "n_dates": int(n),
        "ic_mean": mean,
        "ic_std": std if np.isfinite(std) else None,
        "ic_ir": ir if (ir is not None and np.isfinite(ir)) else None,
        "positive_rate": pos_rate,
    }


# ── Walk-forward ─────────────────────────────────────────────────────────────


def walkforward_ic(
    ic_series: pd.Series,
    horizon: int,
    n_folds: int = 4,
    min_per_fold: int = 50,
) -> list[dict]:
    """Equal-size temporal walk-forward split of `ic_series`.

    Returns list of per-fold summaries:
      [{fold, date_start, date_end, n_dates, ic_mean, ic_std, ic_ir,
        positive_rate}, ...]

    Returns [] if ic_series is too short to split into n_folds × min_per_fold.
    """
    if n_folds < 2:
        raise ValueError(f"n_folds must be >= 2, got {n_folds}")
    if len(ic_series) < n_folds * min_per_fold:
        return []
    fold_size = len(ic_series) // n_folds
    folds: list[dict] = []
    for i in range(n_folds):
        start = i * fold_size
        end = len(ic_series) if i == n_folds - 1 else (i + 1) * fold_size
        sub = ic_series.iloc[start:end]
        summary = summarize_ic(sub, horizon)
        summary["fold"] = i + 1
        summary["date_start"] = str(sub.index[0].date()) if len(sub) else None
        summary["date_end"] = str(sub.index[-1].date()) if len(sub) else None
        folds.append(summary)
    return folds


# ── Regime stratification ───────────────────────────────────────────────────


def regime_stratified_ic(
    ic_series: pd.Series,
    regimes: pd.Series,
    horizon: int,
    min_per_regime: int = 20,
) -> dict:
    """Per-regime IC summary.

    `regimes` must be a Series indexed by dates, values = regime label
    (str or enum.value). Regime buckets with fewer than `min_per_regime`
    observations are dropped.

    Returns dict {regime_label: summary_dict}.
    """
    out: dict = {}
    common = ic_series.index.intersection(regimes.index)
    ic_c = ic_series.reindex(common)
    reg_c = regimes.reindex(common)
    for state in reg_c.dropna().unique():
        sub = ic_c[reg_c == state]
        if len(sub) >= min_per_regime:
            s = summarize_ic(sub, horizon)
            s["n_dates"] = int(len(sub))
            out[str(state)] = s
    return out


# ── Turnover summary ────────────────────────────────────────────────────────


def turnover_summary(composite: pd.DataFrame) -> dict:
    """Summarize a per-date composite signal's turnover.

    Uses the same rank-stability proxy as core/mining/research_miner.py
    `_turnover_proxy` but exposed as a helper so acceptance can report
    turnover independently of composite evaluation.

    Inputs: composite panel (date × symbol), values = signal score
    (not required to be z-scored; rank is used).

    Returns: dict with
      turnover_proxy       : mean 1 - |rank(t) - rank(t-1)| correlation
      n_dates              : number of dates with at least 2-row rank corr
      n_symbols_median     : median non-NaN columns per row
    """
    if composite.empty or composite.shape[0] < 2:
        return {"turnover_proxy": None, "n_dates": 0, "n_symbols_median": 0}
    ranked = composite.rank(axis=1)
    # Rolling 2-row corr between consecutive rows
    # Use shift + row-wise correlation
    prev = ranked.shift(1)
    # pair-wise correlation row-by-row
    corrs: list[float] = []
    for i in range(1, len(ranked)):
        a = ranked.iloc[i].dropna()
        b = prev.iloc[i].dropna()
        common = a.index.intersection(b.index)
        if len(common) >= 3:
            c = a.loc[common].corr(b.loc[common])
            if pd.notna(c):
                corrs.append(float(c))
    if not corrs:
        return {"turnover_proxy": None, "n_dates": 0, "n_symbols_median": 0}
    # proxy = 1 - mean(rank correlation). Higher = more churn.
    proxy = 1.0 - float(np.mean(corrs))
    nsyms = int(composite.notna().sum(axis=1).median())
    return {
        "turnover_proxy": proxy,
        "n_dates": len(corrs),
        "n_symbols_median": nsyms,
    }


# ── Benchmark-relative IC summary ───────────────────────────────────────────


def benchmark_relative_ic_summary(
    ic_by_regime: dict,
    *,
    primary_regime: str = "CRISIS",
    secondary_regime: str = "RISK_ON",
) -> dict:
    """Extract a benchmark-relative-style summary from per-regime IC.

    A proper benchmark-relative metric requires portfolio-level P&L vs
    SPY/QQQ, which lives at the paper/backtest layer. At the IC-only
    research acceptance layer, we surface CRISIS vs RISK_ON IR as a
    proxy for defensive vs pro-risk behavior (see RCMv1 memo §5.1).

    Missing regimes resolve to None; callers should interpret a null
    `primary_regime_ic_ir` as "insufficient data" rather than "zero".
    """
    def _ir(state: str) -> float | None:
        s = ic_by_regime.get(state)
        if not isinstance(s, dict):
            return None
        v = s.get("ic_ir")
        return float(v) if v is not None and np.isfinite(v) else None

    return {
        "primary_regime": primary_regime,
        "primary_regime_ic_ir": _ir(primary_regime),
        "secondary_regime": secondary_regime,
        "secondary_regime_ic_ir": _ir(secondary_regime),
        "note": (
            "IC-level proxy; full benchmark-relative P&L (vs SPY/QQQ) "
            "must be computed at paper/backtest layer"
        ),
    }


# ── IC stability decision ───────────────────────────────────────────────────


def ic_stability_decision(
    full: dict,
    wf: list[dict],
    regime: dict,
    *,
    ir_threshold: float = 0.2,
    walkforward_min_positive_folds: int = 3,
    regime_min_positive: int = 3,
) -> dict:
    """Apply research-level acceptance thresholds.

    Returns dict:
      outcome : "promote_to_paper" | "hold_in_research"
      blocking_reasons : list[str]

    Thresholds are deliberately modest (IR >= 0.2) — this is the
    RESEARCH gate (S0 -> S1), not production gate. Tighten at paper or
    production promote layers per PRD 1 §8.1.
    """
    reasons: list[str] = []
    passed = True

    # Performance: full-period IC_IR
    full_ir = full.get("ic_ir")
    if full_ir is None or full_ir < ir_threshold:
        reasons.append(
            f"Performance: full-period IC_IR={full_ir!r} below "
            f"{ir_threshold} threshold"
        )
        passed = False

    # Walk-forward
    if wf:
        pos_folds = sum(
            1 for f in wf
            if f.get("ic_ir") is not None and f["ic_ir"] > 0
        )
        if pos_folds < walkforward_min_positive_folds:
            reasons.append(
                f"Walk-forward: only {pos_folds}/{len(wf)} folds with "
                "positive IR"
            )
            passed = False

    # Regime stability
    if regime:
        pos_reg = sum(
            1 for r in regime.values()
            if r.get("ic_ir") is not None and r["ic_ir"] > 0
        )
        if pos_reg < regime_min_positive:
            reasons.append(
                f"Regime: only {pos_reg}/{len(regime)} regimes positive"
            )
            passed = False

    return {
        "outcome": "promote_to_paper" if passed else "hold_in_research",
        "blocking_reasons": reasons,
    }
