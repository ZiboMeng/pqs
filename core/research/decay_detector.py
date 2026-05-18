"""G5 — strategy-decay / mechanism-failure early-warning detectors.

PRD docs/prd/20260517-backtest_robustness_completion_prd.md §4 G5.

Literature (arXiv 2003.02682 backward-CUSUM; Strategy Decay Detection):
threshold verdicts (Sharpe<0.4=RED) fire only AFTER decay; sequential
change-point detectors flag it early. Pure compute, NO side effects.

Four detectors on a performance/return series:
  - page_hinkley        — sequential mean-shift (Page-Hinkley)
  - backward_cusum       — recent cumulative deviation vs baseline
  - rolling_psr_degraded — Probabilistic Sharpe Ratio recent < earlier
  - rolling_ic_decay     — rolling mean IC recent < earlier

`detect_decay` combines them into a GREEN/YELLOW/RED early-warning
that the forward attention report consumes ADDITIVELY (alongside, not
replacing, existing thresholds).

Forward-runner integration is LOCKED (PRD §4 G5-A2): additive lazy-
migration field, NEW-TD-only (never retro-judges recorded TDs), and
`observe --dry-run` smoke on ALL active candidates is a HARD
precondition before wiring (feedback_pre_post_audit_must_smoke_
observe). This module is the pure kernel; the gated wiring is a
deliberate follow-up step, not auto-applied (no wiring before the
gate — PRD self-consistency + project no-dead-code discipline).
"""
from __future__ import annotations

import math

import numpy as np


def page_hinkley(x, delta: float = 0.5, lam: float = 5.0) -> dict:
    """Page-Hinkley sequential mean-decrease test (input z-normalized,
    so ``delta``/``lam`` are scale-free std units). Alarm when the
    cumulative downward deviation exceeds ``lam``. ``delta`` = slack
    (>0 gives the no-change statistic negative drift, preventing
    random-walk false alarms — standard Page-Hinkley)."""
    a = np.asarray(x, float)
    a = a[np.isfinite(a)]
    if len(a) < 8:
        return {"alarm": False, "stat": float("nan"), "n": int(len(a))}
    sd0 = a.std(ddof=1)
    if sd0 == 0:
        return {"alarm": False, "stat": 0.0, "n": int(len(a))}
    a = (a - a.mean()) / sd0          # z-normalize → lam is scale-free
    mean = 0.0
    mt = 0.0
    m_min = 0.0
    for i, v in enumerate(a, 1):
        mean += (v - mean) / i
        mt += (mean - v - delta)          # accumulates when v drops below mean
        m_min = min(m_min, mt)
    stat = mt - m_min
    return {"alarm": bool(stat > lam), "stat": float(stat),
            "n": int(len(a))}


def backward_cusum(x, k_std: float = 3.0, tail_frac: float = 0.25) -> dict:
    """Backward CUSUM: cumulative deviation of the most-recent
    ``tail_frac`` of the series from the earlier-baseline mean, in
    baseline-std units. Alarm when |CUSUM| exceeds ``k_std``."""
    a = np.asarray(x, float)
    a = a[np.isfinite(a)]
    if len(a) < 12:
        return {"alarm": False, "cusum": float("nan"), "n": int(len(a))}
    cut = max(4, int(len(a) * (1.0 - tail_frac)))
    base = a[:cut]
    tail = a[cut:]
    mu, sd = base.mean(), base.std(ddof=1)
    if sd == 0 or len(tail) < 2:
        return {"alarm": False, "cusum": 0.0, "n": int(len(a))}
    cusum = float(np.sum(tail - mu) / (sd * math.sqrt(len(tail))))
    return {"alarm": bool(abs(cusum) > k_std), "cusum": cusum,
            "n": int(len(a))}


def _psr(r: np.ndarray, sr_benchmark: float = 0.0) -> float:
    r = r[np.isfinite(r)]
    if len(r) < 8 or r.std(ddof=1) == 0:
        return float("nan")
    mu, sd = r.mean(), r.std(ddof=1)
    sr = mu / sd
    g3 = float(((r - mu) ** 3).mean() / sd ** 3)
    g4 = float(((r - mu) ** 4).mean() / sd ** 4)
    denom = math.sqrt(max(1e-12,
                          1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr ** 2))
    z = (sr - sr_benchmark) * math.sqrt(len(r) - 1.0) / denom
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def rolling_psr_degraded(returns, window: int = 60,
                         drop: float = 0.30) -> dict:
    """Recent-window PSR materially below the earlier-window PSR."""
    a = np.asarray(returns, float)
    a = a[np.isfinite(a)]
    if len(a) < 2 * window:
        return {"alarm": False, "psr_early": float("nan"),
                "psr_recent": float("nan"), "n": int(len(a))}
    early = _psr(a[:window])
    recent = _psr(a[-window:])
    if not (np.isfinite(early) and np.isfinite(recent)):
        return {"alarm": False, "psr_early": early,
                "psr_recent": recent, "n": int(len(a))}
    return {"alarm": bool(recent < early - drop),
            "psr_early": float(early), "psr_recent": float(recent),
            "n": int(len(a))}


def rolling_ic_decay(ic_series, window: int = 20,
                     drop: float = 0.02) -> dict:
    """Recent rolling-mean IC materially below the earlier rolling-mean
    IC (signal losing predictive power)."""
    a = np.asarray(ic_series, float)
    a = a[np.isfinite(a)]
    if len(a) < 2 * window:
        return {"alarm": False, "ic_early": float("nan"),
                "ic_recent": float("nan"), "n": int(len(a))}
    early = float(a[:window].mean())
    recent = float(a[-window:].mean())
    return {"alarm": bool(recent < early - drop),
            "ic_early": early, "ic_recent": recent, "n": int(len(a))}


def detect_decay(returns, ic_series=None, **kw) -> dict:
    """Combine the four detectors into an additive early-warning.

    Verdict: RED if ≥2 detectors fire (or Page-Hinkley AND
    backward-CUSUM both fire); YELLOW if exactly 1 fires; GREEN if 0.
    Pure: returns a dict, mutates nothing, judges only the series
    passed (caller enforces NEW-TD-only — this never sees recorded
    TDs it shouldn't).
    """
    ph = page_hinkley(returns, kw.get("delta", 0.5), kw.get("lam", 5.0))
    bc = backward_cusum(returns, kw.get("k_std", 3.0),
                        kw.get("tail_frac", 0.25))
    pr = rolling_psr_degraded(returns, kw.get("psr_window", 60),
                              kw.get("psr_drop", 0.30))
    ic = (rolling_ic_decay(ic_series, kw.get("ic_window", 20),
                           kw.get("ic_drop", 0.02))
          if ic_series is not None
          else {"alarm": False, "n": 0, "skipped": True})
    fired = [n for n, d in (("page_hinkley", ph), ("backward_cusum", bc),
                            ("rolling_psr", pr), ("rolling_ic", ic))
             if d.get("alarm")]
    if len(fired) >= 2 or (ph["alarm"] and bc["alarm"]):
        verdict = "RED"
    elif len(fired) == 1:
        verdict = "YELLOW"
    else:
        verdict = "GREEN"
    return {"verdict": verdict, "fired": fired,
            "page_hinkley": ph, "backward_cusum": bc,
            "rolling_psr": pr, "rolling_ic": ic,
            "additive": True,
            "note": "early-warning ADDITIVE to existing thresholds "
                    "(does not replace); NEW-TD-only; forward wiring "
                    "gated behind observe --dry-run smoke (PRD G5-A2)"}
