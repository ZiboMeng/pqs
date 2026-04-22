# Deep-Mining 50-Round — Final Synthesis (R50)

**PRD**: `docs/prd_deep_mining_50round.md`
**Date**: 2026-04-22
**Status**: **FINAL SYNTHESIS — honest "no validated best yet" conclusion**
**Authority**: Per §11.6 R50 is the end-gate for the loop. This doc is the
deliverable.

---

## TL;DR

After **50 rounds** of deep mining across 7 tracks (daily+ML, intraday,
DSL, universe expansion, XGBoost rigor, Transformer, final synthesis):

- **0/302** mining trials passed acceptance pack v2 on fresh backtest
- The single "promising" spec (`6d15b735a64c`, lineage round_28_expanded)
  passes 9/10 archive gates but **fails fresh full-period QQQ gate by
  -10.33pt CAGR**
- **1 LLM-generated factor promoted** to PRODUCTION_FACTORS
  (`drawup_from_252d_low`, R15) — held
- **2 LLM-generated factors added to RESEARCH_FACTORS** (R7, R10) —
  cross-validated in R42/R43
- **XGBoost weight model: PARK** (R46 verdict)
- **Transformer: PARK** (R48 verdict)
- **Universe expansion: PROPOSAL submitted, awaits user authorization**
  (R38 v3 proposal; 37 new symbols candidate)

**Recommendation**: `config/production_strategy.yaml` **remains in
`conservative_default` state**. No change to production behavior.

---

## Round-by-round highlights

### Track A — Daily + ML (R1-R15)
- **R1-R15**: LLM-assisted factor proposal funnel, deep_check on 26 candidates
- **Key factor added**: `drawup_from_252d_low` to PRODUCTION_FACTORS (R15,
  user-authorized). 4-method consensus: R3 deep_check OOS IR +0.386,
  R6 Ridge #1, R6 XGBoost #7, R12 factor_screen #2.
- **R16 post-promotion mining**: confirmed drawup contribution (+30pt OOS
  IR from -0.391 to -0.089) but still below +0.30 threshold.

### Track B — Intraday (R16-R25)
- Research continued on intraday factors. `realized_vol_60m_21d` showed
  IC_21d ≈ +0.10 (R5), CRISIS regime IR +0.79. Registered as
  RESEARCH_FACTOR.
- **R23**: DSL A/B test confirmed +2.3pt CAGR alpha from 5 cross-ticker rules
- **R25**: DSL stress test revealed asymmetry — protective in 2022 slow
  bear (MaxDD -9.7% vs SPY -28%) but hurts in 2020 COVID V-recovery.
  Added caveat to proposal doc.

### Track C — DSL (R26-R33)
- 2 new DSL rules added (R24): `leveraged_etfs_dual_confirmation`
  (leveraged ETF risk gate) + `xlu_outperformance_signals_defensive_rotation`
  (utility-driven defensive signal)
- Cross-ticker rules now 3→5. Rule 5 asymmetry flagged for user review.

### Track D — Universe Expansion (R34-R41 planned; R34-R38 executed)
- **R34**: S&P 500 pool sync (513 symbols fresh to 2026-04-22)
- **R35**: Alpha audit — 134 ALPHA_GENERATOR + 43 BETA_PLUS_ALPHA =
  177 α>3% candidates
- **R36**: Layer 1 admission screen — 500/513 (97.5%) pass
- **R37**: Risk labels + priority buckets — 175 SATELLITE_ALPHA pool
- **R38**: Universe expansion proposal v3 submitted to user (37 new
  symbols staged across 3 categories)
- **R39-R41**: DEFERRED — await user authorization on R38 proposal

### Track E — XGBoost Rigor (R42-R46)
- **R42**: 5-fold TimeSeriesSplit CV on 42-factor registry
  - Mean OOS R² = -0.070 (std 0.43, 2/5 folds positive)
  - `mom_252d` rank #1 but std 1.11 (unstable)
  - `drawup_from_252d_low` rank #27/35 with NEG mean — counter-evidence
    to R15 promotion
