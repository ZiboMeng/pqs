"""G2 — PBO for mining sweeps (report-only red-flag, no auto-kill).

PRD docs/prd/20260517-backtest_robustness_completion_prd.md §4 G2.

`probability_backtest_overfitting` (overfit_metrics) is the CSCV
kernel. This module is the mining-facing wrapper: given the per-trial
× per-period performance matrix collected DURING a sweep, compute PBO
and a config-thresholded red-flag for the Track A report.

Forward-only (G2-A2, honest limit — same root cause as boundary memo
§6 / PRD §6): `rcm_trials` persists only scalar per-trial summaries
(ic_mean / nav_sharpe / …), NOT per-trial per-period series. So PBO
CANNOT be retro-computed for cycle04-12; it applies to FUTURE sweeps
that collect the matrix transiently. No historical mining is re-run
for PBO. Integration contract (no fake wiring — mirrors the project's
beta-stamp/B.MV "helper now, wire at first consumer" discipline): a
future sweep that collects `per_trial_period_perf` calls
`compute_mining_pbo(...)` and stamps the result into the study
artifact + Track A report; until such a sweep exists, deep miner
wiring would be dead code and is intentionally deferred.
"""
from __future__ import annotations

import numpy as np

from core.research.overfit_metrics import probability_backtest_overfitting

# config-ized (PRD: all thresholds configurable). Default 0.5 = the
# CSCV neutral point (IS-best underperforms OOS median half the time).
DEFAULT_PBO_RED_FLAG_THRESHOLD = 0.5


def compute_mining_pbo(
    per_trial_period_perf: np.ndarray,
    *,
    red_flag_threshold: float = DEFAULT_PBO_RED_FLAG_THRESHOLD,
) -> dict:
    """PBO + report-only red-flag for a mining sweep.

    ``per_trial_period_perf`` = (n_periods × n_trials) per-period
    performance (e.g. per-period IC or return) of every tried trial.
    Returns ``{pbo, red_flag, n_combinations, S, threshold,
    note}``. ``red_flag`` is diagnostic ONLY — NO auto-kill (a human
    adjudicates; PRD G2-A3).
    """
    M = np.asarray(per_trial_period_perf, dtype=float)
    if M.ndim != 2 or M.shape[1] < 2 or M.shape[0] < 4:
        return {"pbo": float("nan"), "red_flag": False,
                "n_combinations": 0,
                "note": "insufficient matrix (need ≥4 periods, ≥2 trials) "
                        "— PBO not computable, NOT a pass"}
    res = probability_backtest_overfitting(M)
    pbo = res.get("pbo", float("nan"))
    red = bool(np.isfinite(pbo) and pbo > red_flag_threshold)
    return {"pbo": pbo, "red_flag": red,
            "n_combinations": res.get("n_combinations", 0),
            "S": res.get("S"), "mean_logit": res.get("mean_logit"),
            "threshold": float(red_flag_threshold),
            "auto_kill": False,
            "note": "diagnostic red-flag only; human adjudicates "
                    "(PRD G2-A3). forward-only: past cycles not "
                    "retro-computable (scalar-only archive)."}
