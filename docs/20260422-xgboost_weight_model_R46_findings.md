# R46 — XGBoost Weight Model Final Findings

**PRD**: `docs/prd_deep_mining_50round.md` §11.6 Track E (R42-R46)
**Date**: 2026-04-22
**Status**: **FINDINGS — awaits user decision**
**Recommendation**: **PARK** (research-only, do NOT promote to production)

---

## Executive summary

After 5 rounds of rigorous evaluation (R3/R4/R6 early pilot +
R42/R43/R44 strict OOS re-evaluation), XGBoost as a production factor
weight model is **not ready for promotion**. The model shows:

1. **OOS R² is systematically negative** when properly held out
2. **Permutation importance and SHAP disagree significantly**, suggesting
   predictions rely on unstable feature interactions
3. **R15-promoted drawup_from_252d_low** (the single factor already
   promoted to PRODUCTION via LLM phase) shows **negative permutation
   importance under 5-fold CV**, counter-validating the R15 decision

The recommendation is to **park the XGB weight model as a research-only
diagnostic tool** and continue using `MultiFactorStrategy` with the
hand-weighted production factor set.

---

## Evidence chain

### R3 — early single-split CV (baseline)
- 80/20 temporal split, train through 2023-02
- Train R² = +0.31, Test OOS R² = +0.03
- Marginal positive signal in early evaluation

### R4 — SHAP added
- Same split, SHAP artifacts produced
- Top SHAP: max_dd_126d, mom_252d, drawdown_current
- Baseline for later comparison

### R6 — weight model pilot
- 80/20 split, top-5 equal-weight portfolio construction
- XGB-weighted: CAGR +6.88% Sharpe +0.50 MaxDD -28.3%
- Equal-weight baseline: CAGR +3.75% Sharpe +0.56 MaxDD -17.3%
- XGB - baseline CAGR delta: **+3.13pt CAGR but -0.07 Sharpe**
- Scope labeled "research-only (PRD M7); not wired to production"

### R42 — 5-fold TimeSeriesSplit CV (rigorous)
- Mean OOS R² = **-0.070** (std 0.43, range [-0.81, +0.39])
- Only **2/5 folds positive** (both pre-2021)
- Post-2021 relationship between features and forward returns
  systematically degraded
- LLM-promoted factors:
  - `weak_market_relative_strength_63d` (R10): rank #8, modest +
  - `spy_trend_gated_mom_63d` (R7): rank #12, marginal +
  - `drawup_from_252d_low` (R15 PRODUCTION): **rank #27, mean -0.004 NEG**
- Classical `mom_126d`: rank #35/35, mean -0.168 (fully reversed)

### R43 — SHAP on same CV folds
- Top SHAP factors: `mean_rev_sma20`, `drawdown_current`, `reversal_5d`
- **Significant rank disagreement with permutation importance**:
  `mom_252d` drops from permutation #1 to SHAP #11; `max_dd_126d`
  drops from permutation #2 to SHAP #15
- Interpretation: permutation penalizes unstable features; SHAP
  captures per-sample contribution. Disagreement signals unreliable
  predictions

### R44 — stricter OOS weight model (60/40 split)
- Train R² = +0.73, Test R² = **-4.56** (catastrophic)
- Synthetic CAGR/Sharpe numbers in `summary.json` are unusable
  (backtest engine doesn't enforce capital constraints for this
  research tool) — but OOS R² alone disqualifies the model

---

## Cross-analysis: when would XGB weight model be production-ready?

Pass criteria (none currently met):

| Gate | R42-R44 status | Required |
|---|---|---|
| OOS R² positive across 3+ folds | 2/5 positive (both pre-2021) | ≥3/5 positive |
| Mean OOS R² ≥ +0.03 | -0.070 | ≥+0.03 |
| SHAP ↔ permutation agreement | Rank correlation moderate | ρ ≥ 0.6 |
| CAGR delta vs equal-weight > +2pt sustained | +3.13 in R6 but unstable | sustained |
| Sharpe delta positive | R6 Sharpe delta -0.07 (slightly worse) | ≥0 |
| Cost robustness (2x stress) | not tested | 2x cost passes |

---

## Implications for R15 drawup production promotion

The R15 decision to promote `drawup_from_252d_low` to PRODUCTION factor
set was made based on:
- R3 deep_check OOS IR +0.386 (single-split 30-sym panel)
- R6 Ridge permutation #1 (single-split)
- R6 XGBoost permutation #7 (single-split)
- R12 factor_screen #2 of 33 (IC-only)

**R42/R43 5-fold CV evidence contradicts the single-split result:**
- Permutation importance rank #27/35 with negative mean
- SHAP rank ~#30 with low |SHAP| (0.003)

This is NOT sufficient to demote drawup from PRODUCTION — the R15 evidence
was specific (5-symbol panel, 30-sym OOS walk-forward) and the LLM
promotion gated on multiple independent methods. But **the R46
recommendation flags this counter-evidence for user review**: a 50+ trial
mining run on post-R15 codebase that actually passes OOS gates would
be the definitive test.

**Does not block user**: the LLM Round 16 mining run already showed that
drawup promotion in PRODUCTION did improve OOS IR from -0.391 to -0.089
(30-point gain) — that was the empirical rationale for promotion.
R46 simply records that the gain is not sufficient to push OOS past the
+0.3 gate, and XGB CV confirms this ordering.

---

## Recommended action (user decision required)

| Option | Action |
|---|---|
| **A** (recommended) | Park XGB weight model. Continue MFS. Keep R44 summary as benchmark for future re-evaluation if universe expands (R38 v3 proposal) |
| **B** | Demote `drawup_from_252d_low` from PRODUCTION_FACTORS back to RESEARCH_FACTORS (based on R42/R43 CV counter-evidence) |
| **C** | Run combined ensemble R45: 50/50 MFS + XGB weight blend on 2026 holdout, measure incremental alpha |
| **D** | Invest in richer feature engineering (add regime-interactions, cross-sectional factors) and retry R42 |

---

## Artifacts

| Round | Artifact | Purpose |
|---|---|---|
| R3 | `data/ml/xgb_cv/R3_baseline/*` | Baseline CV (pre-shap) |
| R4 | `data/ml/xgb_cv/R4_with_shap/*` | Early SHAP on single split |
| R6 | `data/ml/xgb_weights/R6_daily_weight/*` | First weight model pilot |
| R42 | `data/ml/xgb_cv/R42_expanded_registry/*` | 5-fold CV on 42-factor registry |
| R43 | `data/ml/xgb_cv/R43_expanded_shap/*` | SHAP on same 5 folds |
| R44 | `data/ml/xgb_weights/R44_strict_oos/*` | 60/40 split retry |

---

## Conclusion

XGBoost is a valuable **research tool** for factor attribution, regime
analysis, and post-hoc importance ranking — but is **not production-ready**
as a replacement for the hand-weighted `MultiFactorStrategy` composite.

The 5-fold CV evidence is unambiguous: predictive relationships that
XGBoost learns in 2016-2021 data systematically do not transfer to
2021-2026. This is fundamental — not a hyperparameter problem.

**R46 verdict: PARK**. Use XGBoost for diagnostics only.

---

*Findings synthesized from deep-mining R3, R4, R6, R42, R43, R44
(commits through `195ab88`). Per §11.6 the R46 findings doc is the
gate for XGBoost weight model promotion; user's explicit authorization
required to change PRODUCTION behavior.*
