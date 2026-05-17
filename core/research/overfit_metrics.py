"""R2 — Deflated Sharpe Ratio + Probability of Backtest Overfitting.

Per literature review §1.C [S13][S14] (Bailey & López de Prado). With
many trials the best Sharpe among unskilled strategies is positive by
chance (False Strategy Theorem). Every redo attempt must report DSR
(skill-probability after correcting for #trials + non-normality) and
PBO (combinatorially-symmetric rank-degradation probability).
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

_EULER = 0.5772156649015329


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam rational approximation)."""
    if not (0.0 < p < 1.0):
        raise ValueError("p in (0,1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > 1 - pl:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def expected_max_sharpe(n_trials: int, sr_std: float) -> float:
    """E[max Sharpe] of ``n_trials`` zero-skill strategies (False
    Strategy Theorem) — the SR threshold a real strategy must clear. [S13]"""
    if n_trials < 2:
        return 0.0
    z1 = _norm_ppf(1.0 - 1.0 / n_trials)
    z2 = _norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return sr_std * ((1.0 - _EULER) * z1 + _EULER * z2)


def deflated_sharpe_ratio(
    returns: Sequence[float],
    n_trials: int,
    sr_trials_std: float | None = None,
) -> dict:
    """DSR = P(true SR > 0 | observed SR, #trials, skew, kurtosis). [S13]

    ``returns`` = the strategy's per-period returns. ``n_trials`` = how
    many configs were tried to find it (selection-bias correction).
    ``sr_trials_std`` = std of Sharpe across those trials (if known);
    falls back to the analytic 1/sqrt(T) when not supplied.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    T = len(r)
    if T < 8 or r.std(ddof=1) == 0:
        return {"deflated_sharpe": float("nan"), "sharpe": float("nan"),
                "sr0": float("nan"), "n_trials": n_trials, "T": T}
    mu, sd = r.mean(), r.std(ddof=1)
    sr = mu / sd
    g3 = float(((r - mu) ** 3).mean() / sd ** 3)          # skew
    g4 = float(((r - mu) ** 4).mean() / sd ** 4)          # kurtosis (raw)
    if sr_trials_std is None:
        sr_trials_std = 1.0 / math.sqrt(T)
    sr0 = expected_max_sharpe(n_trials, sr_trials_std)
    denom = math.sqrt(max(1e-12, 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr ** 2))
    dsr = _norm_cdf((sr - sr0) * math.sqrt(T - 1.0) / denom)
    return {"deflated_sharpe": float(dsr), "sharpe": float(sr),
            "sr0": float(sr0), "skew": g3, "kurtosis": g4,
            "n_trials": int(n_trials), "T": int(T)}


def probability_backtest_overfitting(perf_matrix: np.ndarray) -> dict:
    """PBO via combinatorially-symmetric cross-validation (Bailey et al.).

    ``perf_matrix`` = (n_periods × n_configs) per-period performance
    (e.g. returns) of every tried config. Split periods into S even
    groups; for each train/test combination pick the IS-best config,
    record its OOS rank; PBO = P(logit of OOS rank-percentile ≤ 0)
    = fraction of combinations where the IS-best config underperforms
    the OOS median. [S14]
    """
    from itertools import combinations as _cmb

    M = np.asarray(perf_matrix, dtype=float)
    n_periods, n_cfg = M.shape
    S = min(10, n_periods - (n_periods % 2)) if n_periods >= 4 else 2
    S = S if S % 2 == 0 else S - 1
    if S < 2 or n_cfg < 2:
        return {"pbo": float("nan"), "n_combinations": 0, "S": S}
    bounds = np.linspace(0, n_periods, S + 1, dtype=int)
    groups = [np.arange(bounds[i], bounds[i + 1]) for i in range(S)]
    logits = []
    for is_combo in _cmb(range(S), S // 2):
        is_idx = np.concatenate([groups[g] for g in is_combo])
        oos_idx = np.concatenate(
            [groups[g] for g in range(S) if g not in is_combo])
        is_perf = M[is_idx].mean(axis=0)
        oos_perf = M[oos_idx].mean(axis=0)
        n_star = int(np.argmax(is_perf))
        # OOS rank percentile of the IS-best config
        rank = (oos_perf < oos_perf[n_star]).sum() / n_cfg
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(math.log(rank / (1.0 - rank)))
    logits = np.array(logits)
    pbo = float((logits <= 0).mean())
    return {"pbo": pbo, "n_combinations": len(logits), "S": S,
            "mean_logit": float(logits.mean())}
