# Trial 9 historical walk-forward prior — per-regime fix

**Date**: 2026-05-05  
**Operator**: zibomeng (Claude Opus 4.7)  
**Output JSON**: `data/ml/research_cycle_eval/trial9_historical_walkforward_prior.json`  
**Script**: `dev/scripts/forward/trial9_historical_walkforward_prior.py`

## Context

trial9 forward observation has TD60 decision point ~2026-07-30. PRD §7.1
defines GREEN / YELLOW / RED on that day from rolling 60d cum_ret vs SPY,
vs QQQ, MaxDD, and combo NAV. Before TD60 we want a **prior estimate**
of which verdict to expect under different forward regimes.

The 2026-05-02 prior run had a bug: regime classifier received SPY/QQQ
from cycle05's panel, where SPY/QQQ have 2110+ NaN gaps (panel is
outer-merge of a 53-stock + 6-cross-asset universe, where benchmark
columns are not first-class). Result: 200d rolling means were
universally NaN → every day labeled `UNKNOWN` → per-regime breakdown
collapsed to a single bucket.

## Fix

Load SPY/QQQ directly via `BarStore.load(..., adjusted=True)` (clean
continuous 2007+ benchmark series), reindex onto cycle05 panel calendar
with forward-fill, then run the regime classifier.

| Metric (post-fix) | Value |
|---|---|
| Panel range | 2009-01-02 → 2025-12-31 (NO 2026 sealed access) |
| Sample windows | 131 valid 60-TD windows, monthly start sampling |
| Regime distribution (4876 days) | RISK_ON 38% / UNKNOWN 36% (early 200d warmup) / RISK_OFF 15% / BULL 6% / BEAR 4% / SIDEWAYS / CRISIS each <1% |

## Per-regime TD60 verdict prior

| Regime | n | GREEN | YELLOW | RED |
|---|---|---|---|---|
| BEAR        | 9  | 22% | 11% | **67%** |
| BULL        | 9  | 22% | 44% | 33% |
| RISK_OFF    | 27 | 11% | 30% | **59%** |
| **RISK_ON** | **76** | **37%** | 29% | 34% |
| UNKNOWN     | 10 | 40% | 40% | 20% |
| **All**     | 131 | 30% | 30% | 41% |

**Caveats**:
- BEAR / BULL n=9 each → high variance; 22% GREEN under BEAR could just
  be sampling
- UNKNOWN cluster is early 2009-2010 (200d warmup) — survivorship and
  GFC-recovery bias both push toward optimistic verdicts
- This is **in-sample upper bound** — trial 9 was mined on the 2009-2025
  panel. True OOS prior is strictly lower

## Forward-relevant regime read

trial9 init eve (2026-05-01 trading day) SPY regime classification:

```
trend (SPY / SPY-200d - 1):  +7.41%
drawdown vs 252d max:         0.00%   (SPY at all-time highs)
60d annualized vol:          15.40%
=> regime: RISK_ON
```

If forward regime stays **RISK_ON** through TD60 (~2026-07-30):
- **prior P(GREEN) ≈ 37%** (in-sample upper bound; likely lower OOS)
- prior P(YELLOW) ≈ 29%
- prior P(RED) ≈ 34%

If regime flips to RISK_OFF / BEAR before TD60 (≥5% drawdown OR vol > 25%):
- prior P(GREEN) drops to 11-22%
- prior P(RED) rises to 59-67%

**Practical takeaway**: trial9 needs continued RISK_ON regime to clear
TD60 GREEN. Watch for drawdown >5% from current ATH OR vol spike >25%
between now and 2026-07-30 — either flips the regime and shifts prior
sharply toward RED.

## Combo evidence (unchanged from prior run; numbers slightly shifted
   due to +1 valid window)

trial9 + RCMv1 + Cand-2 equal-weight combo NAV vs RCMv1+Cand-2 baseline:

| Metric | % windows where combo improves |
|---|---|
| Sharpe | 58% (76/131) |
| MaxDD  | **92% (121/131)** |
| Either | 95% (124/131) |

trial9's diversifier role hypothesis is supported on **DD reduction**
much more than on Sharpe — adding trial9 to the fleet reduces drawdown
in 92% of historical 60-TD windows, but raises Sharpe in only 58%.
This is consistent with the cycle #05 R41 verdict (low-vol diversifier,
NOT alpha-additive).

## Action items

- **NONE today**: prior is informational, no decision triggered.
- **TD20 / TD40 attention check** (PRD trial9 §7.1) — operator should
  also report observed regime alongside cum_ret comparison so
  prior-vs-actual gap is visible.
- **Post-TD60**: rerun this script with TD60 actuals folded in to
  update prior with actual OOS evidence. This is OK because TD60+
  data IS the evidence (not training input).

## OOS discipline

- BarStore reads stop at panel_end = 2025-12-31 (cycle05 yaml's panel)
- SPY/QQQ regime classification at 2026-05-01 uses BarStore daily data
  through 2026-05-01 only (one trading day before trial9 init)
- No 2026-05-04+ data consumed
- Prior is fully derivable from data ≤ trial9 init eve
