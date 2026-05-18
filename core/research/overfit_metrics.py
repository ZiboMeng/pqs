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


def minimum_backtest_length(
    observed_sr_annual: float,
    n_trials: int,
    safety_multiple: float = 1.0,
) -> dict:
    """Minimum Backtest Length in years (Bailey, Borwein, LdP, Zhu 2014).

    PRD §4 G3-A1. With ``n_trials`` configs tried, the expected max
    annualized Sharpe of zero-skill strategies is ~sqrt(2 ln N); a
    real result needs enough years that its observed annualized Sharpe
    clears that bar. Closed form:

        MinBTL (years) ≈ (2 · ln N) / SR_annual²

    ``safety_multiple`` (config) scales the requirement (e.g. 1.5 =
    demand 50% more history than the bare bound). Returns
    ``{min_btl_years, expected_max_sr_annual, ...}``. NaN-safe.
    """
    if (n_trials is None or n_trials < 2 or observed_sr_annual is None
            or not np.isfinite(observed_sr_annual)
            or abs(observed_sr_annual) < 1e-9):
        return {"min_btl_years": float("nan"), "n_trials": n_trials,
                "note": "undefined (need n_trials>=2 and SR!=0)"}
    emax = math.sqrt(2.0 * math.log(n_trials))
    min_btl = safety_multiple * (2.0 * math.log(n_trials)
                                 / (observed_sr_annual ** 2))
    return {"min_btl_years": float(min_btl),
            "expected_max_sr_annual": float(emax),
            "n_trials": int(n_trials),
            "safety_multiple": float(safety_multiple)}


def check_min_backtest_length(
    observed_sr_annual: float,
    n_trials: int,
    actual_years: float,
    safety_multiple: float = 1.0,
) -> dict:
    """Track A fail-closed gate (PRD §4 G3-A1).

    ``passed=False`` (fail-closed) when actual history is shorter than
    the Bailey MinBTL OR inputs are undefined. Diagnostic; the caller
    decides enforcement (no silent pass on missing inputs).
    """
    mb = minimum_backtest_length(observed_sr_annual, n_trials,
                                 safety_multiple)
    req = mb.get("min_btl_years", float("nan"))
    if not np.isfinite(req) or actual_years is None \
            or not np.isfinite(actual_years):
        return {"passed": False, "reason": "undefined_inputs_fail_closed",
                **mb, "actual_years": actual_years}
    ok = float(actual_years) >= req
    return {"passed": bool(ok),
            "reason": "ok" if ok else "backtest_shorter_than_min_btl",
            "actual_years": float(actual_years), **mb}


def recompute_dsr(
    returns: Sequence[float],
    honest_n_trials: int,
    *,
    prior_n_trials: int | None = None,
    sr_trials_std: float | None = None,
) -> dict:
    """G1-A3 — recompute DSR with an honest trial count.

    General go-forward tool: given the saved per-period ``returns`` and
    an honest ``honest_n_trials`` (from ``dsr_trial_accounting`` or a
    runtime ONC), returns the corrected DSR plus, if ``prior_n_trials``
    is given, the placeholder-N DSR and the delta — so a backfill can
    show "was X (placeholder N=p), now Y (honest N=h)" auditably.

    NOTE (honest limitation, boundary memo §6): the already-run ML-redo
    experiments did NOT persist their per-fold paired arrays (JSONs are
    scalar-only), so this tool CANNOT exactly re-number those past
    results — their correction stays qualitative (placeholder-N →
    optimistic → not an evidence anchor; robust = IC-sign). Forward
    contract: new ML experiment scripts MUST persist the per-period
    array so DSR is recomputable.
    """
    honest = deflated_sharpe_ratio(returns, honest_n_trials, sr_trials_std)
    out = {"honest_n_trials": int(honest_n_trials),
           "dsr_honest": honest["deflated_sharpe"],
           "sharpe": honest.get("sharpe"), "T": honest.get("T")}
    if prior_n_trials is not None:
        prior = deflated_sharpe_ratio(returns, prior_n_trials, sr_trials_std)
        out["prior_n_trials"] = int(prior_n_trials)
        out["dsr_prior_placeholder"] = prior["deflated_sharpe"]
        if (np.isfinite(out["dsr_honest"])
                and np.isfinite(out["dsr_prior_placeholder"])):
            out["dsr_delta"] = round(
                out["dsr_honest"] - out["dsr_prior_placeholder"], 6)
            # honest N >= placeholder ⇒ DSR must not increase
            out["direction_ok"] = (
                honest_n_trials < prior_n_trials
                or out["dsr_honest"] <= out["dsr_prior_placeholder"] + 1e-9)
    return out


def effective_n_trials_onc(returns_matrix: np.ndarray, k_cap: int = 20) -> dict:
    """Effective # of *independent* trials via ONC (López de Prado).

    PRD §4 G1-A2. ``returns_matrix`` = (n_periods × n_configs) per-period
    returns of every tried config. Correlated configs are not
    independent trials; clustering the trial-return correlation matrix
    and counting clusters gives the effective independent N to feed
    ``deflated_sharpe_ratio``. **forward-only**: past PQS mining cycles
    did not persist per-trial return series (rcm_trials = scalar
    summaries only), so this cannot be applied retroactively — see
    boundary memo §5. Returns ``{"effective_n": k, "n_configs": C}``.

    Mechanism: distance = sqrt(0.5*(1-corr)); KMeans for k in
    [2, min(C-1, k_cap)]; pick k with max mean silhouette (the ONC
    base loop). Degenerate inputs fall back to n_configs (conservative
    = no independence reduction).
    """
    M = np.asarray(returns_matrix, dtype=float)
    if M.ndim != 2 or M.shape[1] < 2:
        return {"effective_n": int(M.shape[1]) if M.ndim == 2 else 1,
                "n_configs": int(M.shape[1]) if M.ndim == 2 else 1}
    C = M.shape[1]
    corr = np.corrcoef(M, rowvar=False)
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    try:
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score
    except Exception:
        return {"effective_n": C, "n_configs": C,
                "note": "sklearn absent — conservative fallback C"}
    best_k, best_s = C, -1.0
    for k in range(2, min(C - 1, k_cap) + 1):
        try:
            lbl = KMeans(n_clusters=k, n_init=10,
                         random_state=42).fit_predict(dist)
            if len(set(lbl)) < 2:
                continue
            s = silhouette_score(dist, lbl, metric="precomputed") \
                if False else silhouette_score(dist, lbl)
        except Exception:
            continue
        if s > best_s:
            best_s, best_k = s, k
    return {"effective_n": int(best_k), "n_configs": int(C),
            "silhouette": round(float(best_s), 4)}


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