- **R43**: SHAP attribution — top: mean_rev_sma20 / drawdown_current
  (mean-reversion family). Permutation vs SHAP disagree (ρ moderate)
  signaling unreliable predictions.
- **R44**: 60/40 split stricter OOS — Test R² -4.56 (catastrophic)
- **R46**: **Verdict PARK**. 6/6 pass criteria fail.

### Track F — Transformer (R47-R48)
- **R47**: 5-config hyperparameter sweep — Peak config seq_len=126
  epochs=10 achieves OOS R² -0.0042 (approx zero, beats XGBoost by 7.5pt)
- **R48**: Phase 3 intraday pivot **NO-GO** (per §11.5 criterion — Phase 2
  didn't flip sign to positive)

### Track G — Final Synthesis (R49-R50)
- **R49**: Comprehensive acceptance pack — only `6d15b735a64c` passed
  archive gates; fresh full-period backtest reveals -10.33pt QQQ excess
- **R50**: THIS DOC

---

## Key empirical findings across the 50-round sweep

### Finding 1: factor→forward-return in 2021+ is systematically degraded
Across XGBoost CV (R42), SHAP (R43), Transformer (R47), Ridge-only
baselines, every method finds OOS R² ≤ 0 in 2021-2026 test folds
regardless of model class. The issue is **factor space**, not model
selection.

Evidence:
- R42 folds 3-5 (2021-2026): OOS R² = [-0.81, -0.20, -0.08]
- R44 60/40 split (train up to 2022): Test R² = -4.56
- R47 Transformer peak: OOS R² -0.0042 (approx zero)
- Phase B mining 80+ trials post-P0.1-fix: all OOS IR negative

### Finding 2: R15 drawup promotion has mixed evidence
- R15 supporting: OOS IR +0.386 (30-sym), Ridge #1, XGB single-split #7,
  factor_screen #2
- R42/R43 counter: 5-fold CV rank #27/35, negative mean permutation
- **R46 does not compel demotion** (R15 was multi-method consensus)
  but records counter-evidence for user review

### Finding 3: DSL rules provide +alpha in measured regimes but with asymmetric risk
- R23 A/B test: +2.3pt CAGR with 5 rules
- R25 stress test: 2020 COVID recovery hurt by Rules 2/5 (defensive
  rotation too heavy)
- **Recommendation**: reduce Rule 2 basket weight from 50% to 25% OR add
  fast-exit on SPY>SMA50 condition. User decision required.

### Finding 4: LLM factor funnel is valid methodology
- 26 LLM candidates proposed (R1-R14)
- 3 promoted or added (1 PRODUCTION: drawup; 2 RESEARCH:
  spy_trend_gated_mom_63d, weak_market_relative_strength_63d)
- Funnel correctly rejected 23 candidates (correlation dedup, IC weak,
  OOS walk-forward fail)
- Research-grade methodology **worked** even though production-level
  alpha remained elusive

### Finding 5: Universe is likely bottleneck
- Current 52-symbol universe has ~10-12 alpha generators (R20)
- S&P 500 pool has 177 (R35)
- **16x expansion potential** if R38 proposal approved
- R39-R41 planned validation on expanded universe requires user auth

---

## What "no validated best yet" means operationally

Per `config/production_strategy.yaml` status field definitions:

> - `conservative_default` — no post-fix validated best yet; using
>   best-known manual calibration; allowed for backtest/research but
>   M3 alignment check will WARN in paper live

System remains in this state. Production pipeline:
- Backtest: works with current 7-factor MultiFactorStrategy default weights
- Paper live: allowed but with M3 alignment WARN
- Real broker: BLOCKED (no promote authorization to `active`)

---

## User decisions awaiting

| Decision | Source | Options |
|---|---|---|
| 1. Approve R38 universe expansion v3? | R38 proposal doc | A (full 37) / B (Stage 1 11 only) / C (revise) / D (decline) |
| 2. Demote R15 drawup based on R42/R43 counter-evidence? | R46 findings | A (keep) / B (demote to RESEARCH) |
| 3. Reduce DSL Rule 2 weight or add fast-exit? | R25 stress caveat | A (50→25%) / B (fast-exit) / C (leave as-is) |
| 4. R45 ensemble test (MFS + XGB blend)? | R46 option C | A (run) / B (skip — Park XGB stands) |
| 5. Resubmit mining after universe expansion? | R39-R41 deferred | post-decision-1 |

---

## Recommended next phase (post-50-round)

Given the evidence accumulated:

**Priority A (if user approves R38)**: R39-R41 mining on expanded 85-symbol
universe → possibly unlock alpha in new sector exposures (healthcare,
staples, financials) that current tech-concentrated 52-symbol pool
can't reach.

**Priority B**: Cost-aware execution layer — intraday 60m timing signals
(R8 validated +3.26 bps/event) could compound on any daily alpha.
Requires decide_timing integration into paper live (already done) + 
validation_timing_value v2 with holding-path tracking.

**Priority C**: Microstructure factor family — order flow imbalance,
spread dynamics, auction volume. Currently factor registry has NO
microstructure. Could unlock new signal class outside saturated
daily-returns space.

**Priority D**: Regime-conditional strategy switching — system currently
applies one strategy (MFS) with regime scaling. Evidence suggests
different strategies work in different regimes; could implement
explicit "regime → strategy" mapping.

---

## Artifacts summary

| Type | Path | Contents |
|---|---|---|
| Round log | `docs/ralph_loop_log.md` | All 50 rounds 11-part Chinese reports |
| Promote proposal | `docs/production_factor_promote_proposal_weak_market_and_gated_mom.md` | R7/R10 factor proposal |
| Expansion proposal | `docs/universe_expansion_proposal_v3.md` | R38 37-symbol expansion |
| XGB findings | `docs/xgboost_weight_model_R46_findings.md` | Track E verdict |
| This doc | `docs/deep_mining_50round_final_synthesis.md` | R50 final |
| LLM candidates | `research/llm_candidates/round_01-26/` | 26 YAML candidates |
| Acceptance artifacts | `artifacts/acceptance_packs/` | All runs of acceptance_pack.py |
| Mining archive | `data/mining/archive.db` | 302 trials, 12 lineages |
| XGB CV artifacts | `data/ml/xgb_cv/` | R3/R4/R42/R43 per-fold parquets |
| Transformer | `data/ml/transformer/` | Phase 1 + R47 sweep results |
| Universe risk profile | `data/ml/universe_risk_profile_R37_sp500.csv` | 514 symbols labeled |

---

## Honest conclusion

The deep-mining 50-round loop **completed its mandate** per PRD §10
criterion #4: "明确证明'当前 universe + factor 空间不足以支撑新增 alpha'".

What did work:
- Research methodology (LLM funnel, deep_check, interaction mining)
- Tooling (XGBoost CV + SHAP, universe admission screen, risk profile)
- Factor registry expansion (drawup to PRODUCTION; R7+R10 to RESEARCH)
- DSL cross-ticker rules (+2.3pt CAGR alpha in measured regimes)
- Audit trail (lineage_tag + YAML candidates + per-round log)

What did NOT work:
- Producing a spec that passes acceptance pack v2 full_period_fresh_backtest
- Beating QQQ over fresh full period across any mined trial
- XGBoost / Transformer as production weight models

The right next step is **user review** of the 5 pending decisions above.
If R38 universe expansion is authorized, R39-R41 mining on the new pool
has the highest leverage for unlocking new alpha — current 52-symbol
universe is tech-saturated and factor-saturated.

---

*R50 synthesized from 50 rounds of autonomous deep mining
(commits e5fb4d2 ... through `1910c2d`). Loop terminates per §11.8
on reaching R50 and satisfying §10 criterion #4.*
