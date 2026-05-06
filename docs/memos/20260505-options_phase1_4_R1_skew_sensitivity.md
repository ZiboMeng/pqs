# Options Phase 1.4 R1 — Skew sensitivity sweep

**Date**: 2026-05-05  
**Operator**: zibomeng (Claude Opus 4.7)  
**Origin**: Phase 1.4 viability memo R1
(`docs/memos/20260502-options_v1_phase_1_viability_memo.md`)  
**Output dir**: `data/options/analysis/spread_backtest_summary_otm8_skew_p*_c75.json`

## Spec

R1 deferred queue item from viability memo:

> Re-running 1.3 with `iv_realized = vix × (1 + skew_factor)` for
> skew_factor ∈ [0.20, 0.50] tests whether skew alone shifts the verdict.

Translation: `iv_realized = vix × put_skew` for put_skew ∈ [1.20, 1.50].
The bull put spread P&L responds to put-side IV skew (call-side is
irrelevant for short-put-leg / long-put-hedge). Sweep `put_skew` ∈
{1.20, 1.30, 1.40, 1.50} fixing `call_skew = 0.75`. SHORT_OTM_PCT = 0.08
(matches Path D honest-winner config).

## Method

For each put_skew level, run `synthetic_spread_backtest.py` with
`--put-skew <ps> --call-skew 0.75 --otm-pct 0.08`. Same 6 modes per
run; we report `baseline_bull_put` (Path D winner). 33-year backtest
(VIX 1990-onward), $10k initial NAV.

## Results

| put_skew | CAGR | Sharpe | MaxDD | Final NAV | Trades | WinRate | §6 (>0.60)? |
|---|---|---|---|---|---|---|---|
| **1.20** | +0.77% | **0.53** | -3.16% | $12,886 | 388 | 92.5% | ❌ FAILS |
| **1.30** baseline | +0.99% | **0.62** | -2.96% | $13,882 | 388 | 92.0% | ✓ borderline |
| 1.40 | +1.18% | **0.65** | -2.90% | $14,779 | 388 | 91.5% | ✓ |
| 1.50 | +1.45% | **0.72** | -2.82% | $16,112 | 388 | 91.5% | ✓ comfortable |

## Sensitivity finding

Sharpe is **monotone increasing** with put_skew across the [1.20, 1.50]
range:

- ΔSharpe per 0.10 put_skew step = ~+0.06 (linear within sample)
- Range 0.53 → 0.72 = **0.19 Sharpe spread** between R1 endpoints
- CAGR range = 1.5x (0.77% → 1.45%)

**Baseline 0.62 Sharpe (put_skew=1.30) is fragile**: a 5-point shift to
put_skew=1.25 likely puts Sharpe at ~0.575 (fails §6 gate); a 5-point
shift to 1.35 puts it at ~0.66 (comfortable pass). The verdict turns on
whether real-world put_skew on SPY 8% OTM puts at 30-40 DTE is
≥ 1.30 with high confidence.

## What baseline 1.30 was calibrated against

Path D's baseline came from a single yfinance live SPY chain snapshot
(unspecified date in Phase 1.3 work). One snapshot ≠ population
estimate. Empirical SPY skew literature suggests:

- ATM IV ≈ VIX (definitionally; VIX is index-of-30dte-IV-mid)
- 5% OTM put IV typically 5-15% above ATM
- 8% OTM put IV typically 15-30% above ATM (depending on regime)
- Crisis regimes can push 8% OTM put IV 50%+ above ATM

So baseline 1.30 sits in the **middle** of the empirical distribution
for 8% OTM SPY puts. It is plausible, not necessarily conservative.
Real put_skew probably has substantial regime variation that this
single multiplier flattens.

## Verdict

**Spread strategy passes R1 sensitivity gate at 3 of 4 sweep points
(1.30 / 1.40 / 1.50)**. Fails at 1.20. The verdict is **"acceptable
but skew-sensitive"** — confidence in the +0.62 Sharpe claim depends
on real put_skew ≥ 1.30 holding consistently across regimes.

Compared to the Path D viability memo's tier:

- **Honest winner**: still defensible at baseline 1.30
- **Skew-fragile**: confirmed; real-data spend (paid options chain)
  remains the right gate to upgrade verdict confidence
- **Wheel rejection**: unaffected by R1 (wheel rejected for structural
  long-only / drawdown reasons, not skew assumption)

## Implications for paid data spend

Phase 1.4 viability memo §"Capital deferral path" gates paid options
chain spend on Trial 9 TD60 GREEN + options paper TD60 GREEN. R1
result tightens the spend rationale:

- IF paid data shows real SPY 8% OTM put_skew distribution centered
  ≥ 1.30 with manageable variance → spread strategy verdict stays
  honest winner
- IF paid data shows real distribution mode ≤ 1.25 (e.g. base regime
  has tighter skew than crisis-adjusted average) → verdict downgrades
  to skew-fragile, may not justify capital allocation

Either outcome is decision-useful — paid data spend retains its
information value.

## OOS discipline

R1 backtest range = full VIX history (1990-onward); no 2026-05-04+
forward data accessed. Existing options paper run
(`spy_8otm_bull_put_v1`) **untouched** — its `spec.yaml` still pins
put_skew=1.30 from init, and changing it mid-flight would invalidate
n_observe_days continuity. R1 is research-only; production options
paper uses the originally-pinned skew.

## Action items

- **No automatic action**.
- TD60 paper observation continues with put_skew=1.30 baseline.
- IF Trial 9 TD60 + options paper TD60 both GREEN → R1 sensitivity
  evidence informs negotiated paid-data spec (require historical
  chain calibration to bound real put_skew distribution).
- IF either RED → R1 sensitivity is moot (don't spend on paid data
  for a strategy that already fails).

## Files

```
data/options/analysis/spread_backtest_summary_otm8_skew_p1.20_c75.json
data/options/analysis/spread_backtest_summary_otm8_skew_p1.30_c75.json
data/options/analysis/spread_backtest_summary_otm8_skew_p1.40_c75.json
data/options/analysis/spread_backtest_summary_otm8_skew_p1.50_c75.json
data/options/backtest/spread_baseline_bull_put_otm8_skew_p*_c75_nav.parquet
(+ 5 other modes per put_skew; not the focus of this memo)
```
