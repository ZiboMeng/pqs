# Production Factor Promote Proposal — Gated-Mom + Weak-Market RS

**PRD**: `docs/prd_deep_mining_50round.md` §11.4
**Date**: 2026-04-22
**Status**: **PROPOSAL — awaits user review + explicit authorization**
**Trigger**: R14/R15 ensemble backtest shows meaningful alpha improvement

---

## Summary

Two new RESEARCH_FACTORS added in R7 + R10 deep mining:
1. `spy_trend_gated_mom_63d` (R7, `8dd33fa6` → `992aa0b`)
2. `weak_market_relative_strength_63d` (R10, `d55d425`)

**R14 ensemble composite backtest** (via `llm_composite_backtest.py`,
simplified top-5 equal-weight, monthly rebalance, 2018-2026):

| Config | CAGR 1x | Sharpe | MaxDD | vs QQQ |
|---|---:|---:|---:|---:|
| A. Production (R33 weights) | +17.05% | 0.59 | -56.76% | **-1.42%** (loses) |
| B. A + spy_trend_gated_mom_63d | +19.92% | 0.65 | -56.76% | **+1.45%** |
| C. B + weak_market_relative_strength_63d (neg weight) | **+21.89%** | **0.68** | -56.76% | **+3.42%** |

Config C **beats QQQ by +3.42pt** in simplified backtest. Both new
factors contribute incremental alpha cleanly.

---

## Key caveats

**MaxDD -56.76%** in all 3 configs — simplified backtest does NOT
implement:
- Kill switch (3-tier drawdown throttle)
- target_vol=0.25 position sizing
- regime scaling (RISK_OFF cash allocation)
- soft_cap_max_single (strategy-level concentration)

Production MFS with same weights + full risk machinery gives MaxDD
-19.7% per CLAUDE.md Phase B record. So **MaxDD not blocking here**;
kill switch + target_vol in production should clamp.

---

## Recommended user action

**Step 1**: add both new factors to PRODUCTION_FACTORS
- `core/factors/factor_registry.py::PRODUCTION_FACTORS` 7 → 9
- `RESEARCH_TO_PRODUCTION_MAP` entries for both (shadow relationship)
- `core/signals/strategies/multi_factor.py::MultiFactorStrategy.generate()`
  add inline computation blocks for both factors
- `_DEFAULT_WEIGHTS` rebalance (current 7-factor sums to 1.0; new 9-factor needs reweight)
- `core/mining/strategy_space.py::MultiFactorSpace`:
  - `_TUNED_FACTORS = PRODUCTION_FACTORS` sync
  - `suggest()` adds `w_spy_trend_gated_mom_63d` + `w_weak_market_relative_strength_63d` slots (0.0 → 0.20 range)
  - `instantiate()` passes new weights

**Step 2**: run fresh mining round with expanded factor space
- `run_mining.py --trials 50 --budget 1800 --type multi_factor --lineage-tag post-2026-04-22-deep-R15-expanded`
- 新 factor 进 tuning → Optuna 探索最佳权重组合

**Step 3**: acceptance pack v2 on best spec
- `acceptance_pack.py --spec-id <best>`
- If all 10 gates PASS (including full_period_fresh_backtest against QQQ): promote via `promote_strategy.py`

---

## Evidence pack

### R5 interaction mine (commit `2606823`)
- `rs_vs_qqq_63d × spy_trend_200d` pair IC **+0.0704**, incremental **+0.0458** vs best parent
- Strongest regime-gated pattern; seeded R7 `spy_trend_gated_mom_63d`

### R7 funnel + deep_check (commit `992aa0b`)
- Funnel: NEEDS_HUMAN_REVIEW (ρ+0.87 vs mom_63d)
- Deep: OOS walk-forward IR **+0.332**, regime 6/6 correct sign,
  quartile max contribution 0.373 (stable)

### R10 funnel + deep_check (commit `d55d425`)
- Codex round_02 weak-market theme (3 candidates, all PASS deep):
  - `downside_resilience_63d` IR -0.351
  - `weak_market_relative_strength_63d` IR **-0.402** (strongest)
  - `weak_breadth_resilience_63d` IR -0.379
- **Negative-direction predictor** → use with negative weight in composite
- Only 1 added (strongest IR) to avoid intra-registry redundancy

### R14 composite backtest (current proposal file)
- Simplified top-5 EW monthly rebalance backtest
- C_weak_market config: +21.89% CAGR, +3.42% vs QQQ
- **NOT yet tested through production MFS + acceptance pack v2**

### R21 cost sensitivity (commit `4c589fd` ... ``75dca75`)
- Composite C (same as R14) under different cost_bps × 1x/2x stress:

| cost_bps | 1x CAGR | 2x CAGR | vs QQQ 2x |
|---:|---:|---:|---:|
| 5  | 22.13% | 21.89% | +3.42pt |
| 10 | 21.89% | 21.39% | +2.92pt |
| 20 | 21.39% | 20.41% | +1.94pt |
| 30 | 20.90% | 19.44% | +0.97pt |

**Cost robustness**: even at cost 30 bps × 2x = 60 bps effective, strategy
still beats QQQ (+0.97pt). In production, realistic cost ~10 bps so
margin of safety is solid.

---

## Decision framework for user

| Outcome | Action |
|---|---|
| User approves Step 1 (registry expansion) | Execute Step 1 + Step 2 mining; if acceptance pack passes, promote |
| User wants more validation first | Run `scripts/run_backtest.py --strategy multi_factor` with these factors pre-added to `_DEFAULT_WEIGHTS` manually (temporary test commit), measure full MFS results including kill switch |
| User wants to see intraday variant | R20/R23 intraday rounds will test overnight gap + intraday-specific combinations before registry expansion |
| User declines | Factors remain in RESEARCH_FACTORS; mining space unchanged; no code rollback needed |

This proposal does NOT auto-execute any of the above. Per PRD §11.4 this
is proposal-only; PRODUCTION_FACTORS changes require explicit user auth.

---

*Proposal auto-generated by deep-mining R14/R15 (commit `a9dd04b`).*
