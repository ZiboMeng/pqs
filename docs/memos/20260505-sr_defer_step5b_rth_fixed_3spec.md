# SR defer Path A — Step 5b RTH-fixed 3-spec evaluation

**Date**: 2026-05-05  
**Operator**: zibomeng (Claude Opus 4.7)  
**Backtest range**: 2018-01-01 → 2025-12-31 (OOS-clean — no 2026 sealed access)  
**Filter**: productionized `core/research/sr_signal_filter.py` with RTH-only window  
**Output dir**: `data/sr_validation/`

## Context

Step 5b v1 (pre-2026-05-05) ran the SR defer filter without RTH window
filtering. The filter took the LAST 60m bar of each day from the raw
60m series, which on 5/5 sampled symbols was a post-market 20:00 or
21:00 ET bar (ETH session, thin liquidity, often noise-amplified).
That contamination invalidated v1 numbers.

The 6.1-min plumbing PRD (commit `d3c7f73`) productionized the filter
in `core/research/sr_signal_filter.py` with RTH-only window
(`time >= 09:30 AND time < 16:00`). Step 5b harness (commit `4cae21c`)
swapped to call the productionized API. This memo reports the post-fix
3-spec evaluation.

## Method

For each of trial9 / RCMv1 / Cand-2:

| Arm | Description |
|---|---|
| A | Daily mode T+1 open via BacktestEngine, no SR filter (control baseline) |
| D | Daily mode T+1 open via BacktestEngine + RTH-fixed SR defer filter on target_wts |

Filter config = TimingThresholds defaults (`near_resistance_pct=0.005`,
`swing_n=5`, `lookback_bars=20`). Top-N=10, $10k initial capital, default
cost model. Range 2018-01-01 → 2025-12-31 (panel end-trim BEFORE SR
computation enforces sealed-window discipline).

## Results

| Spec | Arm | Final NAV | CAGR | Sharpe | MaxDD | vs SPY | vs QQQ | Defer fires |
|---|---|---|---|---|---|---|---|---|
| **trial9** | A | $122,362 | 29.37% | 0.78 | -52.14% | +969.96% | +836.00% | — |
| trial9 | D | $148,245 | 31.95% | 0.85 | -52.09% | +1228.79% | +1094.82% | 976/19935 (4.90%) |
| **RCMv1** | A | $70,588 | 22.25% | 0.67 | -44.58% | +452.22% | +318.25% | — |
| RCMv1 | D | $80,519 | 23.92% | 0.72 | -42.42% | +551.53% | +417.56% | 1098/19980 (5.50%) |
| **Cand-2** | A | $137,151 | 30.89% | 0.98 | -34.64% | +1117.85% | +983.88% | — |
| Cand-2 | D | $161,981 | 33.15% | 1.06 | -30.61% | +1366.15% | +1232.18% | 1113/19931 (5.58%) |

## Δ table (Arm D − Arm A)

| Spec | ΔSharpe | ΔCAGR | ΔMaxDD | Δvs SPY | Δvs QQQ |
|---|---|---|---|---|---|
| trial9 | +0.07 | +2.58 pp | +0.05 pp | +258.83 pp | +258.82 pp |
| RCMv1  | **+0.05** | +1.67 pp | **+2.16 pp** | +99.31 pp | +99.31 pp |
| Cand-2 | **+0.08** | +2.26 pp | **+4.03 pp** | +248.30 pp | +248.30 pp |

## Verdict

**3/3 spec passed the +0.05 Sharpe pre-commit threshold**. Lift is consistent
in direction (always positive on Sharpe + CAGR), with magnitude
~+0.05-0.08 Sharpe and +1.67-2.58 pp CAGR. RCMv1 and Cand-2 also see
material MaxDD improvement (+2.16 / +4.03 pp); trial9's MaxDD essentially
unchanged.

Defer activation rate ~4.9-5.6% across all three specs (very consistent),
suggesting the filter's per-cell trigger frequency is structural to the
60m-RTH-close-near-resistance condition, not artifact of any single
spec's selection patterns.

## Caveats

1. **In-sample contamination**: All three specs were mined on a panel
   covering 2018-2025. The Sharpe lift here is on the same window, so
   the spec selection is implicitly fitted to the lift-favorable
   direction. True OOS would require the candidates to face SR defer
   on data they did NOT see during mining — which today means the
   2026 sealed window (1 trading day so far for trial9, 0 for RCMv1
   / Cand-2 since they're aborted).

2. **SR defer thresholds also fitted**: `near_resistance_pct=0.005` /
   `swing_n=5` / `lookback_bars=20` are "expert-prior" defaults.
   No threshold sweep was run before this evaluation — there's no
   evidence the threshold itself was "OOS-mined". This is a smaller
   contamination than #1 but still present.

3. **MaxDD path on trial9**: -52% on a 2018-2025 backtest reflects the
   universe's exposure to 2018 vol-spike + 2020 covid + 2022 rate-hike
   drawdowns when the mining objective optimizes IC_IR not DD. Forward
   trial9 with PRD §7.1 attention-check on rolling 60d MaxDD will tell
   whether this magnitude reproduces.

4. **Forward observation streams unaffected**: This Step 5b backtest
   does NOT touch any of the 3 candidates' forward observation manifests.
   trial9 forward continues with `execution_policy=None` (the legacy
   path) until user explicitly authorizes flipping
   `execution_policy.enable_sr_defer=true` for a new (post-mining)
   candidate.

## Action items

- **No automatic action**. Decision to ship `enable_sr_defer=true` on
  the next mining-candidate's frozen yaml is **directional** and
  belongs to the user.
- 6.1-min Step 6+ (factor-mining S/R-derived factors going through
  RESEARCH_FACTORS funnel) is a separate workstream — already shipped
  as `dist_to_swing_high_20d` / `dist_to_swing_low_20d` /
  `sr_range_compression_20d` in `RESEARCH_FACTORS` per commit `b51d3f1`.
  These are research-only until promoted; future mining cycles can
  pull them.

## OOS discipline

Range 2018-01-01 → 2025-12-31 used. No 2026 data accessed (panel
end-trim before SR computation; backtest engine end=2025-12-31).
2026-05-04+ trial9 forward TDs untouched.

## Files

```
data/sr_validation/
  trial9_arm_A_baseline_metrics.json
  trial9_arm_A_baseline_nav.parquet
  trial9_arm_D_sr_defer_RTH_metrics.json
  trial9_arm_D_sr_defer_RTH_nav.parquet
  rcmv1_arm_A_baseline_metrics.json
  rcmv1_arm_A_baseline_nav.parquet
  rcmv1_arm_D_sr_defer_RTH_metrics.json
  rcmv1_arm_D_sr_defer_RTH_nav.parquet
  cand2_arm_A_baseline_metrics.json
  cand2_arm_A_baseline_nav.parquet
  cand2_arm_D_sr_defer_RTH_metrics.json
  cand2_arm_D_sr_defer_RTH_nav.parquet
```
